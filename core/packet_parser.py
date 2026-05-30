"""
数据包解析器

负责将网络字节流解码为 NRLPacket 结构。
"""
import struct
import logging
from typing import Optional, Dict, Tuple, List

from .protocol import (
    NRLHeader, NRLPacket, PacketType, DevModel, TextSubtype,
    PROTOCOL_VERSION, HEADER_SIZE, is_valid_callsign
)

logger = logging.getLogger(__name__)


class PacketParser:
    """NRL2 数据包解析器"""

    @staticmethod
    def decode(data: bytes, addr: Optional[tuple] = None) -> Optional[NRLPacket]:
        """将网络字节流解码为 NRLPacket

        Args:
            data: 原始 UDP 数据
            addr: 来源地址 (host, port)

        Returns:
            解码成功返回 NRLPacket，失败返回 None
        """
        if len(data) < HEADER_SIZE:
            return None

        try:
            # 检查版本
            version = data[0:4]
            if version != PROTOCOL_VERSION:
                return None

            # 解析长度
            length = struct.unpack(">H", data[4:6])[0]

            # 长度合理性校验：不超过 UDP 包最大值 65535
            if length > 65535:
                logger.debug(f"数据包长度字段异常: {length}")
                return None

            # 检查数据完整性
            if len(data) < length and length > HEADER_SIZE:
                logger.debug(f"数据包不完整: 期望 {length} 字节，实际 {len(data)} 字节")
                return None

            # 解析头部字段
            header = NRLHeader(
                version=version,
                length=length,
                dmr_id=data[6:9],
                password=data[9:20],
                packet_type=data[20],
                status=data[21],
                count=struct.unpack(">H", data[22:24])[0],
                callsign=data[24:30],
                ssid=data[30],
                dev_mode=data[31],
            )

            # 呼号有效性验证
            if not is_valid_callsign(header.callsign):
                return None

            # 扩展字段 (Type=9 或 DevModel=200/255)
            if (header.packet_type == PacketType.SERVER_VOICE or
                    header.dev_mode in (DevModel.SERVER, DevModel.FULL_NETWORK)):
                header.original_callsign = data[32:38]
                header.original_ssid = data[38]
                header.original_ip = data[39:43]
            else:
                header.original_callsign = b""
                header.original_ssid = 0
                header.original_ip = b"\x00" * 4

            # 数据部分
            payload = PacketParser._extract_payload(data, length, header.packet_type)

            return NRLPacket(header=header, data=payload, addr=addr)

        except (struct.error, IndexError) as e:
            logger.debug(f"解码错误: {e}")
            return None

    @staticmethod
    def _extract_payload(data: bytes, length: int, packet_type: int) -> bytes:
        """提取数据包负载部分

        兼容新旧版服务端：
        - 新版: Length 字段正确，严格按 Length 截取
        - 旧版: Length 可能仅填头部长度(48)，但 UDP 包中仍携带语音数据
        - Type=7 响应: 服务端追加 CSV 数据但未更新 Length 字段
        """
        actual_len = len(data)
        
        if length > HEADER_SIZE:
            if actual_len > length:
                # 实际数据比 Length 字段长（如 Type=7 房间列表响应），
                # 服务端追加了数据但未更新 Length，以实际接收长度为准
                return data[HEADER_SIZE:actual_len]
            else:
                return data[HEADER_SIZE:length]
        elif actual_len > HEADER_SIZE:
            # 兼容旧版服务端或 Length 字段不准确的情况
            logger.debug(
                f"旧版/兼容包: Type={packet_type}, "
                f"Length={length}, 实际数据={actual_len - HEADER_SIZE}字节")
            return data[HEADER_SIZE:]
        else:
            return b""

    @staticmethod
    def parse_text_subtype(data: bytes) -> Dict[str, str]:
        """解析 Type=5 文本数据的子类型前缀

        返回: {"subtype": str, "content": str, "raw": str}
        """
        raw = data.decode('utf-8', errors='ignore')
        for prefix, subtype in TextSubtype.PREFIXES.items():
            if raw.startswith(prefix):
                return {
                    "subtype": subtype,
                    "content": raw[len(prefix):],
                    "raw": raw,
                }
        # 无前缀，视为纯文本
        return {"subtype": "text", "content": raw, "raw": raw}

    @staticmethod
    def parse_location_content(content: str) -> Tuple[float, float]:
        """解析位置坐标字符串

        输入: "31.8612,117.2839" 或 "31.8612,117.2839,50.0,10.0"
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

    @staticmethod
    def parse_group_list_response(data: bytes) -> List[Dict[str, object]]:
        """解析房间列表响应数据

        服务器返回格式: CSV "id,name\\nid,name\\n..."
        跳过 subtype 字节 (data[0]) 后解析 CSV
        返回: [{"id": int, "name": str}, ...]
        """
        result = []
        if not data or len(data) < 2:
            return result
        
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
    def parse_join_group_response(data: bytes) -> Tuple[int, str]:
        """解析加入房间响应数据

        返回: (group_id: int, group_name: str)，失败时 group_name 为 "error"
        """
        if not data or len(data) < 5:
            return (-1, "error")
        
        group_id = struct.unpack('>I', data[1:5])[0]
        
        if len(data) > 5:
            result_text = data[5:].decode('utf-8', errors='ignore').strip()
            if 'error' in result_text.lower():
                return (group_id, "error")
            
            # 成功时格式为 "id房间名"，提取房间名
            i = 0
            while i < len(result_text) and result_text[i].isdigit():
                i += 1
            group_name = result_text[i:] if i < len(result_text) else result_text
            return (group_id, group_name.strip())
        
        return (group_id, "")

    @staticmethod
    def format_location_message(lat: float, lng: float) -> str:
        """格式化位置消息（带 [loc] 前缀）"""
        return f"[loc]{lat:.6f},{lng:.6f}"

    @staticmethod
    def generate_map_url(lat: float, lng: float) -> str:
        """生成高德地图链接"""
        if lat == 0.0 and lng == 0.0:
            return ""
        return f"https://uri.amap.com/marker?position={lng:.6f},{lat:.6f}"
