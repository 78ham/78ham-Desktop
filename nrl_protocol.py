"""
78HAM协议处理模块
基于78HAM项目的协议格式实现
"""
import struct
import time
import socket
import logging
from typing import Optional, Tuple

class NRLPacket:
    """78HAM协议数据包类"""
    
    # 协议常量
    PROTOCOL_VERSION = b"NRL2"
    HEADER_SIZE = 48
    
    # 数据类型
    TYPE_VOICE = 1      # G.711语音数据
    TYPE_HEARTBEAT = 2  # 心跳包
    TYPE_CONFIG = 3     # 设备配置
    TYPE_TEXT = 5       # 文本消息
    TYPE_CONTROL = 6    # 设备控制
    TYPE_JOIN_GROUP = 7 # 加入群组
    TYPE_OPUS = 8       # Opus 16K语音 (服务端新增)
    TYPE_SERVER_VOICE = 9 # 服务器互联语音 (后续版本废弃)
    TYPE_AT = 11        # AT命令透传 (服务端新增)
    
    def __init__(self):
        self.timestamp = time.time()
        self.udp_addr = None
        self.version = self.PROTOCOL_VERSION
        self.length = 0
        self.dmr_id = b"\x00" * 3  # DMRID (3字节)
        self.password = b"\x00" * 11  # 密码 (11字节)
        self.packet_type = 0
        self.status = 0x01  # 状态 (0x01表示在线)
        self.count = 0
        self.callsign = b"" * 6
        self.ssid = 0
        self.dev_mode = 0x10  # 设备模式 (0保留，1-99硬件，100-199软件，200-255服务器特殊用途)
        self.original_callsign = b"" * 6
        self.original_ssid = 0
        self.original_ip = b"\x00" * 4
        self.data = b""
    
    def encode(self) -> bytes:
        """编码数据包 - 严格按照NRL21协议规范"""
        # 计算总长度
        data_len = len(self.data) if self.data else 0
        total_length = 48 + data_len
        
        # 构建头部
        header = bytearray(48)
        
        # 协议版本 (4字节) - 固定为NRL2
        header[0:4] = b'NRL2'
        
        # 总长度（2字节，大端序）
        struct.pack_into(">H", header, 4, total_length)
        
        # DMRID（3字节）- 设备唯一标识
        header[6:9] = self.dmr_id.ljust(3, b'\x00')[:3]
        
        # 密码（11字节）
        header[9:20] = self.password.ljust(11, b'\x00')[:11]
        
        # 数据包类型（1字节）
        header[20] = self.packet_type
        
        # 状态（1字节）- 根据协议规范，bit0用作DCD/PTT标志
        header[21] = self.status if self.status else 0x01
        
        # 计数器（2字节，大端序）- 根据协议规范，计数器在偏移22-23
        struct.pack_into(">H", header, 22, self.count)
        
        # 呼号（6字节）
        if isinstance(self.callsign, str):
            callsign_bytes = self.callsign.encode('utf-8').ljust(6, b'\x00')[:6]
        else:
            callsign_bytes = self.callsign.ljust(6, b'\x00')[:6]
        header[24:30] = callsign_bytes
        
        # SSID（1字节）
        header[30] = self.ssid
        
        # 设备模式（1字节）
        header[31] = self.dev_mode if self.dev_mode else 0x10
        
        # 服务器互联语音包（Type=9）或特殊设备（DevModel=200/255）的额外字段
        if (self.packet_type == NRLPacket.TYPE_SERVER_VOICE or 
            self.dev_mode == 200 or self.dev_mode == 255):
            # 原始呼号（6字节）
            if isinstance(self.original_callsign, str):
                orig_callsign_bytes = self.original_callsign.encode('utf-8').ljust(6, b'\x00')[:6]
            else:
                orig_callsign_bytes = self.original_callsign.ljust(6, b'\x00')[:6]
            header[32:38] = orig_callsign_bytes
            
            # 原始SSID（1字节）
            header[38] = self.original_ssid
            
            # 原始IP（4字节）
            if len(self.original_ip) >= 4:
                header[39:43] = self.original_ip[:4]
            else:
                header[39:43] = b'\x00' * 4
        else:
            # 其他类型包，这些字段填充为0
            header[32:38] = b'\x00' * 6
            header[38] = 0
            header[39:43] = b'\x00' * 4
        
        # 保留字段（5字节）显式清零
        header[43:48] = b'\x00' * 5
        
        # 数据部分
        if data_len > 0:
            return bytes(header) + self.data
        else:
            return bytes(header)
    
    def decode(self, data: bytes) -> bool:
        """解码数据包 - 严格按照NRL21协议规范"""
        if len(data) < self.HEADER_SIZE:
            return False
        
        try:
            # 检查版本
            self.version = data[0:4]
            if self.version != self.PROTOCOL_VERSION:
                return False
            
            # 解析长度
            self.length = struct.unpack(">H", data[4:6])[0]
            
            # 检查数据长度
            if len(data) < self.length:
                # 报文不完整，无法解析
                import logging
                logging.getLogger(__name__).debug(
                    f"数据包不完整: 期望 {self.length} 字节，实际 {len(data)} 字节")
                return False
            
            # DMRID (3字节) - 设备唯一标识
            self.dmr_id = data[6:9]
            
            # 密码 (11字节)
            self.password = data[9:20]
            
            # 类型
            self.packet_type = data[20]
            
            # 状态 - 根据协议规范，bit0用作DCD/PTT标志
            self.status = data[21]
            
            # 计数器 - 根据协议规范，计数器在偏移22-23
            self.count = struct.unpack(">H", data[22:24])[0]
            
            # 呼号
            callsign_bytes = data[24:30]
            self.callsign = callsign_bytes.rstrip(b'\x00').rstrip(b'\r')
            
            # 呼号有效性验证，与服务端 IsCallSign 保持一致
            if not self.is_valid_callsign(self.callsign):
                return False
            
            # SSID
            self.ssid = data[30]
            
            # 设备模式
            self.dev_mode = data[31]
            
            # 服务器互联语音包（Type=9）或特殊设备（DevModel=200/255）的额外字段
            if (self.packet_type == NRLPacket.TYPE_SERVER_VOICE or 
                self.dev_mode == 200 or self.dev_mode == 255):
                # 原始呼号
                orig_callsign_bytes = data[32:38]
                self.original_callsign = orig_callsign_bytes.rstrip(b'\x00').rstrip(b'\r')
                
                # 原始SSID
                self.original_ssid = data[38]
                
                # 原始IP
                self.original_ip = data[39:43]
            else:
                # 其他类型包，这些字段填充为0
                self.original_callsign = b""
                self.original_ssid = 0
                self.original_ip = b"\x00" * 4
            
            # 数据部分
            # 新版服务端：Length 字段正确，严格按 Length 截取
            # 旧版服务端：Length 字段可能仅填头部长度(48)甚至为 0，
            #   但 UDP 包中头部后面仍然携带了语音数据。
            #   Go 服务端解码直接用 d[48:]，不看 Length 字段。
            #   客户端对语音类型包做兼容：Length <= HEADER_SIZE 时回退取剩余数据。
            if self.length > self.HEADER_SIZE:
                self.data = data[self.HEADER_SIZE:self.length]
            elif (self.packet_type in (NRLPacket.TYPE_VOICE,
                                       NRLPacket.TYPE_OPUS,
                                       NRLPacket.TYPE_SERVER_VOICE)
                  and len(data) > self.HEADER_SIZE):
                # 兼容旧版服务端：Length 异常但实际携带了语音数据
                import logging
                logging.getLogger(__name__).debug(
                    f"旧版语音包兼容: Type={self.packet_type}, "
                    f"Length={self.length}, 实际数据={len(data) - self.HEADER_SIZE}字节")
                self.data = data[self.HEADER_SIZE:]
            else:
                self.data = b""
            
            return True
            
        except (struct.error, IndexError) as e:
            import logging
            logging.getLogger(__name__).debug(f"解码错误: {e}")
            return False
    
    @staticmethod
    def is_valid_callsign(callsign: bytes) -> bool:
        """验证呼号格式，与服务端 IsCallSign 保持一致
        
        呼号只能包含大写字母 A-Z 和数字 0-9
        """
        if not callsign:
            return False
        for b in callsign:
            # bytes 迭代已是整数，无需 ord()
            if not ((ord('A') <= b <= ord('Z')) or (ord('0') <= b <= ord('9'))):
                return False
        return True
    
    def get_callsign_ssid(self) -> str:
        """获取呼号和SSID组合字符串"""
        try:
            callsign_str = self.callsign.decode('utf-8', errors='ignore').strip()
            return f"{callsign_str}-{self.ssid}"
        except:
            return f"UNKNOWN-{self.ssid}"
    
    def __str__(self) -> str:
        return (f"NRLPacket(version={self.version}, type={self.packet_type}, "
                f"callsign={self.get_callsign_ssid()}, dmr_id={self.dmr_id.hex()})")


