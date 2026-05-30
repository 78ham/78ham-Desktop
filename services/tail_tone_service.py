"""
尾音服务

在 PTT 语音结束后发送尾音（提示音 / 自定义音频 / MDC1200 信令）。
"""
import struct
import math
import wave
import logging
import threading
from typing import Optional, Callable, List

from services.mdc1200 import MDC1200Encoder, OP_PTT_ID

logger = logging.getLogger(__name__)

# 最大尾音时长（秒）
MAX_TAIL_DURATION_S = 3.0
# 默认尾音参数（DTMF 拨号音 "91" 双发）
DEFAULT_TAIL_AMPLITUDE = 4000  # int16 幅度
DTMF_DIGIT_MS = 50             # 每个数字持续时长（毫秒）
DTMF_PAUSE_MS = 30             # 数字间静音（毫秒）
DTMF_REPEAT = 1                # 重复次数
# DTMF 频率表：{digit: (row_freq, col_freq)}
DTMF_FREQS = {
    '1': (697, 1209), '2': (697, 1336), '3': (697, 1477),
    '4': (770, 1209), '5': (770, 1336), '6': (770, 1477),
    '7': (852, 1209), '8': (852, 1336), '9': (852, 1477),
    '*': (941, 1209), '0': (941, 1336), '#': (941, 1477),
}
# 原生采样率（尾音素材均为 8kHz）
NATIVE_SAMPLE_RATE = 8000


