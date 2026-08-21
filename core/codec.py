"""
语音编解码器

统一接口，支持 G.711 A-law 和 Opus 两种编码格式。
接收端根据数据包 Type 字段自动选择解码器。
"""
import os
import sys
import struct
import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


# ==================== 抽象接口 ====================

class VoiceCodec(ABC):
    """语音编解码器抽象基类"""

    @abstractmethod
    def encode(self, pcm_data: bytes) -> bytes:
        """PCM → 编码数据"""
        ...

    @abstractmethod
    def decode(self, encoded_data: bytes) -> bytes:
        """编码数据 → PCM"""
        ...

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """采样率 (Hz)"""
        ...

    @property
    @abstractmethod
    def frame_duration_ms(self) -> int:
        """帧时长 (ms)"""
        ...

    @property
    def frame_samples(self) -> int:
        """每帧采样数"""
        return self.sample_rate * self.frame_duration_ms // 1000

    @property
    def pcm_frame_bytes(self) -> int:
        """每帧 PCM 字节数 (16-bit mono)"""
        return self.frame_samples * 2

    @property
    @abstractmethod
    def encoded_frame_bytes(self) -> Optional[int]:
        """编码后帧字节数（变长编码返回 None）"""
        ...


# ==================== G.711 A-law ====================

# 预计算查找表（模块加载时一次性生成）
def _alaw2linear(code: int) -> int:
    """A-law 解码到线性 PCM"""
    code ^= 0x55
    sign = code & 0x80
    seg = (code & 0x70) >> 4
    quant = code & 0x0F

    if seg == 0:
        sample = (quant << 1) | 0x01
    else:
        sample = ((quant << 1) | 0x21) << (seg - 1)

    return (sample << 3) if sign == 0 else -(sample << 3)


def _linear2alaw(sample: int) -> int:
    """线性 PCM 编码到 A-law"""
    if sample < 0:
        if sample == -32768:
            sample = -32767
        sample = -sample
        sign = 0x00
    else:
        sign = 0x80

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


# 预计算查找表（加速编解码）
_ALAW_DECODE_TABLE = tuple(_alaw2linear(i) for i in range(256))


class G711Codec(VoiceCodec):
    """G.711 A-law 编解码器

    - 采样率: 8kHz
    - 帧时长: 20ms
    - 帧大小: 160 samples = 160 bytes (编码后)
    - 压缩比: 2:1 (16-bit PCM → 8-bit A-law)
    """

    FRAME_SIZE = 160        # 编码后字节数
    SILENCE_VALUE = 0xD5    # 标准 A-law 零电平码

    @property
    def sample_rate(self) -> int:
        return 8000

    @property
    def frame_duration_ms(self) -> int:
        return 20

    @property
    def encoded_frame_bytes(self) -> Optional[int]:
        return self.FRAME_SIZE

    def encode(self, pcm_data: bytes) -> bytes:
        """PCM 数据编码为 G.711 A-law

        输入: 320 字节 PCM (160 samples * 2 bytes @ 8kHz = 20ms)
        输出: 160 字节 A-law
        """
        if not pcm_data:
            return bytes([self.SILENCE_VALUE] * self.FRAME_SIZE)

        try:
            sample_count = len(pcm_data) // 2
            # 使用 struct 解包并编码
            samples = struct.unpack(f'<{sample_count}h', pcm_data[:sample_count * 2])
            encoded = bytes(_linear2alaw(s) for s in samples)
        except Exception as e:
            logger.debug(f"G.711 编码错误: {e}")
            return bytes([_linear2alaw(0)] * self.FRAME_SIZE)

        # 确保输出正好是 160 字节
        if len(encoded) > self.FRAME_SIZE:
            return encoded[:self.FRAME_SIZE]
        elif len(encoded) < self.FRAME_SIZE:
            return encoded + bytes([self.SILENCE_VALUE] * (self.FRAME_SIZE - len(encoded)))

        return encoded

    def decode(self, alaw_data: bytes) -> bytes:
        """G.711 A-law 数据解码为 PCM

        输入: 160 字节 A-law
        输出: 320 字节 PCM (16-bit LE)
        """
        if not alaw_data:
            return b""

        try:
            # 使用预计算查找表加速解码
            return struct.pack(f'<{len(alaw_data)}h', *(_ALAW_DECODE_TABLE[b] for b in alaw_data))
        except Exception as e:
            logger.debug(f"G.711 解码错误: {e}, 数据长度: {len(alaw_data)}")
            return b""


# ==================== Opus ====================

# 尝试导入 Opus 后端
_OPUS_BACKEND: Optional[str] = None
_OPUS_AVAILABLE = False

