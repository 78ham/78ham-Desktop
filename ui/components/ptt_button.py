"""
PTT 按钮组件

大型按下说话按钮，支持鼠标按下/松开和全局热键。
视觉反馈：空闲/发射中/接收中 三种状态。
"""
import customtkinter as ctk
from typing import Optional, Callable

from ui.theme import Colors, Fonts, Spacing, Sizes


class PttButton(ctk.CTkFrame):
    """PTT 按钮组件

    功能：
    - 鼠标按下开始发射，松开停止
    - 显示发射/接收状态
    - 发射计时
    - 热键提示
    """

    def __init__(self, master,
                 on_press: Optional[Callable[[], None]] = None,
                 on_release: Optional[Callable[[], None]] = None,
                 **kwargs):
        super().__init__(master, **kwargs)

        self._on_press = on_press
        self._on_release = on_release
        self._is_transmitting = False
        self._is_receiving = False
        self._enabled = True

        self._build_ui()

    def _build_ui(self):
        """构建 UI"""
        # PTT 主按钮
        self._button = ctk.CTkButton(
            self,
            text="按 住 说 话",
            width=Sizes.PTT_BUTTON_WIDTH,
            height=Sizes.PTT_BUTTON_HEIGHT,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_HEADING, "bold"),
            fg_color=Colors.PTT_IDLE,
            hover_color=Colors.PTT_HOVER,
            corner_radius=10,
        )
        self._button.pack(padx=Spacing.PAD_MD, pady=Spacing.PAD_SM)

        # 绑定鼠标按下事件
        self._button.bind("<ButtonPress-1>", self._on_mouse_press)

        # 状态提示
        self._hint_label = ctk.CTkLabel(
            self, text="热键: F5",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            text_color=Colors.TEXT_MUTED,
        )
        self._hint_label.pack(pady=(0, Spacing.PAD_XS))

    # ==================== 事件处理 ====================

    def _on_mouse_press(self, event=None):
        """鼠标按下"""
        if not self._enabled or self._is_transmitting:
            return
        self._start_transmit()
        # 绑定全局鼠标释放事件，确保鼠标移出按钮后松开仍能停止发射
        self.winfo_toplevel().bind("<ButtonRelease-1>", self._on_global_mouse_release)

    def _on_global_mouse_release(self, event=None):
        """全局鼠标松开事件"""
        # 取消全局绑定
        self.winfo_toplevel().unbind("<ButtonRelease-1>")
        if not self._is_transmitting:
            return
        self._stop_transmit()

    def _start_transmit(self):
        """开始发射"""
        self._is_transmitting = True
        self._button.configure(
            text="● 发射中...",
            fg_color=Colors.PTT_ACTIVE,
        )
        if self._on_press:
            self._on_press()

    def _stop_transmit(self):
        """停止发射"""
        self._is_transmitting = False
        self._button.configure(
            text="按 住 说 话",
            fg_color=Colors.PTT_IDLE,
        )
        if self._on_release:
            self._on_release()

    # ==================== 公开接口 ====================

    def set_enabled(self, enabled: bool):
        """启用/禁用 PTT"""
        self._enabled = enabled
        if not enabled:
            self._button.configure(
                text="PTT 不可用",
                fg_color="#555555",
            )
        else:
            self._button.configure(
                text="按 住 说 话",
                fg_color=Colors.PTT_IDLE,
            )

    def set_receiving(self, receiving: bool, from_callsign: str = ""):
        """设置接收状态"""
        self._is_receiving = receiving
        if receiving:
            self._button.configure(
                text=f"♪ 接收: {from_callsign}" if from_callsign else "♪ 接收中",
                fg_color=Colors.RECEIVING,
            )
        elif not self._is_transmitting:
            self._button.configure(
                text="按 住 说 话",
                fg_color=Colors.PTT_IDLE,
            )

    def set_hotkey_hint(self, key: str):
        """更新热键提示"""
        self._hint_label.configure(text=f"热键: {key.upper()}")

    def set_transmitting(self):
        """外部设置发射状态（热键触发时使用）"""
        if not self._is_transmitting:
            self._start_transmit()

    def set_idle(self):
        """外部设置空闲状态（热键触发时使用）"""
        if self._is_transmitting:
            self._stop_transmit()

    @property
    def is_transmitting(self) -> bool:
        return self._is_transmitting

    def force_release(self):
        """强制停止发射（用于断开连接时）"""
        if self._is_transmitting:
            self._stop_transmit()
