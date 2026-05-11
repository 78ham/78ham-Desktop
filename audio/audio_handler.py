"""
音频处理模块
处理麦克风输入和扬声器输出，以及G.711编解码
"""
import threading # 用于线程安全
import numpy as np #type:ignore
import logging
import time
import pyaudio #type:ignore
from typing import Optional, Callable, Dict
from collections import deque
from core.codec import G711Codec, OpusCodec
from core.protocol import PacketType

class AudioHandler:
    """音频处理类"""
    
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
        
        # 日志
        self.logger = logging.getLogger(__name__)
        
        # 音频缓冲区
        self.record_buffer = []
        self.play_buffer = deque()  # 播放缓冲区，使用deque提高性能
        
        # 语音数据缓存（累积到一帧PCM后发送）
        self.voice_data_cache = bytearray()
        self.voice_cache_lock = threading.Lock()
        self.last_voice_send_time = 0.0
        
        # 网络抖动缓冲
        self.jitter_buffer_size = 3  # 缓冲3个数据包（约60ms）
        self.jitter_buffer = deque(maxlen=self.jitter_buffer_size)
        self.jitter_buffer_lock = threading.Lock()
        
        # 播放停止标志 - 用于避免超时检查线程与播放回调的死锁
        self.playback_stop_flag = False
        
    def _get_format(self, format_str: str) -> int:
        """获取PyAudio格式"""
        format_map = {
            "paInt16": pyaudio.paInt16,
            "paInt32": pyaudio.paInt32,
            "paFloat32": pyaudio.paFloat32,
        }
        return format_map.get(format_str, pyaudio.paInt16)
    
    @staticmethod
    def _calc_pcm_frame_size(codec_type: str, sample_rate: int) -> int:
        """根据编码格式和采样率计算每帧PCM字节数
        
        G.711: 8kHz, 20ms帧 = 160 samples = 320字节PCM
        Opus:  16kHz, 20ms帧 = 320 samples = 640字节PCM
        """
        frame_duration_s = 0.02  # 20ms
        bytes_per_sample = 2  # 16-bit PCM
        return int(sample_rate * frame_duration_s * bytes_per_sample)
    
    def set_codec_type(self, codec_type: str, sample_rate: int = None):
        """运行时切换编码格式
        
        Args:
            codec_type: "g711" 或 "opus"
            sample_rate: 新采样率（None则使用默认值）
        """
        self.codec_type = codec_type
        if sample_rate is not None:
            self.sample_rate = sample_rate
        self.pcm_frame_size = self._calc_pcm_frame_size(codec_type, self.sample_rate)
        self.logger.info(f"音频编码格式已切换为: {codec_type}, PCM帧大小: {self.pcm_frame_size}字节, 采样率: {self.sample_rate}Hz")
    
    def _ensure_pyaudio(self):
        """延迟初始化PyAudio，线程安全，避免多线程同时初始化PortAudio"""
        if self.pyaudio is None:
            with self.lock:
                if self.pyaudio is None:
                    self.pyaudio = pyaudio.PyAudio()
    
    def list_audio_devices(self):
        """
        列出所有音频设备
        这个方法会列出所有音频设备，包括输入设备和输出设备。
        每个设备会包含以下信息：
        - 索引 (index)
        - 名称 (name)
        - 最大输入通道数 (max_input_channels)
        - 最大输出通道数 (max_output_channels)
        - 默认采样率 (default_sample_rate)
        """
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
            print(f"设备 {i}: {device_info['name']}")
            print(f"  输入通道: {device_info['maxInputChannels']}")
            print(f"  输出通道: {device_info['maxOutputChannels']}")
            print(f"  默认采样率: {device_info['defaultSampleRate']}")
            print()
        
        return devices
    
    def get_input_devices(self):
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
    
    def get_output_devices(self):
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
    
    def set_input_device(self, device_index: int):
        """设置输入设备"""
        self._ensure_pyaudio()
        try:
            device_info = self.pyaudio.get_device_info_by_index(device_index)
            if device_info['maxInputChannels'] == 0:
                raise ValueError(f"设备 {device_index} 不支持输入")
            
            self.input_device_index = device_index
            self.logger.info(f"输入设备已设置为: {device_info['name']}")
            return True
        except Exception as e:
            self.logger.error(f"设置输入设备失败: {e}")
            return False
    
    def set_output_device(self, device_index: int):
        """设置输出设备"""
        self._ensure_pyaudio()
        try:
            device_info = self.pyaudio.get_device_info_by_index(device_index)
            if device_info['maxOutputChannels'] == 0:
                raise ValueError(f"设备 {device_index} 不支持输出")
            
            self.output_device_index = device_index
            self.logger.info(f"输出设备已设置为: {device_info['name']}")
            return True
        except Exception as e:
            self.logger.error(f"设置输出设备失败: {e}")
            return False
    
    def get_current_input_device(self):
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
                self.logger.error(f"获取输入设备信息失败: {e}")
        return None
    
    def get_current_output_device(self):
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
                self.logger.error(f"获取输出设备信息失败: {e}")
        return None
    
    def start_recording(self, callback: Optional[Callable[[bytes], None]] = None):
        """开始录音"""
        self._ensure_pyaudio()
        with self.lock:
            if self.is_recording:
                self.logger.warning("已经在录音中")
                return
            
            try:
                self.audio_callback = callback
                self.is_recording = True
                self.record_buffer = []
                
                # 设置输入设备参数
                input_params = {
                    'format': self.format,
                    'channels': self.channels,
                    'rate': self.sample_rate,
                    'input': True,
                    'frames_per_buffer': self.chunk_size,
                    'stream_callback': self._record_callback
                }
                
                # 如果有指定输入设备，使用指定设备
                if self.input_device_index is not None:
                    input_params['input_device_index'] = self.input_device_index
                    device_info = self.get_current_input_device()
                    device_name = device_info['name'] if device_info else f"设备{self.input_device_index}"
                    self.logger.info(f"使用输入设备: {device_name}")
                else:
                    self.logger.info("使用系统默认输入设备")
                
                self.input_stream = self.pyaudio.open(**input_params)
                
                self.input_stream.start_stream()
                self.logger.info("开始录音")
                
            except Exception as e:
                self.logger.error(f"开始录音失败: {e}")
                self.is_recording = False
                raise
    
    def stop_recording(self) -> bytes:
        """停止录音并返回录音数据 - 修复：不在持有self.lock时调用stop_stream()"""
        stream_to_stop = None
        with self.lock:
            if not self.is_recording:
                self.logger.warning("没有在录音")
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
                self.logger.error(f"停止录音失败: {e}")
                raise
        
        # 在锁外停止流，避免潜在阻塞（带超时保护）
        if stream_to_stop:
            try:
                self._safe_stop_stream(stream_to_stop, "录音")
            except Exception as e:
                self.logger.error(f"关闭录音流失败: {e}")
        
        self.logger.info("停止录音")
        return recorded_data
    
    def start_playback(self):
        """开始播放"""
        self._ensure_pyaudio()
        with self.lock:
            if self.is_playing:
                self.logger.warning("已经在播放中")
                return
            
            try:
                self.is_playing = True
                self.playback_stop_flag = False  # 重置停止标志
                self.play_buffer = deque()  # 使用deque而非列表，支持高效的两端操作
                
                # 设置输出设备参数
                output_params = {
                    'format': self.format,
                    'channels': self.channels,
                    'rate': self.sample_rate,
                    'output': True,
                    'frames_per_buffer': self.chunk_size,
                    'stream_callback': self._play_callback
                }
                
                # 如果有指定输出设备，使用指定设备
                if self.output_device_index is not None:
                    output_params['output_device_index'] = self.output_device_index
                    device_info = self.get_current_output_device()
                    device_name = device_info['name'] if device_info else f"设备{self.output_device_index}"
                    self.logger.info(f"使用输出设备: {device_name}")
                else:
                    self.logger.info("使用系统默认输出设备")
                
                self.output_stream = self.pyaudio.open(**output_params)
                
                self.output_stream.start_stream()
                self.logger.info("开始播放")
                
            except Exception as e:
                self.logger.error(f"开始播放失败: {e}")
                self.is_playing = False
                raise
    
    def stop_playback(self):
        """停止播放 - 修复死锁：不在持有self.lock时调用stop_stream()"""
        # 先刷入抖动缓冲区中的滞留数据
        self.flush_jitter_buffer()
        
        stream_to_stop = None
        with self.lock:
            if not self.is_playing:
                self.logger.warning("没有在播放")
                return
            
            try:
                self.is_playing = False
                self.playback_stop_flag = True  # 设置停止标志，通知回调立即退出
                
                stream_to_stop = self.output_stream
                self.output_stream = None
                
                self.play_buffer = deque()
                
            except Exception as e:
                self.logger.error(f"停止播放失败: {e}")
                raise
        
        # 在锁外停止流，避免与_play_callback死锁（带超时保护）
        if stream_to_stop:
            try:
                self._safe_stop_stream(stream_to_stop, "播放")
            except Exception as e:
                self.logger.error(f"关闭播放流失败: {e}")
        
        self.logger.info("停止播放")
    
    def _record_callback(self, in_data, frame_count, time_info, status):
        """改进的录音回调函数
        这个函数是录音回调函数，用于处理麦克风输入数据。

        1. 按PCM帧大小管理缓冲区（G.711: 320字节, Opus: 640字节）
        2. 避免不规则的填充导致的失真
        3. 确保每个语音包时间长度固定（20ms）
        4. 参考78HAM的音频处理逻辑
        
        时间关系（G.711）：
        - 采样率: 8000 Hz
        - 每个样本: 2字节 (16位)
        - 320字节PCM = 160个样本 = 20ms
        - 对应160字节G.711数据包
        
        时间关系（Opus）：
        - 采样率: 16000 Hz
        - 每个样本: 2字节 (16位)
        - 640字节PCM = 320个样本 = 20ms
        - 对应变长Opus数据包
        """
        if not self.is_recording:
            return (None, pyaudio.paContinue)
        
        self.record_buffer.append(in_data)
        
        # 处理语音数据缓存 - 按PCM帧大小管理
        pending_callbacks = []
        with self.voice_cache_lock:
            self.voice_data_cache.extend(in_data)
            current_time = time.time()
            
            # 关键逻辑：当缓存达到或超过一帧PCM时，立即发送
            # G.711: 320字节PCM → 160字节G.711 = 20ms
            # Opus:  640字节PCM → 变长Opus帧 = 20ms
            frame_size = self.pcm_frame_size
            while len(self.voice_data_cache) >= frame_size:
                # 提取恰好一帧PCM
                send_data = bytes(self.voice_data_cache[:frame_size])
                self.voice_data_cache = self.voice_data_cache[frame_size:]
                self.last_voice_send_time = current_time
                
                if self.audio_callback:
                    pending_callbacks.append(send_data)
        
        # 在锁外调用回调，减少锁持有时间
        for send_data in pending_callbacks:
            self.audio_callback(send_data)
            self.logger.debug(f"发送音频数据: {len(send_data)} bytes PCM")
        
        return (None, pyaudio.paContinue)
    
    def _play_callback(self, in_data, frame_count, time_info, status):
        """播放回调函数 - 改进数据长度匹配和缓冲区管理"""
        # 检查停止标志，如果已标记停止则立即返回
        if not self.is_playing or self.playback_stop_flag:
            return (b'\x00' * frame_count * self.channels * 2, pyaudio.paContinue)
        
        # 计算期望的数据长度（16-bit音频，每个样本2字节）
        expected_length = frame_count * self.channels * 2
        
        # 从播放缓冲区获取数据
        data_chunks = []
        current_length = 0
        
        with self.lock:
            # 从缓冲区收集足够的数据
            while self.play_buffer and current_length < expected_length:
                try:
                    data_chunk = self.play_buffer.popleft()
                    if data_chunk:
                        data_chunks.append(data_chunk)
                        current_length += len(data_chunk)
                except (IndexError, AttributeError) as e:
                    # 缓冲区可能被修改或格式错误，记录但继续
                    self.logger.debug(f"播放缓冲获取异常: {e}")
                    break
        
        if data_chunks:
            # 合并所有数据块
            combined_data = b''.join(data_chunks)
            
            if len(combined_data) == expected_length:
                return (combined_data, pyaudio.paContinue)
            elif len(combined_data) > expected_length:
                # 数据过多，截断并放回多余部分
                result_data = combined_data[:expected_length]
                remaining_data = combined_data[expected_length:]
                if remaining_data:
                    with self.lock:
                        self.play_buffer.appendleft(remaining_data)
                return (result_data, pyaudio.paContinue)
            else:
                # 数据不足，用静音填充
                silence = b'\x00' * (expected_length - len(combined_data))
                return (combined_data + silence, pyaudio.paContinue)
        else:
            # 如果没有数据，播放静音
            return (b'\x00' * expected_length, pyaudio.paContinue)
    
    def add_playback_data(self, data: bytes):
        """添加播放数据到缓冲区 - 支持网络抖动缓冲"""
        if not self.is_playing or not data:
            return
        
        with self.jitter_buffer_lock:
            # 添加时间戳到数据包
            timestamped_data = (time.time(), data)
            self.jitter_buffer.append(timestamped_data)
            
            # 如果缓冲区已满，开始处理数据
            if len(self.jitter_buffer) >= self.jitter_buffer_size:
                self._process_jitter_buffer()
    
    def _process_jitter_buffer(self):
        """处理抖动缓冲区中的数据"""
        with self.jitter_buffer_lock:
            if not self.jitter_buffer:
                return
            
            # 按时间戳排序数据包
            sorted_packets = sorted(self.jitter_buffer, key=lambda x: x[0])
            
            # 将排序后的数据添加到播放缓冲区
            with self.lock:
                for timestamp, data in sorted_packets:
                    self.play_buffer.append(data)
            
            # 清空抖动缓冲区
            self.jitter_buffer.clear()
    
    @staticmethod
    def _safe_stop_stream(stream, name: str = "流", timeout: float = 2.0):
        """在线程中停止并关闭 PyAudio 流，防止驱动层无限阻塞
        
        某些音频驱动下 stop_stream() / close() 可能无限挂起，
        这里在子线程中执行并用超时兜底。
        """
        done = threading.Event()
        exc = [None]  # 用列表捕获子线程异常
        
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
            logging.getLogger(__name__).warning(
                f"{name}流 stop/close 超时（>{timeout}s），强制跳过"
            )
        elif exc[0] is not None:
            raise exc[0]
    
    def flush_jitter_buffer(self):
        """将抖动缓冲区中滞留的数据强制刷入播放缓冲区，避免数据丢失"""
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
        
        # 转换为numpy数组
        audio_data = np.frombuffer(data, dtype=np.int16)
        
        # 计算RMS值
        rms = np.sqrt(np.mean(audio_data**2))
        
        # 归一化到0-1范围
        max_value = np.iinfo(np.int16).max
        normalized_level = min(rms / max_value, 1.0)
        
        return normalized_level
    
    def get_buffer_status(self) -> dict:
        """获取音频缓冲区状态（用于 GUI 监控）
        
        Returns:
            dict: {
                'play_depth': int,        # 播放缓冲帧数
                'play_ms': int,           # 播放缓冲延迟（毫秒），每帧20ms
                'record_cache_bytes': int, # 录音编码缓存字节数
                'is_playing': bool,       # 是否正在播放
                'is_recording': bool,     # 是否正在录音
            }
        """
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
        
        # 每帧固定 20ms（G.711: 320B PCM, Opus: 640B PCM 均为 20ms）
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
                self.logger.error(f"关闭时停止录音失败: {e}")
            
            try:
                self.stop_playback()
            except Exception as e:
                self.logger.error(f"关闭时停止播放失败: {e}")
            
            if self.pyaudio is not None:
                try:
                    # 用子线程 + 超时保护 terminate()，防止驱动层阻塞
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
                        self.logger.warning("PyAudio terminate() 超时（>2s），强制跳过")
                    elif exc[0] is not None:
                        raise exc[0]
                except Exception as e:
                    self.logger.error(f"终止PyAudio失败: {e}")
                self.pyaudio = None
                
            self.logger.info("音频处理已关闭")
            
        except Exception as e:
            self.logger.error(f"关闭音频处理失败: {e}")


