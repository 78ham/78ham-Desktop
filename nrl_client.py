"""
78HAM客户端主类
实现与服务器的UDP通信，设备管理，语音处理等功能
"""
import socket
import select
import threading
import time
import logging
import yaml #type: ignore
import json
import os
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass

from nrl_protocol import (NRLProtocol, NRLPacket, OpusCodec,
    format_location_message, parse_text_subtype, parse_location_content, generate_map_url)
from audio_handler import AudioHandler, VoiceProcessor

# 操作系统名称映射
OS_NAME_MAP = {
    "nt": "Windows",
    "posix": "Linux/Unix",
    "darwin": "macOS",
}


def get_os_display_name() -> str:
    """获取可读的操作系统名称"""
    return OS_NAME_MAP.get(os.name, "未知")


class LocationProvider:
    """位置获取提供者，支持多级回退:
    1. Windows Location API (GPS/基站/WiFi)
    2. IP 地理定位 (公网 IP)
    """

    _logger = logging.getLogger("LocationProvider")

    @classmethod
    def get_location(cls) -> tuple:
        """获取当前位置

        返回: (lat: float, lng: float, source: str)
        source 为 "gps" / "ip" / "unavailable"
        """
        # 1. 尝试 Windows Location API
        result = cls._try_winrt_gps()
        if result:
            return (result[0], result[1], "gps")

        # 2. 尝试 IP 地理定位
        result = cls._try_ip_geolocation()
        if result:
            return (result[0], result[1], "ip")

        return (0.0, 0.0, "unavailable")

    @classmethod
    def _try_winrt_gps(cls) -> tuple:
        """尝试通过 Windows Location API 获取坐标"""
        if os.name != "nt":
            return None
        try:
            import asyncio
            from winrt.windows.devices.geolocation import Geolocator  # type: ignore

            async def _get_pos():
                locator = Geolocator()
                pos = await locator.get_geopoint_async()
                coord = pos.coordinate
                return (coord.latitude, coord.longitude)

            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_get_pos())
            finally:
                loop.close()
        except ImportError:
            cls._logger.debug("winrt 未安装，跳过 GPS 定位")
        except Exception as e:
            cls._logger.debug(f"Windows GPS 定位失败: {e}")
        return None

    @classmethod
    def _try_ip_geolocation(cls) -> tuple:
        """尝试通过 IP 地址获取大致位置"""
        try:
            import requests  # type: ignore
            resp = requests.get("http://ip-api.com/json/?fields=lat,lon,status", timeout=5)
            data = resp.json()
            if data.get("status") == "success":
                return (float(data["lat"]), float(data["lon"]))
        except ImportError:
            cls._logger.debug("requests 未安装，跳过 IP 定位")
        except Exception as e:
            cls._logger.debug(f"IP 定位失败: {e}")
        return None


@dataclass
class DeviceConfig:
    """设备配置"""
    callsign: str
    ssid: int
    dmr_id: str
    password: str
    model: int

@dataclass
class ServerConfig:
    """服务器配置"""
    host: str
    port: int

@dataclass
class ServerInfo:
    """服务器信息"""
    name: str
    host: str
    port: int
    password: str = ""
    online: int = 0
    total: int = 0
    
    @classmethod
    def from_config(cls, cfg: dict) -> "ServerInfo":
        """从配置字典创建，兼容新旧格式"""
        port_val = cfg.get('port', 60050)
        if isinstance(port_val, str):
            try:
                port_val = int(port_val)
            except (ValueError, TypeError):
                port_val = 60050
        return cls(
            name=cfg.get('name', '服务器'),
            host=cfg.get('host', '127.0.0.1'),
            port=port_val,
            password=cfg.get('password', ''),
            online=cfg.get('online', 0),
            total=cfg.get('total', 0),
        )

@dataclass
class AudioConfig:
    """音频配置"""
    sample_rate: int
    channels: int
    codec: str          # 语音编码格式: "g711" 或 "opus"
    format: str

@dataclass
class NetworkConfig:
    """网络配置"""
    buffer_size: int
    heartbeat_interval: int

@dataclass
class LocationConfig:
    """位置配置"""
    default_lat: float = 0.0
    default_lng: float = 0.0
    auto_report: bool = False
    report_interval: int = 600  # 秒

