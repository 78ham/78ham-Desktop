"""
录音控制面板组件

提供本地录音功能控制界面。
"""
import os
import time
import customtkinter as ctk
from typing import Callable, List, Optional

from ui.theme import Colors, Fonts, Spacing


def _shorten_path(path: str, max_len: int = 34) -> str:
    """把路径压缩成面板可显示的短文本，保留末尾目录名。"""
    display = path
    home = os.path.expanduser("~")
    if display.startswith(home):
        display = "~" + display[len(home):]
    if len(display) <= max_len:
        return display
    return "…" + display[-(max_len - 1):]


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / (1024 * 1024):.1f}MB"


class RecordingPanel(ctk.CTkFrame):
    """录音控制面板

    功能：
    - 开始/停止录音
    - 显示录音状态和时长
    - 选择录音保存目录
    - 显示最近录音文件列表
    - 打开录音目录
    """

    def __init__(self, master,
                 on_start_recording: Optional[Callable[[], None]] = None,
                 on_stop_recording: Optional[Callable[[], None]] = None,
                 on_open_recordings_dir: Optional[Callable[[], None]] = None,
                 on_change_save_dir: Optional[Callable[[], None]] = None,
                 **kwargs):
        super().__init__(master, **kwargs)

        self._on_start_recording = on_start_recording
        self._on_stop_recording = on_stop_recording
        self._on_open_recordings_dir = on_open_recordings_dir
        self._on_change_save_dir = on_change_save_dir

        # 录音状态
        self._is_recording = False
        self._recording_start_time: float = 0.0
        self._timer_id: Optional[str] = None

        # 文件列表行
        self._file_rows: List[ctk.CTkFrame] = []
        self._empty_label: Optional[ctk.CTkLabel] = None

        self._build_ui()

    def _build_ui(self):
        """构建 UI"""
        # 标题
        ctk.CTkLabel(
            self, text="软件音频录音",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_BODY, "bold"),
        ).pack(anchor="w", padx=Spacing.PAD_SM, pady=(Spacing.PAD_XS, 0))

        # 录音按钮
        self._record_btn = ctk.CTkButton(
            self, text="开始录音", width=120,
            fg_color=Colors.TRANSMITTING,
            hover_color=Colors.PTT_ACTIVE,
            command=self._on_record_button_click,
        )
        self._record_btn.pack(pady=Spacing.PAD_SM)

        # 录音状态行：指示灯 + 状态文本 + 时长
        self._status_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._status_frame.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)

        self._status_indicator = ctk.CTkLabel(
            self._status_frame, text="●", width=15,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            text_color=Colors.TEXT_MUTED,
        )
        self._status_indicator.pack(side="left")

        self._status_label = ctk.CTkLabel(
            self._status_frame, text="就绪",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            text_color=Colors.TEXT_MUTED,
        )
        self._status_label.pack(side="left", padx=Spacing.PAD_XS)

        self._duration_label = ctk.CTkLabel(
            self._status_frame, text="00:00",
            font=(Fonts.FAMILY_MONO, Fonts.SIZE_SMALL),
            width=50,
        )
        self._duration_label.pack(side="right")

        # 保存位置行：路径 + 更改按钮
        dir_frame = ctk.CTkFrame(self, fg_color="transparent")
        dir_frame.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)

        ctk.CTkLabel(
            dir_frame, text="保存位置",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            text_color=Colors.TEXT_MUTED,
        ).pack(side="left")

        self._dir_label = ctk.CTkLabel(
            dir_frame, text="",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            anchor="w",
        )
        self._dir_label.pack(side="left", fill="x", expand=True, padx=Spacing.PAD_XS)

        self._change_dir_btn = ctk.CTkButton(
            dir_frame, text="更改", width=44,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            fg_color="gray",
            command=self._on_change_dir_click,
        )
        self._change_dir_btn.pack(side="right")

        # 分隔线
        sep = ctk.CTkFrame(self, height=1, fg_color=Colors.TEXT_MUTED)
        sep.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_SM)

        # 最近录音标题 + 打开目录按钮
        recent_frame = ctk.CTkFrame(self, fg_color="transparent")
        recent_frame.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)

        ctk.CTkLabel(
            recent_frame, text="最近录音",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL, "bold"),
        ).pack(side="left")

        self._open_dir_btn = ctk.CTkButton(
            recent_frame, text="打开目录", width=60,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            fg_color="gray",
            command=self._on_open_dir_click,
        )
        self._open_dir_btn.pack(side="right")

        # 录音文件列表（滚动区域）
        self._file_list_frame = ctk.CTkScrollableFrame(
            self, height=120,
            label_text="",
            fg_color=Colors.BG_CARD,
        )
        self._file_list_frame.pack(fill="both", expand=True,
                                   padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)

        self._update_recording_state()

    # ==================== 事件转发 ====================

    def _on_record_button_click(self):
        """录音按钮点击"""
        if self._is_recording:
            if self._on_stop_recording:
                self._on_stop_recording()
        else:
            if self._on_start_recording:
                self._on_start_recording()

    def _on_open_dir_click(self):
        if self._on_open_recordings_dir:
            self._on_open_recordings_dir()

    def _on_change_dir_click(self):
        if self._on_change_save_dir:
            self._on_change_save_dir()

    # ==================== 状态与目录 ====================

    def set_recording_state(self, is_recording: bool):
        """设置录音状态并同步时长计时。"""
        if is_recording == self._is_recording:
            return
        self._is_recording = is_recording
        self._update_recording_state()

        if is_recording:
            self._recording_start_time = time.monotonic()
            self._update_duration()
        else:
            self._stop_timer()
            self._duration_label.configure(text="00:00")

    def set_recordings_dir(self, path: str):
        """更新保存目录显示。"""
        self._dir_label.configure(text=_shorten_path(path))
        self._dir_label.configure(text_color=Colors.TEXT_SECONDARY)

    def _update_recording_state(self):
        """更新录音状态UI"""
        if self._is_recording:
            self._record_btn.configure(
                text="停止录音",
                fg_color=Colors.DISCONNECTED,
            )
            self._status_indicator.configure(text_color=Colors.TRANSMITTING)
            self._status_label.configure(
                text="录音中...",
                text_color=Colors.TRANSMITTING,
            )
        else:
            self._record_btn.configure(
                text="开始录音",
                fg_color=Colors.TRANSMITTING,
            )
            self._status_indicator.configure(text_color=Colors.TEXT_MUTED)
            self._status_label.configure(
                text="就绪",
                text_color=Colors.TEXT_MUTED,
            )

    def _update_duration(self):
        """更新录音时长显示"""
        if self._is_recording:
            duration = time.monotonic() - self._recording_start_time
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            self._duration_label.configure(text=f"{minutes:02d}:{seconds:02d}")
            self._timer_id = self.after(1000, self._update_duration)

    def _stop_timer(self):
        if self._timer_id:
            self.after_cancel(self._timer_id)
            self._timer_id = None

    # ==================== 文件列表 ====================

    def set_files(self, paths: List[str]):
        """用给定文件列表整体刷新列表显示。"""
        for row in self._file_rows:
            row.destroy()
        self._file_rows = []
        self._set_empty_hint(len(paths) == 0)
        for path in paths:
            self.add_recording_file(path)

    def add_recording_file(self, file_path: str):
        """追加一个录音文件到列表末尾。"""
        self._set_empty_hint(False)

        row = ctk.CTkFrame(self._file_list_frame, fg_color="transparent")
        row.pack(fill="x", pady=2)

        ctk.CTkLabel(
            row, text=os.path.basename(file_path),
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        try:
            size_text = _format_size(os.path.getsize(file_path))
        except OSError:
            size_text = ""
        ctk.CTkLabel(
            row, text=size_text,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            text_color=Colors.TEXT_MUTED,
            width=60,
        ).pack(side="right")

        self._file_rows.append(row)

    def _set_empty_hint(self, show: bool):
        """管理“暂无录音”空态提示。"""
        exists = self._empty_label is not None and self._empty_label.winfo_exists()
        if show and not exists:
            self._empty_label = ctk.CTkLabel(
                self._file_list_frame, text="暂无录音",
                font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
                text_color=Colors.TEXT_MUTED,
            )
            self._empty_label.pack(pady=Spacing.PAD_MD)
        elif not show and exists:
            self._empty_label.destroy()

    def set_enabled(self, enabled: bool):
        """启用/禁用面板"""
        state = "normal" if enabled else "disabled"
        self._record_btn.configure(state=state)
        self._open_dir_btn.configure(state=state)
        self._change_dir_btn.configure(state=state)