class VoiceProcessor:
    """语音处理器，处理G.711和Opus编解码
    
    参考78HAM的G.711和Opus实现，提供编解码功能
    支持错误恢复和数据包丢失处理
    
    G.711 (Type=1): 8kHz, 160字节/帧, 20ms
    Opus  (Type=8): 16kHz, 变长/帧, 20ms
    """
    
    def __init__(self, codec_type: str = "g711"):
        self.codec_type = codec_type
        self.g711_codec = G711Codec()
        
        # Opus编解码器（延迟初始化，避免未安装时崩溃）
        self._opus_codec = None
        
        self.logger = logging.getLogger(__name__)
        
        # 统计信息
        self.encode_count = 0
        self.decode_count = 0
        self.error_count = 0
    
    @property
    def opus_codec(self):
        """延迟初始化Opus编解码器"""
        if self._opus_codec is None:
            if not OpusCodec.is_available():
                raise ImportError("opuslib 未安装，无法使用Opus编码。请运行: pip install opuslib")
            self._opus_codec = OpusCodec()
        return self._opus_codec
    
    def set_codec(self, codec_type: str):
        """切换编码格式"""
        self.codec_type = codec_type
        self.logger.info(f"语音编码格式已切换为: {codec_type}")
    
    def encode_voice(self, pcm_data: bytes) -> bytes:
        """编码PCM语音数据
        
        根据当前codec_type选择编码器：
        - g711: PCM → G.711 A-law (320字节PCM → 160字节)
        - opus: PCM → Opus (640字节PCM → 变长)
        """
        if self.codec_type == "opus":
            return self._encode_opus(pcm_data)
        else:
            return self._encode_g711(pcm_data)
    
    def decode_voice(self, data: bytes) -> bytes:
        """解码语音数据为PCM
        
        根据当前codec_type选择解码器：
        - g711: G.711 A-law → PCM (160字节 → 320字节)
        - opus: Opus → PCM (变长 → 640字节)
        """
        if self.codec_type == "opus":
            return self._decode_opus(data)
        else:
            return self._decode_g711(data)
    
    def decode_voice_by_type(self, data: bytes, packet_type: int) -> bytes:
        """根据数据包类型解码语音数据（接收端使用，不依赖当前codec_type）
        
        用于接收端自动识别数据包类型并解码，
        避免因本端codec设置与远端不同导致解码失败。
        """
        if packet_type == PacketType.OPUS:
            return self._decode_opus(data)
        else:
            return self._decode_g711(data)
    
    def _encode_g711(self, pcm_data: bytes) -> bytes:
        """G.711编码：320字节PCM → 160字节G.711"""
        try:
            if not pcm_data:
                self.logger.warning("PCM数据为空，返回静音帧")
                return b'\x80' * 160
            
            encoded = self.g711_codec.encode(pcm_data)
            
            if not encoded or len(encoded) == 0:
                self.logger.warning(f"G.711编码失败: 编码结果为空")
                return b'\x80' * 160
            
            self.encode_count += 1
            self.logger.debug(f"G.711编码: {len(pcm_data)} bytes PCM -> {len(encoded)} bytes")
            return encoded
            
        except Exception as e:
            self.logger.error(f"G.711编码异常: {e}")
            self.error_count += 1
            return b'\x80' * 160
    
    def _encode_opus(self, pcm_data: bytes) -> bytes:
        """Opus编码：640字节PCM → 变长Opus帧"""
        try:
            if not pcm_data:
                self.logger.warning("PCM数据为空，返回Opus静音帧")
                return self.opus_codec.encode(b'\x00' * OpusCodec.PCM_FRAME_BYTES)
            
            encoded = self.opus_codec.encode(pcm_data)
            
            if not encoded or len(encoded) == 0:
                self.logger.warning("Opus编码失败: 编码结果为空")
                return self.opus_codec.encode(b'\x00' * OpusCodec.PCM_FRAME_BYTES)
            
            self.encode_count += 1
            self.logger.debug(f"Opus编码: {len(pcm_data)} bytes PCM -> {len(encoded)} bytes")
            return encoded
            
        except Exception as e:
            self.logger.error(f"Opus编码异常: {e}")
            self.error_count += 1
            return b''
    
    def _decode_g711(self, g711_data: bytes) -> bytes:
        """G.711解码：160字节G.711 → 320字节PCM"""
        try:
            if not g711_data:
                self.logger.warning("G.711数据为空，返回静音数据")
                return b'\x00' * 320  # 160 samples * 2 bytes
            
            pcm_data = self.g711_codec.decode(g711_data)
            
            if not pcm_data:
                self.logger.warning(f"G.711解码失败: 输入长度={len(g711_data)}")
                return b'\x00' * 320
            
            self.decode_count += 1
            self.logger.debug(f"G.711解码: {len(g711_data)} bytes -> {len(pcm_data)} bytes PCM")
            return pcm_data
            
        except Exception as e:
            self.logger.error(f"G.711解码异常: {e}, 数据长度={len(g711_data) if g711_data else 0}")
            self.error_count += 1
            return b'\x00' * 320
    
    def _decode_opus(self, opus_data: bytes) -> bytes:
        """Opus解码：变长Opus帧 → 640字节PCM"""
        try:
            if not opus_data:
                self.logger.warning("Opus数据为空，返回静音数据")
                return b'\x00' * OpusCodec.PCM_FRAME_BYTES
            
            pcm_data = self.opus_codec.decode(opus_data)
            
            if not pcm_data:
                self.logger.warning(f"Opus解码失败: 输入长度={len(opus_data)}")
                return b'\x00' * OpusCodec.PCM_FRAME_BYTES
            
            self.decode_count += 1
            self.logger.debug(f"Opus解码: {len(opus_data)} bytes -> {len(pcm_data)} bytes PCM")
            return pcm_data
            
        except Exception as e:
            self.logger.error(f"Opus解码异常: {e}, 数据长度={len(opus_data) if opus_data else 0}")
            self.error_count += 1
            return b'\x00' * OpusCodec.PCM_FRAME_BYTES
    
    def process_recorded_audio(self, pcm_data: bytes) -> bytes:
        """处理录制的音频数据"""
        return self.encode_voice(pcm_data)
    
    def process_received_audio(self, audio_data: bytes, packet_type: int = 1) -> bytes:
        """处理接收的音频数据（根据数据包类型自动解码）"""
        return self.decode_voice_by_type(audio_data, packet_type)
    
    def get_stats(self) -> Dict[str, int]:
        """获取处理统计信息"""
        return {
            'encode_count': self.encode_count,
            'decode_count': self.decode_count,
            'error_count': self.error_count
        }