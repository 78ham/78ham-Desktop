"""语音处理器 - 处理 G.711 和 Opus 编解码"""
import logging
from typing import Dict
from core.codec import G711Codec, OpusCodec
from core.protocol import PacketType

logger = logging.getLogger(__name__)


class VoiceProcessor:
    """语音处理器

    职责：
    - G.711 / Opus 编解码
    - 编码统计
    """

    def __init__(self, codec_type: str = "g711"):
        self.codec_type = codec_type
        self.g711_codec = G711Codec()
        self._opus_codec = None

        self.encode_count = 0
        self.decode_count = 0
        self.error_count = 0

    @property
    def opus_codec(self) -> OpusCodec:
        if self._opus_codec is None:
            if not OpusCodec.is_available():
                raise ImportError("opuslib 未安装，无法使用Opus编码。请运行: pip install opuslib")
            self._opus_codec = OpusCodec()
        return self._opus_codec

    def set_codec(self, codec_type: str):
        self.codec_type = codec_type

    def encode_voice(self, pcm_data: bytes) -> bytes:
        if self.codec_type == "opus":
            return self._encode_opus(pcm_data)
        return self._encode_g711(pcm_data)

    def decode_voice(self, data: bytes) -> bytes:
        if self.codec_type == "opus":
            return self._decode_opus(data)
        return self._decode_g711(data)

    def decode_voice_by_type(self, data: bytes, packet_type: int) -> bytes:
        if packet_type == PacketType.OPUS:
            return self._decode_opus(data)
        return self._decode_g711(data)

    def _encode_g711(self, pcm_data: bytes) -> bytes:
        try:
            if not pcm_data:
                return b'\xD5' * 160
            encoded = self.g711_codec.encode(pcm_data)
            if not encoded:
                return b'\xD5' * 160
            self.encode_count += 1
            return encoded
        except Exception as e:
            logger.error(f"G.711编码异常: {e}")
            self.error_count += 1
            return b'\xD5' * 160

    def _encode_opus(self, pcm_data: bytes) -> bytes:
        try:
            if not pcm_data:
                return self.opus_codec.encode(b'\x00' * OpusCodec.PCM_FRAME_BYTES)
            encoded = self.opus_codec.encode(pcm_data)
            if not encoded:
                return self.opus_codec.encode(b'\x00' * OpusCodec.PCM_FRAME_BYTES)
            self.encode_count += 1
            return encoded
        except Exception as e:
            logger.error(f"Opus编码异常: {e}")
            self.error_count += 1
            return b''

    def _decode_g711(self, g711_data: bytes) -> bytes:
        try:
            if not g711_data:
                return b'\x00' * 320
            pcm_data = self.g711_codec.decode(g711_data)
            if not pcm_data:
                return b'\x00' * 320
            self.decode_count += 1
            return pcm_data
        except Exception as e:
            logger.error(f"G.711解码异常: {e}")
            self.error_count += 1
            return b'\x00' * 320

    def _decode_opus(self, opus_data: bytes) -> bytes:
        try:
            if not opus_data:
                return b'\x00' * OpusCodec.PCM_FRAME_BYTES
            pcm_data = self.opus_codec.decode(opus_data)
            if not pcm_data:
                return b'\x00' * OpusCodec.PCM_FRAME_BYTES
            self.decode_count += 1
            return pcm_data
        except Exception as e:
            logger.error(f"Opus解码异常: {e}")
            self.error_count += 1
            return b'\x00' * OpusCodec.PCM_FRAME_BYTES

    def process_recorded_audio(self, pcm_data: bytes) -> bytes:
        return self.encode_voice(pcm_data)

    def process_received_audio(self, audio_data: bytes, packet_type: int = 1) -> bytes:
        return self.decode_voice_by_type(audio_data, packet_type)

    def get_stats(self) -> Dict[str, int]:
        return {
            'encode_count': self.encode_count,
            'decode_count': self.decode_count,
            'error_count': self.error_count,
        }
