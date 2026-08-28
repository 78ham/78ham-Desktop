"""
录音控制面板组件

提供本地录音功能控制界面。
"""
import os
import customtkinter as ctk
from tkinter import messagebox
from typing import Optional, Callable
import time

from ui.theme import Colors, Fonts, Spacing


class RecordingPanel(ctk.CTkFrame):
    """录音控制面板
    
    功能：
    - 开始/停止录音
    - 显示录音状态和时长
    - 显示最近录音文件列表
    - 打开录音目录
    """
    
    def __init__(self, master,
                 on_start_recording: Optional[Callable[[], None]] = None,
                 on_stop_recording: Optional[Callable[[], None]] = None,
                 on_open_recordings_dir: Optional[Callable[[], None]] = None,
                 **kwargs):
        super().__init__(master, **kwargs)
        
        self._on_start_recording = on_start_recording
        self._on_stop_recording = on_stop_recording
        self._on_open_recordings_dir = on_open_recordings_dir
        
        # 录音状态
        self._is_recording = False
        self._recording_start_time: float = 0.0
        self._timer_id: Optional[str] = None
        
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
            hover_color="#c0392b",
            command=self._on_record_button_click,
        )
        self._record_btn.pack(pady=Spacing.PAD_SM)
        
        # 录音状态
        self._status_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._status_frame.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)
        
        # 状态指示灯
        self._status_indicator = ctk.CTkLabel(
            self._status_frame, text="●", width=15,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            text_color=Colors.TEXT_MUTED,
        )
        self._status_indicator.pack(side="left")
        
        # 状态文本
        self._status_label = ctk.CTkLabel(
            self._status_frame, text="就绪",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            text_color=Colors.TEXT_MUTED,
        )
        self._status_label.pack(side="left", padx=Spacing.PAD_XS)
        
        # 录音时长
        self._duration_label = ctk.CTkLabel(
            self._status_frame, text="00:00",
            font=(Fonts.FAMILY_MONO, Fonts.SIZE_SMALL),
            width=50,
        )
        self._duration_label.pack(side="right")
        
        # 分隔线
        sep = ctk.CTkFrame(self, height=1, fg_color=Colors.TEXT_MUTED)
        sep.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_SM)
        
        # 最近录音标题
        recent_frame = ctk.CTkFrame(self, fg_color="transparent")
        recent_frame.pack(fill="x", padx=Spacing.PAD_SM, pady=Spacing.PAD_XS)
        
        ctk.CTkLabel(
            recent_frame, text="最近录音",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL, "bold"),
        ).pack(side="left")
        
        # 打开目录按钮
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
        
        # 空列表提示
        self._empty_label = ctk.CTkLabel(
            self._file_list_frame, text="暂无录音",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            text_color=Colors.TEXT_MUTED,
        )
        self._empty_label.pack(pady=Spacing.PAD_MD)
        
        # 初始化状态
        self._update_recording_state()
    
    def _on_record_button_click(self):
        """录音按钮点击"""
        if self._is_recording:
            if self._on_stop_recording:
                self._on_stop_recording()
        else:
            if self._on_start_recording:
                self._on_start_recording()
    
    def _on_open_dir_click(self):
        """打开录音目录"""
        if self._on_open_recordings_dir:
            self._on_open_recordings_dir()
    
    def set_recording_state(self, is_recording: bool):
        """设置录音状态
        
        Args:
            is_recording: 是否正在录音
        """
        self._is_recording = is_recording
        self._update_recording_state()
        
        if is_recording:
            self._recording_start_time = time.time()
            self._start_timer()
        else:
            self._stop_timer()
            self._duration_label.configure(text="00:00")
    
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
    
    def _start_timer(self):
        """启动时长更新计时器"""
        self._update_duration()
    
    def _stop_timer(self):
        """停止时长更新计时器"""
        if self._timer_id:
            self.after_cancel(self._timer_id)
            self._timer_id = None
    
    def _update_duration(self):
        """更新录音时长显示"""
        if self._is_recording:
            duration = time.time() - self._recording_start_time
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            self._duration_label.configure(text=f"{minutes:02d}:{seconds:02d}")
            self._timer_id = self.after(1000, self._update_duration)
    
    def add_recording_file(self, file_path: str):
        """添加录音文件到列表
        
        Args:
            file_path: 录音文件路径
        """
        # 移除空列表提示
        if self._empty_label.winfo_exists():
            self._empty_label.destroy()
        
        # 创建文件项
        file_item = ctk.CTkFrame(self._file_list_frame, fg_color="transparent")
        file_item.pack(fill="x", pady=2)
        
        # 文件名
        filename = os.path.basename(file_path)
        file_label = ctk.CTkLabel(
            file_item, text=filename,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            anchor="w",
        )
        file_label.pack(side="left", fill="x", expand=True)
        
        # 文件大小
        try:
            size = os.path.getsize(file_path)
            if size < 1024:
                size_str = f"{size}B"
            elif size < 1024 * 1024:
                size_str = f"{size/1024:.1f}KB"
            else:
                size_str = f"{size/(1024*1024):.1f}MB"
        except:
            size_str = ""
        
        size_label = ctk.CTkLabel(
            file_item, text=size_str,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            text_color=Colors.TEXT_MUTED,
            width=60,
        )
        size_label.pack(side="right")
    
    def clear_file_list(self):
        """清空文件列表"""
        for widget in self._file_list_frame.winfo_children():
            if widget != self._empty_label:
                widget.destroy()
        
        # 重新显示空列表提示
        if not self._empty_label.winfo_exists():
            self._empty_label = ctk.CTkLabel(
                self._file_list_frame, text="暂无录音",
                font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
                text_color=Colors.TEXT_MUTED,
            )
            self._empty_label.pack(pady=Spacing.PAD_MD)
    
    def set_enabled(self, enabled: bool):
        """启用/禁用面板"""
        state = "normal" if enabled else "disabled"
        self._record_btn.configure(state=state)
        self._open_dir_btn.configure(state=state)
