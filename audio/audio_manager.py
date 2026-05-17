"""
音频管理器

对现有 audio_handler.py 的薄封装层，提供统一接口。
后续可逐步将 audio_handler.py 拆分为 recorder.py / player.py / jitter_buffer.py。
"""
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class AudioManager:
    """音频管理器

    封装录音和播放功能，协调编解码与 PTT 状态。
    当前阶段直接委托给 audio_handler.AudioHandler。
    """

    def __init__(self, sample_rate: int = 8000, channels: int = 1,
                 chunk_size: int = 320, format_str: str = "paInt16",
                 codec_type: str = "g711"):
        # 延迟导入，保持向后兼容
        from audio.audio_handler import AudioHandler, VoiceProcessor

        self._handler = AudioHandler(
            sample_rate=sample_rate,
            channels=channels,
            chunk_size=chunk_size,
            format_str=format_str,
            codec_type=codec_type,
        )
        self._voice_processor = VoiceProcessor(codec_type=codec_type)
        self._codec_type = codec_type

        logger.info(f"AudioManager 初始化 (编码: {codec_type}, 采样率: {sample_rate}Hz)")

    # ==================== 录音 ====================

    def start_recording(self, callback: Callable[[bytes], None]):
        """开始录音

        Args:
            callback: 每帧 PCM 数据的回调函数
        """
        self._handler.start_recording(callback)

    def stop_recording(self):
        """停止录音"""
        self._handler.stop_recording()

    def is_recording(self) -> bool:
        """是否正在录音"""
        return self._handler.is_recording_active()

    # ==================== 播放 ====================

    def start_playback(self):
        """开始播放"""
        self._handler.start_playback()

    def stop_playback(self):
        """停止播放"""
        self._handler.stop_playback()

    def is_playing(self) -> bool:
        """是否正在播放"""
        return self._handler.is_playback_active()

    def add_playback_data(self, pcm_data: bytes):
        """添加 PCM 数据到播放缓冲区"""
        self._handler.add_playback_data_immediate(pcm_data)

    @property
    def playback_stop_flag(self) -> bool:
        return self._handler.playback_stop_flag

    @playback_stop_flag.setter
    def playback_stop_flag(self, value: bool):
        self._handler.playback_stop_flag = value

    # ==================== 编解码 ====================

    def encode_voice(self, pcm_data: bytes) -> bytes:
        """编码语音数据"""
        return self._voice_processor.encode_voice(pcm_data)

    def decode_voice_by_type(self, data: bytes, packet_type: int) -> bytes:
        """根据包类型解码语音数据"""
        return self._voice_processor.decode_voice_by_type(data, packet_type)

    # ==================== 编码切换 ====================

    def set_codec(self, codec_type: str, sample_rate: int):
        """切换编码格式（需要重建音频流）"""
        from audio.audio_handler import AudioHandler, VoiceProcessor

        chunk_size = 640 if codec_type == 'opus' else 320

        self._handler.stop_recording()
        self._handler.stop_playback()
        self._handler.close()
        self._handler = AudioHandler(
            sample_rate=sample_rate,
            channels=1,
            chunk_size=chunk_size,
            format_str="paInt16",
            codec_type=codec_type,
        )
        self._voice_processor.set_codec(codec_type)
        self._codec_type = codec_type

    # ==================== 设备管理 ====================

    def list_devices(self):
        """列出音频设备"""
        return self._handler.list_audio_devices()

    def get_input_devices(self) -> list:
        """获取可用的输入设备列表"""
        return self._handler.get_input_devices()

    def get_output_devices(self) -> list:
        """获取可用的输出设备列表"""
        return self._handler.get_output_devices()

    def set_input_device(self, device_index: int) -> bool:
        """设置输入设备"""
        return self._handler.set_input_device(device_index)

    def set_output_device(self, device_index: int) -> bool:
        """设置输出设备"""
        return self._handler.set_output_device(device_index)

    def get_current_input_device(self) -> dict:
        """获取当前输入设备信息"""
        return self._handler.get_current_input_device()

    def get_current_output_device(self) -> dict:
        """获取当前输出设备信息"""
        return self._handler.get_current_output_device()

    def get_buffer_status(self) -> dict:
        """获取缓冲区状态"""
        return self._handler.get_buffer_status()

    # ==================== 生命周期 ====================

    def close(self):
        """关闭音频管理器"""
        try:
            self._handler.close()
        except Exception as e:
            logger.error(f"关闭音频管理器异常: {e}")