class NRLProtocol:
    """78HAM协议处理类"""
    
    def __init__(self):
        self.packet_count = 0
    
    @staticmethod
    def _parse_dmr_id_hex(dmr_id: str) -> bytes:
        """将DMRID十六进制字符串转换为3字节
        
        DMRID由用户自行申请，直接使用配置中的十六进制值。
        """
        if not dmr_id:
            return b'\x00' * 3
        # 去除可能的前导空格，取前6位十六进制字符
        clean = dmr_id.strip()
        if len(clean) >= 6 and all(c in '0123456789abcdefABCDEF' for c in clean[:6]):
            return bytes.fromhex(clean[:6])
        # 如果格式不对，尝试填充到6位
        clean = clean.replace(' ', '')
        if len(clean) < 6:
            clean = clean.zfill(6)
        if all(c in '0123456789abcdefABCDEF' for c in clean[:6]):
            return bytes.fromhex(clean[:6])
        return b'\x00' * 3
    
    def create_voice_packet(self, callsign: str, ssid: int, dmr_id: str, 
                          voice_data: bytes, dev_mode: int = 1) -> NRLPacket:
        """创建语音数据包 - G.711 A-law (Type=1)
        
        新规范：20ms帧 @ 8kHz，160字节G.711数据
        语音包格式：48字节头部 + 160字节G.711数据
        """
        packet = NRLPacket()
        packet.packet_type = NRLPacket.TYPE_VOICE
        packet.callsign = callsign.encode('utf-8').ljust(6, b'\x00')[:6]
        packet.ssid = ssid
        
        packet.dmr_id = self._parse_dmr_id_hex(dmr_id)
        
        packet.dev_mode = dev_mode if dev_mode else 0x01  # 默认设备模式
        packet.status = 0x01  # 根据协议规范，bit0用作DCD/PTT标志
        
        # 确保语音数据正好是160字节
        if not voice_data or len(voice_data) == 0:
            voice_data = b'\x80' * 160  # 静音数据
        elif len(voice_data) < 160:
            voice_data = voice_data.ljust(160, b'\x80')  # G.711静音值
        elif len(voice_data) > 160:
            voice_data = voice_data[:160]
        
        packet.data = voice_data
        packet.count = self.packet_count
        self.packet_count = (self.packet_count + 1) & 0xFFFF  # 确保16位计数器
        return packet
    
    def create_opus_voice_packet(self, callsign: str, ssid: int, dmr_id: str, 
                                opus_data: bytes, dev_mode: int = 1) -> NRLPacket:
        """创建Opus语音数据包 - Opus 16K (Type=8)
        
        Opus是变长编码，数据长度不固定（通常40-80字节）
        语音包格式：48字节头部 + Opus编码数据
        """
        packet = NRLPacket()
        packet.packet_type = NRLPacket.TYPE_OPUS
        packet.callsign = callsign.encode('utf-8').ljust(6, b'\x00')[:6]
        packet.ssid = ssid
        
        packet.dmr_id = self._parse_dmr_id_hex(dmr_id)
        
        packet.dev_mode = dev_mode if dev_mode else 0x01
        packet.status = 0x01
        
        # Opus数据是变长的，直接使用
        packet.data = opus_data if opus_data else b''
        packet.count = self.packet_count
        self.packet_count = (self.packet_count + 1) & 0xFFFF
        return packet
    
    def create_heartbeat_packet(self, callsign: str, ssid: int, dmr_id: str = None, 
                               dev_mode: int = 0x10) -> NRLPacket:
        """创建心跳包 - 根据协议规范，心跳包只有头部，没有数据部分
        
        参考78HAM的encodeNRL21函数
        心跳包特点：
        - Type字段为2（TYPE_HEARTBEAT）
        - 没有数据部分（长度为48字节）
        - SSID通常为200表示服务器连接
        - 计数器通常为1（作为协议的一部分）
        """
        packet = NRLPacket()
        packet.packet_type = NRLPacket.TYPE_HEARTBEAT
        packet.callsign = callsign.encode('utf-8').ljust(6, b'\x00')[:6]
        packet.ssid = ssid  # 通常为200
        
        # 根据协议规范，心跳包使用3字节DMRID
        dmr_id_bytes = self._parse_dmr_id_hex(dmr_id or "")
            
        packet.dmr_id = dmr_id_bytes
        packet.dev_mode = dev_mode if dev_mode else 0x10  # 默认0x10表示正常模式
        packet.status = 0x01  # 根据协议规范，状态为0x01
        packet.count = 1  # 心跳包计数器通常为1（与Go版本一致）
        packet.data = b""  # 心跳包没有数据部分
        return packet
    
    def create_config_packet(self, callsign: str, ssid: int, dmr_id: str, 
                           config_data: bytes, dev_mode: int = 1) -> NRLPacket:
        """创建配置数据包"""
        packet = NRLPacket()
        packet.packet_type = NRLPacket.TYPE_CONFIG
        packet.callsign = callsign.encode('utf-8').ljust(6, b'\x00')[:6]
        packet.ssid = ssid
        # 使用3字节DMRID
        packet.dmr_id = self._parse_dmr_id_hex(dmr_id)
        packet.dev_mode = dev_mode
        packet.data = config_data
        packet.count = self.packet_count
        self.packet_count = (self.packet_count + 1) & 0xFFFF  # 确保16位计数器
        return packet

    def create_text_packet(self, callsign: str, ssid: int, dmr_id: str, text_data: bytes, dev_mode: int = 1) -> NRLPacket:
        """创建文本数据包 - 根据协议规范，文本包长度=48+文本长度"""
        packet = NRLPacket()
        packet.packet_type = NRLPacket.TYPE_TEXT
        packet.callsign = callsign.encode('utf-8').ljust(6, b'\x00')[:6]
        packet.ssid = ssid
        
        # 根据协议规范，使用3字节DMRID
        packet.dmr_id = self._parse_dmr_id_hex(dmr_id)
        
        packet.dev_mode = dev_mode if dev_mode else 0x01  # 默认设备模式
        packet.status = 0x01  # 根据协议规范，状态为0x01
        packet.data = text_data
        packet.count = self.packet_count
        self.packet_count = (self.packet_count + 1) & 0xFFFF  # 确保16位计数器
        return packet
    
    def create_server_voice_packet(self, callsign: str, ssid: int, dmr_id: str, 
                                 voice_data: bytes, original_callsign: str, 
                                 original_ssid: int, original_ip: bytes, 
                                 dev_mode: int = 1) -> NRLPacket:
        """创建服务器互联语音包 - Type=9，包含原始呼号/IP信息"""
        packet = NRLPacket()
        packet.packet_type = NRLPacket.TYPE_SERVER_VOICE
        packet.callsign = callsign.encode('utf-8').ljust(6, b'\x00')[:6]
        packet.ssid = ssid
        
        # 根据协议规范，使用3字节DMRID
        packet.dmr_id = self._parse_dmr_id_hex(dmr_id)
        
        packet.dev_mode = dev_mode if dev_mode else 0x01  # 默认设备模式
        packet.status = 0x01  # 根据协议规范，bit0用作DCD/PTT标志
        
        # 设置原始设备信息
        packet.original_callsign = original_callsign.encode('utf-8').ljust(6, b'\x00')[:6]
        packet.original_ssid = original_ssid
        packet.original_ip = original_ip.ljust(4, b'\x00')[:4] if len(original_ip) >= 4 else b'\x00' * 4
        
        # 确保语音数据正好是160字节（新规范：20ms @ 8kHz）
        if len(voice_data) != 160:
            if len(voice_data) < 160:
                voice_data = voice_data.ljust(160, b'\x80')  # G.711静音值
            else:
                voice_data = voice_data[:160]
        
        packet.data = voice_data
        packet.count = self.packet_count
        self.packet_count = (self.packet_count + 1) & 0xFFFF  # 确保16位计数器
        return packet
