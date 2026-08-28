"""Record PCM audio already handled by the client.

This service deliberately does not open an input device. PCM is supplied by
the talk pipeline through :meth:`append_pcm` (local microphone frames and
received network frames both feed the same buffer).
"""
import logging
import os
import threading
import time
import wave
from datetime import datetime
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_RECORDINGS_DIR = os.path.join(
    os.path.expanduser("~"), "Documents", "78HAM_Recordings"
)


def _ensure_writable_dir(path: str) -> bool:
    """Create path if needed; return True only when it is a usable directory."""
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:
        logger.error("无法创建录音目录 %s: %s", path, exc)
        return False
    return os.path.isdir(path)


class RecordingService:
    """Capture received and transmitted client audio to a WAV file."""

    def __init__(self, settings, recordings_dir: Optional[str] = None):
        self._settings = settings
        self._lock = threading.Lock()
        self._is_recording = False
        self._recording_start_time = 0.0
        self._recording_file: Optional[str] = None
        self._recording_frames: List[bytes] = []
        self._max_duration_timer: Optional[threading.Timer] = None

        # 保存目录优先级：显式参数 > 配置文件 > 默认目录；目录不可用时回退默认
        requested = recordings_dir or settings.recording.save_dir
        if requested and _ensure_writable_dir(requested):
            self._recordings_dir = requested
        else:
            if requested:
                logger.warning("录音目录不可用，回退默认目录: %s", requested)
            self._recordings_dir = DEFAULT_RECORDINGS_DIR
            _ensure_writable_dir(self._recordings_dir)

        self.on_recording_started: Optional[Callable[[], None]] = None
        self.on_recording_stopped: Optional[Callable[[str], None]] = None
        self.on_recording_error: Optional[Callable[[str], None]] = None

    # ==================== 保存目录 ====================

    @property
    def recordings_dir(self) -> str:
        return self._recordings_dir

    def set_recordings_dir(self, path: str) -> bool:
        """切换录音保存目录，对下一次录音生效。无效路径返回 False 且保持原目录。"""
        if not path or not _ensure_writable_dir(path):
            return False
        self._recordings_dir = path
        logger.info("录音保存目录已切换: %s", path)
        return True

    def list_recordings(self) -> List[str]:
        """列出目录中已有的录音文件（最新在前）。"""
        try:
            names = os.listdir(self._recordings_dir)
        except OSError:
            return []
        paths = [
            os.path.join(self._recordings_dir, name)
            for name in names
            if name.startswith("recording_") and name.lower().endswith(".wav")
        ]
        return sorted((p for p in paths if os.path.isfile(p)),
                      key=os.path.getmtime, reverse=True)

    # ==================== 录音控制 ====================

    def start_recording(self) -> bool:
        """Start buffering software PCM. No microphone is opened."""
        timer: Optional[threading.Timer] = None
        with self._lock:
            if self._is_recording:
                return False
            if not _ensure_writable_dir(self._recordings_dir):
                message = f"录音目录不可用: {self._recordings_dir}"
                logger.error(message)
                if self.on_recording_error:
                    self.on_recording_error(message)
                return False
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # 秒级时间戳可能撞名（同一秒内两次录音），追加序号避免覆盖
            base = f"recording_{timestamp}"
            file_path = os.path.join(self._recordings_dir, f"{base}.wav")
            suffix = 1
            while os.path.exists(file_path):
                file_path = os.path.join(
                    self._recordings_dir, f"{base}_{suffix}.wav")
                suffix += 1
            self._recording_file = file_path
            self._recording_frames = []
            self._recording_start_time = time.monotonic()
            self._is_recording = True
            max_duration = self._settings.recording.max_duration
            if max_duration:
                timer = threading.Timer(max_duration, self.stop_recording)
                timer.daemon = True
                self._max_duration_timer = timer
        if timer:
            timer.start()
        if self.on_recording_started:
            self.on_recording_started()
        logger.info("开始软件音频录音: %s", self._recording_file)
        return True

    def append_pcm(self, pcm_data: bytes):
        """Append one already-decoded PCM frame from the talk pipeline."""
        if not pcm_data:
            return
        with self._lock:
            if self._is_recording:
                self._recording_frames.append(bytes(pcm_data))

    def stop_recording(self) -> Optional[str]:
        """停止录音并写盘，返回文件路径；未在录音时返回 None。

        可以从任意线程调用（包括最长时长定时器线程），因此
        on_recording_stopped / on_recording_error 回调可能不在调用方线程，
        GUI 侧需要自行切回主线程。
        """
        with self._lock:
            if not self._is_recording:
                return None
            self._is_recording = False
            timer, self._max_duration_timer = self._max_duration_timer, None
            file_path = self._recording_file
            frames = self._recording_frames
            self._recording_frames = []
        if timer:
            timer.cancel()
        try:
            if not frames or not file_path:
                raise RuntimeError("没有采集到软件语音 PCM")
            with wave.open(file_path, "wb") as wav_file:
                wav_file.setnchannels(self._settings.audio.channels)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self._settings.audio.sample_rate)
                wav_file.writeframes(b"".join(frames))
            logger.info("软件音频录音已保存: %s (%d 帧)", file_path, len(frames))
            if self.on_recording_stopped:
                self.on_recording_stopped(file_path)
            return file_path
        except Exception as exc:
            message = f"保存软件录音失败: {exc}"
            logger.error(message)
            if self.on_recording_error:
                self.on_recording_error(message)
            return None

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._is_recording

    @property
    def recording_file(self) -> Optional[str]:
        return self._recording_file
