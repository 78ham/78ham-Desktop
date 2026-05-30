"""
MDC1200 信令编码器

MDC1200 是一种用于模拟无线电的带内信令协议。
通过 1200/1800 Hz FSK 调制，在语音通道中传输设备 ID 和控制命令。

移植自小程序 utils/mdc1200.js。

用途：
- PTT ID（发射前/后发送设备标识）
- 呼叫（Call）
- 紧急告警（Emergency）
- 遥毙/遥开（Stun/Revive）
"""
import struct
import math
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# MDC1200 操作码
OP_PTT_ID = 0x01       # PTT ID
OP_EMERGENCY = 0x80    # 紧急告警
OP_CALL = 0x20         # 呼叫
OP_STUN = 0x22         # 遥毙
OP_REVIVE = 0x23       # 遥开
OP_ACK = 0x0C          # 确认

# FSK 参数
SAMPLE_RATE = 8000
FREQ_1200 = 1200       # bit=0 (space)
FREQ_1800 = 1800       # bit=1 (mark)

# 相位增量（模拟 uint32 溢出）
INCR_1200 = 644245094   # 1200 Hz @ 8000 Hz
INCR_1800 = 966367642   # 1800 Hz @ 8000 Hz
UINT32_MAX = 0x100000000

# 正弦表（256 点，Int16 幅度）
_SINTABLE = None


def _ensure_sintable():
    """延迟初始化正弦查找表"""
    global _SINTABLE
    if _SINTABLE is not None:
        return
    _SINTABLE = [0] * 256
    for i in range(256):
        _SINTABLE[i] = int(22282 * math.sin(2 * math.pi * i / 256))


def _get_sintable():
    """返回正弦查找表（延迟生成）"""
    _ensure_sintable()
    return _SINTABLE


def _flip(val: int, bits: int) -> int:
    """位反转"""
    result = 0
    for i in range(bits):
        if (val >> i) & 1:
            result |= 1 << (bits - 1 - i)
    return result


def _docrc(data: bytes, length: int) -> int:
    """计算 MDC1200 CRC (CCITT-16 变体，带位反射)"""
    crc = 0x0000
    for i in range(length):
        c = _flip(data[i], 8)
        for j in range(7, -1, -1):
            bit = crc & 0x8000
            crc = (crc << 1) & 0xFFFF
            if c & (1 << j):
                bit ^= 0x8000
            if bit:
                crc ^= 0x1021
    crc = _flip(crc, 16)
    crc ^= 0xFFFF
    return crc & 0xFFFF


class MDC1200Encoder:
    """MDC1200 信令编码器

    生成 FSK 调制的 PCM 音频样本，可直接拼接到语音数据前后。

    用法：
        encoder = MDC1200Encoder()
        encoder.set_packet(OP_PTT_ID, 0x00, unit_id)
        samples = encoder.get_samples()
        # samples 是 int16 PCM 数据，8000Hz 采样率
    """

    LEADER = bytes([0x55, 0x55, 0x55, 0x55, 0x55, 0x55, 0x55,
                    0x07, 0x09, 0x2A, 0x44, 0x6F])

    def __init__(self):
        self._data: Optional[bytearray] = None
        self._loaded = 0

    def set_packet(self, op: int, arg: int, unit_id: int) -> bool:
        """设置单包数据"""
        self._data = bytearray(26)
        self._data[:12] = self.LEADER
        self._data[12] = op
        self._data[13] = arg
        self._data[14] = (unit_id >> 8) & 0xFF
        self._data[15] = unit_id & 0xFF
        self._enc_str(12)
        self._loaded = 26
        return True

    def set_double_packet(self, op: int, arg: int, unit_id: int,
                          extra0: int, extra1: int,
                          extra2: int, extra3: int) -> bool:
        """设置双包数据"""
        self._data = bytearray(40)
        self._data[:12] = self.LEADER
        self._data[12] = op
        self._data[13] = arg
        self._data[14] = (unit_id >> 8) & 0xFF
        self._data[15] = unit_id & 0xFF
        self._enc_str(12)
        self._data[26] = extra0
        self._data[27] = extra1
        self._data[28] = extra2
        self._data[29] = extra3
        self._enc_str(26)
        self._loaded = 40
        return True

    def get_samples(self, amplitude: float = 0.2) -> bytes:
        """生成 PCM 音频样本

        Args:
            amplitude: 音量缩放 (0.0-1.0)

        Returns:
            int16 little-endian PCM 数据 (8000Hz mono)
        """
        if not self._data or self._loaded == 0:
            return b''

        samples = []
        tthu = 0
        thu = 0
        bpos = 0
        ipos = -1
        xorb = 1
        lb = 0

        generating = True
        while generating:
            lthu = thu
            thu = (thu + INCR_1200) % UINT32_MAX

            if thu < lthu:
                ipos += 1
                if ipos > 7:
                    ipos = 0
                    bpos += 1
                    if bpos >= self._loaded:
                        generating = False
                        break

                b = (self._data[bpos] >> (7 - ipos)) & 0x01
                xorb = 1 if b != lb else 0
                lb = b

            if xorb:
                tthu = (tthu + INCR_1800) % UINT32_MAX
            else:
                tthu = (tthu + INCR_1200) % UINT32_MAX

            ofs = (tthu >> 24) & 0xFF
            sample = int(_get_sintable()[ofs] * amplitude)
            samples.append(sample)

        pcm = struct.pack(f'<{len(samples)}h', *samples)
        self._loaded = 0
        return pcm

    def _enc_str(self, offset: int):
        """编码：CRC + 伪 ECC + 交织"""
        # CRC
        crc_input = bytes(self._data[offset:offset + 4])
        crc = _docrc(crc_input, 4)
        self._data[offset + 4] = crc & 0xFF
        self._data[offset + 5] = (crc >> 8) & 0xFF
        self._data[offset + 6] = 0

        # 伪 ECC
        csr = [0] * 7
        for i in range(7):
            input_byte = self._data[offset + i]
            output_byte = 0
            for j in range(8):
                for k in range(6, 0, -1):
                    csr[k] = csr[k - 1]
                csr[0] = (input_byte >> j) & 0x01
                ecc_bit = (csr[0] ^ csr[2] ^ csr[5] ^ csr[6]) & 0x01
                output_byte |= (ecc_bit << j)
            self._data[offset + 7 + i] = output_byte

        # 交织
        lbits = [0] * 112
        k = 0
        m = 0
        for i in range(14):
            byte_val = self._data[offset + i]
            for j in range(8):
                lbits[k] = (byte_val >> j) & 0x01
                k += 16
                if k >= 112:
                    m += 1
                    k = m
        k = 0
        for i in range(14):
            output_byte = 0
            for j in range(7, -1, -1):
                if lbits[k]:
                    output_byte |= (1 << j)
                k += 1
            self._data[offset + i] = output_byte