# 将本地 libs/ 目录加入 DLL 搜索路径（支持 PyInstaller 打包和开发环境）
_base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_libs_dir = os.path.join(_base_dir, 'libs')

if sys.platform == 'win32':
    if os.path.isdir(_libs_dir):
        os.environ['PATH'] = _libs_dir + os.pathsep + os.environ.get('PATH', '')
        try:
            os.add_dll_directory(_libs_dir)  # Python 3.8+
        except AttributeError:
            pass
        # 预加载 opus.dll 以确保 opuslib 能找到
        try:
            import ctypes
            ctypes.CDLL(os.path.join(_libs_dir, 'opus.dll'))
        except Exception:
            pass

elif sys.platform == 'linux':
    # Linux: 先尝试系统库，再尝试打包目录中的 libopus.so.0
    import ctypes.util
    _opus_lib = ctypes.util.find_library('opus')
    if _opus_lib:
        try:
            import ctypes
            ctypes.CDLL(_opus_lib)
        except Exception:
            pass
    else:
        # PyInstaller 打包场景：从 _MEIPASS 目录加载
        _candidate = os.path.join(_libs_dir, 'libopus.so.0')
        if os.path.isfile(_candidate):
            try:
                import ctypes
                ctypes.CDLL(_candidate)
            except Exception:
                pass

try:
    import opuslib  # type: ignore
    import opuslib.api  # type: ignore
    _OPUS_BACKEND = "opuslib"
    _OPUS_AVAILABLE = True
except Exception as e:
    logger.debug(f"opuslib 加载失败: {e}")

if _OPUS_BACKEND is None:
    try:
        import av as _av  # type: ignore
        _test_codec = _av.Codec("libopus", "w")
        _OPUS_BACKEND = "av"
        _OPUS_AVAILABLE = True
    except Exception:
        pass


