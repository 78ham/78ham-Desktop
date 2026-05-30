"""
NRL2 协议数据结构定义

纯数据结构，不包含业务逻辑。
协议头部 48 字节固定格式，数据部分变长。
"""
import sys
import struct
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, Union


class PacketType(IntEnum):
    """NRL2 数据包类型"""
    VOICE = 1           # G.711 语音数据
    HEARTBEAT = 2       # 心跳包
    CONFIG = 3          # 设备配置
    TEXT = 5            # 文本消息
    CONTROL = 6         # 设备控制
    JOIN_GROUP = 7      # 加入群组
    OPUS = 8            # Opus 16K 语音
    SERVER_VOICE = 9    # 服务器互联语音（后续版本废弃）
    AT = 11             # AT 命令透传


class DevModel(IntEnum):
    """设备型号标识"""
    WECHAT_MP = 100     # 微信小程序
    ANDROID = 101       # Android
    IOS = 102           # iOS
    WINDOWS = 103       # Windows 桌面
    LINUX = 104         # Linux 桌面
    BROWSER = 105       # 浏览器
    EMERGENCY = 106     # 紧急设备
    SERVER = 200        # 服务器
    BM_GATEWAY = 201    # BM 网关
    NANNY = 250         # 监控设备
    FULL_NETWORK = 255  # 全网


def get_default_dev_model() -> int:
    """根据当前平台返回默认设备型号"""
    platform_map = {
        'win32': DevModel.WINDOWS,
        'linux': DevModel.LINUX,
        'darwin': DevModel.WINDOWS,  # macOS 暂用 Windows 标识
    }
    return platform_map.get(sys.platform, DevModel.WINDOWS)


class TextSubtype:
    """文本消息子类型前缀（与服务端 decode.go 规范一致）"""
    TEXT = "text"
    LOC = "loc"
    JSON = "json"
    XML = "xml"
    HTML = "html"
    BIN = "bin"
    IMG = "img"
    VIDEO = "video"
    AUDIO = "audio"

    # 前缀 → 子类型映射
    PREFIXES = {
        "[text]": "text",
        "[loc]": "loc",
        "[json]": "json",
        "[xml]": "xml",
        "[html]": "html",
        "[bin]": "bin",
        "[img]": "img",
        "[video]": "video",
        "[audio]": "audio",
    }


# 协议常量
PROTOCOL_VERSION = b"NRL2"
HEADER_SIZE = 48
DEFAULT_HEARTBEAT_INTERVAL = 2  # 秒（与安卓/小程序一致）
MAX_TEXT_LENGTH = 1460 - HEADER_SIZE  # 最大文本长度


# 呼号验证字符集（预计算，避免重复 ord() 调用）
_VALID_CALLSIGN_BYTES = frozenset(
    b for b in (b'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
)


@dataclass
class NRLHeader:
    """NRL2 协议头部（48 字节）

    偏移  长度  字段
    0-3   4    版本 "NRL2"
    4-5   2    总长度（大端序）
    6-8   3    DMRID
    9-19  11   密码
    20    1    数据包类型
    21    1    状态（bit0=DCD/PTT）
    22-23 2    计数器（大端序）
    24-29 6    呼号
    30    1    SSID
    31    1    设备模式
    32-37 6    原始呼号（Type=9 或 DevModel=200/255）
    38    1    原始 SSID
    39-42 4    原始 IP
    43-47 5    保留
    """
    version: bytes = field(default=PROTOCOL_VERSION)
    length: int = 0
    dmr_id: bytes = field(default=b"\x00\x00\x00")
    password: bytes = field(default=b"\x00" * 11)
    packet_type: int = 0
    status: int = 0x01
    count: int = 0
    callsign: bytes = field(default=b"\x00" * 6)
    ssid: int = 0
    dev_mode: int = field(default_factory=get_default_dev_model)
    original_callsign: bytes = field(default=b"\x00" * 6)
    original_ssid: int = 0
    original_ip: bytes = field(default=b"\x00" * 4)

    def get_callsign_str(self) -> str:
        """获取呼号字符串（去除填充）"""
        return self.callsign.rstrip(b'\x00').decode('utf-8', errors='ignore').strip()

    def get_callsign_ssid(self) -> str:
        """获取 呼号-SSID 组合字符串"""
        return f"{self.get_callsign_str()}-{self.ssid}"

    def has_extended_fields(self) -> bool:
        """是否包含扩展字段（原始呼号/IP）"""
        return (self.packet_type == PacketType.SERVER_VOICE or
                self.dev_mode in (DevModel.SERVER, DevModel.FULL_NETWORK))


@dataclass
class NRLPacket:
    """NRL2 完整数据包 = 头部 + 数据"""
    header: NRLHeader = field(default_factory=NRLHeader)
    data: bytes = b""
    addr: Optional[tuple] = None        # 来源地址（接收时记录）
    timestamp: float = field(default_factory=time.time)

    @property
    def packet_type(self) -> int:
        return self.header.packet_type

    @property
    def callsign_ssid(self) -> str:
        return self.header.get_callsign_ssid()

    def is_voice(self) -> bool:
        """是否为语音类型包"""
        return self.header.packet_type in (
            PacketType.VOICE, PacketType.OPUS, PacketType.SERVER_VOICE
        )

    def is_transmitting(self) -> bool:
        """状态位 bit0 是否为发送模式"""
        return bool(self.header.status & 0x01)

    def __str__(self) -> str:
        return (f"NRLPacket(type={self.header.packet_type}, "
                f"callsign={self.callsign_ssid}, "
                f"dmr_id={self.header.dmr_id.hex()}, "
                f"data_len={len(self.data)})")


def is_valid_callsign(callsign: Union[str, bytes, None]) -> bool:
    """验证呼号格式，与服务端 IsCallSign 保持一致

    呼号只能包含大写字母 A-Z 和数字 0-9
    
    Args:
        callsign: 呼号字符串或字节串
        
    Returns:
        呼号是否有效
    """
    if not callsign:
        return False
    
    # 统一转为 bytes 处理
    if isinstance(callsign, str):
        try:
            callsign = callsign.encode('ascii')
        except UnicodeEncodeError:
            return False
    
    # 使用预计算的字符集进行快速验证
    return all(b in _VALID_CALLSIGN_BYTES for b in callsign)
