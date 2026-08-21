"""Record PCM audio already handled by the client.

This service deliberately does not open an input device. PCM is supplied by
the talk pipeline through :meth:`append_pcm`.
"""
import logging
import os
import threading
import time
import wave
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class RecordingService:
    """Capture received and transmitted client audio to a WAV file."""

    def __init__(self, audio_handler, settings):
        # audio_handler is retained in the constructor for caller compatibility
        # but is intentionally never started or used for recording.
        self._settings = settings
        self._lock = threading.Lock()
        self._is_recording = False
        self._recording_start_time = 0.0
        self._recording_file: Optional[str] = None
        self._recording_frames = []
        self._max_duration_timer: Optional[threading.Timer] = None
        self._recordings_dir = os.path.join(
            os.path.expanduser("~"), "Documents", "78HAM_Recordings"
        )
        os.makedirs(self._recordings_dir, exist_ok=True)

        self.on_recording_started: Optional[Callable[[], None]] = None
        self.on_recording_stopped: Optional[Callable[[str], None]] = None
        self.on_recording_error: Optional[Callable[[str], None]] = None

    def start_recording(self) -> bool:
        """Start buffering software PCM. No microphone is opened."""
        with self._lock:
            if self._is_recording:
                return False
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._recording_file = os.path.join(
                self._recordings_dir, f"recording_{timestamp}.wav"
            )
            self._recording_frames = []
            self._recording_start_time = time.time()
            self._is_recording = True
            max_duration = self._settings.recording.max_duration
            if max_duration:
                timer = threading.Timer(max_duration, self.stop_recording)
                timer.daemon = True
                self._max_duration_timer = timer
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
            if self.on_recording_stopped:
                self.on_recording_stopped(file_path)
            logger.info("软件音频录音已保存: %s (%d 帧)", file_path, len(frames))
            return file_path
        except Exception as exc:
            message = f"保存软件录音失败: {exc}"
            logger.error(message)
            if self.on_recording_error:
                self.on_recording_error(message)
            return None

    def bind_audio_handler(self, audio_handler):
        """Compatibility no-op: software recording has no input handler."""

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._is_recording

    @property
    def recording_duration(self) -> float:
        with self._lock:
            return time.time() - self._recording_start_time if self._is_recording else 0.0

    @property
    def recording_file(self) -> Optional[str]:
        return self._recording_file

    def get_recordings_dir(self) -> str:
        return self._recordings_dir
