"""
录音服务

提供本地录音功能，支持录制为WAV文件。
"""
import os
import time
import wave
import logging
import threading
from typing import Optional, Callable
from datetime import datetime

logger = logging.getLogger(__name__)


class RecordingService:
    """录音服务
    
    功能：
    - 录制本地音频（麦克风输入）
    - 保存为WAV文件
    - 支持开始/停止录音
    - 录音文件自动命名
    """
    
    def __init__(self, audio_handler, settings):
        """初始化录音服务
        
        Args:
            audio_handler: AudioHandler实例
            settings: Settings实例
        """
        self._audio_handler = audio_handler
        self._settings = settings
        
        # 录音状态
        self._is_recording = False
        self._recording_start_time: float = 0.0
        self._recording_file: Optional[str] = None
        self._recording_frames: list = []
        self._lock = threading.Lock()
        self._max_duration_timer: Optional[threading.Timer] = None
        
        # 回调
        self.on_recording_started: Optional[Callable[[], None]] = None
        self.on_recording_stopped: Optional[Callable[[str], None]] = None
        self.on_recording_error: Optional[Callable[[str], None]] = None
        
        # 录音目录
        self._recordings_dir = os.path.join(os.path.expanduser("~"), "Documents", "78HAM_Recordings")
        os.makedirs(self._recordings_dir, exist_ok=True)
        
        logger.info(f"录音服务初始化完成，录音目录: {self._recordings_dir}")
    
    def start_recording(self) -> bool:
        """开始录音
        
        Returns:
            是否成功开始录音
        """
        with self._lock:
            if self._is_recording:
                logger.warning("已经在录音中")
                return False

            try:
                # 生成录音文件名
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                self._recording_file = os.path.join(
                    self._recordings_dir, 
                    f"recording_{timestamp}.wav"
                )
                
                # 清空录音帧缓冲
                self._recording_frames = []
                
                # 使用独立回调，避免覆盖 PTT 发射回调。
                self._audio_handler.add_recording_callback(self._audio_callback)
                self._audio_handler.start_recording()

                self._is_recording = True
                self._recording_start_time = time.time()
                max_duration = self._settings.recording.max_duration
                if max_duration:
                    self._max_duration_timer = threading.Timer(
                        max_duration, self.stop_recording)
                    self._max_duration_timer.daemon = True
                    self._max_duration_timer.start()
                
                logger.info(f"开始录音: {self._recording_file}")
                
                if self.on_recording_started:
                    self.on_recording_started()
                
                return True
                
            except Exception as e:
                logger.error(f"开始录音失败: {e}")
                if self.on_recording_error:
                    self.on_recording_error(f"开始录音失败: {e}")
                self._audio_handler.remove_recording_callback(self._audio_callback)
                return False

    def bind_audio_handler(self, audio_handler):
        """Bind the service to a newly-created audio stream manager."""
        with self._lock:
            if self._is_recording:
                raise RuntimeError("cannot replace audio handler while recording")
            self._audio_handler = audio_handler
    
    def stop_recording(self) -> Optional[str]:
        """停止录音
        
        Returns:
            录音文件路径，失败返回None
        """
        with self._lock:
            if not self._is_recording:
                logger.warning("没有在录音")
                return None
            
            try:
                self._is_recording = False
                if self._max_duration_timer:
                    self._max_duration_timer.cancel()
                    self._max_duration_timer = None
                
                # 停止音频录制
                self._audio_handler.remove_recording_callback(self._audio_callback)
                self._audio_handler.stop_recording()
                
                # 保存录音文件
                if self._recording_frames and self._recording_file:
                    self._save_wav_file()
                    
                    duration = time.time() - self._recording_start_time
                    logger.info(f"录音完成: {self._recording_file} ({duration:.1f}秒)")
                    
                    if self.on_recording_stopped:
                        self.on_recording_stopped(self._recording_file)
                    
                    return self._recording_file
                else:
                    logger.warning("录音数据为空")
                    if self.on_recording_error:
                        self.on_recording_error("录音数据为空")
                    return None
                    
            except Exception as e:
                logger.error(f"停止录音失败: {e}")
                if self.on_recording_error:
                    self.on_recording_error(f"停止录音失败: {e}")
                return None
    
    def _audio_callback(self, data: bytes):
        """音频数据回调
        
        Args:
            data: PCM音频数据
        """
        with self._lock:
            if self._is_recording:
                self._recording_frames.append(data)
    
    def _save_wav_file(self):
        """保存录音为WAV文件"""
        if not self._recording_frames or not self._recording_file:
            return
        
        try:
            # 获取音频参数
            sample_rate = self._settings.audio.sample_rate
            channels = self._settings.audio.channels
            sample_width = 2  # 16-bit PCM
            
            # 写入WAV文件
            with wave.open(self._recording_file, 'wb') as wav_file:
                wav_file.setnchannels(channels)
                wav_file.setsampwidth(sample_width)
                wav_file.setframerate(sample_rate)
                
                # 合并所有音频帧
                audio_data = b''.join(self._recording_frames)
                wav_file.writeframes(audio_data)
            
            logger.info(f"WAV文件保存成功: {self._recording_file}")
            
        except Exception as e:
            logger.error(f"保存WAV文件失败: {e}")
            raise
    
    @property
    def is_recording(self) -> bool:
        """是否正在录音"""
        return self._is_recording
    
    @property
    def recording_duration(self) -> float:
        """获取当前录音时长（秒）"""
        if self._is_recording:
            return time.time() - self._recording_start_time
        return 0.0
    
    @property
    def recording_file(self) -> Optional[str]:
        """获取当前录音文件路径"""
        return self._recording_file
    
    def get_recordings_dir(self) -> str:
        """获取录音目录"""
        return self._recordings_dir
