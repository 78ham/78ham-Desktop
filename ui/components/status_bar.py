"""
状态栏组件

显示连接状态、呼号、服务器信息、房间、编码格式等。
底部固定的信息条。
"""
import customtkinter as ctk
from typing import Optional

from ui.theme import Colors, Fonts, Spacing


class StatusBar(ctk.CTkFrame):
    """底部状态栏

    显示内容：
    - 连接状态指示灯
    - 呼号-SSID
    - 当前服务器
    - 当前房间
    - 编码格式
    - 在线时长
    """

    def __init__(self, master, **kwargs):
        super().__init__(master, height=30, **kwargs)
        self.pack_propagate(False)

        self._build_ui()
        self.reset()

    def _build_ui(self):
        """构建 UI"""
        # 状态指示灯
        self._indicator = ctk.CTkLabel(
            self, text="●", width=20,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_BODY),
            text_color=Colors.DISCONNECTED,
        )
        self._indicator.pack(side="left", padx=(Spacing.PAD_SM, 2))

        # 连接状态文字
        self._status_label = ctk.CTkLabel(
            self, text="未连接",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
        )
        self._status_label.pack(side="left", padx=(0, Spacing.PAD_MD))

        # 分隔符
        self._add_separator()

        # 呼号
        self._callsign_label = ctk.CTkLabel(
            self, text="---",
            font=(Fonts.FAMILY_MONO, Fonts.SIZE_SMALL),
        )
        self._callsign_label.pack(side="left", padx=Spacing.PAD_SM)

        self._add_separator()

        # 服务器
        self._server_label = ctk.CTkLabel(
            self, text="",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
        )
        self._server_label.pack(side="left", padx=Spacing.PAD_SM)

        self._add_separator()

        # 房间
        self._room_label = ctk.CTkLabel(
            self, text="",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
        )
        self._room_label.pack(side="left", padx=Spacing.PAD_SM)

        # 右侧：编码格式
        self._codec_label = ctk.CTkLabel(
            self, text="",
            font=(Fonts.FAMILY_MONO, Fonts.SIZE_SMALL),
        )
        self._codec_label.pack(side="right", padx=Spacing.PAD_SM)

    def _add_separator(self):
        """添加竖线分隔符"""
        sep = ctk.CTkLabel(self, text="|", width=10,
                           font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
                           text_color=Colors.TEXT_MUTED)
        sep.pack(side="left")

    # ==================== 公开接口 ====================

    def reset(self):
        """重置为未连接状态"""
        self.set_connection_state("disconnected")
        self._server_label.configure(text="")
        self._room_label.configure(text="")
        self._codec_label.configure(text="")

    def set_connection_state(self, state: str):
        """设置连接状态

        Args:
            state: "connected" / "connecting" / "disconnected" / "reconnecting"
        """
        color_map = {
            "connected": Colors.CONNECTED,
            "connecting": Colors.CONNECTING,
            "disconnected": Colors.DISCONNECTED,
            "reconnecting": Colors.CONNECTING,
        }
        text_map = {
            "connected": "已连接",
            "connecting": "连接中...",
            "disconnected": "未连接",
            "reconnecting": "重连中...",
        }
        color = color_map.get(state, Colors.DISCONNECTED)
        text = text_map.get(state, "未知")
        self._indicator.configure(text_color=color)
        self._status_label.configure(text=text)

    def set_callsign(self, callsign: str, ssid: int = 0):
        """设置呼号显示"""
        display = f"{callsign}-{ssid}" if ssid else callsign
        self._callsign_label.configure(text=display)

    def set_server(self, name: str):
        """设置当前服务器名称"""
        self._server_label.configure(text=name)

    def set_room(self, room_name: str):
        """设置当前房间"""
        self._room_label.configure(text=f"房间: {room_name}" if room_name else "")

    def set_codec(self, codec: str):
        """设置编码格式"""
        self._codec_label.configure(text=codec.upper() if codec else "")
