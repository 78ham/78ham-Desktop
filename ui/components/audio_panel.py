"""
音频控制面板组件

音频设备选择、编码格式切换、音量/播放控制。
"""
import customtkinter as ctk
from typing import Optional, Callable, List

from ui.theme import Colors, Fonts, Spacing


class AudioPanel(ctk.CTkFrame):
    """音频控制面板

    功能：
    - 编码格式选择 (G.711 / Opus)
    - 播放开关
    - 音频设备信息
    """

    def __init__(self, master,
                 on_codec_change: Optional[Callable[[str], None]] = None,
                 on_playback_toggle: Optional[Callable[[bool], None]] = None,
                 **kwargs):
        super().__init__(master, **kwargs)

        self._on_codec_change = on_codec_change
        self._on_playback_toggle = on_playback_toggle
        self._playback_enabled = True

        self._build_ui()

    def _build_ui(self):
        """构建 UI"""
        # 标题
        ctk.CTkLabel(
            self, text="音频设置",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_BODY, "bold"),
        ).pack(anchor="w", padx=Spacing.PAD_SM, pady=(Spacing.PAD_XS, 0))

        # 编码格式
        codec_frame = ctk.CTkFrame(self, fg_color="transparent")
        codec_frame.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)

        ctk.CTkLabel(
            codec_frame, text="编码:",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
        ).pack(side="left")

        self._codec_var = ctk.StringVar(value="g711")
        self._codec_menu = ctk.CTkOptionMenu(
            codec_frame,
            variable=self._codec_var,
            values=["g711", "opus"],
            width=90,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            command=self._on_codec_selected,
        )
        self._codec_menu.pack(side="left", padx=Spacing.PAD_SM)

        # 播放开关
        playback_frame = ctk.CTkFrame(self, fg_color="transparent")
        playback_frame.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)

        ctk.CTkLabel(
            playback_frame, text="播放:",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
        ).pack(side="left")

        self._playback_switch = ctk.CTkSwitch(
            playback_frame, text="",
            command=self._on_playback_switched,
            width=40,
        )
        self._playback_switch.pack(side="left", padx=Spacing.PAD_SM)
        self._playback_switch.select()  # 默认开启

        # 状态信息
        self._info_label = ctk.CTkLabel(
            self, text="",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            text_color=Colors.TEXT_MUTED,
        )
        self._info_label.pack(anchor="w", padx=Spacing.PAD_SM,
                              pady=(0, Spacing.PAD_XS))

    # ==================== 事件处理 ====================

    def _on_codec_selected(self, choice: str):
        """编码格式变化"""
        if self._on_codec_change:
            self._on_codec_change(choice)

    def _on_playback_switched(self):
        """播放开关切换"""
        self._playback_enabled = self._playback_switch.get() == 1
        if self._on_playback_toggle:
            self._on_playback_toggle(self._playback_enabled)

    # ==================== 公开接口 ====================

    def set_codec(self, codec: str):
        """设置当前编码"""
        self._codec_var.set(codec)

    def set_info(self, text: str):
        """设置状态信息文本"""
        self._info_label.configure(text=text)

    def set_playback_enabled(self, enabled: bool):
        """设置播放开关状态"""
        self._playback_enabled = enabled
        if enabled:
            self._playback_switch.select()
        else:
            self._playback_switch.deselect()

    @property
    def playback_enabled(self) -> bool:
        return self._playback_enabled

    def set_enabled(self, enabled: bool):
        """启用/禁用整个面板"""
        state = "normal" if enabled else "disabled"
        self._codec_menu.configure(state=state)
        self._playback_switch.configure(state=state)