class NRLClient:
    """78HAM客户端的主类"""
    
    def __init__(self, config_file: str = "config.yaml"):
        self.logger = logging.getLogger(__name__)
        self.config_file = config_file
        
        # 配置
        self.device_config: Optional[DeviceConfig] = None
        self.server_config: Optional[ServerConfig] = None
        self.audio_config: Optional[AudioConfig] = None
        self.network_config: Optional[NetworkConfig] = None
        self.location_config: Optional[LocationConfig] = None
        
        # 服务器列表
        self.servers_list: list[ServerInfo] = []
        self.current_server_index: int = 0
        
        # 网络
        self.socket = None
        self.is_connected = False
        self.receive_thread = None
        self.heartbeat_thread = None
        self.location_report_thread = None
        self.running = False
        
        # 协议处理
        self.protocol = NRLProtocol()
        
        # 音频处理
        self.audio_handler = None
        self.voice_processor = None
        
        # 状态
        self._status_lock = threading.Lock()
        self.device_status = {
            'online': False,
            'last_heartbeat': 0,
            'packets_sent': 0,
            'packets_received': 0,
            'voice_packets_sent': 0,
            'voice_packets_received': 0
        }
        
        # 回调函数
        self.message_callback: Optional[Callable[[Dict], None]] = None
        self.voice_callback: Optional[Callable[[bytes], None]] = None
        self.status_callback: Optional[Callable[[str, Any], None]] = None
        
        # 调试选项：绕过空包检查，强制解码所有包
        self.debug_force_decode = False
        
        # 语音自动播放控制
        self.last_voice_packet_time = 0.0  # 最后收到语音包的时间
        self.voice_playback_timeout = 0.5  # 语音播放超时时间（秒）
        self.playback_check_thread = None  # 播放超时检查线程
        self.is_recording_local = False  # 本地正在录音标志，录音期间禁用自动播放
        
        # 房间（Group）状态
        self.current_group_id: int = 0           # 当前所在房间 ID
        self.current_group_name: str = "公共大厅"  # 当前房间名
        self.group_list: list = []                # 房间列表缓存 [{"id": int, "name": str}, ...]
        self._group_list_pending: bool = False     # 等待房间列表响应
        self._join_group_pending: bool = False     # 等待加入房间响应
        self._group_list_timeout: float = 3.0      # 房间列表请求超时（秒）
        self._join_group_timeout: float = 3.0      # 加入房间请求超时（秒）
        self.group_list_callback: Optional[Callable[[list], None]] = None   # 房间列表更新回调
        self.group_change_callback: Optional[Callable[[int, str], None]] = None  # 房间切换结果回调
        
        # 加载配置
        self.load_config(config_file)
        
        # 初始化音频
        self.init_audio()
    
    def _inc_status(self, key: str, amount: int = 1):
        """线程安全地递增 device_status 计数器"""
        with self._status_lock:
            self.device_status[key] += amount
    
    def _set_status_value(self, key: str, value):
        """线程安全地设置 device_status 值"""
        with self._status_lock:
            self.device_status[key] = value
    
    def load_config(self, config_file: str):
        """加载配置文件"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            
            if not config_data:
                config_data = {}
            
            # 设备配置
            device_cfg = config_data.get('device', {})
            self.device_config = DeviceConfig(
                callsign=device_cfg.get('callsign', 'N0CALL'),
                ssid=device_cfg.get('ssid', 1),
                dmr_id=device_cfg.get('dmr_id', '123456'),
                password=device_cfg.get('password', ''),
                model=device_cfg.get('model', 1)
            )
            
            # 服务器配置
            server_cfg = config_data.get('server', {})
            self.server_config = ServerConfig(
                host=server_cfg.get('host', '127.0.0.1'),
                port=server_cfg.get('port', 60050)
            )
            
            # 加载服务器列表
            servers_cfg = config_data.get('servers', [])
            current_server_idx = config_data.get('current_server', 0)
            
            # 兼容新版服务器 PlatformList 格式
            if not servers_cfg:
                servers_cfg = config_data.get('PlatformList', [])
            
            if servers_cfg:
                self.servers_list = []
                for server in servers_cfg:
                    server_info = ServerInfo.from_config(server)
                    self.servers_list.append(server_info)
                
                # 设置当前服务器索引
                if 0 <= current_server_idx < len(self.servers_list):
                    self.current_server_index = current_server_idx
                else:
                    self.current_server_index = 0
                
                # 使用当前选择的服务器配置
                if self.servers_list:
                    current_server = self.servers_list[self.current_server_index]
                    self.server_config.host = current_server.host
                    self.server_config.port = current_server.port
                    
                self.logger.info(f"已加载 {len(self.servers_list)} 个服务器配置，当前使用: {self.servers_list[self.current_server_index].name if self.servers_list else '无'}")
            else:
                # 如果没有服务器列表，使用单个服务器配置
                self.servers_list = [ServerInfo(
                    name="默认服务器",
                    host=self.server_config.host,
                    port=self.server_config.port
                )]
                self.current_server_index = 0
            
            # 音频配置
            audio_cfg = config_data.get('audio', {})
            # 兼容新旧字段名：优先读 tx_codec，回退到 codec
            codec = audio_cfg.get('tx_codec', audio_cfg.get('codec', 'g711'))
            # 根据编码格式自动确定采样率
            default_rate = 16000 if codec == 'opus' else 8000
            sample_rate = audio_cfg.get('sample_rate', default_rate)
            # 如果用户配置了错误的采样率，自动修正
            if codec == 'opus' and sample_rate != 16000:
                self.logger.info(f"Opus编码需要16kHz采样率，自动从{sample_rate}Hz修正为16000Hz")
                sample_rate = 16000
            elif codec == 'g711' and sample_rate != 8000:
                self.logger.info(f"G.711编码使用8kHz采样率，自动从{sample_rate}Hz修正为8000Hz")
                sample_rate = 8000
            
            self.audio_config = AudioConfig(
                sample_rate=sample_rate,
                channels=audio_cfg.get('channels', 1),
                codec=codec,
                format=audio_cfg.get('format', 'paInt16')
            )
            
            # 网络配置
            network_cfg = config_data.get('network', {})
            self.network_config = NetworkConfig(
                buffer_size=network_cfg.get('buffer_size', 1460),
                heartbeat_interval=network_cfg.get('heartbeat_interval', 30)
            )
            
            # 位置配置
            location_cfg = config_data.get('location', {})
            self.location_config = LocationConfig(
                default_lat=location_cfg.get('default_lat', 0.0),
                default_lng=location_cfg.get('default_lng', 0.0),
                auto_report=location_cfg.get('auto_report', False),
                report_interval=location_cfg.get('report_interval', 600)
            )
            
            self.logger.info("配置加载成功")
            
        except Exception as e:
            self.logger.error(f"加载配置失败: {e}")
            raise
    
    def save_config(self):
        """保存当前发射编码到配置文件（保留注释和格式）"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            import re
            codec_value = self.audio_config.codec
            
            # 替换 tx_codec 字段值
            if 'tx_codec:' in content:
                content = re.sub(
                    r'(tx_codec:\s*)["\']?\w+["\']?',
                    rf'\g<1>"{codec_value}"',
                    content
                )
            elif 'codec:' in content:
                # 兼容旧字段名：替换为新字段名
                content = re.sub(
                    r'(codec:\s*)["\']?\w+["\']?',
                    rf'tx_codec: "{codec_value}"',
                    content
                )
            else:
                # 字段不存在，在 audio 段落末尾追加
                content = re.sub(
                    r'(audio:\s*\n(?:\s+\S.*\n)*)',
                    lambda m: m.group(0).rstrip('\n') + f'\n  tx_codec: "{codec_value}"\n',
                    content
                )
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            self.logger.info(f"发射编码已保存到 {self.config_file}: {codec_value}")
        except Exception as e:
            self.logger.error(f"保存配置失败: {e}")
    
    def init_audio(self):
        """初始化音频处理"""
        try:
            # 根据编码格式确定PCM帧大小作为chunk_size
            if self.audio_config.codec == 'opus':
                chunk_size = 640  # 320 samples * 2 bytes @ 16kHz = 20ms
            else:
                chunk_size = 320  # 160 samples * 2 bytes @ 8kHz = 20ms
            
            self.audio_handler = AudioHandler(
                sample_rate=self.audio_config.sample_rate,
                channels=self.audio_config.channels,
                chunk_size=chunk_size,
                format_str=self.audio_config.format,
                codec_type=self.audio_config.codec
            )
            
            self.voice_processor = VoiceProcessor(codec_type=self.audio_config.codec)
            
            self.logger.info(f"音频处理初始化成功 (编码: {self.audio_config.codec}, 采样率: {self.audio_config.sample_rate}Hz)")
            
        except Exception as e:
            self.logger.error(f"音频处理初始化失败: {e}")
            raise
    
    def connect(self) -> bool:
        """连接到服务器"""
        try:
            # === 关键：先停止旧线程，避免 old threads 继续运行并堆积 GUI 回调 ===
            self.running = False
            for t in (self.receive_thread, self.heartbeat_thread, self.playback_check_thread, self.location_report_thread):
                if t and t.is_alive():
                    t.join(timeout=1.0)
            self.receive_thread = None
            self.heartbeat_thread = None
            self.playback_check_thread = None
            self.location_report_thread = None
            
            # 关闭旧 socket
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
            
            # 创建UDP套接字
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setblocking(False)  # 非阻塞模式，防止sendto阻塞音频回调
            
            # 设置接收缓冲区大小
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 
                                     self.network_config.buffer_size)
            except:
                self.logger.warning("设置接收缓冲区失败，使用默认配置")
            
            # 发送初始包进行设备注册
            test_packet = self.protocol.create_heartbeat_packet(
                self.device_config.callsign, 
                self.device_config.ssid, 
                dmr_id=self.device_config.dmr_id, 
                dev_mode=self.device_config.model   
            )
            
            try:
                self.socket.sendto(test_packet.encode(), 
                                 (self.server_config.host, self.server_config.port))
            except BlockingIOError:
                self.logger.warning("初始连接包发送缓冲区满，将在心跳中重试")
            
            self.logger.info(f"已发送初始连接包到 {self.server_config.host}:{self.server_config.port}")
            
            self.is_connected = True
            self.running = True
            
            # 启动接收线程
            self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.receive_thread.start()
            
            # 启动心跳线程
            self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
            self.heartbeat_thread.start()
            
            # 启动播放超时检查线程
            self.playback_check_thread = threading.Thread(target=self._playback_timeout_loop, daemon=True)
            self.playback_check_thread.start()
            
            # 启动自动位置上报线程（如果配置开启）
            if self.location_config and self.location_config.auto_report:
                self.location_report_thread = threading.Thread(target=self._location_report_loop, daemon=True)
                self.location_report_thread.start()
                self.logger.info(f"自动位置上报已开启，间隔 {self.location_config.report_interval} 秒")
            
            self._update_status('connected', True)
            self.logger.info(f"连接到服务器成功: {self.server_config.host}:{self.server_config.port}")
            self.logger.info(f"------------------------------------")
            self.logger.info(f"78HAM客户端测试版本")
            self.logger.info(f"------------------------------------")
            self.logger.info("欢迎使用78HAM客户端,本客户端目前为测试版本")
            self.logger.info(f"当前的操作系统为：{get_os_display_name()}")
            self.logger.info(f"当前连接到服务器的设备呼号: {self.device_config.callsign}")
            self.logger.info(f"当前连接到服务器的设备SSID: {self.device_config.ssid}")
            self.logger.info(f"------------------------------------")

            return True
            
        except socket.error as e:
            self.logger.error(f"套接字错误: {e}")
            self.is_connected = False
            return False
        except Exception as e:
            self.logger.error(f"连接服务器失败: {e}")
            self.is_connected = False
            return False
    
    def disconnect(self):
        """断开连接"""
        self.running = False
        self.is_connected = False
        
        # 并行等待后台线程退出（>500ms 仍未退出则强制跳过）
        import concurrent.futures
        threads = [(t, name) for t, name in (
            (self.receive_thread, "receive"),
            (self.heartbeat_thread, "heartbeat"),
            (self.playback_check_thread, "playback_check"),
            (self.location_report_thread, "location_report"),
        ) if t and t.is_alive()]
        
        if threads:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(threads)) as ex:
                futures = {ex.submit(t.join, 0.5): name for t, name in threads}
                for f in concurrent.futures.as_completed(futures, timeout=0.6):
                    pass  # 不关心结果，只要都完成即可
            for t, name in threads:
                if t.is_alive():
                    self.logger.warning(f"{name} 线程未能在 0.5s 内退出，强制跳过")
        
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        
        self._update_status('connected', False)
        self.logger.info("已断开服务器连接")
    
    def _receive_loop(self):
        """接收数据循环
        
        使用 select.select() 等待 socket 可读，避免忙等导致 CPU 占用过高。
        连续错误达到上限后执行真正的重连（重建 socket + 重新注册）。
        """
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while self.running:
            try:
                if not self.socket:
                    time.sleep(0.1)
                    continue
                
                # 使用 select 等待 socket 可读，超时 100ms
                ready, _, _ = select.select([self.socket], [], [], 0.1)
                if not ready:
                    continue
                
                # 接收数据
                data, addr = self.socket.recvfrom(self.network_config.buffer_size)
                
                if not data or len(data) < 48:
                    self.logger.warning(f"接收到无效数据包（长度: {len(data)}）")
                    continue
                
                # 解析数据包
                packet = NRLPacket()
                if not packet.decode(data):
                    self.logger.debug(f"数据包解析失败: {addr}")
                    continue
                
                # 处理数据包
                self._handle_packet(packet, addr)
                self._inc_status('packets_received')
                
                # 重置错误计数
                consecutive_errors = 0
                
            except OSError as e:
                if not self.running:
                    break
                self.logger.error(f"接收数据错误: {e}")
                consecutive_errors += 1
            except Exception as e:
                if self.running:
                    self.logger.error(f"接收数据错误: {e}")
                    consecutive_errors += 1
            
            # 检查连续错误，执行真正的重连
            if consecutive_errors >= max_consecutive_errors:
                self.logger.error(f"连续接收错误达到{max_consecutive_errors}次，尝试重新连接")
                consecutive_errors = 0
                self._attempt_reconnect()
    
    def _attempt_reconnect(self):
        """尝试重新连接到服务器"""
        self.is_connected = False
        
        # 关闭旧 socket
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        
        time.sleep(2)  # 等待后重试
        
        if not self.running:
            return
        
        try:
            # 重建 socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setblocking(False)
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF,
                                     self.network_config.buffer_size)
            except:
                pass
            
            # 重新发送注册包
            test_packet = self.protocol.create_heartbeat_packet(
                self.device_config.callsign,
                self.device_config.ssid,
                dmr_id=self.device_config.dmr_id,
                dev_mode=self.device_config.model
            )
            self.socket.sendto(test_packet.encode(),
                             (self.server_config.host, self.server_config.port))
            
            self.is_connected = True
            self.logger.info(f"重新连接成功: {self.server_config.host}:{self.server_config.port}")
        except Exception as e:
            self.logger.error(f"重新连接失败: {e}")
    
    def _heartbeat_loop(self):
        """心跳循环
        
        参考78HAM的设备在线检查机制
        主要功能：
        1. 定期发送心跳包维持连接
        2. 检测心跳响应超时
        3. 在连接丢失时自动重连
        """
        heartbeat_failures = 0
        max_failures = 3
        poll_interval = 0.5  # 500ms 检查一次 running 标志，确保能快速退出
        ticks_per_heartbeat = int(self.network_config.heartbeat_interval / poll_interval)
        tick = 0
        
        while self.running:
            try:
                if tick <= 0:
                    if self.is_connected:
                        if not self.send_heartbeat():
                            heartbeat_failures += 1
                            if heartbeat_failures >= max_failures:
                                self.logger.warning("心跳失败次数过多，标记为离线")
                                self.is_connected = False
                                heartbeat_failures = 0
                        else:
                            heartbeat_failures = 0
                    tick = ticks_per_heartbeat
                
                tick -= 1
                time.sleep(poll_interval)
                
            except Exception as e:
                self.logger.error(f"心跳错误: {e}")
                heartbeat_failures += 1
                if heartbeat_failures >= max_failures:
                    self.is_connected = False
                    heartbeat_failures = 0
                tick = 0  # 出错后下次循环重试
    
    def _location_report_loop(self):
        """自动上报位置循环

        在 auto_report 开启且连接成功后，按 report_interval 间隔
        自动解析位置（GPS → IP → 默认配置）并发送给服务器。
        """
        # 连接后立即上报一次
        try:
            lat, lng, source = self.resolve_location()
            if lat != 0.0 or lng != 0.0:
                self.send_location_message(lat, lng)
                self.logger.info(f"自动上报位置: {lat:.6f},{lng:.6f} (来源: {source})")
            else:
                self.logger.warning("自动上报位置失败：无可用位置")
        except Exception as e:
            self.logger.error(f"自动上报位置异常: {e}")

        while self.running:
            try:
                # 将长 sleep 拆成 500ms 轮询，确保 running=False 后快速退出
                poll_interval = 0.5
                ticks_total = int(self.location_config.report_interval / poll_interval)
                for _ in range(ticks_total):
                    if not self.running:
                        break
                    time.sleep(poll_interval)
                if not self.running or not self.is_connected:
                    break
                lat, lng, source = self.resolve_location()
                if lat != 0.0 or lng != 0.0:
                    self.send_location_message(lat, lng)
                    self.logger.info(f"自动上报位置: {lat:.6f},{lng:.6f} (来源: {source})")
                else:
                    self.logger.warning("自动上报位置失败：无可用位置")
            except Exception as e:
                self.logger.error(f"自动上报位置异常: {e}")

    def _playback_timeout_loop(self):
        """播放超时检查循环 - 定期检查是否需要关闭播放
        
        使用标志而非直接调用stop_playback()以避免与播放回调的死锁
        """
        while self.running:
            try:
                if self.audio_handler and self.audio_handler.is_playback_active():
                    current_time = time.time()
                    time_since_last_voice = current_time - self.last_voice_packet_time
                    
                    # 如果超过超时时间未收到语音包，则设置停止标志
                    if time_since_last_voice > self.voice_playback_timeout:
                        # 仅在首次超时时设置标志，避免重复日志
                        if not self.audio_handler.playback_stop_flag:
                            self.logger.info(f"语音播放超时（{time_since_last_voice:.1f}秒），标记停止播放")
                            self.audio_handler.playback_stop_flag = True
                
                time.sleep(0.5)  # 每500毫秒检查一次
                
            except Exception as e:
                self.logger.error(f"播放超时检查错误: {e}")
    
    def _handle_packet(self, packet: NRLPacket, addr: tuple):
        """处理接收到的数据包"""
        self.logger.debug(f"收到数据包: {packet}")
        
        # 检查状态位的DCD/PTT标志
        if packet.packet_type in (NRLPacket.TYPE_VOICE, NRLPacket.TYPE_OPUS, NRLPacket.TYPE_SERVER_VOICE):
            # 如果状态位bit0为0，表示监听/非发送模式，应丢弃包
            if packet.status & 0x01 == 0:
                self.logger.debug(f"丢弃语音包: 状态位表示非发送模式 from {packet.get_callsign_ssid()}")
                return
        
        if packet.packet_type == NRLPacket.TYPE_VOICE:
            self._handle_voice_packet(packet)
            self._inc_status('voice_packets_received')
            
        elif packet.packet_type == NRLPacket.TYPE_OPUS:
            self._handle_opus_voice_packet(packet)
            self._inc_status('voice_packets_received')
            
        elif packet.packet_type == NRLPacket.TYPE_HEARTBEAT:
            self._handle_heartbeat_packet(packet)
            
        elif packet.packet_type == NRLPacket.TYPE_TEXT:
            self._handle_text_packet(packet)
            
        elif packet.packet_type == NRLPacket.TYPE_SERVER_VOICE:
            self._handle_server_voice_packet(packet)
            self._inc_status('voice_packets_received')
            
        elif packet.packet_type == NRLPacket.TYPE_JOIN_GROUP:
            self._handle_join_group_response(packet)
            
        else:
            self.logger.info(f"收到未知类型数据包: type={packet.packet_type}")
    
    def _normalize_voice_data(self, packet: NRLPacket, context: str = "语音") -> bool:
        """统一处理语音包数据：验证、调试模式填充、返回是否有效
        
        根据数据包类型确定期望帧大小：
        - G.711 (Type=1): 160字节
        - Opus (Type=8): 变长，不校验长度
        - 服务器互联 (Type=9): 160字节
        """
        is_opus = (packet.packet_type == NRLPacket.TYPE_OPUS)
        expected_size = 160  # G.711 / 服务器互联的期望大小
        
        if not packet.data or len(packet.data) == 0:
            if not self.debug_force_decode:
                self.logger.warning(f"收到空{context}数据包 from {packet.get_callsign_ssid()}")
                return False
            self.logger.info(f"[调试模式] 收到空{context}数据包，强制解码 from {packet.get_callsign_ssid()}")
            packet.data = b'\x80' * expected_size
        
        # Opus是变长编码，不做长度校验
        if is_opus:
            return True
        
        # G.711长度校验
        if self.debug_force_decode and len(packet.data) != expected_size:
            if len(packet.data) > expected_size:
                original_len = len(packet.data)
                packet.data = packet.data[:expected_size]
                self.logger.info(f"[调试模式] {context}包长度异常 ({original_len} bytes)，截取前{expected_size}字节")
            elif len(packet.data) < expected_size:
                original_len = len(packet.data)
                packet.data = packet.data + b'\x80' * (expected_size - len(packet.data))
                self.logger.info(f"[调试模式] {context}包长度不足 ({original_len} bytes)，补充静音至{expected_size}字节")
        elif not self.debug_force_decode and len(packet.data) != expected_size:
            self.logger.warning(f"{context}数据包长度不是{expected_size}字节: {len(packet.data)} from {packet.get_callsign_ssid()}")
        return True
    
    def _play_voice_pcm(self, pcm_data: bytes, packet: NRLPacket, extra_info: dict = None):
        """统一的语音播放处理逻辑"""
        if not pcm_data:
            self.logger.error(f"语音解码失败，返回空数据 from {packet.get_callsign_ssid()}")
            return
        
        # 更新最后语音包时间
        self.last_voice_packet_time = time.time()
        
        # 如果播放未启动且本地未录音，自动启动播放
        if self.audio_handler and not self.is_recording_local:
            self.audio_handler.playback_stop_flag = False
            if not self.audio_handler.is_playback_active():
                try:
                    self.audio_handler.start_playback()
                except Exception as e:
                    self.logger.error(f"启动播放失败: {e}")
                    return
            self.audio_handler.add_playback_data_immediate(pcm_data)
        elif self.is_recording_local:
            self.logger.debug(f"本地正在录音，忽略远端语音包播放 from {packet.get_callsign_ssid()}")
        
        # 调用回调函数
        if self.voice_callback:
            self.voice_callback(pcm_data, extra_info) if extra_info else self.voice_callback(pcm_data)
    
    def _handle_voice_packet(self, packet: NRLPacket):
        """处理G.711语音数据包 (Type=1)"""
        try:
            if not self._normalize_voice_data(packet, "G.711语音"):
                return
            
            # 根据数据包类型解码，不依赖本端codec设置
            pcm_data = self.voice_processor.decode_voice_by_type(packet.data, packet.packet_type)
            self._play_voice_pcm(pcm_data, packet)
            
            self.logger.debug(f"处理G.711语音数据包成功: {len(packet.data)} bytes from {packet.get_callsign_ssid()}")
        except Exception as e:
            self.logger.error(f"处理G.711语音数据包失败: {e}")
            self.logger.error(f"数据包信息: type={packet.packet_type}, callsign={packet.get_callsign_ssid()}, data_len={len(packet.data)}")
    
    def _handle_opus_voice_packet(self, packet: NRLPacket):
        """处理Opus语音数据包 (Type=8)"""
        try:
            if not self._normalize_voice_data(packet, "Opus语音"):
                return
            
            # 根据数据包类型解码
            pcm_data = self.voice_processor.decode_voice_by_type(packet.data, packet.packet_type)
            self._play_voice_pcm(pcm_data, packet)
            
            self.logger.debug(f"处理Opus语音数据包成功: {len(packet.data)} bytes from {packet.get_callsign_ssid()}")
        except Exception as e:
            self.logger.error(f"处理Opus语音数据包失败: {e}")
            self.logger.error(f"数据包信息: type={packet.packet_type}, callsign={packet.get_callsign_ssid()}, data_len={len(packet.data)}")
    
    def _handle_heartbeat_packet(self, packet: NRLPacket):
        """处理心跳数据包 心跳包只有头部，没有数据"""
        self._set_status_value('last_heartbeat', time.time())
        self.logger.debug(f"收到心跳包: {packet.get_callsign_ssid()}, DMRID: {packet.dmr_id.hex()}")
        
        # 验证心跳包格式
        if packet.data:
            self.logger.warning(f"心跳包包含数据: {len(packet.data)} 字节，不符合协议规范")
        
        if len(packet.dmr_id) != 3:
            self.logger.warning(f"心跳包DMRID长度异常: {len(packet.dmr_id)} 字节")
    
    def _handle_text_packet(self, packet: NRLPacket):
        """处理文本数据包 文本包长度=48+文本长度"""
        try:
            # 验证文本包格式
            if not packet.data:
                if not self.debug_force_decode:
                    self.logger.warning(f"收到空文本数据包 from {packet.get_callsign_ssid()}")
                    return
                else:
                    self.logger.info(f"[调试模式] 收到空文本数据包，强制解码 from {packet.get_callsign_ssid()}")
                    packet.data = b'[EmptyTXTPak]'
            elif self.debug_force_decode:
                # 调试模式：忽略长度检查，直接使用原始数据解码
                self.logger.debug(f"[调试模式] 文本包长度: {len(packet.data)} bytes，直接解码")
            
            text_data = packet.data.decode('utf-8', errors='ignore')
            parsed = parse_text_subtype(packet.data)
            message = {
                'type': 'text',
                'subtype': parsed['subtype'],
                'from': packet.get_callsign_ssid(),
                'data': text_data,
                'content': parsed['content'],
                'timestamp': time.time(),
                'length': len(packet.data)
            }
            
            # 位置消息额外解析坐标和地图链接
            if parsed['subtype'] == 'loc':
                lat, lng = parse_location_content(parsed['content'])
                message['lat'] = lat
                message['lng'] = lng
                message['map_url'] = generate_map_url(lat, lng)
            
            if self.message_callback:
                self.message_callback(message)
            
            self.logger.info(f"收到文本消息: {text_data} (长度: {len(packet.data)} 字节)")
            
        except Exception as e:
            self.logger.error(f"处理文本数据包失败: {e}")
            self.logger.error(f"数据包信息: type={packet.packet_type}, callsign={packet.get_callsign_ssid()}, data_len={len(packet.data)}")
    
    def _handle_server_voice_packet(self, packet: NRLPacket):
        """处理服务器互联语音包 - Type=9，包含原始呼号/IP信息"""
        try:
            self.logger.debug(f"收到服务器互联语音包: {packet.get_callsign_ssid()}, "
                           f"原始设备: {packet.original_callsign.decode('utf-8', errors='ignore')}-{packet.original_ssid}, "
                           f"原始IP: {'.'.join(str(b) for b in packet.original_ip)}")
            
            if not self._normalize_voice_data(packet, "服务器互联语音"):
                return
            
            # 根据数据包类型解码（Type=9使用G.711编码）
            pcm_data = self.voice_processor.decode_voice_by_type(packet.data, packet.packet_type)
            
            # 携带原始设备信息播放
            original_info = {
                'original_callsign': packet.original_callsign.decode('utf-8', errors='ignore').strip(),
                'original_ssid': packet.original_ssid,
                'original_ip': '.'.join(str(b) for b in packet.original_ip),
                'relay_callsign': packet.get_callsign_ssid()
            }
            self._play_voice_pcm(pcm_data, packet, original_info)
            
            self.logger.debug(f"处理服务器互联语音数据包成功: {len(packet.data)} bytes from {packet.get_callsign_ssid()}")
        except Exception as e:
            self.logger.error(f"处理服务器互联语音数据包失败: {e}")
            self.logger.error(f"数据包信息: type={packet.packet_type}, callsign={packet.get_callsign_ssid()}, data_len={len(packet.data)}")
    
    def _handle_join_group_response(self, packet: NRLPacket):
        """处理房间操作响应包 (Type=7)

        Subtype 1: 加入/切换房间响应
        Subtype 2: 房间列表响应
        """
        try:
            if not packet.data or len(packet.data) < 1:
                self.logger.warning("收到空的房间操作响应包")
                return

            subtype = packet.data[0]

            if subtype == 2 and self._group_list_pending:
                # 房间列表响应
                self._group_list_pending = False
                group_list = self.protocol.parse_group_list_response(packet.data)
                self.group_list = group_list
                self.logger.info(f"收到房间列表: 共 {len(group_list)} 个房间")
                for g in group_list:
                    self.logger.info(f"  房间 {g['id']}: {g['name']}")
                if self.group_list_callback:
                    self.group_list_callback(group_list)

            elif subtype == 1 and self._join_group_pending:
                # 加入房间响应
                self._join_group_pending = False
                group_id, group_name = self.protocol.parse_join_group_response(packet.data)
                if group_name == "error":
                    self.logger.warning(f"加入房间 {group_id} 失败: 服务器拒绝（可能无权限或房间不存在）")
                    if self.group_change_callback:
                        self.group_change_callback(-1, "error")
                else:
                    self.current_group_id = group_id
                    self.current_group_name = group_name
                    self.logger.info(f"已切换到房间: {group_id}-{group_name}")
                    self._update_status('current_group', f"{group_id}-{group_name}")
                    if self.group_change_callback:
                        self.group_change_callback(group_id, group_name)
            else:
                self.logger.debug(f"收到房间操作响应 (subtype={subtype})，无待处理请求")

        except Exception as e:
            self.logger.error(f"处理房间操作响应失败: {e}")
            self.logger.error(f"数据包信息: type={packet.packet_type}, data_len={len(packet.data) if packet.data else 0}")

    def request_group_list(self) -> bool:
        """请求服务器房间列表

        发送 Type=7, Subtype=2 的 UDP 包请求公共房间列表。
        结果通过 group_list_callback 回调返回，或直接访问 self.group_list。
        """
        if not self.is_connected:
            self.logger.warning("未连接到服务器，无法请求房间列表")
            return False

        try:
            packet = self.protocol.create_group_list_packet(
                self.device_config.callsign,
                self.device_config.ssid,
                dmr_id=self.device_config.dmr_id,
                dev_mode=self.device_config.model
            )
            self.socket.sendto(packet.encode(),
                             (self.server_config.host, self.server_config.port))
            self._group_list_pending = True
            self._inc_status('packets_sent')
            self.logger.info("已发送房间列表请求")
            return True
        except Exception as e:
            self.logger.error(f"发送房间列表请求失败: {e}")
            return False

    def join_group(self, group_id: int) -> bool:
        """加入/切换到指定房间

        发送 Type=7, Subtype=1 的 UDP 包请求切换房间。
        结果通过 group_change_callback 回调返回。
        """
        if not self.is_connected:
            self.logger.warning("未连接到服务器，无法切换房间")
            return False

        try:
            packet = self.protocol.create_join_group_packet(
                self.device_config.callsign,
                self.device_config.ssid,
                dmr_id=self.device_config.dmr_id,
                group_id=group_id,
                dev_mode=self.device_config.model
            )
            self.socket.sendto(packet.encode(),
                             (self.server_config.host, self.server_config.port))
            self._join_group_pending = True
            self._inc_status('packets_sent')
            self.logger.info(f"已发送加入房间请求: {group_id}")
            return True
        except Exception as e:
            self.logger.error(f"发送加入房间请求失败: {e}")
            return False

    def send_voice_data(self, voice_data: bytes) -> bool:
        """发送语音数据
        
        根据当前编码格式创建对应的数据包：
        - G.711 (Type=1): 160字节固定长度
        - Opus (Type=8): 变长编码
        使用状态位的bit0作为发送/接收标志
        有一个计数器用于包排序
        """
        try:
            if not self.is_connected:
                self.logger.warning("未连接到服务器，无法发送语音")
                return False
            
            if not voice_data:
                self.logger.warning("语音数据为空")
                return False
            
            # 根据编码格式创建对应的数据包
            codec = self.audio_config.codec
            if codec == 'opus':
                packet = self.protocol.create_opus_voice_packet(
                    self.device_config.callsign,
                    self.device_config.ssid,
                    dmr_id=self.device_config.dmr_id,
                    opus_data=voice_data,
                    dev_mode=self.device_config.model
                )
            else:
                packet = self.protocol.create_voice_packet(
                    self.device_config.callsign,
                    self.device_config.ssid,
                    dmr_id=self.device_config.dmr_id,
                    voice_data=voice_data,
                    dev_mode=self.device_config.model
                )
            
            if not packet:
                self.logger.error("语音包创建失败")
                return False
            
            # 发送数据包
            packet_data = packet.encode()
            
            if not packet_data or len(packet_data) == 0:
                self.logger.error("语音包编码失败")
                return False
            
            self.socket.sendto(packet_data, 
                             (self.server_config.host, self.server_config.port))
            
            self._inc_status('voice_packets_sent')
            self._inc_status('packets_sent')
            
            self.logger.debug(f"语音包已发送: {len(voice_data)} bytes, 总长度: {len(packet_data)} bytes")
            return True
            
        except BlockingIOError:
            # 非阻塞模式下发缓冲区满，丢弃当前包（实时音频可接受丢包）
            self.logger.debug("语音包发送缓冲区满，丢弃当前包")
            return False
        except socket.error as e:
            self.logger.error(f"语音数据发送失败（套接字错误）: {e}")
            return False
        except Exception as e:
            self.logger.error(f"发送语音数据失败: {e}")
            return False
    
    def send_text_message(self, message: str) -> bool:
        """发送文本消息 - 根据协议规范，文本包长度=48+文本长度
        """
        try:
            if not self.is_connected:
                self.logger.warning("未连接到服务器，无法发送文本消息")
                return False
            
            if not message or len(message) == 0:
                self.logger.warning("文本消息为空")
                return False
            
            # 编码文本消息（UTF-8）
            text_bytes = message.encode('utf-8')
            
            # 限制文本长度（参考78HAM的缓冲区大小1460字节）
            max_text_length = 1460 - 48  # 减去头部长度
            if len(text_bytes) > max_text_length:
                self.logger.warning(f"文本消息过长（{len(text_bytes)}字节），截断为{max_text_length}字节")
                text_bytes = text_bytes[:max_text_length]
            
            # 创建文本数据包
            packet = self.protocol.create_text_packet(
                self.device_config.callsign,
                self.device_config.ssid,
                dmr_id=self.device_config.dmr_id,
                text_data=text_bytes,
                dev_mode=self.device_config.model
            )
            
            # 发送数据包
            packet_data = packet.encode()
            self.socket.sendto(packet_data, 
                             (self.server_config.host, self.server_config.port))
            
            self._inc_status('packets_sent')
            self.logger.info(f"文本消息已发送: {message} (长度: {len(text_bytes)} 字节)")
            return True
            
        except BlockingIOError:
            self.logger.warning("文本消息发送缓冲区满，发送失败")
            return False
        except socket.error as e:
            self.logger.error(f"文本消息发送失败（套接字错误）: {e}")
            return False
        except Exception as e:
            self.logger.error(f"发送文本消息失败: {e}")
            return False
    
    def send_location_message(self, lat: float, lng: float) -> bool:
        """发送位置消息（[loc] 子类型）

        将坐标格式化为 [loc]lat,lng 并作为 Type=5 文本消息发送。
        """
        if not self.is_connected:
            self.logger.warning("未连接到服务器，无法发送位置消息")
            return False
        if lat == 0.0 and lng == 0.0:
            self.logger.warning("坐标无效，无法发送位置消息")
            return False
        loc_msg = format_location_message(lat, lng)
        return self.send_text_message(loc_msg)
    
    def get_current_location(self) -> tuple:
        """获取当前位置（阻塞调用，建议在子线程中使用）

        返回: (lat: float, lng: float, source: str)
        source: "gps" / "ip" / "unavailable"
        """
        return LocationProvider.get_location()

    def resolve_location(self) -> tuple:
        """解析最终可用位置：GPS → IP → 默认配置

        返回: (lat: float, lng: float, source: str)
        source: "gps" / "ip" / "default" / "unavailable"
        """
        lat, lng, source = self.get_current_location()
        if lat != 0.0 or lng != 0.0:
            return (lat, lng, source)
        # 尝试使用默认配置
        if self.location_config and (self.location_config.default_lat != 0.0 or self.location_config.default_lng != 0.0):
            return (self.location_config.default_lat, self.location_config.default_lng, "default")
        return (0.0, 0.0, "unavailable")
    
    def send_heartbeat(self) -> bool:
        """发送心跳包
        心跳包48字节

        参数：
        - SSID: 200（服务器连接标记）这个如果不是服务器不需要设置，还是自己的SSID
        - Type: 2（TYPE_HEARTBEAT）

        """
        try:
            if not self.is_connected or not self.socket:
                return False
            
            # 创建心跳包
            packet = self.protocol.create_heartbeat_packet(
                self.device_config.callsign,
                self.device_config.ssid,  # 使用设备配置的SSID
                dmr_id=self.device_config.dmr_id,
                dev_mode=self.device_config.model   # 设备模式
            )
            
            if not packet:
                self.logger.error("心跳包创建失败")
                return False
            
            packet_data = packet.encode()
            
            if not packet_data or len(packet_data) == 0:
                self.logger.error("心跳包编码失败")
                return False
            
            # 发送心跳包
            self.socket.sendto(packet_data, 
                             (self.server_config.host, self.server_config.port))
            
            self._inc_status('packets_sent')
            self.logger.debug(f"心跳包已发送: {packet.get_callsign_ssid()}, "
                            f"DMRID: {packet.dmr_id.hex()}, 长度: {len(packet_data)} bytes")
            return True
            
        except BlockingIOError:
            self.logger.debug("心跳包发送缓冲区满，跳过本次心跳")
            return False
        except socket.error as e:
            self.logger.error(f"心跳包发送失败（套接字错误）: {e}")
            return False
        except Exception as e:
            self.logger.error(f"发送心跳包失败: {e}")
            return False
    
    def start_voice_transmission(self) -> bool:
        """开始语音传输"""
        try:
            if not self.is_connected:
                self.logger.warning("未连接到服务器")
                return False
            
            if not self.audio_handler:
                self.logger.error("音频处理器未初始化")
                return False
            
            # 标记本地正在录音，禁用自动播放
            self.is_recording_local = True
            
            # 开始录音并设置回调
            def audio_callback(pcm_data):
                # 编码语音数据
                g711_data = self.voice_processor.encode_voice(pcm_data)
                
                # 发送语音数据
                if g711_data:
                    self.send_voice_data(g711_data)
            
            self.audio_handler.start_recording(audio_callback)
            
            self.logger.info("语音传输已启动")
            return True
            
        except Exception as e:
            self.logger.error(f"启动语音传输失败: {e}")
            self.is_recording_local = False  # 失败时重置标志
            return False
    
    def stop_voice_transmission(self):
        """停止语音传输"""
        try:
            # 取消本地录音标志，恢复自动播放
            self.is_recording_local = False
            
            if self.audio_handler:
                self.audio_handler.stop_recording()
                # 保持播放开启以接收其他设备的语音
            
            self.logger.info("语音传输已停止")
            
        except Exception as e:
            self.logger.error(f"停止语音传输失败: {e}")
    
    def set_codec(self, codec_type: str) -> bool:
        """运行时切换发射编码格式（自动保存到配置文件）
        
        接收端不受影响，会根据数据包Type字段自动识别并解码。
        
        Args:
            codec_type: "g711" 或 "opus"
            
        Returns:
            切换是否成功
        """
        if codec_type not in ("g711", "opus"):
            self.logger.error(f"不支持的编码格式: {codec_type}")
            return False
        
        if codec_type == self.audio_config.codec:
            return True  # 已经是目标格式
        
        # Opus需要opuslib支持
        if codec_type == "opus" and not OpusCodec.is_available():
            self.logger.error("opuslib 未安装，无法使用Opus编码")
            return False
        
        # 确保不在录音中切换
        if self.is_recording_local:
            self.logger.warning("录音中无法切换编码格式，请先停止PTT")
            return False
        
        try:
            # 更新配置
            self.audio_config.codec = codec_type
            
            # 更新采样率
            if codec_type == 'opus':
                self.audio_config.sample_rate = 16000
                chunk_size = 640
            else:
                self.audio_config.sample_rate = 8000
                chunk_size = 320
            
            # 更新音频处理器
            if self.audio_handler:
                self.audio_handler.stop_playback()
                self.audio_handler.close()
                self.audio_handler = AudioHandler(
                    sample_rate=self.audio_config.sample_rate,
                    channels=self.audio_config.channels,
                    chunk_size=chunk_size,
                    format_str=self.audio_config.format,
                    codec_type=codec_type
                )
            
            # 更新语音处理器
            if self.voice_processor:
                self.voice_processor.set_codec(codec_type)
            
            self.logger.info(f"语音编码格式已切换为: {codec_type} (采样率: {self.audio_config.sample_rate}Hz)")
            
            # 持久化到配置文件
            self.save_config()
            
            return True
            
        except Exception as e:
            self.logger.error(f"切换编码格式失败: {e}")
            return False
    
    def get_device_info(self) -> Dict[str, Any]:
        """获取设备信息"""
        return {
            'callsign': self.device_config.callsign,
            'ssid': self.device_config.ssid,
            'dmr_id': self.device_config.dmr_id,
            'model': self.device_config.model,
            'online': self.is_connected,
            'status': self.device_status
        }
    
    def get_audio_buffer_status(self) -> Dict[str, Any]:
        """获取音频缓冲区状态（用于 GUI 监控）"""
        if self.audio_handler:
            return self.audio_handler.get_buffer_status()
        return {
            'play_depth': 0,
            'play_ms': 0,
            'record_cache_bytes': 0,
            'is_playing': False,
            'is_recording': False,
        }
    
    def get_status(self) -> Dict[str, Any]:
        """获取客户端状态"""
        return {
            'connected': self.is_connected,
            'running': self.running,
            'device_info': self.get_device_info(),
            'audio_active': self.audio_handler.is_recording_active() if self.audio_handler else False,
            'server': f"{self.server_config.host}:{self.server_config.port}" if self.server_config else None
        }
    
    def _update_status(self, key: str, value: Any):
        """更新状态并调用回调"""
        if self.status_callback:
            try:
                self.status_callback(key, value)
            except Exception as e:
                self.logger.error(f"状态回调错误: {e}")
    
    def set_message_callback(self, callback: Callable[[Dict], None]):
        """设置消息回调"""
        self.message_callback = callback
    
    def set_voice_callback(self, callback: Callable[[bytes], None]):
        """设置语音回调"""
        self.voice_callback = callback
    
    def set_status_callback(self, callback: Callable[[str, Any], None]):
        """设置状态回调"""
        self.status_callback = callback
    
    def enable_debug_force_decode(self, enable: bool = True):
        """启用/禁用调试模式：强制解码空包
        
        Args:
            enable: True 启用调试模式，False 禁用
        """
        self.debug_force_decode = enable
        status = "已启用" if enable else "已禁用"
        self.logger.info(f"调试模式强制解码空包 {status}")
    
    def close(self):
        """关闭客户端"""
        self.logger.info("正在关闭78HAM客户端...")
        
        # 先停止语音传输（停止录音 + 重置本地录音标志）
        try:
            self.stop_voice_transmission()
        except Exception as e:
            self.logger.error(f"停止语音传输异常: {e}")
        
        # 断开服务器连接（设置 running=False，等待线程退出，关闭 socket）
        try:
            self.disconnect()
        except Exception as e:
            self.logger.error(f"断开连接异常: {e}")
        
        # 关闭音频处理（安全停止录制/播放 + 终止 PyAudio）
        try:
            if self.audio_handler:
                self.audio_handler.close()
        except Exception as e:
            self.logger.error(f"关闭音频异常: {e}")
        
        self.logger.info("78HAM客户端已关闭")
    
    def get_servers_list(self) -> list[ServerInfo]:
        """获取服务器列表"""
        return self.servers_list.copy()
    
    def get_current_server_info(self) -> Optional[ServerInfo]:
        """获取当前服务器信息"""
        if 0 <= self.current_server_index < len(self.servers_list):
            return self.servers_list[self.current_server_index]
        return None
    
    def switch_server(self, server_index: int) -> bool:
        """切换服务器
        
        Args:
            server_index: 服务器索引
            
        Returns:
            True: 切换成功，False: 切换失败
        """
        try:
            if not (0 <= server_index < len(self.servers_list)):
                self.logger.error(f"无效的服务器索引: {server_index}")
                return False
            
            # 如果正在连接，先断开
            was_connected = self.is_connected
            if was_connected:
                self.logger.info("正在断开当前连接...")
                self.disconnect()
                time.sleep(0.5)  # 等待断开完成
            
            # 切换服务器
            old_server = self.servers_list[self.current_server_index]
            self.current_server_index = server_index
            new_server = self.servers_list[self.current_server_index]
            
            # 更新服务器配置
            self.server_config.host = new_server.host
            self.server_config.port = new_server.port
            
            self.logger.info(f"服务器已切换: {old_server.name} -> {new_server.name}")
            self.logger.info(f"新服务器地址: {new_server.host}:{new_server.port}")
            
            # 如果为连接状态，尝试重连
            if was_connected:
                self.logger.info("正在重新连接新服务器...")
                return self.connect()
            
            return True
            
        except Exception as e:
            self.logger.error(f"切换服务器失败: {e}")
            return False