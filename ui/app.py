"""
78HAM 新架构 GUI 主窗口

使用 TalkService/RoomService/LocationService 作为业务层，
组合各 UI 组件构建完整界面。
"""
import os
import sys
import time
import logging
import threading
import customtkinter as ctk
from typing import Optional

from config.settings import Settings
from services.talk_service import TalkService
from services.room_service import RoomService
from services.location_service import LocationService
from ptt.hotkey import PttController

from ui.theme import Colors, Fonts, Spacing, Sizes
from ui.components.status_bar import StatusBar
from ui.components.ptt_button import PttButton
from ui.components.chat_panel import ChatPanel
from ui.components.room_selector import RoomSelector
from ui.components.audio_panel import AudioPanel
from ui.components.config_dialog import ConfigDialog

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
        self._ptt_controller: Optional[PttController] = None

        # 状态
        self._connected = False

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
        )
        self._audio_panel.pack(fill="x", pady=(0, Spacing.PAD_SM))

        self._room_selector = RoomSelector(
            left_panel,
            on_join_room=self._on_join_room,
            on_refresh=self._on_refresh_rooms,
        )
        self._room_selector.pack(fill="x", pady=(0, Spacing.PAD_SM))

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

        # 服务器信息
        self._server_label = ctk.CTkLabel(
            toolbar, text="",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            text_color=Colors.TEXT_SECONDARY,
        )
        self._server_label.pack(side="left", padx=Spacing.PAD_MD)

        # 右侧：配置按钮
        self._config_btn = ctk.CTkButton(
            toolbar, text="配置", width=60,
            fg_color="gray",
            command=self._open_config,
        )
        self._config_btn.pack(side="right", padx=Spacing.PAD_XS)

    # ==================== 服务初始化 ====================

    def _init_services(self):
        """初始化业务服务层"""
        self._talk = TalkService(self._settings)
        self._room = RoomService(self._settings, self._talk.udp_client)
        self._location = LocationService(self._settings)

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
            self._server_label.configure(
                text=f"{server.name} ({server.host}:{server.port})")
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
        self._status_bar.set_connection_state("connecting")
        self._connect_btn.configure(text="连接中...", state="disabled")
        self._chat_panel.add_system_message("正在连接...")

        # 在后台线程执行连接
        def _do_connect():
            success = self._talk.start()
            self.after(0, lambda: self._on_connect_result(success))

        threading.Thread(target=_do_connect, daemon=True).start()

    def _on_connect_result(self, success: bool):
        """连接结果回调（主线程）"""
        if success:
            self._connected = True
            self._status_bar.set_connection_state("connected")
            self._connect_btn.configure(text="断开", state="normal",
                                        fg_color=Colors.DISCONNECTED)
            self._chat_panel.add_system_message("连接成功")
            self._location.start_auto_report()
            self._ptt_button.set_enabled(True)
            self._chat_panel.set_enabled(True)
            self._room_selector.set_enabled(True)
        else:
            self._connected = False
            self._status_bar.set_connection_state("disconnected")
            self._connect_btn.configure(text="连接", state="normal")
            self._chat_panel.add_system_message("连接失败")

    def _disconnect(self):
        """断开连接"""
        self._ptt_button.force_release()
        self._location.stop_auto_report()
        self._talk.stop()
        self._connected = False
        self._status_bar.set_connection_state("disconnected")
        self._connect_btn.configure(text="连接", state="normal",
                                    fg_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"])
        self._chat_panel.add_system_message("已断开连接")
        self._update_ui_state()

    def _on_ptt_press(self):
        """PTT 按下"""
        if not self._connected:
            return
        self._talk.start_transmitting()

    def _on_ptt_release(self):
        """PTT 松开"""
        if not self._connected:
            return
        self._talk.stop_transmitting()

    def _on_send_text(self, text: str):
        """发送文本消息"""
        if not self._connected:
            self._chat_panel.add_system_message("未连接，无法发送")
            return
        if self._talk.send_text_message(text):
            self._chat_panel.add_message(
                self._settings.device.callsign, text)
        else:
            self._chat_panel.add_system_message("发送失败")

    def _on_send_location(self):
        """发送位置"""
        if not self._connected:
            return
        lat, lng, source = self._location.get_location()
        if lat == 0.0 and lng == 0.0:
            self._chat_panel.add_system_message("定位失败")
            return
        if self._talk.send_location(lat, lng):
            self._chat_panel.add_message(
                self._settings.device.callsign,
                f"{lat:.6f},{lng:.6f} (来源: {source})",
                msg_type="location")

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

    def _on_codec_change(self, codec: str):
        """切换编码"""
        if self._talk and self._talk.set_codec(codec):
            self._status_bar.set_codec(codec)
            self._chat_panel.add_system_message(f"编码已切换: {codec}")
        else:
            self._chat_panel.add_system_message("编码切换失败")
            # 恢复显示
            self._audio_panel.set_codec(self._settings.audio.codec)

    def _on_playback_toggle(self, enabled: bool):
        """播放开关"""
        # TalkService 内部处理播放状态
        pass

    def _open_config(self):
        """打开配置对话框"""
        ConfigDialog(self, on_save=self._on_config_saved)

    def _on_config_saved(self, filename: str, config_data: dict):
        """配置保存回调"""
        if filename:
            self._chat_panel.add_system_message(f"配置已保存: {filename}")
        else:
            self._chat_panel.add_system_message("配置已更新")

    # ==================== 服务层回调（可能从非主线程调用） ====================

    def _on_service_message(self, msg: dict):
        """TalkService 消息回调"""
        def _update():
            msg_type = msg.get('type', 'text')
            from_call = msg.get('from', '?')
            content = msg.get('content', msg.get('raw', ''))

            if msg_type == 'group_response':
                # 房间响应交给 RoomService 处理
                self._room.handle_group_response(msg.get('data', b''))
            elif msg_type == 'location':
                self._chat_panel.add_message(from_call, content, msg_type="location")
            else:
                self._chat_panel.add_message(from_call, content)

        self.after(0, _update)

    def _on_service_voice(self, pcm_data: bytes, info: dict):
        """TalkService 语音数据回调"""
        from_call = info.get('from', '')
        # 更新 PTT 按钮显示接收状态
        self.after(0, lambda: self._ptt_button.set_receiving(True, from_call))
        # 短暂延迟后恢复
        self.after(500, lambda: self._ptt_button.set_receiving(False))

    def _on_service_connection_changed(self, state: str):
        """连接状态变化回调"""
        def _update():
            self._status_bar.set_connection_state(state)
            if state == "disconnected" and self._connected:
                self._connected = False
                self._connect_btn.configure(text="连接", state="normal")
                self._chat_panel.add_system_message("连接已断开")
                self._update_ui_state()
            elif state == "reconnecting":
                self._chat_panel.add_system_message("正在重连...")
            elif state == "connected" and not self._connected:
                self._connected = True
                self._connect_btn.configure(text="断开", state="normal",
                                            fg_color=Colors.DISCONNECTED)
                self._chat_panel.add_system_message("重连成功")
                self._update_ui_state()

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

    def _on_close(self):
        """窗口关闭"""
        try:
            if self._ptt_controller:
                self._ptt_controller.unregister()
            if self._location:
                self._location.stop_auto_report()
            if self._talk:
                self._talk.stop()
        except Exception as e:
            logger.error(f"关闭时异常: {e}")
        finally:
            self.destroy()

    def run(self):
        """启动主循环"""
        logger.info("78HAM 新架构 GUI 启动")
        self.mainloop()