# ==================== 房间（Group）协议方法 ====================

    def create_group_list_packet(self, callsign: str, ssid: int, dmr_id: str,
                                 dev_mode: int = 1) -> NRLPacket:
        """创建获取房间列表请求包 (Type=7, Subtype=2)

        服务端收到后返回公共房间 CSV 列表，格式: "id,name\\nid,name\\n..."
        参考服务端 udphub.go case 7 -> case 2
        """
        packet = NRLPacket()
        packet.packet_type = NRLPacket.TYPE_JOIN_GROUP  # Type=7
        packet.callsign = callsign.encode('utf-8').ljust(6, b'\x00')[:6]
        packet.ssid = ssid
        packet.dmr_id = self._parse_dmr_id_hex(dmr_id)
        packet.dev_mode = dev_mode if dev_mode else 0x01
        packet.status = 0x01
        packet.data = b'\x02'  # subtype 2 = 获取组列表
        packet.count = self.packet_count
        self.packet_count = (self.packet_count + 1) & 0xFFFF
        return packet

    def create_join_group_packet(self, callsign: str, ssid: int, dmr_id: str,
                                 group_id: int, dev_mode: int = 1) -> NRLPacket:
        """创建加入/切换房间请求包 (Type=7, Subtype=1)

        data[0] = 1 (切换组指令), data[1:5] = group_id (big-endian uint32)
        参考服务端 udphub.go case 7 -> case 1
        """
        packet = NRLPacket()
        packet.packet_type = NRLPacket.TYPE_JOIN_GROUP  # Type=7
        packet.callsign = callsign.encode('utf-8').ljust(6, b'\x00')[:6]
        packet.ssid = ssid
        packet.dmr_id = self._parse_dmr_id_hex(dmr_id)
        packet.dev_mode = dev_mode if dev_mode else 0x01
        packet.status = 0x01
        packet.data = b'\x01' + struct.pack('>I', group_id)
        packet.count = self.packet_count
        self.packet_count = (self.packet_count + 1) & 0xFFFF
        return packet

    @staticmethod
    def parse_group_list_response(data: bytes) -> list:
        """解析房间列表响应数据

        服务器返回格式: CSV "id,name\\nid,name\\n..."
        跳过 subtype 字节 (data[0]) 后解析 CSV
        返回: [{"id": int, "name": str}, ...]
        """
        result = []
        if not data or len(data) < 2:
            return result
        # data[0] 是 subtype (2)，data[1:] 是 CSV 文本
        text = data[1:].decode('utf-8', errors='ignore').strip()
        if not text:
            return result
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
            parts = line.split(',', 1)
            if len(parts) >= 2:
                try:
                    group_id = int(parts[0].strip())
                    group_name = parts[1].strip()
                    result.append({"id": group_id, "name": group_name})
                except ValueError:
                    continue
        return result

    @staticmethod
    def parse_join_group_response(data: bytes) -> tuple:
        """解析加入房间响应数据

        服务器返回格式: 原始包 data + 追加字符串如 "0公共大厅" 或 "999error"
        跳过 subtype 字节和 group_id (前5字节) 后解析结果文本
        返回: (group_id: int, group_name: str)，失败时 group_name 为 "error"
        """
        if not data or len(data) < 5:
            return (-1, "error")
        # data[0] = subtype (1), data[1:5] = group_id (big-endian)
        group_id = struct.unpack('>I', data[1:5])[0]
        # data[5:] 是服务器追加的结果文本
        if len(data) > 5:
            result_text = data[5:].decode('utf-8', errors='ignore').strip()
            if 'error' in result_text.lower():
                return (group_id, "error")
            # 成功时格式为 "id房间名"，提取房间名（跳过开头的数字ID）
            i = 0
            while i < len(result_text) and result_text[i].isdigit():
                i += 1
            group_name = result_text[i:] if i < len(result_text) else result_text
            return (group_id, group_name.strip())
        return (group_id, "")


