"""
聊天面板组件

右侧面板分为两部分：
- 通联日志（上方 2/3）：文本消息、位置消息等通联记录
- 软件日志（下方 1/3）：系统通知、连接状态等软件事件
"""
import time
import customtkinter as ctk
from typing import Optional, Callable

from ui.theme import Colors, Fonts, Spacing


class ChatPanel(ctk.CTkFrame):
    """聊天/消息面板

    布局：
    +---------------------------+
    | 通联日志 (2/3)            |
    | [文本/位置/语音消息]      |
    +---------------------------+
    | 软件日志 (1/3)            |
    | [系统通知/连接状态]       |
    +---------------------------+
    | [输入框] [发送] [位置]    |
    +---------------------------+
    """

    def __init__(self, master,
                 on_send_text: Optional[Callable[[str], None]] = None,
                 on_send_location: Optional[Callable[[], None]] = None,
                 **kwargs):
        super().__init__(master, **kwargs)

        self._on_send_text = on_send_text
        self._on_send_location = on_send_location

        self._build_ui()

    def _build_ui(self):
        """构建 UI"""
        # 使用 grid 实现 2:1 比例
        self.grid_rowconfigure(0, weight=2)  # 通联日志区
        self.grid_rowconfigure(1, weight=1)  # 软件日志区
        self.grid_rowconfigure(2, weight=0)  # 输入区
        self.grid_columnconfigure(0, weight=1)

        # ---- 通联日志区 ----
        comm_frame = ctk.CTkFrame(self)
        comm_frame.grid(row=0, column=0, sticky="nsew",
                        padx=Spacing.PAD_XS, pady=(Spacing.PAD_XS, 0))
        comm_frame.grid_rowconfigure(1, weight=1)
        comm_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            comm_frame, text="通联日志",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL, "bold"),
            text_color=Colors.TEXT_SECONDARY,
        ).grid(row=0, column=0, sticky="w", padx=4, pady=(2, 0))

        self._comm_log = ctk.CTkTextbox(
            comm_frame,
            font=(Fonts.FAMILY_MONO, Fonts.SIZE_BODY),
            state="disabled",
            wrap="word",
        )
        self._comm_log.grid(row=1, column=0, sticky="nsew",
                            padx=Spacing.PAD_XS, pady=(0, Spacing.PAD_XS))

        # ---- 软件日志区 ----
        sys_frame = ctk.CTkFrame(self)
        sys_frame.grid(row=1, column=0, sticky="nsew",
                       padx=Spacing.PAD_XS, pady=Spacing.PAD_XS)
        sys_frame.grid_rowconfigure(1, weight=1)
        sys_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            sys_frame, text="软件日志",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL, "bold"),
            text_color=Colors.TEXT_SECONDARY,
        ).grid(row=0, column=0, sticky="w", padx=4, pady=(2, 0))

        self._sys_log = ctk.CTkTextbox(
            sys_frame,
            font=(Fonts.FAMILY_MONO, Fonts.SIZE_BODY),
            state="disabled",
            wrap="word",
        )
        self._sys_log.grid(row=1, column=0, sticky="nsew",
                           padx=Spacing.PAD_XS, pady=(0, Spacing.PAD_XS))

        # ---- 输入区域 ----
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.grid(row=2, column=0, sticky="ew",
                         padx=Spacing.PAD_XS, pady=Spacing.PAD_XS)

        self._input_entry = ctk.CTkEntry(
            input_frame,
            placeholder_text="输入消息...",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_BODY),
        )
        self._input_entry.pack(side="left", fill="x", expand=True,
                               padx=(0, Spacing.PAD_SM))
        self._input_entry.bind("<Return>", self._on_enter_pressed)

        self._send_btn = ctk.CTkButton(
            input_frame, text="发送", width=60,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_BODY),
            command=self._do_send_text,
        )
        self._send_btn.pack(side="left", padx=(0, Spacing.PAD_XS))

        self._loc_btn = ctk.CTkButton(
            input_frame, text="位置", width=50,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            fg_color="#27ae60",
            hover_color="#2ecc71",
            command=self._do_send_location,
        )
        self._loc_btn.pack(side="left")

    # ==================== 事件处理 ====================

    def _on_enter_pressed(self, event=None):
        """回车发送"""
        self._do_send_text()

    def _do_send_text(self):
        """发送文本"""
        text = self._input_entry.get().strip()
        if not text:
            return
        self._input_entry.delete(0, "end")
        if self._on_send_text:
            self._on_send_text(text)

    def _do_send_location(self):
        """发送位置"""
        if self._on_send_location:
            self._on_send_location()

    # ==================== 通联日志 ====================

    @staticmethod
    def _format_sender(from_call: str, ssid: int = 0,
                       dmr_id: str = "", is_local: bool = False) -> str:
        """格式化发送者信息: 呼号-SSID [DMRID] (我)"""
        parts = []
        if from_call:
            if ssid:
                parts.append(f"{from_call}-{ssid}")
            else:
                parts.append(from_call)
        if dmr_id:
            parts.append(f"[{dmr_id}]")
        if is_local:
            parts.append("(我)")
        return " ".join(parts) if parts else "未知"

    def add_comm_message(self, from_call: str, content: str,
                         msg_type: str = "text",
                         ssid: int = 0, dmr_id: str = "",
                         is_local: bool = False):
        """添加通联日志消息

        Args:
            from_call: 发送者呼号
            content: 消息内容
            msg_type: "text" / "location"
            ssid: 设备 SSID
            dmr_id: 设备 DMRID
            is_local: 是否为本机发送
        """
        timestamp = time.strftime("%H:%M:%S")
        sender = self._format_sender(from_call, ssid, dmr_id, is_local)

        if msg_type == "location":
            line = f"[{timestamp}] {sender}  📍 {content}\n"
        else:
            line = f"[{timestamp}] {sender}  {content}\n"

        self._append_text(self._comm_log, line)

    # ==================== 软件日志 ====================

    def add_system_message(self, content: str):
        """添加软件日志消息"""
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {content}\n"
        self._append_text(self._sys_log, line)

    # ==================== 公共方法 ====================

    @staticmethod
    def _append_text(textbox: ctk.CTkTextbox, line: str):
        """向文本框追加一行并滚动到底部"""
        textbox.configure(state="normal")
        textbox.insert("end", line)
        textbox.configure(state="disabled")
        textbox.see("end")

    def clear(self):
        """清空所有日志"""
        for tb in (self._comm_log, self._sys_log):
            tb.configure(state="normal")
            tb.delete("1.0", "end")
            tb.configure(state="disabled")

    def set_enabled(self, enabled: bool):
        """启用/禁用输入"""
        state = "normal" if enabled else "disabled"
        self._input_entry.configure(state=state)
        self._send_btn.configure(state=state)
        self._loc_btn.configure(state=state)
