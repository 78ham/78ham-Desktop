"""
房间选择器组件

显示房间列表，支持切换房间。
"""
import customtkinter as ctk
from typing import Optional, Callable, List, Dict

from ui.theme import Fonts, Spacing


class RoomSelector(ctk.CTkFrame):
    """房间选择器

    功能：
    - 显示房间列表（下拉或列表）
    - 刷新房间列表
    - 切换房间
    - 显示当前房间
    """

    def __init__(self, master,
                 on_join_room: Optional[Callable[[int], None]] = None,
                 on_refresh: Optional[Callable[[], None]] = None,
                 **kwargs):
        super().__init__(master, **kwargs)

        self._on_join_room = on_join_room
        self._on_refresh = on_refresh
        self._rooms: List[Dict] = []
        self._current_room_id: Optional[int] = None

        self._build_ui()

    def _build_ui(self):
        """构建 UI"""
        # 标题行
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=Spacing.PAD_XS, pady=(Spacing.PAD_XS, 0))

        ctk.CTkLabel(
            header, text="房间",
            font=(Fonts.FAMILY_UI, Fonts.SIZE_BODY, "bold"),
        ).pack(side="left")

        self._refresh_btn = ctk.CTkButton(
            header, text="刷新", width=50,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_SMALL),
            command=self._do_refresh,
        )
        self._refresh_btn.pack(side="right")

        # 房间下拉选择
        self._room_var = ctk.StringVar(value="-- 选择房间 --")
        self._room_menu = ctk.CTkOptionMenu(
            self,
            variable=self._room_var,
            values=["-- 无房间 --"],
            font=(Fonts.FAMILY_UI, Fonts.SIZE_BODY),
            command=self._on_room_selected,
        )
        self._room_menu.pack(fill="x", padx=Spacing.PAD_XS, pady=Spacing.PAD_XS)

        # 加入按钮
        self._join_btn = ctk.CTkButton(
            self, text="加入房间", width=80,
            font=(Fonts.FAMILY_UI, Fonts.SIZE_BODY),
            command=self._do_join,
        )
        self._join_btn.pack(padx=Spacing.PAD_XS, pady=(0, Spacing.PAD_XS))

    # ==================== 事件处理 ====================

    def _do_refresh(self):
        """刷新房间列表"""
        if self._on_refresh:
            self._on_refresh()

    def _on_room_selected(self, choice: str):
        """下拉选择变化"""
        pass  # 选择后点加入按钮才真正切换

    def _do_join(self):
        """加入选中的房间"""
        selected = self._room_var.get()
        if not selected or selected.startswith("--"):
            return

        # 从显示文本中提取房间 ID
        for room in self._rooms:
            display = f"{room['id']} - {room.get('name', '')}"
            if display == selected:
                if self._on_join_room:
                    self._on_join_room(room['id'])
                return

    # ==================== 公开接口 ====================

    def set_room_list(self, rooms: List[Dict]):
        """更新房间列表

        Args:
            rooms: [{"id": int, "name": str, "online": int}, ...]
        """
        self._rooms = rooms
        if not rooms:
            self._room_menu.configure(values=["-- 无房间 --"])
            self._room_var.set("-- 无房间 --")
            return

        values = []
        for r in rooms:
            display = f"{r['id']} - {r.get('name', '')}"
            if r.get('online'):
                display += f" ({r['online']}人)"
            values.append(display)

        self._room_menu.configure(values=values)

        # 保持当前选择
        if self._current_room_id:
            for r in rooms:
                if r['id'] == self._current_room_id:
                    self._room_var.set(f"{r['id']} - {r.get('name', '')}")
                    return

        self._room_var.set(values[0] if values else "-- 选择房间 --")

    def set_current_room(self, room_id: int, room_name: str = ""):
        """设置当前房间"""
        self._current_room_id = room_id
        if room_name:
            self._room_var.set(f"{room_id} - {room_name}")

    def set_enabled(self, enabled: bool):
        """启用/禁用"""
        state = "normal" if enabled else "disabled"
        self._refresh_btn.configure(state=state)
        self._join_btn.configure(state=state)
        self._room_menu.configure(state=state)