# ==================== 文本消息子类型工具函数 ====================

# Type=5 文本消息子类型前缀定义（与服务端 decode.go 规范一致）
TEXT_SUBTYPE_PREFIXES = {
    "[text]":  "text",
    "[loc]":   "loc",
    "[json]":  "json",
    "[xml]":   "xml",
    "[html]":  "html",
    "[bin]":   "bin",
    "[img]":   "img",
    "[video]": "video",
    "[audio]": "audio",
}


def format_location_message(lat: float, lng: float) -> str:
    """格式化位置消息（带 [loc] 前缀）

    返回: "[loc]31.861200,117.283900"
    """
    return f"[loc]{lat:.6f},{lng:.6f}"


def parse_text_subtype(data: bytes) -> dict:
    """解析 Type=5 文本数据的子类型前缀

    检测 [loc]、[text]、[json] 等前缀，返回结构化信息。
    无前缀时默认 subtype="text"。
    返回: {"subtype": str, "content": str, "raw": str}
    """
    raw = data.decode('utf-8', errors='ignore')
    for prefix, subtype in TEXT_SUBTYPE_PREFIXES.items():
        if raw.startswith(prefix):
            return {
                "subtype": subtype,
                "content": raw[len(prefix):],
                "raw": raw,
            }
    # 无前缀，视为纯文本
    return {"subtype": "text", "content": raw, "raw": raw}


