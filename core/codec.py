"""
语音编解码器

统一接口，支持 G.711 A-law 和 Opus 两种编码格式。
接收端根据数据包 Type 字段自动选择解码器。
"""
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

# 预计算函数
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

    if sign != 0:
        return sample << 3
    else:
        return -(sample << 3)


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


# 预计算查找表
_DECODE_TABLE = tuple(_alaw2linear(i) for i in range(256))


class G711Codec(VoiceCodec):
    """G.711 A-law 编解码器

    - 采样率: 8kHz
    - 帧时长: 20ms
    - 帧大小: 160 samples = 160 bytes (编码后)
    - 压缩比: 2:1 (16-bit PCM → 8-bit A-law)
    """

    FRAME_SIZE = 160        # 编码后字节数
    SILENCE_VALUE = 0x80    # A-law 静音值（对应 PCM 0 附近）

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
            samples = struct.unpack(f'<{sample_count}h', pcm_data[:sample_count * 2])
            encoded = bytearray(_linear2alaw(s) for s in samples)
        except Exception as e:
            logger.debug(f"G.711 编码错误: {e}")
            return bytes([_linear2alaw(0)] * self.FRAME_SIZE)

        # 确保输出正好是 160 字节
        if len(encoded) > self.FRAME_SIZE:
            return bytes(encoded[:self.FRAME_SIZE])
        elif len(encoded) < self.FRAME_SIZE:
            encoded.extend([self.SILENCE_VALUE] * (self.FRAME_SIZE - len(encoded)))

        return bytes(encoded)

    def decode(self, alaw_data: bytes) -> bytes:
        """G.711 A-law 数据解码为 PCM

        输入: 160 字节 A-law
        输出: 320 字节 PCM (16-bit LE)
        """
        if not alaw_data or len(alaw_data) == 0:
            return b""

        try:
            table = _DECODE_TABLE
            return struct.pack(f'<{len(alaw_data)}h', *(table[b] for b in alaw_data))
        except Exception as e:
            logger.debug(f"G.711 解码错误: {e}, 数据长度: {len(alaw_data)}")
            return b""


# ==================== Opus ====================

# 尝试导入 Opus 后端
_OPUS_BACKEND: Optional[str] = None
_OPUS_AVAILABLE = False

try:
    import opuslib  # type: ignore
    import opuslib.api  # type: ignore
    _OPUS_BACKEND = "opuslib"
    _OPUS_AVAILABLE = True
except Exception:
    pass

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
    - 比特率: 36 kbps VBR
    - 应用模式: VOIP
    """

    BITRATE = 36000
    COMPLEXITY = 10

    def __init__(self):
        if not _OPUS_AVAILABLE:
            raise ImportError("Opus 不可用，请安装: pip install av 或 pip install opuslib")

        self._backend = _OPUS_BACKEND

        if self._backend == "opuslib":
            self._encoder = opuslib.Encoder(16000, 1, opuslib.APPLICATION_VOIP)
            self._decoder = opuslib.Decoder(16000, 1)
            self._encoder.bitrate = self.BITRATE
            self._encoder.complexity = self.COMPLEXITY
        elif self._backend == "av":
            self._enc_pts = 0
            self._dec_ogg_pages = []
            self._dec_pcm_frames = []
            self._dec_frame_cursor = 0

        logger.info(f"Opus 编解码器初始化成功 (后端: {self._backend})")

    @property
    def sample_rate(self) -> int:
        return 16000

    @property
    def frame_duration_ms(self) -> int:
        return 20

    @property
    def encoded_frame_bytes(self) -> Optional[int]:
        return None  # 变长编码

    def encode(self, pcm_data: bytes) -> bytes:
        """PCM → Opus

        输入: 640 字节 PCM (320 samples * 2 bytes @ 16kHz = 20ms)
        输出: Opus 编码数据 (变长, 通常 40-80 字节)
        """
        expected = self.pcm_frame_bytes
        if not pcm_data:
            pcm_data = b'\x00' * expected
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
            return b'\x00' * self.pcm_frame_bytes

        try:
            if self._backend == "opuslib":
                return self._decoder.decode(opus_data, self.frame_samples)
            else:
                return self._decode_av(opus_data)
        except Exception as e:
            logger.debug(f"Opus 解码错误: {e}, 数据长度={len(opus_data)}")
            return b'\x00' * self.pcm_frame_bytes

    def _encode_av(self, pcm_data: bytes) -> bytes:
        """PyAV 后端编码"""
        import io
        import numpy as np  # type: ignore

        buf = io.BytesIO()
        out = _av.open(buf, mode='w', format='ogg')
        stream = out.add_stream('libopus', rate=self.sample_rate)
        stream.layout = 'mono'
        stream.bit_rate = self.BITRATE
        stream.format = 's16'

        samples = np.frombuffer(pcm_data, dtype=np.int16)
        frame = _av.AudioFrame.from_ndarray(
            samples.reshape(1, -1), format='s16', layout='mono'
        )
        frame.rate = self.sample_rate
        frame.pts = 0

        for pkt in stream.encode(frame):
            out.mux(pkt)
        for pkt in stream.encode(None):
            out.mux(pkt)
        out.close()

        return buf.getvalue()

    def _decode_av(self, opus_data: bytes) -> bytes:
        """PyAV 后端解码"""
        import io
        import numpy as np  # type: ignore

        self._dec_ogg_pages.append(opus_data)

        # 限制缓存大小，防止内存无限增长（保留最近 10 页）
        if len(self._dec_ogg_pages) > 10:
            self._dec_ogg_pages = self._dec_ogg_pages[-10:]

        if self._dec_frame_cursor < len(self._dec_pcm_frames):
            result = self._dec_pcm_frames[self._dec_frame_cursor]
            self._dec_frame_cursor += 1
            return result

        combined = b''.join(self._dec_ogg_pages)
        buf = io.BytesIO(combined)
        inp = _av.open(buf, mode='r')
        resampler = _av.AudioResampler(format='s16', layout='mono', rate=self.sample_rate)

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

        new_frames = []
        offset = 0
        while offset + self.pcm_frame_bytes <= len(all_pcm):
            new_frames.append(bytes(all_pcm[offset:offset + self.pcm_frame_bytes]))
            offset += self.pcm_frame_bytes

        self._dec_pcm_frames = new_frames
        self._dec_frame_cursor = 1

        if self._dec_pcm_frames:
            return self._dec_pcm_frames[0]

        return b'\x00' * self.pcm_frame_bytes

    @staticmethod
    def is_available() -> bool:
        """检查 Opus 编解码器是否可用"""
        return _OPUS_AVAILABLE

    @staticmethod
    def get_backend() -> Optional[str]:
        """返回当前使用的 Opus 后端名称"""
        return _OPUS_BACKEND
