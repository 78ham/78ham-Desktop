"""
对讲服务

核心业务编排层，协调网络、音频、房间等模块。
参考安卓 TalkService 的设计模式。
"""
import time
import math
import logging
import threading
from typing import Optional, Callable, Dict, Any

from core.protocol import MAX_TEXT_LENGTH, NRLPacket, PacketType
from core.codec import G711Codec, OpusCodec, VoiceCodec, get_codec
from core.packet_factory import PacketFactory
from core.packet_parser import PacketParser
from config.settings import Settings
from network.udp_client import UdpClient
from network.connection_manager import ConnectionManager, ConnectionState

logger = logging.getLogger(__name__)


class TalkService:
    """对讲服务 — 应用核心业务逻辑

    职责：
    - 协调 UDP 客户端、音频管理器、房间服务
    - 处理收到的数据包并分发到对应处理器
    - 管理 PTT 状态（发射/接收）
    - 提供回调接口供 UI 层使用
    """

    # 配置常量
    VOICE_TIMEOUT = 0.5  # 语音播放超时（秒）
    MAX_RECONNECT_ATTEMPTS = 5
    RECONNECT_DELAY = 2.0

    def __init__(self, settings: Settings):
        self.settings = settings

        # 网络层
        self.connection_mgr = ConnectionManager(
            max_reconnect_attempts=self.MAX_RECONNECT_ATTEMPTS,
            reconnect_delay=self.RECONNECT_DELAY,
        )
        self.udp_client = UdpClient(settings, self.connection_mgr)
        self.udp_client.on_packet_received = self._on_packet_received

        # 编解码器
        self._tx_codec: VoiceCodec = self._create_codec(settings.audio.codec)
        self._g711_decoder = G711Codec()
        self._opus_decoder: Optional[OpusCodec] = None
        if OpusCodec.is_available():
            try:
                self._opus_decoder = OpusCodec()
            except Exception:
                pass

        # 包工厂
        self._packet_factory = PacketFactory()

        # PTT 状态（线程安全）
        self._ptt_lock = threading.Lock()
        self._codec_lock = threading.Lock()
        self.is_transmitting = False
        self._is_receiving = False
        self._last_voice_time: float = 0.0
        self._voice_timeout: float = self.VOICE_TIMEOUT
        self._playback_check_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 统计（线程安全）
        self._stats_lock = threading.Lock()
        self.voice_packets_sent = 0
        self.voice_packets_received = 0

        # 回调接口（UI 层注册）
        self.on_message: Optional[Callable[[Dict], None]] = None
        self.on_voice_data: Optional[Callable[[bytes, dict], None]] = None
        self.on_connection_changed: Optional[Callable[[ConnectionState], None]] = None
        self.on_status_update: Optional[Callable[[str, Any], None]] = None

        # 连接状态变更转发
        self.connection_mgr.on_state_changed = self._on_connection_state_changed

    def _create_codec(self, codec_type: str) -> VoiceCodec:
        """创建编码器"""
        options = (
            {'bitrate': self.settings.audio.opus_bitrate}
            if codec_type == 'opus' else {}
        )
        codec = get_codec(codec_type, **options)
        if codec is not None:
            return codec
        return G711Codec()

    # ==================== 生命周期 ====================

    def start(self) -> bool:
        """启动服务（连接到服务器）"""
        if self.udp_client.is_running and self.is_connected:
            return True
        self._stop_event.set()
        if self._playback_check_thread and self._playback_check_thread.is_alive():
            self._playback_check_thread.join(timeout=1.0)
        result = self.udp_client.connect()
        if result:
            # 启动播放超时检查
            self._stop_event.clear()
            self._playback_check_thread = threading.Thread(
                target=self._playback_timeout_loop, daemon=True, name="voice-timeout")
            self._playback_check_thread.start()
        return result

    def stop(self):
        """停止服务"""
        self._stop_event.set()
        with self._ptt_lock:
            self.is_transmitting = False
            self._is_receiving = False
        self.udp_client.disconnect()
        if self._playback_check_thread and self._playback_check_thread.is_alive():
            self._playback_check_thread.join(timeout=1.0)

    @property
    def is_connected(self) -> bool:
        return self.connection_mgr.is_connected

    # ==================== PTT 控制 ====================

    def start_transmitting(self) -> bool:
        """开始发射（PTT 按下）"""
        if not self.is_connected:
            logger.warning("未连接，无法发射")
            return False
        with self._ptt_lock:
            self.is_transmitting = True
        logger.info("PTT 开始发射")
        return True

    def stop_transmitting(self):
        """停止发射（PTT 松开）"""
        with self._ptt_lock:
            self.is_transmitting = False
        logger.info("PTT 停止发射")

    def send_voice_data(self, pcm_data: bytes) -> bool:
        """发送语音数据（由音频录制回调调用）

        Args:
            pcm_data: 原始 PCM 数据（一帧）

        Returns:
            发送是否成功
        """
        with self._ptt_lock:
            if not self.is_connected or not self.is_transmitting:
                return False

        # 在锁内快照编码器与编码类型，保证二者一致：set_codec 会同时替换
        # _tx_codec 与 settings.audio.codec，若不快照可能读到不匹配的组合
        with self._codec_lock:
            tx_codec = self._tx_codec
            codec_type = self.settings.audio.codec

        # 编码
        encoded = tx_codec.encode(pcm_data)
        if not encoded:
            return False

        # 创建数据包
        if codec_type == 'opus':
            packet = self._packet_factory.create_opus_voice(
                self.settings.device.callsign,
                self.settings.device.ssid,
                self.settings.device.dmr_id,
                encoded,
                self.settings.device.model,
                password=self.settings.get_current_password(),
            )
        else:
            packet = self._packet_factory.create_voice(
                self.settings.device.callsign,
                self.settings.device.ssid,
                self.settings.device.dmr_id,
                encoded,
                self.settings.device.model,
                password=self.settings.get_current_password(),
            )

        if self.udp_client.send_packet(packet):
            with self._stats_lock:
                self.voice_packets_sent += 1
            return True
        return False

    # ==================== 文本消息 ====================

    def send_text_message(self, message: str) -> bool:
        """发送文本消息"""
        if not self.is_connected:
            logger.warning("未连接，无法发送文本")
            return False
        if not message:
            return False

        text_bytes = message.encode('utf-8')
        max_len = min(MAX_TEXT_LENGTH, 0xFFFF - 48)
        if len(text_bytes) > max_len:
            logger.warning(f"消息被截断: {len(text_bytes)} > {max_len} 字节")
            text_bytes = text_bytes[:max_len].decode('utf-8', errors='ignore').encode('utf-8')

        packet = self._packet_factory.create_text(
            self.settings.device.callsign,
            self.settings.device.ssid,
            self.settings.device.dmr_id,
            text_bytes,
            self.settings.device.model,
            password=self.settings.get_current_password(),
        )
        return self.udp_client.send_packet(packet)

    def send_location(self, lat: float, lng: float) -> bool:
        """发送位置消息"""
        if (not math.isfinite(lat) or not math.isfinite(lng) or
                not -90.0 <= lat <= 90.0 or not -180.0 <= lng <= 180.0 or
                (lat == 0.0 and lng == 0.0)):
            return False
        loc_msg = PacketParser.format_location_message(lat, lng)
        return self.send_text_message(loc_msg)

    # ==================== 编码切换 ====================

    def set_codec(self, codec_type: str) -> bool:
        """运行时切换发射编码格式"""
        with self._ptt_lock:
            transmitting = self.is_transmitting
        logger.debug(f"set_codec: 请求={codec_type}, 当前={self.settings.audio.codec}, "
                     f"opus可用={OpusCodec.is_available()}, 发射中={transmitting}")
        if codec_type not in ("g711", "opus"):
            return False
        if codec_type == self.settings.audio.codec:
            return True
        if codec_type == "opus" and not OpusCodec.is_available():
            logger.error("Opus 不可用 — opuslib/av 均未加载成功")
            return False
        with self._codec_lock:
            with self._ptt_lock:
                transmitting = self.is_transmitting
            if transmitting:
                logger.warning("发射中无法切换编码 — 正在发射")
                return False
            self.settings.audio.codec = codec_type
            self.settings.audio.sample_rate = 16000 if codec_type == 'opus' else 8000
            self._tx_codec = self._create_codec(codec_type)
        self.settings.save_codec()
        logger.info(f"发射编码已切换: {codec_type}")
        return True

    def set_opus_bitrate(self, bitrate: int) -> bool:
        """运行时切换 Opus 码率"""
        if not 6000 <= bitrate <= 510000:
            return False
        if self.settings.audio.opus_bitrate == bitrate:
            return True
        with self._ptt_lock:
            transmitting = self.is_transmitting
        if transmitting:
            logger.warning("发射中无法切换码率")
            return False

        with self._codec_lock:
            self.settings.audio.opus_bitrate = bitrate
            if isinstance(self._tx_codec, OpusCodec):
                self._tx_codec = self._create_codec('opus')
        self.settings.save_opus_bitrate()
        logger.info(f"Opus 码率已切换: {bitrate} bps")
        return True

    # ==================== 数据包处理 ====================

    def _on_packet_received(self, packet: NRLPacket):
        """处理收到的数据包（由 UdpClient 回调）"""
        try:
            # 语音包：检查 PTT 状态位
            if packet.is_voice():
                if not packet.is_transmitting():
                    return  # 非发送模式，丢弃

            ptype = packet.packet_type
            if ptype == PacketType.VOICE:
                self._handle_voice(packet)
            elif ptype == PacketType.OPUS:
                self._handle_opus_voice(packet)
            elif ptype == PacketType.SERVER_VOICE:
                self._handle_server_voice(packet)
            elif ptype == PacketType.HEARTBEAT:
                self._handle_heartbeat(packet)
            elif ptype == PacketType.TEXT:
                self._handle_text(packet)
            elif ptype == PacketType.JOIN_GROUP:
                self._handle_group_response(packet)
            else:
                logger.debug(f"未知包类型: {ptype}")
        except Exception as e:
            # 处理异常不应触发重连（与网络错误区分）
            logger.error(f"数据包处理异常: {e}")

    def _handle_voice(self, packet: NRLPacket):
        """处理 G.711 语音包"""
        if not packet.data:
            return
        pcm = self._g711_decoder.decode(packet.data)
        if pcm:
            self._deliver_voice(pcm, packet)

    def _handle_opus_voice(self, packet: NRLPacket):
        """处理 Opus 语音包"""
        if not packet.data or not self._opus_decoder:
            return
        pcm = self._opus_decoder.decode(packet.data)
        if pcm:
            self._deliver_voice(pcm, packet)

    def _handle_server_voice(self, packet: NRLPacket):
        """处理服务器互联语音包（Type=9, G.711）"""
        if not packet.data:
            return
        pcm = self._g711_decoder.decode(packet.data)
        if pcm:
            extra = {
                'original_callsign': packet.header.original_callsign.decode('utf-8', errors='ignore').strip(),
                'original_ssid': packet.header.original_ssid,
                'original_ip': '.'.join(str(b) for b in packet.header.original_ip),
                'relay_callsign': packet.callsign_ssid,
            }
            self._deliver_voice(pcm, packet, extra)

    def _deliver_voice(self, pcm_data: bytes, packet: NRLPacket, extra: Optional[Dict] = None):
        """分发解码后的语音数据"""
        with self._ptt_lock:
            transmitting = self.is_transmitting
        with self._stats_lock:
            self.voice_packets_received += 1

        # 发射中不播放远端语音
        if transmitting:
            return

        # 过滤自己发送的语音（服务器会回传）
        local_call = self.settings.device.callsign
        local_ssid = self.settings.device.ssid
        pkt_call = packet.header.get_callsign_str()
        pkt_ssid = packet.header.ssid
        if pkt_call == local_call and pkt_ssid == local_ssid:
            return

        with self._ptt_lock:
            self._last_voice_time = time.monotonic()
            self._is_receiving = True

        dmr_id = packet.header.dmr_id.hex().upper() if packet.header.dmr_id else ""
        info = {
            'from': packet.callsign_ssid,
            'from_callsign': packet.header.get_callsign_str(),
            'ssid': packet.header.ssid,
            'dmr_id': dmr_id,
            'type': packet.packet_type,
            **(extra or {}),
        }
        if self.on_voice_data:
            self.on_voice_data(pcm_data, info)

    def _handle_heartbeat(self, packet: NRLPacket):
        """处理心跳包"""
        logger.debug(f"心跳: {packet.callsign_ssid}")

    def _handle_text(self, packet: NRLPacket):
        """处理文本消息"""
        if not packet.data:
            return

        parsed = PacketParser.parse_text_subtype(packet.data)
        dmr_id = packet.header.dmr_id.hex().upper() if packet.header.dmr_id else ""
        message = {
            'type': 'text',
            'subtype': parsed['subtype'],
            'from': packet.callsign_ssid,
            'from_callsign': packet.header.get_callsign_str(),
            'ssid': packet.header.ssid,
            'dmr_id': dmr_id,
            'content': parsed['content'],
            'raw': parsed['raw'],
            'timestamp': time.time(),
        }

        # 位置消息额外解析
        if parsed['subtype'] == 'loc':
            lat, lng = PacketParser.parse_location_content(parsed['content'])
            message['lat'] = lat
            message['lng'] = lng
            message['map_url'] = PacketParser.generate_map_url(lat, lng)

        if self.on_message:
            self.on_message(message)

        logger.info(f"文本消息: [{parsed['subtype']}] {parsed['content'][:50]} from {packet.callsign_ssid}")

    def _handle_group_response(self, packet: NRLPacket):
        """处理房间操作响应（由 RoomService 进一步处理）"""
        if self.on_message:
            self.on_message({
                'type': 'group_response',
                'data': packet.data,
                'from': packet.callsign_ssid,
            })

    # ==================== 内部线程 ====================

    def _playback_timeout_loop(self):
        """语音播放超时检查"""
        while not self._stop_event.is_set() and self.udp_client.is_running:
            try:
                with self._ptt_lock:
                    last_time = self._last_voice_time
                    receiving = self._is_receiving
                if last_time > 0:
                    elapsed = time.monotonic() - last_time
                    if elapsed > self._voice_timeout and receiving:
                        with self._ptt_lock:
                            self._is_receiving = False
                        if self.on_status_update:
                            self.on_status_update('voice_timeout', None)
                self._stop_event.wait(0.5)
            except Exception as e:
                logger.error(f"播放超时检查错误: {e}")

    def _on_connection_state_changed(self, state: ConnectionState):
        """连接状态变更处理"""
        if self.on_connection_changed:
            self.on_connection_changed(state)

    # ==================== 状态查询 ====================

    def get_status(self) -> Dict[str, Any]:
        """获取服务状态"""
        with self._stats_lock:
            sent = self.voice_packets_sent
            received = self.voice_packets_received
        with self._ptt_lock:
            transmitting = self.is_transmitting
        udp_stats = self.udp_client.get_stats()
        return {
            'connected': self.is_connected,
            'transmitting': transmitting,
            'codec': self.settings.audio.codec,
            'server': f"{self.settings.server.host}:{self.settings.server.port}",
            'callsign': f"{self.settings.device.callsign}-{self.settings.device.ssid}",
            'voice_sent': sent,
            'voice_received': received,
            'packets_sent': udp_stats['packets_sent'],
            'packets_received': udp_stats['packets_received'],
        }