def parse_location_content(content: str) -> tuple:
    """解析位置坐标字符串

    输入: "31.8612,117.2839" 或 "31.8612,117.2839,50.0,10.0"(含海拔、精度)
    返回: (lat: float, lng: float) 或解析失败时 (0.0, 0.0)
    """
    parts = content.strip().split(',')
    if len(parts) >= 2:
        try:
            lat = float(parts[0].strip())
            lng = float(parts[1].strip())
            if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                return (lat, lng)
        except ValueError:
            pass
    return (0.0, 0.0)


def generate_map_url(lat: float, lng: float) -> str:
    """生成高德地图链接

    高德 URI API 格式: position=lng,lat（注意经度在前）
    """
    if lat == 0.0 and lng == 0.0:
        return ""
    return f"https://uri.amap.com/marker?position={lng:.6f},{lat:.6f}"


# G.711编解码相关常量（与Go版本保持一致）
SEG_MASK = 0x70
QUANT_MASK = 0x0F
SEG_SHIFT = 4
BIAS = 0x84

def alaw2linear(code: int) -> int:
    """A-law解码到线性PCM"""
    code ^= 0x55
    
    sign = code & 0x80
    seg = (code & 0x70) >> 4
    quant = code & 0x0F
    
    if seg == 0:
        sample = (quant << 1) | 0x01
    else:
        sample = ((quant << 1) | 0x21) << (seg - 1)
    
    if sign != 0:
        return sample << 3
    else:
        return -(sample << 3)