class TailToneService:
    """尾音服务

    负责加载/生成尾音 PCM 数据，并按当前编码格式分帧提供给发送层。
    """

    def __init__(self, get_codec_fn: Callable[[], str],
                 get_frame_size_fn: Callable[[], int],
                 get_dmr_id_fn: Optional[Callable[[], int]] = None):
        """
        Args:
            get_codec_fn: 返回当前编码类型 ("g711" / "opus")
            get_frame_size_fn: 返回当前 PCM 帧大小（字节）
            get_dmr_id_fn: 返回 DMR ID 整数（MDC ID 为 0 时回退使用）
        """
        self._get_codec = get_codec_fn
        self._get_frame_size = get_frame_size_fn
        self._get_dmr_id = get_dmr_id_fn or (lambda: 0)

        # 配置
        self._enabled = False
        self._tail_type = "default"
        self._custom_file = ""
        self._mdc_id = 0
        self._amplitude = 0.2

        # 缓存（已处理的 PCM 帧列表）
        self._cached_frames: List[bytes] = []
        self._cache_dirty = True

        # 当前缓存对应的编码格式
        self._cached_codec = ""

    # ==================== 配置 ====================

    def configure(self, enabled: bool, tail_type: str = "default",
                  custom_file: str = "", mdc_id: int = 0,
                  amplitude: float = 0.2):
        """更新尾音配置"""
        changed = (
            self._enabled != enabled or
            self._tail_type != tail_type or
            self._custom_file != custom_file or
            self._mdc_id != mdc_id or
            abs(self._amplitude - amplitude) >= 0.001
        )
        if changed:
            self._enabled = enabled
            self._tail_type = tail_type
            self._custom_file = custom_file
            self._mdc_id = mdc_id
            self._amplitude = amplitude
            self._cache_dirty = True
            logger.info(f"尾音配置更新: type={tail_type}, enabled={enabled}")

    def on_codec_changed(self):
        """编码格式变化时清除缓存"""
        self._cache_dirty = True

    def get_mdc_id(self) -> int:
        """获取 MDC ID（为 0 时回退到 DMR ID）"""
        if self._mdc_id > 0:
            return self._mdc_id
        return self._get_dmr_id()

    # ==================== 获取尾音帧 ====================

    def get_tail_tone_frames(self) -> List[bytes]:
        """获取尾音 PCM 帧列表（已按当前编码格式分帧）

        Returns:
            帧列表，每帧大小匹配当前编码的 PCM 帧大小。
            如果尾音未启用或加载失败，返回空列表。
        """
        if not self._enabled:
            return []

        codec = self._get_codec()
        frame_size = self._get_frame_size()

        # 检查缓存是否有效
        if not self._cache_dirty and self._cached_codec == codec:
            return self._cached_frames

        # 生成/加载尾音
        pcm_8k = self._load_tail_pcm()
        if not pcm_8k:
            self._cached_frames = []
            self._cache_dirty = False
            self._cached_codec = codec
            return []

        # Opus 模式需要重采样到 16kHz
        if codec == "opus":
            pcm = self._resample_8k_to_16k(pcm_8k)
        else:
            pcm = pcm_8k

        # 分帧
        frames = self._split_into_frames(pcm, frame_size)

        self._cached_frames = frames
        self._cache_dirty = False
        self._cached_codec = codec

        logger.info(f"尾音已准备: {len(frames)} 帧, codec={codec}, "
                    f"frame_size={frame_size}")
        return frames

    # ==================== 尾音生成/加载 ====================

    def _load_tail_pcm(self) -> Optional[bytes]:
        """根据类型加载 8kHz PCM 尾音数据"""
        try:
            if self._tail_type == "default":
                return self._generate_default_tail()
            elif self._tail_type == "custom":
                return self._load_custom_tail(self._custom_file)
            elif self._tail_type == "mdc":
                return self._generate_mdc_tail(self._mdc_id)
            else:
                logger.warning(f"未知尾音类型: {self._tail_type}")
                return None
        except Exception as e:
            logger.error(f"加载尾音失败: {e}")
            return None

    def _generate_default_tail(self) -> bytes:
        """生成默认尾音（DTMF 拨号音 "91" 双发）"""
        sample_rate = NATIVE_SAMPLE_RATE
        amplitude = DEFAULT_TAIL_AMPLITUDE
        digits = "91"
        all_samples = []

        for repeat in range(DTMF_REPEAT):
            for ch in digits:
                freqs = DTMF_FREQS.get(ch)
                if not freqs:
                    continue
                f_row, f_col = freqs
                num_samples = sample_rate * DTMF_DIGIT_MS // 1000
                fade = num_samples // 10  # 10% 淡入淡出

                for i in range(num_samples):
                    t = i / sample_rate
                    envelope = min(1.0, i / max(fade, 1)) * \
                               min(1.0, (num_samples - i) / max(fade, 1))
                    value = int(amplitude * envelope * (
                        math.sin(2 * math.pi * f_row * t) +
                        math.sin(2 * math.pi * f_col * t)
                    ) / 2)
                    all_samples.append(max(-32768, min(32767, value)))

                # 数字间静音
                pause_samples = sample_rate * DTMF_PAUSE_MS // 1000
                all_samples.extend([0] * pause_samples)

        return struct.pack(f'<{len(all_samples)}h', *all_samples)

    def _load_custom_tail(self, file_path: str) -> Optional[bytes]:
        """加载自定义尾音文件（支持 WAV 和 raw PCM）"""
        if not file_path:
            logger.warning("自定义尾音文件路径为空")
            return None

        try:
            if file_path.lower().endswith('.wav'):
                return self._load_wav(file_path)
            else:
                return self._load_raw_pcm(file_path)
        except Exception as e:
            logger.error(f"加载自定义尾音文件失败: {e}")
            return None

    def _load_wav(self, file_path: str) -> Optional[bytes]:
        """加载 WAV 文件并转换为 8kHz mono int16 PCM"""
        with wave.open(file_path, 'rb') as wf:
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            nframes = wf.getnframes()

            # 限制最大时长
            max_frames = int(framerate * MAX_TAIL_DURATION_S)
            if nframes > max_frames:
                logger.warning(f"尾音文件过长，截断到 {MAX_TAIL_DURATION_S}s")
                nframes = max_frames

            raw = wf.readframes(nframes)

        # 转换为 int16
        if sampwidth == 2:
            samples = list(struct.unpack(f'<{len(raw)//2}h', raw))
        elif sampwidth == 1:
            # 8-bit unsigned -> 16-bit signed
            samples = [(b - 128) * 256 for b in raw]
        elif sampwidth == 4:
            # 32-bit -> 16-bit
            samples_32 = struct.unpack(f'<{len(raw)//4}i', raw)
            samples = [s >> 16 for s in samples_32]
        else:
            logger.error(f"不支持的 WAV 位深: {sampwidth * 8}bit")
            return None

        # 多声道转单声道（取平均）
        if channels == 2:
            mono = []
            for i in range(0, len(samples) - 1, 2):
                mono.append((samples[i] + samples[i + 1]) // 2)
            samples = mono
        elif channels > 2:
            mono = []
            for i in range(0, len(samples) - channels + 1, channels):
                mono.append(sum(samples[i:i + channels]) // channels)
            samples = mono

        # 重采样到 8kHz（如果需要）
        if framerate != NATIVE_SAMPLE_RATE:
            samples = self._resample_samples(samples, framerate,
                                             NATIVE_SAMPLE_RATE)

        return struct.pack(f'<{len(samples)}h', *samples)

    def _load_raw_pcm(self, file_path: str) -> Optional[bytes]:
        """加载 raw PCM 文件（假设 8kHz int16 mono）"""
        with open(file_path, 'rb') as f:
            data = f.read()

        if not data:
            logger.warning("raw PCM 文件为空")
            return None

        # 限制最大时长
        max_bytes = int(NATIVE_SAMPLE_RATE * MAX_TAIL_DURATION_S) * 2
        if len(data) > max_bytes:
            logger.warning(f"raw PCM 文件过长，截断到 {MAX_TAIL_DURATION_S}s")
            data = data[:max_bytes]

        # 确保偶数长度（int16 对齐）
        if len(data) % 2 != 0:
            data = data[:-1]

        return data

    def _generate_mdc_tail(self, unit_id: int) -> bytes:
        """生成 MDC1200 PTT ID 尾音"""
        # 如果 unit_id 为 0，回退到 DMR ID
        if unit_id <= 0:
            unit_id = self.get_mdc_id()
            logger.info(f"MDC ID 为 0，回退到 DMR ID: {unit_id}")

        encoder = MDC1200Encoder()
        encoder.set_packet(OP_PTT_ID, 0x00, unit_id)
        pcm = encoder.get_samples(amplitude=self._amplitude)

        if not pcm:
            logger.error("MDC1200 编码失败")
            return b''

        return pcm

    # ==================== 重采样 ====================

    @staticmethod
    def _resample_8k_to_16k(pcm_8k: bytes) -> bytes:
        """8kHz int16 PCM -> 16kHz int16 PCM（线性插值）"""
        if not pcm_8k:
            return b''

        num_samples = len(pcm_8k) // 2
        samples = struct.unpack(f'<{num_samples}h', pcm_8k)
        out = []

        for i in range(num_samples - 1):
            out.append(samples[i])
            out.append((samples[i] + samples[i + 1]) // 2)
        out.append(samples[-1])
        out.append(0)

        return struct.pack(f'<{len(out)}h', *out)

    @staticmethod
    def _resample_samples(samples: list, src_rate: int,
                          dst_rate: int) -> list:
        """对采样列表进行重采样（线性插值）"""
        if src_rate == dst_rate or not samples:
            return samples

        ratio = src_rate / dst_rate
        out_len = int(len(samples) / ratio)
        out = []

        for i in range(out_len):
            pos = i * ratio
            idx = int(pos)
            frac = pos - idx
            if idx + 1 < len(samples):
                val = samples[idx] * (1 - frac) + samples[idx + 1] * frac
            else:
                val = samples[idx] if idx < len(samples) else 0
            out.append(int(max(-32768, min(32767, val))))

        return out

    # ==================== 帧分割 ====================

    @staticmethod
    def _split_into_frames(pcm_data: bytes, frame_size: int) -> List[bytes]:
        """将连续 PCM 数据分割为固定大小的帧

        末帧不足时补静音。
        """
        if not pcm_data or frame_size <= 0:
            return []

        frames = []
        offset = 0
        while offset < len(pcm_data):
            end = offset + frame_size
            chunk = pcm_data[offset:end]
            # 末帧补静音
            if len(chunk) < frame_size:
                chunk = chunk + b'\x00' * (frame_size - len(chunk))
            frames.append(chunk)
            offset = end

        return frames
