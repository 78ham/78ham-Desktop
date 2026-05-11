"""
聊天面板组件

显示文本消息、系统通知、位置消息等。
支持发送文本和位置。
"""
import time
import customtkinter as ctk
from typing import Optional, Callable, List

from ui.theme import Colors, Fonts, Spacing, Sizes


class ChatPanel(ctk.CTkFrame):
    """聊天/消息面板

    功能：
    - 显示接收到的文本消息
    - 显示系统通知（连接/断开/房间切换等）
    - 发送文本消息输入框
    - 发送位置按钮
    """

    def __init__(self, master,
                 on_send_text: Optional[Callable[[str], None]] = None,
                 on_send_location: Optional[Callable[[], None]] = None,
                 **kwargs):
        super().__init__(master, **kwargs)

        self._on_send_text = on_send_text
        self._on_send_location = on_send_location
        self._messages: List[dict] = []

        self._build_ui()

    def _build_ui(self):
        """构建 UI"""
        # 消息显示区
        self._textbox = ctk.CTkTextbox(
            self,
            font=(Fonts.FAMILY_MONO, Fonts.SIZE_BODY),
            state="disabled",
            wrap="word",
        )
        self._textbox.pack(fill="both", expand=True, padx=Spacing.PAD_XS,
                           pady=(Spacing.PAD_XS, 0))

        # 输入区域
        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(fill="x", padx=Spacing.PAD_XS, pady=Spacing.PAD_XS)

        # 文本输入框
        self._input_entry = ctk.CTkEntry(
            input_frame,
            placeholder_text="输入消息...",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_BODY),
        )
        self._input_entry.pack(side="left", fill="x", expand=True,
                               padx=(0, Spacing.PAD_SM))
        self._input_entry.bind("<Return>", self._on_enter_pressed)

        # 发送按钮
        self._send_btn = ctk.CTkButton(
            input_frame, text="发送", width=60,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_BODY),
            command=self._do_send_text,
        )
        self._send_btn.pack(side="left", padx=(0, Spacing.PAD_XS))

        # 位置按钮
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

    # ==================== 公开接口 ====================

    def add_message(self, from_call: str, content: str,
                    msg_type: str = "text"):
        """添加一条消息

        Args:
            from_call: 发送者呼号
            content: 消息内容
            msg_type: "text" / "location" / "system"
        """
        timestamp = time.strftime("%H:%M:%S")
        self._messages.append({
            "from": from_call,
            "content": content,
            "type": msg_type,
            "time": timestamp,
        })

        # 限制消息数量
        if len(self._messages) > Sizes.CHAT_MAX_MESSAGES:
            self._messages = self._messages[-Sizes.CHAT_MAX_MESSAGES:]

        # 显示
        self._textbox.configure(state="normal")
        if msg_type == "system":
            line = f"[{timestamp}] *** {content}\n"
        elif msg_type == "location":
            line = f"[{timestamp}] [{from_call}] 📍 {content}\n"
        else:
            line = f"[{timestamp}] [{from_call}] {content}\n"
        self._textbox.insert("end", line)
        self._textbox.configure(state="disabled")
        self._textbox.see("end")

    def add_system_message(self, content: str):
        """添加系统消息"""
        self.add_message("系统", content, msg_type="system")

    def clear(self):
        """清空消息"""
        self._messages.clear()
        self._textbox.configure(state="normal")
        self._textbox.delete("1.0", "end")
        self._textbox.configure(state="disabled")

    def set_enabled(self, enabled: bool):
        """启用/禁用输入"""
        state = "normal" if enabled else "disabled"
        self._input_entry.configure(state=state)
        self._send_btn.configure(state=state)
        self._loc_btn.configure(state=state)