def linear2alaw(sample: int) -> int:
    """线性PCM编码到A-law"""
    if sample < 0:
        if sample == -32768:
            sample = -32767
        sample = -sample
        sign = 0x00
    else:
        sign = 0x80
    
    # 13位绝对值用于A-law
    pcm = sample >> 3
    
    seg = 0
    if pcm >= 32:
        seg = 1
        t = 64
        while seg < 7 and pcm >= t:
            t <<= 1
            seg += 1
    
    if seg == 0:
        mant = (pcm >> 1) & 0x0F
    else:
        mant = (pcm >> seg) & 0x0F
    
    return (sign | (seg << 4) | mant) ^ 0x55

class G711Codec:
    """G.711编解码器 - 与78HAM的Go实现保持一致
    
    参考78HAM的g711.go实现，支持A-law编解码
    A-law是用于欧洲、非洲和亚洲大部分地区的标准语音压缩算法
    """
    
    # 预计算解码查找表：256个A-law值 -> 16位PCM样本
    _DECODE_TABLE = tuple(alaw2linear(i) for i in range(256))
    
    @staticmethod
    def encode(pcm_data: bytes) -> bytes:
        """PCM数据编码为G.711 A-law（查表优化）
        
        将16位线性PCM样本编码为8位A-law样本
        新规范：输出160字节（20ms @ 8kHz，160样本）
        """
        if not pcm_data:
            return b'\x80' * 160
        
        encoded = bytearray()
        
        try:
            # 使用 struct 一次解包所有样本，避免逐样本 int.from_bytes
            sample_count = len(pcm_data) // 2
            samples = struct.unpack(f'<{sample_count}h', pcm_data[:sample_count * 2])
            for sample in samples:
                encoded.append(linear2alaw(sample))
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"G.711编码错误: {e}")
            return bytes([linear2alaw(0)]) * 160
        
        # 确保输出正好是160字节
        if len(encoded) > 160:
            return bytes(encoded[:160])
        elif len(encoded) < 160:
            silence_value = linear2alaw(0)
            encoded.extend([silence_value] * (160 - len(encoded)))
        
        return bytes(encoded)
    
    @staticmethod
    def decode(alaw_data: bytes) -> bytes:
        """G.711 A-law数据解码为PCM（查表优化）
        
        将8位A-law样本解码为16位线性PCM样本
        输出为小端序的16位有符号整数对
        """
        if not alaw_data or len(alaw_data) == 0:
            return b""
        
        try:
            # 使用预计算查找表 + struct 一次打包
            table = G711Codec._DECODE_TABLE
            return struct.pack(f'<{len(alaw_data)}h', *(table[b] for b in alaw_data))
        except Exception as e:
            import logging
            logging.getLogger(__name__).debug(f"G.711解码错误: {e}, 数据长度: {len(alaw_data)}")
            return b""


