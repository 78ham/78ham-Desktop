"""
78HAM 新架构 GUI 主窗口

使用 TalkService/RoomService/LocationService 作为业务层，
组合各 UI 组件构建完整界面。
"""
import os
import time
import logging
import threading
import customtkinter as ctk
from typing import Optional

from config.settings import Settings
from services.talk_service import TalkService
from services.room_service import RoomService
from services.location_service import LocationService
from services.tail_tone_service import TailToneService
from services.recording_service import RecordingService
from services.platform_service import PlatformService
from ptt.hotkey import PttController

from audio.audio_manager import AudioManager
from ui.theme import Colors, Fonts, Spacing, Sizes
from ui.components.status_bar import StatusBar
from ui.components.ptt_button import PttButton
from ui.components.chat_panel import ChatPanel
from ui.components.room_selector import RoomSelector
from ui.components.audio_panel import AudioPanel
from ui.components.config_dialog import ConfigDialog
from ui.components.recording_panel import RecordingPanel

logger = logging.getLogger(__name__)


class App(ctk.CTk):
    """78HAM 桌面客户端主窗口（新架构）

    职责：
    - 组合 UI 组件
    - 创建并管理服务层实例
    - 将 UI 事件路由到服务层
    - 将服务层回调路由到 UI 更新
    """

    def __init__(self, config_file: str = "config.yaml"):
        super().__init__()

        # 窗口基本设置
        self.title("78HAM 桌面客户端")
        self.geometry(f"{Sizes.WINDOW_WIDTH}x{Sizes.WINDOW_HEIGHT}")
        self.minsize(Sizes.WINDOW_MIN_WIDTH, Sizes.WINDOW_MIN_HEIGHT)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # 加载配置
        self._config_file = config_file
        self._settings = Settings.load(config_file)

        # 创建服务层
        self._talk: Optional[TalkService] = None
        self._room: Optional[RoomService] = None
        self._location: Optional[LocationService] = None
        self._tail_tone: Optional[TailToneService] = None
        self._recording: Optional[RecordingService] = None
        self._platform: Optional[PlatformService] = None
        self._ptt_controller: Optional[PttController] = None

        # 状态
        self._connected = False
        self._connecting = False  # 防止连接重入
        self._voice_recv_timer: Optional[str] = None  # 语音接收状态恢复计时器 ID
        self._voice_recv_start: float = 0.0            # 语音接收开始时间
        self._voice_recv_info: dict = {}               # 当前语音发送者信息
        self._voice_send_start: float = 0.0            # 本机语音发送开始时间
        self._ptt_active = False                       # PTT 发射中标志（热键/鼠标互斥）
        self._tail_tone_save_timer: Optional[str] = None

        # 构建 UI
        self._build_ui()

        # 初始化服务
        self._init_services()

        # 窗口关闭处理
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # 初始状态更新
        self._update_ui_state()

    def _build_ui(self):
        """构建主界面布局"""
        # 顶部工具栏
        self._build_toolbar()

        # 主内容区（左右分栏）
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=Spacing.PAD_SM,
                     pady=Spacing.PAD_SM)

        # 左侧：PTT + 音频 + 房间
        left_panel = ctk.CTkFrame(content, width=260)
        left_panel.pack(side="left", fill="y", padx=(0, Spacing.PAD_SM))
        left_panel.pack_propagate(False)

        self._ptt_button = PttButton(
            left_panel,
            on_press=self._on_ptt_press,
            on_release=self._on_ptt_release,
        )
        self._ptt_button.pack(fill="x", pady=(0, Spacing.PAD_SM))

        self._audio_panel = AudioPanel(
            left_panel,
            on_codec_change=self._on_codec_change,
            on_playback_toggle=self._on_playback_toggle,
            on_tail_tone_change=self._on_tail_tone_change,
            on_bitrate_change=self._on_bitrate_change,
            on_input_device_change=self._on_input_device_change,
            on_output_device_change=self._on_output_device_change,
        )
        self._audio_panel.pack(fill="x", pady=(0, Spacing.PAD_SM))

        self._room_selector = RoomSelector(
            left_panel,
            on_join_room=self._on_join_room,
            on_refresh=self._on_refresh_rooms,
        )
        self._room_selector.pack(fill="x", pady=(0, Spacing.PAD_SM))
        
        # 录音面板
        self._recording_panel = RecordingPanel(
            left_panel,
            on_start_recording=self._on_start_recording,
            on_stop_recording=self._on_stop_recording,
            on_open_recordings_dir=self._on_open_recordings_dir,
        )
        self._recording_panel.pack(fill="x", pady=(0, Spacing.PAD_SM))

        # 右侧：聊天面板
        self._chat_panel = ChatPanel(
            content,
            on_send_text=self._on_send_text,
            on_send_location=self._on_send_location,
        )
        self._chat_panel.pack(side="left", fill="both", expand=True)

        # 底部状态栏
        self._status_bar = StatusBar(self)
        self._status_bar.pack(side="bottom", fill="x")

    def _build_toolbar(self):
        """构建顶部工具栏"""
        toolbar = ctk.CTkFrame(self, height=40)
        toolbar.pack(fill="x", padx=Spacing.PAD_SM, pady=(Spacing.PAD_SM, 0))
        toolbar.pack_propagate(False)

        # 连接按钮
        self._connect_btn = ctk.CTkButton(
            toolbar, text="连接", width=80,
            command=self._toggle_connection,
        )
        self._connect_btn.pack(side="left", padx=Spacing.PAD_XS)

        # 服务器下拉选择
        server_names = [s.name for s in self._settings.servers_list]
        current_server = self._settings.get_current_server()
        current_name = current_server.name if current_server else ""

        self._server_var = ctk.StringVar(value=current_name)
        self._server_combo = ctk.CTkOptionMenu(
            toolbar,
            values=server_names if server_names else ["无服务器"],
            variable=self._server_var,
            width=200,
            command=self._on_server_selected,
        )
        self._server_combo.pack(side="left", padx=Spacing.PAD_MD)

        # 右侧：配置按钮
        self._config_btn = ctk.CTkButton(
            toolbar, text="配置", width=60,
            fg_color="gray",
            command=self._open_config,
        )
        self._config_btn.pack(side="right", padx=Spacing.PAD_XS)

        # 刷新服务器按钮
        self._refresh_servers_btn = ctk.CTkButton(
            toolbar, text="刷新服务器", width=80,
            fg_color="gray",
            command=self._on_refresh_platform_servers,
        )
        self._refresh_servers_btn.pack(side="right", padx=Spacing.PAD_XS)

    # ==================== 服务初始化 ====================

    def _init_services(self):
        """初始化业务服务层"""
        self._talk = TalkService(self._settings)
        self._room = RoomService(self._settings, self._talk.udp_client)
        self._location = LocationService(self._settings)

        # 音频播放管理器
        self._audio = AudioManager(
            sample_rate=self._settings.audio.sample_rate,
            codec_type=self._settings.audio.codec,
        )
        
        # 录音服务
        self._recording = RecordingService(
            self._audio._handler,  # 获取底层的 AudioHandler
            self._settings,
        )
        self._recording.on_recording_started = self._on_recording_started
        self._recording.on_recording_stopped = self._on_recording_stopped
        self._recording.on_recording_error = self._on_recording_error
        
        # 平台服务（拉取平台服务器列表）
        self._platform = PlatformService(self._settings)
        
        # 自动拉取平台服务器列表（异步，避免阻塞启动）
        threading.Thread(target=self._auto_fetch_platform_servers, daemon=True).start()

        # 初始化码率控件
        self._audio_panel.set_codec(self._settings.audio.codec)
        self._audio_panel.set_bitrate(self._settings.audio.opus_bitrate)

        # 加载音频设备列表
        self._load_audio_devices()

        # 尾音服务
        self._tail_tone = TailToneService(
            get_codec_fn=lambda: self._settings.audio.codec,
            get_frame_size_fn=lambda: self._settings.audio.chunk_size,
            get_dmr_id_fn=self._parse_dmr_id,
        )
        tt = self._settings.tail_tone
        self._tail_tone.configure(
            enabled=tt.enabled,
            tail_type=tt.tail_type,
            custom_file=tt.custom_file,
            mdc_id=tt.mdc_id,
            amplitude=tt.amplitude,
        )
        self._audio_panel.set_tail_tone_config({
            "enabled": tt.enabled,
            "type": tt.tail_type,
            "file": tt.custom_file,
            "mdc_id": tt.mdc_id,
            "amplitude": tt.amplitude,
        })

        # 注册 TalkService 回调
        self._talk.on_message = self._on_service_message
        self._talk.on_voice_data = self._on_service_voice
        self._talk.on_connection_changed = self._on_service_connection_changed
        self._talk.on_status_update = self._on_service_status

        # 注册 RoomService 回调
        self._room.on_group_list = self._on_service_group_list
        self._room.on_group_changed = self._on_service_group_changed

        # 位置服务回调
        self._location.on_send_location = self._talk.send_location

        # PTT 热键
        self._ptt_controller = PttController(
            on_press=self._on_ptt_press,
            on_release=self._on_ptt_release,
        )
        self._ptt_controller.register("f5")
        self._ptt_button.set_hotkey_hint("F5")

        # 更新状态栏
        self._status_bar.set_callsign(
            self._settings.device.callsign,
            self._settings.device.ssid,
        )
        self._status_bar.set_codec(self._settings.audio.codec)
        self._audio_panel.set_codec(self._settings.audio.codec)

        server = self._settings.get_current_server()
        if server:
            self._status_bar.set_server(server.name)

    # ==================== UI 事件处理 ====================

    def _toggle_connection(self):
        """连接/断开切换"""
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        """连接到服务器"""
        # 防止重复点击
        if self._connecting:
            return
        self._connecting = True

        # 检查设备密码，为空则提示输入
        if not self._settings.get_current_password():
            server = self._settings.get_current_server()
            server_name = server.name if server else "服务器"
            pwd = self._prompt_password(server_name)
            if not pwd:
                self._chat_panel.add_system_message("已取消连接")
                self._connecting = False
                return
            self._settings.set_current_password(pwd)
            self._settings.save_updates({
                'device': {'password': self._settings.device.password},
            })

        self._status_bar.set_connection_state("connecting")
        self._connect_btn.configure(text="连接中...", state="disabled")
        self._chat_panel.add_system_message("正在连接...")

        # 在后台线程执行连接
        def _do_connect():
            try:
                server = self._settings.get_current_server()
                if (server and server.username and server.api_password and self._platform
                        and not self._platform.login_current_server(
                            server.username, server.api_password)):
                    self.after(0, lambda: self._on_connect_result(
                        False, "服务器账号登录失败"))
                    return
                success = self._talk.start()
            except Exception:
                logger.exception("连接线程异常")
                success = False
            self.after(0, lambda: self._on_connect_result(success))

        threading.Thread(target=_do_connect, daemon=True).start()

    def _on_connect_result(self, success: bool, error: str = ""):
        """连接结果回调（主线程）"""
        self._connecting = False
        if success:
            self._connected = True
            self._status_bar.set_connection_state("connected")
            self._connect_btn.configure(text="断开", state="normal",
                                        fg_color=Colors.DISCONNECTED)
            self._chat_panel.add_system_message("连接成功")
            if self._audio_panel.playback_enabled:
                self._audio.start_playback()
            self._location.start_auto_report()
            self._ptt_button.set_enabled(True)
            self._chat_panel.set_enabled(True)
            self._room_selector.set_enabled(True)
            # 连接成功后自动获取房间列表
            self._room.request_group_list()
        else:
            self._connected = False
            self._status_bar.set_connection_state("disconnected")
            self._connect_btn.configure(text="连接", state="normal")
            self._chat_panel.add_system_message(error or "连接失败")

    def _disconnect(self):
        """断开连接"""
        # 取消语音接收计时器
        if self._voice_recv_timer:
            self.after_cancel(self._voice_recv_timer)
            self._voice_recv_timer = None
        self._ptt_button.force_release()
        self._audio.stop_playback()
        self._location.stop_auto_report()
        self._talk.stop()
        self._connected = False
        self._status_bar.set_connection_state("disconnected")
        self._connect_btn.configure(text="连接", state="normal",
                                    fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"])
        self._chat_panel.add_system_message("已断开连接")
        self._update_ui_state()

    def _on_ptt_press(self):
        """PTT 按下（可能从热键钩子线程调用，切回主线程执行 UI 操作）"""
        self.after(0, self._do_ptt_press)

    def _on_ptt_release(self):
        """PTT 松开（可能从热键钩子线程调用，切回主线程执行 UI 操作）"""
        self.after(0, self._do_ptt_release)

    def _do_ptt_press(self):
        """PTT 按下实际处理（主线程）"""
        if not self._connected or self._ptt_active:
            return
        
        if self._talk.start_transmitting():
            self._ptt_active = True
            self._ptt_button.set_transmitting()
            self._voice_send_start = time.time()
            try:
                self._audio.start_recording(self._send_voice_frame)
            except Exception as e:
                logger.error(f"启动录音失败: {e}")
                self._talk.stop_transmitting()
                self._ptt_active = False
                self._voice_send_start = 0.0
                self._ptt_button.set_idle()

    def _do_ptt_release(self):
        """PTT 松开实际处理（主线程）"""
        if not self._connected or not self._ptt_active:
            return
        self._ptt_active = False
        self._audio.stop_recording()
        # 发送尾音（is_transmitting 仍为 True 时调用）
        self._send_tail_tone()
        self._talk.stop_transmitting()
        self._ptt_button.set_idle()
        # 记录本机语音发送摘要
        if self._voice_send_start > 0:
            duration = time.time() - self._voice_send_start
            self._voice_send_start = 0.0
            if duration > 0.1:
                dev = self._settings.device
                self._chat_panel.add_comm_message(
                    dev.callsign,
                    f"\U0001f4de语音消息（{duration:.1f}s）",
                    ssid=dev.ssid, dmr_id=dev.dmr_id, is_local=True)

    def _on_send_text(self, text: str):
        """发送文本消息"""
        if not self._connected:
            self._chat_panel.add_system_message("未连接，无法发送")
            return
        if self._talk.send_text_message(text):
            dev = self._settings.device
            self._chat_panel.add_comm_message(
                dev.callsign, text,
                ssid=dev.ssid, dmr_id=dev.dmr_id, is_local=True)
        else:
            self._chat_panel.add_system_message("发送失败")

    def _on_send_location(self):
        """发送位置"""
        if not self._connected:
            return
        lat, lng, source = self._location.get_location()
        # 实时定位失败时，使用 config 中的指定位置
        if lat == 0.0 and lng == 0.0:
            cfg_lat = self._settings.location.default_lat
            cfg_lng = self._settings.location.default_lng
            if cfg_lat != 0.0 or cfg_lng != 0.0:
                lat, lng, source = cfg_lat, cfg_lng, "config"
            else:
                self._chat_panel.add_system_message("定位失败，且未配置默认位置")
                return
        if self._talk.send_location(lat, lng):
            dev = self._settings.device
            self._chat_panel.add_comm_message(
                dev.callsign,
                f"{lat:.6f},{lng:.6f} (来源: {source})",
                msg_type="location",
                ssid=dev.ssid, dmr_id=dev.dmr_id, is_local=True)

    def _on_join_room(self, room_id: int):
        """加入房间"""
        if not self._connected:
            return
        self._room.join_group(room_id)

    def _on_refresh_rooms(self):
        """刷新房间列表"""
        if not self._connected:
            return
        self._room.request_group_list()

    def _load_audio_devices(self):
        """加载音频设备列表到 UI"""
        try:
            input_devices = self._audio.get_input_devices()
            output_devices = self._audio.get_output_devices()
            self._audio_panel.set_input_devices(input_devices)
            self._audio_panel.set_output_devices(output_devices)
            logger.info(f"加载音频设备: 输入 {len(input_devices)} 个, 输出 {len(output_devices)} 个")
        except Exception as e:
            logger.error(f"加载音频设备失败: {e}")

    def _on_input_device_change(self, device_index: int):
        """输入设备变更"""
        if device_index < 0:
            # 选择默认设备
            self._audio.reset_input_device()
            logger.info("输入设备已设为默认")
        else:
            if self._audio.set_input_device(device_index):
                logger.info(f"输入设备已切换: 索引 {device_index}")
            else:
                self._chat_panel.add_system_message("输入设备切换失败")

    def _on_output_device_change(self, device_index: int):
        """输出设备变更"""
        if device_index < 0:
            # 选择默认设备
            self._audio.reset_output_device()
            logger.info("输出设备已设为默认")
        else:
            if self._audio.set_output_device(device_index):
                logger.info(f"输出设备已切换: 索引 {device_index}")
            else:
                self._chat_panel.add_system_message("输出设备切换失败")

    def _on_codec_change(self, codec: str):
        """切换编码"""
        if not self._talk:
            self._chat_panel.add_system_message("编码切换失败: 服务未初始化")
            self._audio_panel.set_codec(self._settings.audio.codec)
            return

        from core.codec import OpusCodec
        if codec == "opus" and not OpusCodec.is_available():
            self._chat_panel.add_system_message("编码切换失败: Opus 不可用，请安装 opuslib")
            self._audio_panel.set_codec(self._settings.audio.codec)
            return

        if codec == "opus" and self._talk.is_transmitting:
            self._chat_panel.add_system_message("编码切换失败: 发射中无法切换")
            self._audio_panel.set_codec(self._settings.audio.codec)
            return

        old_codec = self._settings.audio.codec
        if not self._talk.set_codec(codec):
            self._chat_panel.add_system_message("编码切换失败")
            self._audio_panel.set_codec(self._settings.audio.codec)
            return

        if self._recording and self._recording.is_recording:
            self._chat_panel.add_system_message("录音中无法切换编码")
            self._audio_panel.set_codec(self._settings.audio.codec)
            return

        try:
            sample_rate = 16000 if codec == 'opus' else 8000
            self._audio.set_codec(codec, sample_rate)
            if self._recording:
                self._recording.bind_audio_handler(self._audio._handler)
        except Exception:
            logger.exception("重建音频流失败")
            self._talk.set_codec(old_codec)
            self._audio_panel.set_codec(old_codec)
            self._chat_panel.add_system_message("编码切换失败: 无法重建音频设备")
            return

        self._status_bar.set_codec(codec)
        self._chat_panel.add_system_message(f"编码已切换: {codec}")
        if self._tail_tone:
            self._tail_tone.on_codec_changed()

    def _on_bitrate_change(self, bitrate: int):
        """切换 Opus 码率"""
        if self._talk and self._talk.set_opus_bitrate(bitrate):
            self._chat_panel.add_system_message(f"Opus 码率已切换: {bitrate // 1000} kbps")
        else:
            self._chat_panel.add_system_message("码率切换失败")
            self._audio_panel.set_bitrate(self._settings.audio.opus_bitrate)

    def _on_playback_toggle(self, enabled: bool):
        """播放开关"""
        if enabled and self._connected:
            self._audio.start_playback()
        else:
            self._audio.stop_playback()

    def _on_tail_tone_change(self, config: dict):
        """尾音配置变化"""
        self._tail_tone.configure(
            enabled=config.get("enabled", False),
            tail_type=config.get("type", "default"),
            custom_file=config.get("file", ""),
            mdc_id=config.get("mdc_id", 0),
            amplitude=config.get("amplitude", 0.2),
        )
        # 持久化到配置文件
        self._settings.tail_tone.enabled = config.get("enabled", False)
        self._settings.tail_tone.tail_type = config.get("type", "default")
        self._settings.tail_tone.custom_file = config.get("file", "")
        self._settings.tail_tone.mdc_id = config.get("mdc_id", 0)
        self._settings.tail_tone.amplitude = config.get("amplitude", 0.2)
        if self._tail_tone_save_timer:
            self.after_cancel(self._tail_tone_save_timer)
        self._tail_tone_save_timer = self.after(300, self._persist_tail_tone)
    
    # ==================== 录音功能 ====================
    
    def _on_start_recording(self):
        """开始录音"""
        if not self._recording:
            self._chat_panel.add_system_message("录音服务未初始化")
            return
        
        if self._recording.start_recording():
            self._recording_panel.set_recording_state(True)
            self._chat_panel.add_system_message("开始录制软件音频")
        else:
            self._chat_panel.add_system_message("开始录音失败")
    
    def _on_stop_recording(self):
        """停止录音"""
        if not self._recording:
            return
        
        recording_file = self._recording.stop_recording()
        if recording_file:
            self._recording_panel.set_recording_state(False)
            self._recording_panel.add_recording_file(recording_file)
            self._chat_panel.add_system_message(f"录音已保存: {os.path.basename(recording_file)}")
        else:
            self._recording_panel.set_recording_state(False)
            self._chat_panel.add_system_message("停止录音失败")

    def _send_voice_frame(self, pcm_data: bytes) -> bool:
        """Send a PCM frame and mirror it into the software recording buffer."""
        if self._recording:
            self._recording.append_pcm(pcm_data)
        return self._talk.send_voice_data(pcm_data)
    
    def _on_recording_started(self):
        """录音开始回调"""
        pass  # 已在 _on_start_recording 中处理
    
    def _on_recording_stopped(self, file_path: str):
        """录音停止回调"""
        pass  # 已在 _on_stop_recording 中处理
    
    def _on_recording_error(self, error_msg: str):
        """录音错误回调"""
        self._chat_panel.add_system_message(f"录音错误: {error_msg}")
        self._recording_panel.set_recording_state(False)
    
    def _on_open_recordings_dir(self):
        """打开录音目录"""
        if self._recording:
            recordings_dir = self._recording.get_recordings_dir()
            try:
                os.startfile(recordings_dir)
            except AttributeError:
                # Linux/Mac
                import subprocess
                subprocess.Popen(['xdg-open', recordings_dir])
            except Exception as e:
                self._chat_panel.add_system_message(f"打开录音目录失败: {e}")

    def _persist_tail_tone(self):
        """合并短时间内连续产生的滑块配置写入。"""
        self._tail_tone_save_timer = None
        self._settings.save_tail_tone()

    def _send_tail_tone(self):
        """发送尾音数据（在 is_transmitting 仍为 True 时调用）"""
        if not self._tail_tone:
            return
        frames = self._tail_tone.get_tail_tone_frames()
        if not frames:
            return
        for frame in frames:
            if not self._talk.send_voice_data(frame):
                break

    def _parse_dmr_id(self) -> int:
        """将 device.dmr_id 字符串解析为整数"""
        try:
            dmr = self._settings.device.dmr_id
            return int(dmr, 16) if dmr.startswith("0x") else int(dmr)
        except (ValueError, TypeError):
            return 0

    def _open_config(self):
        """打开配置对话框"""
        ConfigDialog(
            self,
            initial_data=self._settings.to_dict(),
            on_save=self._on_config_saved,
        )

    def _on_config_saved(self, filename: str, config_data: dict):
        """配置保存回调"""
        if self._connected:
            self._disconnect()
        if not self._settings.save_updates(config_data):
            self._chat_panel.add_system_message("配置保存失败")
            return

        refreshed = Settings.load(self._config_file)
        self._settings.device = refreshed.device
        self._settings.server = refreshed.server
        self._settings.audio = refreshed.audio
        self._settings.network = refreshed.network
        self._settings.location = refreshed.location
        self._settings.tail_tone = refreshed.tail_tone
        self._settings.servers_list = refreshed.servers_list
        self._settings.current_server_index = refreshed.current_server_index

        self._status_bar.set_callsign(
            self._settings.device.callsign, self._settings.device.ssid)
        self._chat_panel.add_system_message("配置已更新")
        self._update_server_combo()
        server = self._settings.get_current_server()
        if server:
            self._status_bar.set_server(server.name)

    # ==================== 服务器切换 ====================

    def _on_server_selected(self, name: str):
        """服务器下拉菜单选择回调"""
        # 查找目标服务器索引
        target_index = -1
        for i, srv in enumerate(self._settings.servers_list):
            if srv.name == name:
                target_index = i
                break
        if target_index < 0:
            return
        # 如果选的就是当前服务器，不做操作
        if target_index == self._settings.current_server_index:
            return
        # 已连接则先断开
        if self._connected:
            self._disconnect()
        # 切换服务器
        self._settings.switch_server(target_index)
        self._settings.save_current_server()
        # 更新状态栏
        server = self._settings.get_current_server()
        if server:
            self._status_bar.set_server(server.name)
            self._chat_panel.add_system_message(
                f"已切换到服务器: {server.name} ({server.host}:{server.port})")

    def _update_server_combo(self):
        """刷新服务器下拉菜单选项"""
        server_names = [s.name for s in self._settings.servers_list]
        if not server_names:
            server_names = ["无服务器"]
        self._server_combo.configure(values=server_names)
        current = self._settings.get_current_server()
        if current:
            self._server_var.set(current.name)

    def _prompt_password(self, server_name: str) -> str:
        """弹出密码输入对话框，返回用户输入的密码（取消返回空字符串）"""
        dialog = ctk.CTkToplevel(self)
        dialog.title("输入服务器密码")
        dialog.geometry("350x150")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        # 居中
        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 350) // 2
        y = self.winfo_y() + (self.winfo_height() - 150) // 2
        dialog.geometry(f"+{x}+{y}")

        result = {"password": ""}

        ctk.CTkLabel(
            dialog, text=f"服务器 \"{server_name}\" 未设置密码，请输入：",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_BODY),
        ).pack(pady=(20, 10), padx=20)

        pwd_entry = ctk.CTkEntry(dialog, show="*", width=280)
        pwd_entry.pack(pady=5, padx=20)
        pwd_entry.focus_set()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=10)

        def on_ok(event=None):
            result["password"] = pwd_entry.get()
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        ctk.CTkButton(btn_frame, text="确定", width=80,
                       command=on_ok).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="取消", width=80,
                       fg_color="gray", command=on_cancel).pack(side="left", padx=5)

        # 回车确认
        pwd_entry.bind("<Return>", on_ok)

        dialog.wait_window()
        return result["password"]

    # ==================== 服务层回调（可能从非主线程调用） ====================

    def _on_service_message(self, msg: dict):
        """TalkService 消息回调"""
        def _update():
            msg_type = msg.get('type', 'text')
            from_call = msg.get('from_callsign', msg.get('from', '?'))
            ssid = msg.get('ssid', 0)
            dmr_id = msg.get('dmr_id', '')
            content = msg.get('content', msg.get('raw', ''))

            if msg_type == 'group_response':
                self._room.handle_group_response(msg.get('data', b''))
            elif msg_type == 'location':
                self._chat_panel.add_comm_message(
                    from_call, content, msg_type="location",
                    ssid=ssid, dmr_id=dmr_id)
            else:
                self._chat_panel.add_comm_message(
                    from_call, content, ssid=ssid, dmr_id=dmr_id)

        self.after(0, _update)

    def _on_service_voice(self, pcm_data: bytes, info: dict):
        """TalkService 语音数据回调（可能从非主线程调用）"""
        from_call = info.get('from', '')
        if self._recording:
            self._recording.append_pcm(pcm_data)
        # 播放语音
        if self._audio_panel.playback_enabled:
            self._audio.add_playback_data(pcm_data)

        def _update_recv_state():
            now = time.time()
            # 首个包：记录开始时间和发送者信息
            if self._voice_recv_start == 0.0:
                self._voice_recv_start = now
                self._voice_recv_info = info
            # 取消上一次的恢复计时器，避免闪烁
            if self._voice_recv_timer:
                self.after_cancel(self._voice_recv_timer)
            # 显示接收状态
            self._ptt_button.set_receiving(True, from_call)
            # 最后一个包到达 500ms 后恢复空闲状态并记录摘要
            self._voice_recv_timer = self.after(
                500, self._on_voice_recv_ended)

        self.after(0, _update_recv_state)

    def _on_voice_recv_ended(self):
        """语音接收结束，记录通联日志"""
        duration = time.time() - self._voice_recv_start if self._voice_recv_start else 0
        info = self._voice_recv_info
        # 重置状态
        self._voice_recv_start = 0.0
        self._voice_recv_info = {}
        self._voice_recv_timer = None
        # 恢复 PTT 按钮
        self._ptt_button.set_receiving(False)
        # 写入通联日志
        if duration > 0.1:
            self._chat_panel.add_comm_message(
                info.get('from_callsign', info.get('from', '?')),
                f"\U0001f4de语音消息（{duration:.1f}s）",
                ssid=info.get('ssid', 0),
                dmr_id=info.get('dmr_id', ''))

    def _on_service_connection_changed(self, state: str):
        """连接状态变化回调"""
        state = state.value if hasattr(state, 'value') else state
        def _update():
            self._status_bar.set_connection_state(state)
            if state == "disconnected" and self._connected:
                self._connected = False
                self._ptt_button.force_release()
                self._audio.stop_playback()
                self._location.stop_auto_report()
                self._connect_btn.configure(text="连接", state="normal")
                self._chat_panel.add_system_message("连接已断开")
                self._update_ui_state()
            elif state == "reconnecting":
                self._chat_panel.add_system_message("正在重连...")
            elif state == "connected" and not self._connected and not self._connecting:
                self._connected = True
                self._connect_btn.configure(text="断开", state="normal",
                                            fg_color=Colors.DISCONNECTED)
                self._chat_panel.add_system_message("重连成功")
                self._update_ui_state()
                if self._audio_panel.playback_enabled:
                    self._audio.start_playback()
                self._location.start_auto_report()
                # 连接成功后自动获取房间列表
                self._room.request_group_list()

        self.after(0, _update)

    def _on_service_status(self, status: dict):
        """状态更新回调"""
        pass  # 预留扩展

    def _on_service_group_list(self, groups: list):
        """房间列表回调"""
        def _update():
            self._room_selector.set_room_list(groups)
            self._chat_panel.add_system_message(
                f"获取到 {len(groups)} 个房间")

        self.after(0, _update)

    def _on_service_group_changed(self, group_id: int, group_name: str):
        """房间切换回调"""
        def _update():
            self._room_selector.set_current_room(group_id, group_name)
            self._status_bar.set_room(group_name)
            self._chat_panel.add_system_message(
                f"已切换到房间: {group_id}-{group_name}")

        self.after(0, _update)

    # ==================== 辅助方法 ====================

    def _update_ui_state(self):
        """根据连接状态更新 UI 可用性"""
        connected = self._connected
        self._ptt_button.set_enabled(connected)
        self._chat_panel.set_enabled(connected)
        self._room_selector.set_enabled(connected)
        # 录音面板始终可用（不需要连接）
        self._recording_panel.set_enabled(True)

    def _on_close(self):
        """窗口关闭"""
        try:
            if self._tail_tone_save_timer:
                self.after_cancel(self._tail_tone_save_timer)
                self._persist_tail_tone()
            if self._ptt_controller:
                self._ptt_controller.unregister()
            if self._location:
                self._location.stop_auto_report()
            if self._talk:
                self._talk.stop()
            if self._recording and self._recording.is_recording:
                self._recording.stop_recording()
            if self._audio:
                self._audio.close()
            if self._platform:
                self._platform.close()
        except Exception as e:
            logger.error(f"关闭时异常：{e}")
        finally:
            self.destroy()

    # ==================== 平台服务器管理 ====================

    def _auto_fetch_platform_servers(self):
        """自动拉取平台服务器列表（后台线程）"""
        try:
            servers = self._platform.fetch_platform_servers()
            if servers:
                self.after(0, lambda s=servers: self._merge_platform_servers(s))
            else:
                logger.debug("未获取到平台服务器列表")
        except Exception as e:
            logger.exception("拉取平台服务器失败")
            self.after(0, lambda: self._chat_panel.add_system_message(f"拉取服务器失败：{e}"))

    def _merge_platform_servers(self, platforms: list):
        """合并平台服务器到现有列表"""
        added = self._platform.merge_platform_servers(platforms)
        
        if added >0:
            self.after(0, lambda a=added: self._update_server_combo_and_msg(a))

    def _update_server_combo_and_msg(self, count: int):
        """更新服务器下拉框并显示消息"""
        server_names = [s.name for s in self._settings.servers_list]
        current = self._settings.get_current_server()
        current_name = current.name if current else ""
        
        self._server_var.set(current_name)
        self._server_combo.configure(values=server_names if server_names else ["无服务器"])
        self._chat_panel.add_system_message(f"已导入 {count} 个平台服务器")

    def _on_refresh_platform_servers(self):
        """手动刷新平台服务器列表"""
        self._refresh_servers_btn.configure(state="disabled", text="拉取中...")
        self._chat_panel.add_system_message("正在拉取平台服务器列表...")

        def fetch():
            try:
                servers = self._platform.fetch_platform_servers()
                self.after(0, lambda s=servers: self._on_platform_refresh_result(s))
            except Exception as exc:
                self.after(0, lambda e=exc: self._on_platform_refresh_result([], e))

        threading.Thread(target=fetch, daemon=True, name="platform-refresh").start()

    def _on_platform_refresh_result(self, servers: list, error: Optional[Exception] = None):
        self._refresh_servers_btn.configure(state="normal", text="刷新服务器")
        if error:
            logger.exception("拉取平台服务器失败", exc_info=error)
            self._chat_panel.add_system_message(f"拉取服务器失败：{error}")
        elif servers:
            self._merge_platform_servers(servers)
        else:
            self._chat_panel.add_system_message("未获取到平台服务器列表")

    def run(self):
        """启动主循环"""
        logger.info("78HAM 新架构 GUI 启动")
        self.mainloop()
