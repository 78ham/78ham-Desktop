"""
音频处理模块
处理麦克风输入和扬声器输出，以及G.711编解码
"""
import threading
import numpy as np  # type: ignore
import logging
import time
import pyaudio  # type: ignore
from typing import Optional, Callable, Dict, Tuple, List
from collections import deque
from core.codec import G711Codec, OpusCodec
from core.protocol import PacketType

logger = logging.getLogger(__name__)


class AudioHandler:
    """音频处理类"""
    
    # 音频格式映射（类级别常量，避免重复创建）
    FORMAT_MAP = {
        "paInt16": pyaudio.paInt16,
        "paInt32": pyaudio.paInt32,
        "paFloat32": pyaudio.paFloat32,
    }

    # --- 以下方法将逐步拆分到独立模块：recorder.py / player.py / jitter_buffer.py ---
    
    def __init__(self, sample_rate: int = 8000, channels: int = 1, 
                 chunk_size: int = 320, format_str: str = "paInt16",
                 codec_type: str = "g711"):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.format = self._get_format(format_str)
        self.format_str = format_str
        self.codec_type = codec_type
        
        # 根据编码格式确定PCM帧大小（每帧20ms）
        # G.711: 8kHz * 0.02s * 2bytes = 320字节PCM → 160字节G.711
        # Opus:  16kHz * 0.02s * 2bytes = 640字节PCM → 变长Opus帧
        self.pcm_frame_size = self._calc_pcm_frame_size(codec_type, sample_rate)
        
        self.pyaudio = None  # 延迟初始化，避免阻塞GUI线程
        self.input_stream = None
        self.output_stream = None
        
        # 设备选择
        self.input_device_index = None  # 输入设备索引
        self.output_device_index = None  # 输出设备索引
        
        # 音频回调函数
        self.audio_callback: Optional[Callable[[bytes], None]] = None
        
        # 录音状态
        self.is_recording = False
        self.is_playing = False
        
        # 线程安全（RLock 支持可重入，避免 _ensure_pyaudio 在持有锁时再次获取锁导致死锁）
        self.lock = threading.RLock()
        
        # 音频缓冲区
        self.record_buffer = []
        self.play_buffer = deque()  # 播放缓冲区，使用deque提高性能
        
        # 语音数据缓存（累积到一帧PCM后发送）
        self.voice_data_cache = bytearray()
        self.voice_cache_lock = threading.RLock()
        self.last_voice_send_time = 0.0
        
        # 网络抖动缓冲
        self.jitter_buffer_size = 3  # 缓冲3个数据包（约60ms）
        self.jitter_buffer = deque(maxlen=self.jitter_buffer_size)
        self.jitter_buffer_lock = threading.Lock()
        
        # 播放停止标志 - 用于避免超时检查线程与播放回调的死锁
        self.playback_stop_flag = False

        # 软件重采样状态
        self._recording_native_rate = self.sample_rate
        self._recording_need_resample = False
        
    def _get_format(self, format_str: str) -> int:
        """获取PyAudio格式"""
        return self.FORMAT_MAP.get(format_str, pyaudio.paInt16)
    
    @staticmethod
    def _calc_pcm_frame_size(codec_type: str, sample_rate: int) -> int:
        """根据编码格式和采样率计算每帧PCM字节数
        
        G.711: 8kHz, 20ms帧 = 160 samples = 320字节PCM
        Opus:  16kHz, 20ms帧 = 320 samples = 640字节PCM
        """
        frame_duration_s = 0.02  # 20ms
        bytes_per_sample = 2  # 16-bit PCM
        return int(sample_rate * frame_duration_s * bytes_per_sample)
    
    def set_codec_type(self, codec_type: str, sample_rate: Optional[int] = None):
        """运行时切换编码格式
        
        Args:
            codec_type: "g711" 或 "opus"
            sample_rate: 新采样率（None则使用默认值）
        """
        self.codec_type = codec_type
        if sample_rate is not None:
            self.sample_rate = sample_rate
        self.pcm_frame_size = self._calc_pcm_frame_size(codec_type, self.sample_rate)
        logger.info(f"音频编码格式已切换为: {codec_type}, PCM帧大小: {self.pcm_frame_size}字节, 采样率: {self.sample_rate}Hz")

    def _ensure_pyaudio(self):
        """延迟初始化PyAudio，线程安全，避免多线程同时初始化PortAudio"""
        if self.pyaudio is None:
            with self.lock:
                if self.pyaudio is None:
                    self.pyaudio = pyaudio.PyAudio()
    
    def list_audio_devices(self) -> List[Dict]:
        """列出所有音频设备"""
        self._ensure_pyaudio()
        device_count = self.pyaudio.get_device_count()
        devices = []
        
        for i in range(device_count):
            device_info = self.pyaudio.get_device_info_by_index(i)
            devices.append({
                'index': i,
                'name': device_info['name'],
                'max_input_channels': device_info['maxInputChannels'],
                'max_output_channels': device_info['maxOutputChannels'],
                'default_sample_rate': device_info['defaultSampleRate']
            })
            logger.info(
                f"设备 {i}: {device_info['name']} "
                f"(输入:{device_info['maxInputChannels']}, "
                f"输出:{device_info['maxOutputChannels']}, "
                f"采样率:{device_info['defaultSampleRate']})")
        
        return devices
    
    def get_input_devices(self) -> List[Dict]:
        """获取所有可用的输入设备"""
        self._ensure_pyaudio()
        devices = []
        device_count = self.pyaudio.get_device_count()
        
        for i in range(device_count):
            device_info = self.pyaudio.get_device_info_by_index(i)
            if device_info['maxInputChannels'] > 0:
                devices.append({
                    'index': i,
                    'name': device_info['name'],
                    'channels': device_info['maxInputChannels'],
                    'sample_rate': device_info['defaultSampleRate']
                })
        
        return devices
    
    def get_output_devices(self) -> List[Dict]:
        """获取所有可用的输出设备"""
        self._ensure_pyaudio()
        devices = []
        device_count = self.pyaudio.get_device_count()
        
        for i in range(device_count):
            device_info = self.pyaudio.get_device_info_by_index(i)
            if device_info['maxOutputChannels'] > 0:
                devices.append({
                    'index': i,
                    'name': device_info['name'],
                    'channels': device_info['maxOutputChannels'],
                    'sample_rate': device_info['defaultSampleRate']
                })
        
        return devices
    
    def set_input_device(self, device_index: int) -> bool:
        """设置输入设备"""
        self._ensure_pyaudio()
        try:
            device_info = self.pyaudio.get_device_info_by_index(device_index)
            if device_info['maxInputChannels'] == 0:
                raise ValueError(f"设备 {device_index} 不支持输入")
            
            self.input_device_index = device_index
            logger.info(f"输入设备已设置为: {device_info['name']}")
            return True
        except Exception as e:
            logger.error(f"设置输入设备失败: {e}")
            return False
    
    def set_output_device(self, device_index: int) -> bool:
        """设置输出设备"""
        self._ensure_pyaudio()
        try:
            device_info = self.pyaudio.get_device_info_by_index(device_index)
            if device_info['maxOutputChannels'] == 0:
                raise ValueError(f"设备 {device_index} 不支持输出")
            
            self.output_device_index = device_index
            logger.info(f"输出设备已设置为: {device_info['name']}")
            return True
        except Exception as e:
            logger.error(f"设置输出设备失败: {e}")
            return False
    
    def get_current_input_device(self) -> Optional[Dict]:
        """获取当前输入设备信息"""
        if self.input_device_index is not None:
            self._ensure_pyaudio()
            try:
                device_info = self.pyaudio.get_device_info_by_index(self.input_device_index)
                return {
                    'index': self.input_device_index,
                    'name': device_info['name'],
                    'channels': device_info['maxInputChannels'],
                    'sample_rate': device_info['defaultSampleRate']
                }
            except Exception as e:
                logger.error(f"获取输入设备信息失败: {e}")
        return None
    
    def get_current_output_device(self) -> Optional[Dict]:
        """获取当前输出设备信息"""
        if self.output_device_index is not None:
            self._ensure_pyaudio()
            try:
                device_info = self.pyaudio.get_device_info_by_index(self.output_device_index)
                return {
                    'index': self.output_device_index,
                    'name': device_info['name'],
                    'channels': device_info['maxOutputChannels'],
                    'sample_rate': device_info['defaultSampleRate']
                }
            except Exception as e:
                logger.error(f"获取输出设备信息失败: {e}")
        return None
    
    def start_recording(self, callback: Optional[Callable[[bytes], None]] = None):
        """开始录音"""
        self._ensure_pyaudio()
        with self.lock:
            if self.is_recording:
                logger.warning("已经在录音中")
                return

            try:
                self.audio_callback = callback
                self.is_recording = True
                self.record_buffer = []

                # 检查设备是否支持请求的采样率，不匹配则启用软件重采样
                self._recording_native_rate = self.sample_rate
                self._recording_need_resample = False
                try:
                    dev_index = self.input_device_index
                    if dev_index is not None:
                        dev_info = self.pyaudio.get_device_info_by_index(dev_index)
                    else:
                        dev_info = self.pyaudio.get_device_info_by_index(
                            self.pyaudio.get_default_input_device_info()['index'])
                    native_rate = int(dev_info['defaultSampleRate'])
                    if native_rate != self.sample_rate:
                        self._recording_native_rate = native_rate
                        self._recording_need_resample = True
                        logger.info(
                            f"设备原生采样率 {native_rate}Hz ≠ 目标 {self.sample_rate}Hz，启用软件重采样")
                except Exception as e:
                    logger.debug(f"获取设备采样率失败: {e}，使用请求值")

                # 设置输入设备参数
                native_rate = self._recording_native_rate
                frames_per_buffer = int(native_rate * 0.02)
                input_params = {
                    'format': self.format,
                    'channels': self.channels,
                    'rate': native_rate,
                    'input': True,
                    'frames_per_buffer': frames_per_buffer,
                    'stream_callback': self._record_callback
                }

                # 如果有指定输入设备，使用指定设备
                if self.input_device_index is not None:
                    input_params['input_device_index'] = self.input_device_index
                    device_info = self.get_current_input_device()
                    device_name = device_info['name'] if device_info else f"设备{self.input_device_index}"
                    logger.info(f"使用输入设备: {device_name}")
                else:
                    logger.info("使用系统默认输入设备")

                self.input_stream = self.pyaudio.open(**input_params)
                self.input_stream.start_stream()
                logger.info("开始录音")
                
            except Exception as e:
                logger.error(f"开始录音失败: {e}")
                self.is_recording = False
                raise
    
    def stop_recording(self) -> bytes:
        """停止录音并返回录音数据"""
        stream_to_stop = None
        with self.lock:
            if not self.is_recording:
                logger.warning("没有在录音")
                return b""
            
            try:
                self.is_recording = False
                
                # 清空语音数据缓存
                with self.voice_cache_lock:
                    self.voice_data_cache.clear()
                    self.last_voice_send_time = 0.0
                
                stream_to_stop = self.input_stream
                self.input_stream = None
                
                # 合并录音数据
                recorded_data = b''.join(self.record_buffer)
                self.record_buffer = []
                
            except Exception as e:
                logger.error(f"停止录音失败: {e}")
                raise
        
        # 在锁外停止流，避免潜在阻塞（带超时保护）
        if stream_to_stop:
            try:
                self._safe_stop_stream(stream_to_stop, "录音")
            except Exception as e:
                logger.error(f"关闭录音流失败: {e}")
                try:
                    stream_to_stop.close()
                except Exception:
                    pass

        logger.info("停止录音")
        return recorded_data
    
    def start_playback(self):
        """开始播放"""
        self._ensure_pyaudio()
        with self.lock:
            if self.is_playing:
                logger.warning("已经在播放中")
                return
            
            try:
                self.is_playing = True
                self.playback_stop_flag = False
                self.play_buffer = deque()
                
                # 设置输出设备参数
                play_frames_per_buffer = int(self.sample_rate * 0.02)
                output_params = {
                    'format': self.format,
                    'channels': self.channels,
                    'rate': self.sample_rate,
                    'output': True,
                    'frames_per_buffer': play_frames_per_buffer,
                    'stream_callback': self._play_callback
                }
                
                # 如果有指定输出设备，使用指定设备
                if self.output_device_index is not None:
                    output_params['output_device_index'] = self.output_device_index
                    device_info = self.get_current_output_device()
                    device_name = device_info['name'] if device_info else f"设备{self.output_device_index}"
                    logger.info(f"使用输出设备: {device_name}")
                else:
                    logger.info("使用系统默认输出设备")
                
                self.output_stream = self.pyaudio.open(**output_params)
                self.output_stream.start_stream()
                logger.info("开始播放")
                
            except Exception as e:
                logger.error(f"开始播放失败: {e}")
                self.is_playing = False
                raise
    
    def stop_playback(self):
        """停止播放"""
        # 先刷入抖动缓冲区中的滞留数据
        self.flush_jitter_buffer()
        
        stream_to_stop = None
        with self.lock:
            if not self.is_playing:
                logger.warning("没有在播放")
                return
            
            try:
                self.is_playing = False
                self.playback_stop_flag = True
                
                stream_to_stop = self.output_stream
                self.output_stream = None
                
                self.play_buffer = deque()
                
            except Exception as e:
                logger.error(f"停止播放失败: {e}")
                raise
        
        # 在锁外停止流，避免与_play_callback死锁（带超时保护）
        if stream_to_stop:
            try:
                self._safe_stop_stream(stream_to_stop, "播放")
            except Exception as e:
                logger.error(f"关闭播放流失败: {e}")
        
        logger.info("停止播放")
    
    def _record_callback(self, in_data: bytes, frame_count: int, time_info: dict, status: int):
        """录音回调函数（PyAudio 音频线程调用）"""
        with self.lock:
            if not self.is_recording:
                return (None, pyaudio.paContinue)
            # 注：不再累积 record_buffer。录音 PCM 通过 audio_callback 实时
            # 逐帧消费，整段录音无消费方，累积只会导致长时间发射时内存无界增长。

        # 处理语音数据缓存 - 按PCM帧大小管理
        pending_callbacks = []
        with self.voice_cache_lock:
            # 软件重采样（设备采样率 ≠ 目标采样率时）
            if self._recording_need_resample:
                in_data = self._resample_pcm(
                    in_data, self._recording_native_rate, self.sample_rate)

            self.voice_data_cache.extend(in_data)

            current_time = time.time()
            frame_size = self.pcm_frame_size

            # 当缓存达到或超过一帧PCM时，立即发送
            while len(self.voice_data_cache) >= frame_size:
                send_data = bytes(self.voice_data_cache[:frame_size])
                # 原地删除已消费帧，避免每帧重新分配并拷贝整个 bytearray（O(n)）
                del self.voice_data_cache[:frame_size]
                self.last_voice_send_time = current_time

                if self.audio_callback:
                    pending_callbacks.append(send_data)

        # 在锁外调用回调，减少锁持有时间
        for send_data in pending_callbacks:
            self.audio_callback(send_data)

        return (None, pyaudio.paContinue)

    @staticmethod
    def _resample_pcm(pcm_data: bytes, src_rate: int, dst_rate: int) -> bytes:
        """软件重采样 PCM int16 数据（线性插值）"""
        if src_rate == dst_rate or not pcm_data:
            return pcm_data
        
        samples = np.frombuffer(pcm_data, dtype=np.int16)
        src_len = len(samples)
        dst_len = int(src_len * dst_rate / src_rate)
        
        if dst_len <= 0:
            return b'\x00' * (src_rate // dst_rate * 2)
        
        src_x = np.linspace(0, 1, src_len, endpoint=False)
        dst_x = np.linspace(0, 1, dst_len, endpoint=False)
        resampled = np.interp(dst_x, src_x, samples.astype(np.float64))
        return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()

    def _play_callback(self, in_data: bytes, frame_count: int, time_info: dict, status: int):
        """播放回调函数"""
        expected_length = frame_count * self.channels * 2

        with self.lock:
            if not self.is_playing or self.playback_stop_flag:
                return (b'\x00' * expected_length, pyaudio.paContinue)

            # 从缓冲区收集足够的数据
            data_chunks = []
            current_length = 0
            max_iterations = 100  # 安全保护，避免无限循环
            iterations = 0
            while self.play_buffer and current_length < expected_length and iterations < max_iterations:
                try:
                    data_chunk = self.play_buffer.popleft()
                    if data_chunk:
                        data_chunks.append(data_chunk)
                        current_length += len(data_chunk)
                    iterations += 1
                except (IndexError, AttributeError) as e:
                    logger.debug(f"播放缓冲获取异常: {e}")
                    break
        
        if data_chunks:
            combined_data = b''.join(data_chunks)
            
            if len(combined_data) == expected_length:
                return (combined_data, pyaudio.paContinue)
            elif len(combined_data) > expected_length:
                result_data = combined_data[:expected_length]
                remaining_data = combined_data[expected_length:]
                if remaining_data:
                    with self.lock:
                        # 重新检查播放状态：两次加锁间隙 stop_playback 可能已将
                        # play_buffer 替换为新 deque，避免把残留数据插入废弃缓冲
                        if self.is_playing and not self.playback_stop_flag:
                            self.play_buffer.appendleft(remaining_data)
                return (result_data, pyaudio.paContinue)
            else:
                silence = b'\x00' * (expected_length - len(combined_data))
                return (combined_data + silence, pyaudio.paContinue)
        else:
            return (b'\x00' * expected_length, pyaudio.paContinue)
    
    def add_playback_data(self, data: bytes):
        """添加播放数据到缓冲区 - 支持网络抖动缓冲"""
        if not self.is_playing or not data:
            return
        
        with self.jitter_buffer_lock:
            timestamped_data = (time.time(), data)
            self.jitter_buffer.append(timestamped_data)
        
        if len(self.jitter_buffer) >= self.jitter_buffer_size:
            self._process_jitter_buffer()
    
    def _process_jitter_buffer(self):
        """处理抖动缓冲区中的数据"""
        with self.jitter_buffer_lock:
            if not self.jitter_buffer:
                return
            
            sorted_packets = sorted(self.jitter_buffer, key=lambda x: x[0])
            
            with self.lock:
                for timestamp, data in sorted_packets:
                    self.play_buffer.append(data)
            
            self.jitter_buffer.clear()
    
    @staticmethod
    def _safe_stop_stream(stream, name: str = "流", timeout: float = 2.0):
        """在线程中停止并关闭 PyAudio 流，防止驱动层无限阻塞"""
        done = threading.Event()
        exc = [None]
        
        def _stop():
            try:
                stream.stop_stream()
                stream.close()
            except Exception as e:
                exc[0] = e
            done.set()
        
        t = threading.Thread(target=_stop, daemon=True)
        t.start()
        if not done.wait(timeout=timeout):
            logger.warning(f"{name}流 stop/close 超时（>{timeout}s），强制跳过")
        elif exc[0] is not None:
            raise exc[0]
    
    def flush_jitter_buffer(self):
        """将抖动缓冲区中滞留的数据强制刷入播放缓冲区"""
        with self.jitter_buffer_lock:
            if not self.jitter_buffer:
                return
            sorted_packets = sorted(self.jitter_buffer, key=lambda x: x[0])
            with self.lock:
                for timestamp, data in sorted_packets:
                    self.play_buffer.append(data)
            self.jitter_buffer.clear()
    
    def add_playback_data_immediate(self, data: bytes):
        """立即添加播放数据（绕过抖动缓冲）"""
        if not self.is_playing or not data:
            return
        
        with self.lock:
            self.play_buffer.append(data)
    
    def get_recorded_audio(self) -> bytes:
        """获取录音数据"""
        with self.lock:
            return b''.join(self.record_buffer)
    
    def clear_record_buffer(self):
        """清空录音缓冲区"""
        with self.lock:
            self.record_buffer = []
    
    def is_recording_active(self) -> bool:
        """检查是否正在录音"""
        with self.lock:
            return self.is_recording
    
    def is_playback_active(self) -> bool:
        """检查是否正在播放"""
        with self.lock:
            return self.is_playing
    
    def get_audio_level(self, data: bytes) -> float:
        """获取音频数据的最大音量级别 (0-1)"""
        if not data:
            return 0.0
        
        audio_data = np.frombuffer(data, dtype=np.int16)
        rms = np.sqrt(np.mean(audio_data**2))
        max_value = np.iinfo(np.int16).max
        return min(rms / max_value, 1.0)
    
    def get_buffer_status(self) -> Dict[str, object]:
        """获取音频缓冲区状态（用于 GUI 监控）"""
        try:
            with self.voice_cache_lock:
                record_cache = len(self.voice_data_cache)
        except Exception:
            record_cache = 0
        
        try:
            with self.lock:
                play_depth = len(self.play_buffer)
        except Exception:
            play_depth = 0
        
        return {
            'play_depth': play_depth,
            'play_ms': play_depth * 20,
            'record_cache_bytes': record_cache,
            'is_playing': self.is_playing,
            'is_recording': self.is_recording,
        }
    
    def test_audio_devices(self):
        """测试音频设备"""
        print("测试音频设备...")
        
        # 测试录音
        print("测试录音5秒...")
        try:
            self.start_recording()
            time.sleep(5)
            recorded_data = self.stop_recording()
            print(f"录音测试完成，录制了 {len(recorded_data)} 字节数据")
        except Exception as e:
            print(f"录音测试失败: {e}")
            return
        
        # 测试播放
        if recorded_data:
            print("测试播放...")
            try:
                self.start_playback()
                self.add_playback_data(recorded_data)
                time.sleep(5)
                self.stop_playback()
                print("播放测试完成")
            except Exception as e:
                print(f"播放测试失败: {e}")
    
    def close(self):
        """关闭音频处理"""
        try:
            # 安全停止录音和播放
            try:
                self.stop_recording()
            except Exception as e:
                logger.error(f"关闭时停止录音失败: {e}")
            
            try:
                self.stop_playback()
            except Exception as e:
                logger.error(f"关闭时停止播放失败: {e}")
            
            if self.pyaudio is not None:
                try:
                    pyaudio_instance = self.pyaudio
                    done = threading.Event()
                    exc = [None]
                    def _terminate():
                        try:
                            pyaudio_instance.terminate()
                        except Exception as e:
                            exc[0] = e
                        done.set()
                    t = threading.Thread(target=_terminate, daemon=True)
                    t.start()
                    if not done.wait(timeout=2.0):
                        logger.warning("PyAudio terminate() 超时（>2s），强制跳过")
                    elif exc[0] is not None:
                        raise exc[0]
                except Exception as e:
                    logger.error(f"终止PyAudio失败: {e}")
                self.pyaudio = None
                
            logger.info("音频处理已关闭")
            
        except Exception as e:
            logger.error(f"关闭音频处理失败: {e}")

