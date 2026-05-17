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

# Opus 码率选项：(bps值, 显示文本)
BITRATE_OPTIONS = ["16000", "24000", "32000", "36000", "48000", "64000"]
BITRATE_DISPLAY = ["16 kbps", "24 kbps", "32 kbps", "36 kbps", "48 kbps", "64 kbps"]
BITRATE_DEFAULT = "36000"


class AudioPanel(ctk.CTkFrame):
    """音频控制面板

    功能：
    - 输入/输出设备选择
    - 编码格式选择 (G.711 / Opus)
    - 播放开关
    - 尾音设置
    """

    def __init__(self, master,
                 on_codec_change: Optional[Callable[[str], None]] = None,
                 on_playback_toggle: Optional[Callable[[bool], None]] = None,
                 on_tail_tone_change: Optional[Callable[[dict], None]] = None,
                 on_bitrate_change: Optional[Callable[[int], None]] = None,
                 on_input_device_change: Optional[Callable[[int], None]] = None,
                 on_output_device_change: Optional[Callable[[int], None]] = None,
                 **kwargs):
        super().__init__(master, **kwargs)

        self._on_codec_change = on_codec_change
        self._on_playback_toggle = on_playback_toggle
        self._on_tail_tone_change = on_tail_tone_change
        self._on_bitrate_change = on_bitrate_change
        self._on_input_device_change = on_input_device_change
        self._on_output_device_change = on_output_device_change
        self._playback_enabled = True

        # 设备列表缓存
        self._input_devices = []  # [{index, name, ...}]
        self._output_devices = []

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

        # 输入设备（麦克风）
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)

        ctk.CTkLabel(
            input_frame, text="麦克风:",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
        ).pack(side="left")

        self._input_device_var = ctk.StringVar(value="默认设备")
        self._input_device_menu = ctk.CTkOptionMenu(
            input_frame,
            variable=self._input_device_var,
            values=["默认设备"],
            width=140,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            command=self._on_input_device_selected,
        )
        self._input_device_menu.pack(side="left", padx=Spacing.PAD_SM)

        # 输出设备（扬声器）
        output_frame = ctk.CTkFrame(self, fg_color="transparent")
        output_frame.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)

        ctk.CTkLabel(
            output_frame, text="扬声器:",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
        ).pack(side="left")

        self._output_device_var = ctk.StringVar(value="默认设备")
        self._output_device_menu = ctk.CTkOptionMenu(
            output_frame,
            variable=self._output_device_var,
            values=["默认设备"],
            width=140,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            command=self._on_output_device_selected,
        )
        self._output_device_menu.pack(side="left", padx=Spacing.PAD_SM)

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

        # Opus 码率（仅 opus 时可见）
        self._bitrate_frame = ctk.CTkFrame(self, fg_color="transparent")

        ctk.CTkLabel(
            self._bitrate_frame, text="码率:",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
        ).pack(side="left")

        self._bitrate_var = ctk.StringVar(value=BITRATE_DEFAULT)
        self._bitrate_menu = ctk.CTkOptionMenu(
            self._bitrate_frame,
            variable=self._bitrate_var,
            values=BITRATE_OPTIONS,
            width=100,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            command=self._on_bitrate_selected,
        )
        self._bitrate_menu.pack(side="left", padx=Spacing.PAD_SM)

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

    # ==================== 设备事件处理 ====================

    def _on_input_device_selected(self, choice: str):
        """输入设备选择"""
        if self._on_input_device_change:
            # 根据显示名称查找设备索引
            for dev in self._input_devices:
                if dev['name'] == choice:
                    self._on_input_device_change(dev['index'])
                    return
            # 选择"默认设备"
            self._on_input_device_change(-1)

    def _on_output_device_selected(self, choice: str):
        """输出设备选择"""
        if self._on_output_device_change:
            for dev in self._output_devices:
                if dev['name'] == choice:
                    self._on_output_device_change(dev['index'])
                    return
            self._on_output_device_change(-1)

    # ==================== 音频事件处理 ====================

    def _on_codec_selected(self, choice: str):
        self._update_bitrate_visibility(choice)
        if self._on_codec_change:
            self._on_codec_change(choice)

    def _on_bitrate_selected(self, choice: str):
        if self._on_bitrate_change:
            self._on_bitrate_change(int(choice))

    def _on_playback_switched(self):
        self._playback_enabled = self._playback_switch.get() == 1
        if self._on_playback_toggle:
            self._on_playback_toggle(self._playback_enabled)

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

    def _update_bitrate_visibility(self, codec: str = ""):
        """根据编码格式显示/隐藏码率控件"""
        if not codec:
            codec = self._codec_var.get()
        if codec == "opus":
            self._bitrate_frame.pack(
                fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)
        else:
            self._bitrate_frame.pack_forget()

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

    def set_input_devices(self, devices: list, current_index: int = None):
        """设置输入设备列表

        Args:
            devices: 设备列表 [{index, name, ...}]
            current_index: 当前选中的设备索引，None 表示默认
        """
        self._input_devices = devices
        names = ["默认设备"] + [d['name'] for d in devices]
        self._input_device_menu.configure(values=names)

        if current_index is not None:
            for dev in devices:
                if dev['index'] == current_index:
                    self._input_device_var.set(dev['name'])
                    return
        self._input_device_var.set("默认设备")

    def set_output_devices(self, devices: list, current_index: int = None):
        """设置输出设备列表

        Args:
            devices: 设备列表 [{index, name, ...}]
            current_index: 当前选中的设备索引，None 表示默认
        """
        self._output_devices = devices
        names = ["默认设备"] + [d['name'] for d in devices]
        self._output_device_menu.configure(values=names)

        if current_index is not None:
            for dev in devices:
                if dev['index'] == current_index:
                    self._output_device_var.set(dev['name'])
                    return
        self._output_device_var.set("默认设备")

    def set_codec(self, codec: str):
        """设置当前编码"""
        self._codec_var.set(codec)
        self._update_bitrate_visibility(codec)

    def set_bitrate(self, bitrate: int):
        """设置当前码率"""
        self._bitrate_var.set(str(bitrate))

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
    def playback_enabled(self) -> bool:
        return self._playback_enabled

    def set_enabled(self, enabled: bool):
        """启用/禁用整个面板"""
        state = "normal" if enabled else "disabled"
        self._input_device_menu.configure(state=state)
        self._output_device_menu.configure(state=state)
        self._codec_menu.configure(state=state)
        self._playback_switch.configure(state=state)
        self._tail_switch.configure(state=state)
        self._tail_type_menu.configure(state=state)
        self._tail_file_btn.configure(state=state)
        self._mdc_id_entry.configure(state=state)
        self._mdc_amp_slider.configure(state=state)