# 尝试导入Opus编解码库
# 优先级: opuslib (原生绑定) > av/PyAV (FFmpeg内置opus)
_OPUS_BACKEND = None
try:
    import opuslib  # type: ignore
    import opuslib.api  # type: ignore
    _OPUS_BACKEND = "opuslib"
    OPUS_AVAILABLE = True
except Exception:
    pass

if _OPUS_BACKEND is None:
    try:
        import av as _av  # type: ignore
        # 快速验证 FFmpeg 是否支持 opus 编码
        _test_codec = _av.Codec("libopus", "w")
        _OPUS_BACKEND = "av"
        OPUS_AVAILABLE = True
    except Exception:
        OPUS_AVAILABLE = False


class OpusCodec:
    """Opus编解码器 - 用于78HAM协议 Type=8
    
    支持两种后端：
    - opuslib: 原生 opus 绑定（需要 opus DLL）
    - av (PyAV): FFmpeg 内置 opus（pip install av 即可）
    
    参考78HAM服务器端规范：
    - 采样率: 16kHz
    - 声道数: 1 (Mono)
    - 帧大小: 20ms (320 samples @ 16kHz)
    - 比特率: 32-40 kbps (VBR)
    - 应用模式: OPUS_APPLICATION_VOIP
    - 复杂度: 10
    """
    
    SAMPLE_RATE = 16000
    CHANNELS = 1
    FRAME_DURATION_MS = 20  # 20ms
    FRAME_SIZE = 320  # 320 samples @ 16kHz = 20ms
    PCM_FRAME_BYTES = FRAME_SIZE * 2  # 320 samples * 2 bytes/sample = 640 bytes
    BITRATE = 36000  # 36 kbps VBR
    COMPLEXITY = 10
    
    def __init__(self):
        if not OPUS_AVAILABLE:
            raise ImportError("Opus不可用，请安装: pip install av  或  pip install opuslib")
        
        self._logger = logging.getLogger(__name__)
        self._backend = _OPUS_BACKEND
        
        if self._backend == "opuslib":
            self._encoder = opuslib.Encoder(self.SAMPLE_RATE, self.CHANNELS, opuslib.APPLICATION_VOIP)
            self._decoder = opuslib.Decoder(self.SAMPLE_RATE, self.CHANNELS)
            self._encoder.bitrate = self.BITRATE
            self._encoder.complexity = self.COMPLEXITY
        elif self._backend == "av":
            import io
            # 编码：每帧独立 ogg 容器（输出 ogg 页面数据，可直接发 UDP）
            self._enc_pts = 0
            # 解码：累积 ogg 页面数据，重建 ogg 流解码 + resample
            self._dec_ogg_pages = []      # 已接收的 ogg 页面数据
            self._dec_pcm_frames = []     # 解码后的 PCM 帧缓存
            self._dec_frame_cursor = 0    # 下次返回的帧索引
        
        self._logger.info(f"Opus编解码器初始化成功 (后端: {self._backend})")
    
    def encode(self, pcm_data: bytes) -> bytes:
        """将16位PCM数据编码为Opus帧
        
        输入: 640字节PCM (320 samples * 2 bytes @ 16kHz = 20ms)
        输出: Opus编码数据 (变长, 通常40-80字节)
        """
        if not pcm_data:
            pcm_data = b'\x00' * self.PCM_FRAME_BYTES
        
        # 确保输入是正确的帧大小
        if len(pcm_data) < self.PCM_FRAME_BYTES:
            pcm_data = pcm_data + b'\x00' * (self.PCM_FRAME_BYTES - len(pcm_data))
        elif len(pcm_data) > self.PCM_FRAME_BYTES:
            pcm_data = pcm_data[:self.PCM_FRAME_BYTES]
        
        try:
            if self._backend == "opuslib":
                return self._encoder.encode(pcm_data, self.FRAME_SIZE)
            else:
                return self._encode_av(pcm_data)
        except Exception as e:
            self._logger.debug(f"Opus编码错误: {e}")
            try:
                if self._backend == "opuslib":
                    return self._encoder.encode(b'\x00' * self.PCM_FRAME_BYTES, self.FRAME_SIZE)
                else:
                    return self._encode_av(b'\x00' * self.PCM_FRAME_BYTES)
            except Exception:
                return b''
    
    def _encode_av(self, pcm_data: bytes) -> bytes:
        """每帧独立 ogg 容器编码（输出 ogg 页面数据，SNR=24.7dB）"""
        import io
        import numpy as np  # type: ignore
        
        buf = io.BytesIO()
        out = _av.open(buf, mode='w', format='ogg')
        stream = out.add_stream('libopus', rate=self.SAMPLE_RATE)
        stream.layout = 'mono'
        stream.bit_rate = self.BITRATE
        stream.format = 's16'
        
        samples = np.frombuffer(pcm_data, dtype=np.int16)
        frame = _av.AudioFrame.from_ndarray(
            samples.reshape(1, -1), format='s16', layout='mono'
        )
        frame.rate = self.SAMPLE_RATE
        frame.pts = 0
        
        for pkt in stream.encode(frame):
            out.mux(pkt)
        for pkt in stream.encode(None):
            out.mux(pkt)
        out.close()
        
        return buf.getvalue()
    
    def decode(self, opus_data: bytes) -> bytes:
        """将Opus数据解码为16位PCM
        
        输入: Opus编码数据 (变长)
        输出: 640字节PCM (320 samples * 2 bytes @ 16kHz = 20ms)
        """
        if not opus_data:
            return b'\x00' * self.PCM_FRAME_BYTES
        
        try:
            if self._backend == "opuslib":
                return self._decoder.decode(opus_data, self.FRAME_SIZE)
            else:
                return self._decode_av(opus_data)
        except Exception as e:
            self._logger.debug(f"Opus解码错误: {e}, 数据长度={len(opus_data)}")
            return b'\x00' * self.PCM_FRAME_BYTES
    
    def _decode_av(self, opus_data: bytes) -> bytes:
        """解码一个 ogg 页面数据为 16kHz 16bit PCM
        
        累积所有收到的 ogg 页面数据，重建 ogg 流解码 + resample，
        缓存 PCM 帧，每次返回一帧（640字节）。
        """
        import io
        import numpy as np  # type: ignore
        
        # 追加新页面
        self._dec_ogg_pages.append(opus_data)
        
        # 从缓存取帧
        if self._dec_frame_cursor < len(self._dec_pcm_frames):
            result = self._dec_pcm_frames[self._dec_frame_cursor]
            self._dec_frame_cursor += 1
            return result
        
        # 重建 ogg 流，解码所有累积的页面
        combined = b''.join(self._dec_ogg_pages)
        buf = io.BytesIO(combined)
        inp = _av.open(buf, mode='r')
        resampler = _av.AudioResampler(format='s16', layout='mono', rate=self.SAMPLE_RATE)
        
        all_pcm = bytearray()
        for frame in inp.decode():
            for rf in resampler.resample(frame):
                arr = rf.to_ndarray()
                if arr.dtype != np.int16:
                    arr = arr.astype(np.int16)
                all_pcm.extend(arr.tobytes())
        for rf in resampler.resample(None):
            arr = rf.to_ndarray()
            if arr.dtype != np.int16:
                arr = arr.astype(np.int16)
            all_pcm.extend(arr.tobytes())
        inp.close()
        
        # 按 640 字节切分为帧
        new_frames = []
        offset = 0
        while offset + self.PCM_FRAME_BYTES <= len(all_pcm):
            new_frames.append(bytes(all_pcm[offset:offset + self.PCM_FRAME_BYTES]))
            offset += self.PCM_FRAME_BYTES
        
        self._dec_pcm_frames = new_frames
        self._dec_frame_cursor = 1  # 跳过第 0 帧（pre-skip），从第 1 帧开始返回
        
        if self._dec_pcm_frames:
            return self._dec_pcm_frames[0]
        
        return b'\x00' * self.PCM_FRAME_BYTES
    
    @staticmethod
    def is_available() -> bool:
        """检查Opus编解码器是否可用"""
        return OPUS_AVAILABLE
    
    @staticmethod
    def get_backend() -> str:
        """返回当前使用的Opus后端名称"""
        return _OPUS_BACKEND or "none"