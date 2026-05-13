"""
音频控制面板组件

音频设备选择、编码格式切换、音量/播放控制、尾音设置。
"""
import os
import customtkinter as ctk
from tkinter import filedialog
from typing import Optional, Callable

from ui.theme import Colors, Fonts, Spacing

# 尾音类型映射：显示名 -> 内部值
TAIL_TYPE_MAP = {
    "默认": "default",
    "自定义": "custom",
    "MDC": "mdc",
}
TAIL_TYPE_REVERSE = {v: k for k, v in TAIL_TYPE_MAP.items()}
TAIL_TYPE_DISPLAY = list(TAIL_TYPE_MAP.keys())


class AudioPanel(ctk.CTkFrame):
    """音频控制面板

    功能：
    - 编码格式选择 (G.711 / Opus)
    - 播放开关
    - 麦克风增益控制
    - 尾音设置
    """

    def __init__(self, master,
                 on_codec_change: Optional[Callable[[str], None]] = None,
                 on_playback_toggle: Optional[Callable[[bool], None]] = None,
                 on_gain_change: Optional[Callable[[float], None]] = None,
                 on_tail_tone_change: Optional[Callable[[dict], None]] = None,
                 **kwargs):
        super().__init__(master, **kwargs)

        self._on_codec_change = on_codec_change
        self._on_playback_toggle = on_playback_toggle
        self._on_gain_change = on_gain_change
        self._on_tail_tone_change = on_tail_tone_change
        self._playback_enabled = True
        self._mic_gain = 1.0

        # 尾音状态
        self._tail_enabled = False
        self._tail_type = "default"
        self._tail_file = ""
        self._mdc_id = 0
        self._mdc_amplitude = 0.2

        self._build_ui()

    def _build_ui(self):
        """构建 UI"""
        # ===== 音频设置 =====
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
        self._playback_switch.select()

        # 麦克风增益
        gain_frame = ctk.CTkFrame(self, fg_color="transparent")
        gain_frame.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)

        ctk.CTkLabel(
            gain_frame, text="增益:",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
        ).pack(side="left")

        self._gain_slider = ctk.CTkSlider(
            gain_frame,
            from_=0.0,
            to=3.0,
            number_of_steps=30,
            command=self._on_gain_slider_changed,
            width=120,
        )
        self._gain_slider.pack(side="left", padx=Spacing.PAD_SM)
        self._gain_slider.set(1.0)

        self._gain_label = ctk.CTkLabel(
            gain_frame, text="1.0x",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            width=40,
        )
        self._gain_label.pack(side="left")

        # ===== 尾音设置 =====
        sep = ctk.CTkFrame(self, height=1, fg_color=Colors.TEXT_MUTED)
        sep.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_SM)

        ctk.CTkLabel(
            self, text="尾音设置",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_BODY, "bold"),
        ).pack(anchor="w", padx=Spacing.PAD_SM, pady=(0, Spacing.PAD_XS))

        # 尾音开关
        tail_enable_frame = ctk.CTkFrame(self, fg_color="transparent")
        tail_enable_frame.pack(fill="x", padx=Spacing.PAD_SM,
                               pady=Spacing.PAD_XS)

        ctk.CTkLabel(
            tail_enable_frame, text="启用:",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
        ).pack(side="left")

        self._tail_switch = ctk.CTkSwitch(
            tail_enable_frame, text="",
            command=self._on_tail_switched,
            width=40,
        )
        self._tail_switch.pack(side="left", padx=Spacing.PAD_SM)

        # 尾音类型
        tail_type_frame = ctk.CTkFrame(self, fg_color="transparent")
        tail_type_frame.pack(fill="x", padx=Spacing.PAD_SM,
                             pady=Spacing.PAD_XS)

        ctk.CTkLabel(
            tail_type_frame, text="类型:",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
        ).pack(side="left")

        self._tail_type_var = ctk.StringVar(value="默认")
        self._tail_type_menu = ctk.CTkOptionMenu(
            tail_type_frame,
            variable=self._tail_type_var,
            values=TAIL_TYPE_DISPLAY,
            width=90,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            command=self._on_tail_type_selected,
        )
        self._tail_type_menu.pack(side="left", padx=Spacing.PAD_SM)

        # 自定义文件行（默认隐藏）
        self._tail_file_frame = ctk.CTkFrame(self, fg_color="transparent")

        self._tail_file_label = ctk.CTkLabel(
            self._tail_file_frame, text="未选择文件",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            text_color=Colors.TEXT_MUTED,
            width=140,
            anchor="w",
        )
        self._tail_file_label.pack(side="left", padx=(0, Spacing.PAD_XS))

        self._tail_file_btn = ctk.CTkButton(
            self._tail_file_frame, text="选择",
            width=50,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            command=self._on_tail_file_browse,
        )
        self._tail_file_btn.pack(side="left")

        # MDC ID 行（默认隐藏）
        self._mdc_id_frame = ctk.CTkFrame(self, fg_color="transparent")

        ctk.CTkLabel(
            self._mdc_id_frame, text="ID:",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
        ).pack(side="left")

        self._mdc_id_var = ctk.StringVar(value="0")
        self._mdc_id_entry = ctk.CTkEntry(
            self._mdc_id_frame,
            textvariable=self._mdc_id_var,
            width=80,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
        )
        self._mdc_id_entry.pack(side="left", padx=Spacing.PAD_SM)
        self._mdc_id_entry.bind("<FocusOut>", self._on_mdc_id_changed)
        self._mdc_id_entry.bind("<Return>", self._on_mdc_id_changed)

        # MDC 音量行（默认隐藏）
        self._mdc_amp_frame = ctk.CTkFrame(self, fg_color="transparent")

        ctk.CTkLabel(
            self._mdc_amp_frame, text="音量:",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
        ).pack(side="left")

        self._mdc_amp_slider = ctk.CTkSlider(
            self._mdc_amp_frame,
            from_=0.05,
            to=1.0,
            number_of_steps=19,
            command=self._on_mdc_amp_changed,
            width=100,
        )
        self._mdc_amp_slider.pack(side="left", padx=Spacing.PAD_SM)
        self._mdc_amp_slider.set(0.2)

        self._mdc_amp_label = ctk.CTkLabel(
            self._mdc_amp_frame, text="0.2",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            width=30,
        )
        self._mdc_amp_label.pack(side="left")

        # 状态信息
        self._info_label = ctk.CTkLabel(
            self, text="",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            text_color=Colors.TEXT_MUTED,
        )
        self._info_label.pack(anchor="w", padx=Spacing.PAD_SM,
                              pady=(0, Spacing.PAD_XS))

        # 初始化尾音 UI 可见性
        self._update_tail_type_visibility()

    # ==================== 音频事件处理 ====================

    def _on_codec_selected(self, choice: str):
        if self._on_codec_change:
            self._on_codec_change(choice)

    def _on_playback_switched(self):
        self._playback_enabled = self._playback_switch.get() == 1
        if self._on_playback_toggle:
            self._on_playback_toggle(self._playback_enabled)

    def _on_gain_slider_changed(self, value: float):
        self._mic_gain = round(value, 1)
        self._gain_label.configure(text=f"{self._mic_gain:.1f}x")
        if self._on_gain_change:
            self._on_gain_change(self._mic_gain)

    # ==================== 尾音事件处理 ====================

    def _on_tail_switched(self):
        self._tail_enabled = self._tail_switch.get() == 1
        self._emit_tail_tone_change()

    def _on_tail_type_selected(self, display_name: str):
        self._tail_type = TAIL_TYPE_MAP.get(display_name, "default")
        self._update_tail_type_visibility()
        self._emit_tail_tone_change()

    def _on_tail_file_browse(self):
        path = filedialog.askopenfilename(
            title="选择尾音文件",
            filetypes=[
                ("音频文件", "*.wav *.raw *.pcm"),
                ("WAV 文件", "*.wav"),
                ("Raw PCM", "*.raw *.pcm"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self._tail_file = path
            # 显示文件名（截断过长路径）
            display = os.path.basename(path)
            if len(display) > 18:
                display = display[:15] + "..."
            self._tail_file_label.configure(
                text=display, text_color=Colors.TEXT_PRIMARY)
            self._emit_tail_tone_change()

    def _on_mdc_id_changed(self, event=None):
        try:
            val = int(self._mdc_id_var.get())
            self._mdc_id = max(0, min(65535, val))
        except ValueError:
            self._mdc_id = 0
            self._mdc_id_var.set("0")
        self._emit_tail_tone_change()

    def _on_mdc_amp_changed(self, value: float):
        self._mdc_amplitude = round(value, 2)
        self._mdc_amp_label.configure(text=f"{self._mdc_amplitude:.2f}")
        self._emit_tail_tone_change()

    def _emit_tail_tone_change(self):
        if self._on_tail_tone_change:
            self._on_tail_tone_change({
                "enabled": self._tail_enabled,
                "type": self._tail_type,
                "file": self._tail_file,
                "mdc_id": self._mdc_id,
                "amplitude": self._mdc_amplitude,
            })

    def _update_tail_type_visibility(self):
        """根据尾音类型显示/隐藏对应控件"""
        # 先隐藏所有
        self._tail_file_frame.pack_forget()
        self._mdc_id_frame.pack_forget()
        self._mdc_amp_frame.pack_forget()

        # 根据类型显示
        if self._tail_type == "custom":
            self._tail_file_frame.pack(
                fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)
        elif self._tail_type == "mdc":
            self._mdc_id_frame.pack(
                fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)
            self._mdc_amp_frame.pack(
                fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)

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

    def set_mic_gain(self, gain: float):
        """设置麦克风增益值"""
        self._mic_gain = max(0.0, min(3.0, gain))
        self._gain_slider.set(self._mic_gain)
        self._gain_label.configure(text=f"{self._mic_gain:.1f}x")

    def set_tail_tone_config(self, config: dict):
        """从配置恢复尾音 UI 状态"""
        enabled = config.get("enabled", False)
        tail_type = config.get("type", "default")
        custom_file = config.get("file", "")
        mdc_id = config.get("mdc_id", 0)
        amplitude = config.get("amplitude", 0.2)

        self._tail_enabled = enabled
        self._tail_type = tail_type
        self._tail_file = custom_file
        self._mdc_id = mdc_id
        self._mdc_amplitude = amplitude

        if enabled:
            self._tail_switch.select()
        else:
            self._tail_switch.deselect()

        display_name = TAIL_TYPE_REVERSE.get(tail_type, "默认")
        self._tail_type_var.set(display_name)

        if custom_file:
            display = os.path.basename(custom_file)
            if len(display) > 18:
                display = display[:15] + "..."
            self._tail_file_label.configure(
                text=display, text_color=Colors.TEXT_PRIMARY)

        self._mdc_id_var.set(str(mdc_id))
        self._mdc_amp_slider.set(amplitude)
        self._mdc_amp_label.configure(text=f"{amplitude:.2f}")

        self._update_tail_type_visibility()

    @property
    def mic_gain(self) -> float:
        return self._mic_gain

    @property
    def playback_enabled(self) -> bool:
        return self._playback_enabled

    def set_enabled(self, enabled: bool):
        """启用/禁用整个面板"""
        state = "normal" if enabled else "disabled"
        self._codec_menu.configure(state=state)
        self._playback_switch.configure(state=state)
        self._gain_slider.configure(state=state)
        self._tail_switch.configure(state=state)
        self._tail_type_menu.configure(state=state)
        self._tail_file_btn.configure(state=state)
        self._mdc_id_entry.configure(state=state)
        self._mdc_amp_slider.configure(state=state)
