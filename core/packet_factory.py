"""
数据包工厂

负责创建各种类型的 NRL2 数据包。
"""
import struct
import threading
from typing import Optional

from .protocol import (
    NRLHeader, NRLPacket, PacketType, DevModel,
    PROTOCOL_VERSION, HEADER_SIZE, get_default_dev_model, is_valid_callsign
)

class PacketFactory:
    """NRL2 数据包工厂

    维护全局包计数器，创建各种类型的数据包。
    """

    # 语音数据固定大小
    VOICE_FRAME_SIZE = 160
    SILENCE_FRAME = b'\xD5' * VOICE_FRAME_SIZE

    def __init__(self):
        self._packet_count = 0
        self._count_lock = threading.Lock()

    def _next_count(self) -> int:
        """获取下一个包计数器值"""
        with self._count_lock:
            count = self._packet_count
            self._packet_count = (self._packet_count + 1) & 0xFFFF
            return count

    @staticmethod
    def parse_dmr_id_hex(dmr_id: str) -> bytes:
        """将 DMR ID 转为协议要求的 3 字节无符号整数。

        配置中的普通值（例如 ``123456``）是十进制，只有显式带
        ``0x`` 前缀的值才按十六进制解析。
        """
        if not dmr_id:
            return b'\x00' * 3

        clean = str(dmr_id).strip().replace(' ', '')
        try:
            value = int(clean, 16) if clean.lower().startswith('0x') else int(clean, 10)
        except ValueError:
            return b'\x00' * 3
        if not 0 <= value <= 0xFFFFFF:
            return b'\x00' * 3
        return value.to_bytes(3, 'big')

    def _make_header(self, callsign: str, ssid: int, dmr_id: str,
                     packet_type: int, dev_mode: Optional[int] = None,
                     status: int = 0x01, count: Optional[int] = None,
                     password: str = "") -> NRLHeader:
        """创建通用头部"""
        if dev_mode is None:
            dev_mode = get_default_dev_model()
        
        # 呼号编码和填充
        callsign = callsign.strip().upper()
        if not is_valid_callsign(callsign):
            raise ValueError(f"无效呼号: {callsign!r}")
        callsign_bytes = callsign.encode('ascii').ljust(6, b'\x00')
        
        return NRLHeader(
            version=PROTOCOL_VERSION,
            packet_type=packet_type,
            callsign=callsign_bytes,
            ssid=ssid,
            dmr_id=self.parse_dmr_id_hex(dmr_id),
            password=(password or '').encode('utf-8')[:11].ljust(11, b'\x00'),
            dev_mode=dev_mode,
            status=status,
            count=count if count is not None else self._next_count(),
        )

    @staticmethod
    def _pad_voice_data(voice_data: bytes) -> bytes:
        """填充语音数据到固定大小"""
        if not voice_data or len(voice_data) == 0:
            return PacketFactory.SILENCE_FRAME
        
        data_len = len(voice_data)
        if data_len < PacketFactory.VOICE_FRAME_SIZE:
            return voice_data.ljust(PacketFactory.VOICE_FRAME_SIZE, b'\xD5')
        elif data_len > PacketFactory.VOICE_FRAME_SIZE:
            return voice_data[:PacketFactory.VOICE_FRAME_SIZE]
        
        return voice_data

    def create_heartbeat(self, callsign: str, ssid: int, dmr_id: str = "",
                         dev_mode: Optional[int] = None, *,
                         password: str = "") -> NRLPacket:
        """创建心跳包（仅头部，无数据）"""
        header = self._make_header(
            callsign, ssid, dmr_id,
            packet_type=PacketType.HEARTBEAT,
            dev_mode=dev_mode,
            count=1,  # 心跳包计数器固定为 1（与 Go 版本一致）
            password=password,
        )
        return NRLPacket(header=header, data=b"")

    def create_voice(self, callsign: str, ssid: int, dmr_id: str,
                     voice_data: bytes, dev_mode: int = DevModel.WINDOWS, *,
                     password: str = "") -> NRLPacket:
        """创建 G.711 语音包 (Type=1)

        voice_data: 160 字节 G.711 A-law 编码数据
        """
        voice_data = self._pad_voice_data(voice_data)
        
        header = self._make_header(
            callsign, ssid, dmr_id,
            packet_type=PacketType.VOICE,
            dev_mode=dev_mode,
            password=password,
        )
        return NRLPacket(header=header, data=voice_data)

    def create_opus_voice(self, callsign: str, ssid: int, dmr_id: str,
                          opus_data: bytes, dev_mode: int = DevModel.WINDOWS, *,
                          password: str = "") -> NRLPacket:
        """创建 Opus 语音包 (Type=8)

        opus_data: 变长 Opus 编码数据
        """
        header = self._make_header(
            callsign, ssid, dmr_id,
            packet_type=PacketType.OPUS,
            dev_mode=dev_mode,
            password=password,
        )
        return NRLPacket(header=header, data=opus_data or b'')

    def create_text(self, callsign: str, ssid: int, dmr_id: str,
                    text_data: bytes, dev_mode: int = DevModel.WINDOWS, *,
                    password: str = "") -> NRLPacket:
        """创建文本消息包 (Type=5)"""
        header = self._make_header(
            callsign, ssid, dmr_id,
            packet_type=PacketType.TEXT,
            dev_mode=dev_mode,
            password=password,
        )
        return NRLPacket(header=header, data=text_data)

    def create_group_list_request(self, callsign: str, ssid: int, dmr_id: str,
                                  dev_mode: Optional[int] = None, *,
                                  password: str = "") -> NRLPacket:
        """创建获取房间列表请求包 (Type=7, Subtype=2)"""
        header = self._make_header(
            callsign, ssid, dmr_id,
            packet_type=PacketType.JOIN_GROUP,
            dev_mode=dev_mode,
            password=password,
        )
        return NRLPacket(header=header, data=b'\x02')

    def create_join_group(self, callsign: str, ssid: int, dmr_id: str,
                          group_id: int, dev_mode: int = DevModel.WINDOWS, *,
                          password: str = "") -> NRLPacket:
        """创建加入/切换房间请求包 (Type=7, Subtype=1)

        data[0] = 1 (切换组指令), data[1:5] = group_id (big-endian uint32)
        """
        if not (0 <= group_id <= 0xFFFFFFFF):
            raise ValueError(f"group_id 超出范围: {group_id}，有效范围 0-4294967295")
        
        header = self._make_header(
            callsign, ssid, dmr_id,
            packet_type=PacketType.JOIN_GROUP,
            dev_mode=dev_mode,
            password=password,
        )
        data = b'\x01' + struct.pack('>I', group_id)
        return NRLPacket(header=header, data=data)

    def create_server_voice(self, callsign: str, ssid: int, dmr_id: str,
                            voice_data: bytes, original_callsign: str,
                            original_ssid: int, original_ip: bytes,
                            dev_mode: Optional[int] = None, *,
                            password: str = "") -> NRLPacket:
        """创建服务器互联语音包 (Type=9)"""
        voice_data = self._pad_voice_data(voice_data)
        
        header = self._make_header(
            callsign, ssid, dmr_id,
            packet_type=PacketType.SERVER_VOICE,
            dev_mode=dev_mode,
            password=password,
        )
        header.original_callsign = original_callsign.encode('utf-8').ljust(6, b'\x00')[:6]
        header.original_ssid = original_ssid
        header.original_ip = original_ip[:4] if len(original_ip) >= 4 else b'\x00' * 4

        return NRLPacket(header=header, data=voice_data)

    @staticmethod
    def encode_packet(packet: NRLPacket) -> bytes:
        """将 NRLPacket 编码为网络字节流"""
        h = packet.header
        data_len = len(packet.data) if packet.data else 0
        total_length = HEADER_SIZE + data_len
        if total_length > 0xFFFF:
            raise ValueError(f"数据包过大: {total_length} 字节")

        header_buf = bytearray(HEADER_SIZE)

        # 协议版本 (4 字节)
        header_buf[0:4] = PROTOCOL_VERSION

        # 总长度 (2 字节, 大端序)
        struct.pack_into(">H", header_buf, 4, total_length)

        # DMRID (3 字节)
        header_buf[6:9] = h.dmr_id[:3].ljust(3, b'\x00')

        # 密码 (11 字节)
        header_buf[9:20] = h.password[:11].ljust(11, b'\x00')

        # 数据包类型 (1 字节)
        header_buf[20] = h.packet_type

        # 状态 (1 字节)
        header_buf[21] = h.status

        # 计数器 (2 字节, 大端序)
        struct.pack_into(">H", header_buf, 22, h.count)

        # 呼号 (6 字节)
        if isinstance(h.callsign, str):
            callsign_bytes = h.callsign.encode('utf-8').ljust(6, b'\x00')[:6]
        else:
            callsign_bytes = h.callsign.ljust(6, b'\x00')[:6]
        header_buf[24:30] = callsign_bytes

        # SSID (1 字节)
        header_buf[30] = h.ssid

        # 设备模式 (1 字节)
        header_buf[31] = h.dev_mode

        # 扩展字段 (Type=9 或 DevModel=200/255)
        if h.has_extended_fields():
            if isinstance(h.original_callsign, str):
                orig = h.original_callsign.encode('utf-8').ljust(6, b'\x00')[:6]
            else:
                orig = h.original_callsign.ljust(6, b'\x00')[:6]
            header_buf[32:38] = orig
            header_buf[38] = h.original_ssid
            header_buf[39:43] = h.original_ip[:4] if len(h.original_ip) >= 4 else b'\x00' * 4
        else:
            header_buf[32:43] = b'\x00' * 11

        # 保留字段 (5 字节)
        header_buf[43:48] = b'\x00' * 5

        # 拼接数据
        if data_len > 0:
            return bytes(header_buf) + packet.data
        return bytes(header_buf)