class OpusCodec(VoiceCodec):
    """Opus 编解码器

    - 采样率: 16kHz
    - 帧时长: 20ms
    - 帧大小: 320 samples (变长编码输出)
    - 比特率: 可配置 (默认 36 kbps VBR)
    - 应用模式: VOIP
    """

    DEFAULT_BITRATE = 36000
    COMPLEXITY = 10
    PCM_FRAME_BYTES = 640  # 16kHz * 20ms * 2bytes

    # 全档位码率：从窄带到宽带语音场景（单位 bps）
    BITRATE_PRESETS = {
        "窄带 6kbps": 6000,
        "窄带 8kbps": 8000,
        "窄带 12kbps": 12000,
        "窄带 16kbps": 16000,
        "窄带 20kbps": 20000,
        "宽带 24kbps": 24000,
        "宽带 32kbps": 32000,
        "宽带 36kbps": 36000,
        "宽带 48kbps": 48000,
        "宽带 64kbps": 64000,
        "超宽带 96kbps": 96000,
        "超宽带 128kbps": 128000,
        "全频段 256kbps": 256000,
        "全频段 510kbps": 510000,
    }

    # 有效码率范围（Opus 编码器实际支持）
    MIN_BITRATE = 6000
    MAX_BITRATE = 510000

    def __init__(self, bitrate: int = DEFAULT_BITRATE, *, vbr: bool = True, complexity: int = 10):
        if not _OPUS_AVAILABLE:
            raise ImportError("Opus 不可用，请安装: pip install av 或 pip install opuslib")

        self._backend = _OPUS_BACKEND
        self._bitrate = self._clamp_bitrate(bitrate)
        self._vbr = vbr
        self._complexity = max(0, min(10, complexity))

        if self._backend == "opuslib":
            self._encoder = opuslib.Encoder(16000, 1, opuslib.APPLICATION_VOIP)
            self._decoder = opuslib.Decoder(16000, 1)
            self._apply_encoder_settings()
        elif self._backend == "av":
            self._encoder = _av.CodecContext.create('libopus', 'w')
            self._encoder.sample_rate = 16000
            self._encoder.layout = 'mono'
            self._encoder.format = 's16'
            self._encoder.bit_rate = self._bitrate
            self._decoder = _av.CodecContext.create('libopus', 'r')
            self._encoder.open()
            self._decoder.open()

        logger.info(f"Opus 编解码器初始化成功 (后端: {self._backend}, 码率: {self._bitrate} bps)")

    def _apply_encoder_settings(self):
        """将当前码率/VBR/复杂度等参数同步到底层编码器"""
        if self._backend == "opuslib":
            self._encoder.bitrate = self._bitrate
            self._encoder.vbr = 1 if self._vbr else 0
            self._encoder.complexity = self._complexity

    @classmethod
    def _clamp_bitrate(cls, bitrate: int) -> int:
        """将码率限制在 Opus 有效范围内"""
        try:
            bitrate = int(bitrate)
        except (TypeError, ValueError):
            bitrate = cls.DEFAULT_BITRATE
        return max(cls.MIN_BITRATE, min(cls.MAX_BITRATE, bitrate))

    @property
    def bitrate(self) -> int:
        """当前编码码率 (bps)"""
        return self._bitrate

    @bitrate.setter
    def bitrate(self, value: int):
        """运行时动态切换码率"""
        self._bitrate = self._clamp_bitrate(value)
        self._apply_encoder_settings()
        logger.info(f"Opus 码率已切换: {self._bitrate} bps")

    @property
    def vbr(self) -> bool:
        return self._vbr

    @vbr.setter
    def vbr(self, value: bool):
        self._vbr = bool(value)
        self._apply_encoder_settings()

    @property
    def complexity(self) -> int:
        return self._complexity

    @complexity.setter
    def complexity(self, value: int):
        self._complexity = max(0, min(10, value))
        self._apply_encoder_settings()

    @property
    def sample_rate(self) -> int:
        return 16000

    @property
    def frame_duration_ms(self) -> int:
        return 20

    @property
    def encoded_frame_bytes(self) -> Optional[int]:
        return None  # 变长编码

    def set_bitrate(self, bitrate: int):
        """外部统一入口：设置码率"""
        self.bitrate = bitrate

    def encode(self, pcm_data: bytes) -> bytes:
        """PCM → Opus

        输入: 640 字节 PCM (320 samples * 2 bytes @ 16kHz = 20ms)
        输出: Opus 编码数据 (变长, 通常 40-80 字节)
        """
        if not pcm_data:
            pcm_data = b'\x00' * self.PCM_FRAME_BYTES
        
        expected = self.PCM_FRAME_BYTES
        if len(pcm_data) < expected:
            pcm_data = pcm_data + b'\x00' * (expected - len(pcm_data))
        elif len(pcm_data) > expected:
            pcm_data = pcm_data[:expected]

        try:
            if self._backend == "opuslib":
                return self._encoder.encode(pcm_data, self.frame_samples)
            else:
                return self._encode_av(pcm_data)
        except Exception as e:
            logger.debug(f"Opus 编码错误: {e}")
            return b''

    def decode(self, opus_data: bytes) -> bytes:
        """Opus → PCM

        输入: Opus 编码数据 (变长)
        输出: 640 字节 PCM (320 samples * 2 bytes @ 16kHz = 20ms)
        """
        if not opus_data:
            return b'\x00' * self.PCM_FRAME_BYTES

        try:
            if self._backend == "opuslib":
                return self._decoder.decode(opus_data, self.frame_samples)
            else:
                return self._decode_av(opus_data)
        except Exception as e:
            logger.debug(f"Opus 解码错误: {e}, 数据长度={len(opus_data)}")
            return b'\x00' * self.PCM_FRAME_BYTES

    def _encode_av(self, pcm_data: bytes) -> bytes:
        """Encode one raw Opus packet, never an Ogg container."""
        import numpy as np  # type: ignore
        samples = np.frombuffer(pcm_data, dtype=np.int16)
        frame = _av.AudioFrame.from_ndarray(
            samples.reshape(1, -1), format='s16', layout='mono'
        )
        frame.rate = self.sample_rate
        packets = self._encoder.encode(frame)
        return bytes(packets[0]) if packets else b''

    def _decode_av(self, opus_data: bytes) -> bytes:
        """Decode one raw Opus packet."""
        import numpy as np  # type: ignore
        packet = _av.Packet(opus_data)
        frames = self._decoder.decode(packet)
        if not frames:
            return b'\x00' * self.PCM_FRAME_BYTES
        samples = frames[0].to_ndarray()
        if samples.dtype != np.int16:
            samples = samples.astype(np.int16)
        pcm = samples.tobytes()
        return pcm[:self.PCM_FRAME_BYTES].ljust(self.PCM_FRAME_BYTES, b'\x00')

    @staticmethod
    def is_available() -> bool:
        """检查 Opus 编解码器是否可用"""
        return _OPUS_AVAILABLE

    @staticmethod
    def get_backend() -> Optional[str]:
        """返回当前使用的 Opus 后端名称"""
        return _OPUS_BACKEND


# codec registry
_CODEC_REGISTRY = {}


def register_codec(name, codec_cls):
    _CODEC_REGISTRY[name] = codec_cls


def get_codec(name, **kwargs):
    cls = _CODEC_REGISTRY.get(name)
    if cls is None:
        return None
    return cls(**kwargs)


def list_codecs():
    return list(_CODEC_REGISTRY.keys())


register_codec('g711', G711Codec)
register_codec('opus', OpusCodec)
