"""
全局热键 PTT 控制器

支持 Windows 全局热键注册，用于 PTT（按下说话）功能。
参考安卓 PttController 的设计模式。
"""
import os
import logging
import threading
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class PttController:
    """全局热键 PTT 控制器

    支持注册全局热键，按下时触发发射，松开时停止。

    Windows: 使用 keyboard 库（需要管理员权限或 hook 权限）
    Linux/macOS: 预留接口，后续实现
    """

    def __init__(self, on_press: Callable[[], None], on_release: Callable[[], None]):
        """
        Args:
            on_press: PTT 按下回调
            on_release: PTT 松开回调
        """
        self._on_press = on_press
        self._on_release = on_release
        self._registered = False
        self._hotkey: Optional[str] = None
        self._hook = None

    def register(self, key: str = "f5") -> bool:
        """注册全局热键

        Args:
            key: 热键名称（如 "f5", "ctrl+space", "scroll lock"）

        Returns:
            注册是否成功
        """
        if os.name != 'nt':
            logger.warning("全局热键目前仅支持 Windows")
            return False

        try:
            import keyboard  # type: ignore

            # 先取消旧注册
            self.unregister()

            # 注册按下和松开事件
            keyboard.on_press_key(key, lambda _: self._on_press(), suppress=False)
            keyboard.on_release_key(key, lambda _: self._on_release(), suppress=False)

            self._registered = True
            self._hotkey = key
            logger.info(f"PTT 热键已注册: {key}")
            return True

        except ImportError:
            logger.warning("keyboard 库未安装，无法注册全局热键 (pip install keyboard)")
            return False
        except Exception as e:
            logger.error(f"注册热键失败: {e}")
            return False

    def unregister(self):
        """取消热键注册"""
        if not self._registered:
            return

        try:
            import keyboard  # type: ignore
            if self._hotkey:
                keyboard.unhook_all()
            self._registered = False
            self._hotkey = None
            logger.info("PTT 热键已取消注册")
        except Exception as e:
            logger.error(f"取消热键注册失败: {e}")

    @property
    def is_registered(self) -> bool:
        return self._registered

    @property
    def current_key(self) -> Optional[str]:
        return self._hotkey
