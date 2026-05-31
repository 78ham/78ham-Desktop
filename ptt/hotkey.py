"""
全局热键 PTT 控制器

支持 Windows/Linux 全局热键注册，用于 PTT（按下说话）功能。
Windows: 使用 keyboard 库（需要管理员权限）
Linux: 使用 pynput 库（X11，不需要 root 权限）
"""
import sys
import os
import logging
import threading
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class PttController:
    """全局热键 PTT 控制器

    支持注册全局热键，按下时触发发射，松开时停止。

    Windows: 使用 keyboard 库（需要管理员权限或 hook 权限）
    Linux: 使用 pynput 库（X11 环境，不需要 root 权限）
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
        self._press_hook = None
        self._release_hook = None
        self._pynput_listener = None

    def _safe_callback(self, callback: Callable[[], None]):
        """在热键钩子线程中安全调用回调，隔离异常"""
        try:
            callback()
        except Exception as e:
            logger.error(f"PTT 回调错误: {e}")

    def register(self, key: str = "f5") -> bool:
        """注册全局热键

        Args:
            key: 热键名称（如 "f5", "ctrl+space", "scroll lock"）

        Returns:
            注册是否成功
        """
        if sys.platform == 'win32':
            return self._register_windows(key)
        elif sys.platform == 'linux':
            return self._register_linux(key)
        else:
            logger.warning(f"不支持的平台: {sys.platform}")
            return False

    def _register_windows(self, key: str) -> bool:
        """Windows 平台注册热键（使用 keyboard 库）"""
        try:
            import keyboard  # type: ignore

            # 先取消旧注册
            self.unregister()

            # 注册按下和松开事件，保存句柄
            self._press_hook = keyboard.on_press_key(key, lambda _: self._safe_callback(self._on_press), suppress=False)
            self._release_hook = keyboard.on_release_key(key, lambda _: self._safe_callback(self._on_release), suppress=False)

            self._registered = True
            self._hotkey = key
            logger.info(f"PTT 热键已注册 (Windows): {key}")
            return True

        except ImportError:
            logger.warning("keyboard 库未安装，无法注册全局热键 (pip install keyboard)")
            return False
        except PermissionError:
            logger.error("注册热键失败：需要管理员权限。请以管理员身份运行程序。")
            return False
        except Exception as e:
            logger.error(f"注册热键失败: {e}")
            return False

    def _register_linux(self, key: str) -> bool:
        """Linux 平台注册热键（使用 pynput 库）"""
        try:
            from pynput import keyboard as pynput_keyboard

            # 先取消旧注册
            self.unregister()

            target_key = self._map_key_to_pynput(key)
            if target_key is None:
                logger.error(f"不支持的热键: {key}")
                return False

            def on_press(k):
                if k == target_key:
                    self._safe_callback(self._on_press)

            def on_release(k):
                if k == target_key:
                    self._safe_callback(self._on_release)

            self._pynput_listener = pynput_keyboard.Listener(
                on_press=on_press,
                on_release=on_release
            )
            self._pynput_listener.daemon = True
            self._pynput_listener.start()

            self._registered = True
            self._hotkey = key
            logger.info(f"PTT 热键已注册 (Linux/pynput): {key}")
            return True

        except ImportError:
            logger.warning("pynput 库未安装，无法注册全局热键 (pip install pynput)")
            return False
        except Exception as e:
            logger.error(f"注册热键失败: {e}")
            return False

    @staticmethod
    def _map_key_to_pynput(key: str):
        """将按键名称映射到 pynput 按键对象"""
        from pynput.keyboard import Key, KeyCode

        key_lower = key.lower().strip()

        special_keys = {
            'f1': Key.f1, 'f2': Key.f2, 'f3': Key.f3, 'f4': Key.f4,
            'f5': Key.f5, 'f6': Key.f6, 'f7': Key.f7, 'f8': Key.f8,
            'f9': Key.f9, 'f10': Key.f10, 'f11': Key.f11, 'f12': Key.f12,
            'space': Key.space,
            'ctrl': Key.ctrl_l, 'ctrl_l': Key.ctrl_l, 'ctrl_r': Key.ctrl_r,
            'alt': Key.alt_l, 'alt_l': Key.alt_l, 'alt_r': Key.alt_r,
            'shift': Key.shift_l, 'shift_l': Key.shift_l, 'shift_r': Key.shift_r,
            'scroll lock': Key.scroll_lock,
            'caps lock': Key.caps_lock,
            'insert': Key.insert, 'delete': Key.delete,
            'home': Key.home, 'end': Key.end,
            'page up': Key.page_up, 'page down': Key.page_down,
        }

        if key_lower in special_keys:
            return special_keys[key_lower]

        # 单字符按键
        if len(key_lower) == 1:
            return KeyCode.from_char(key_lower)

        return None

    def unregister(self):
        """取消热键注册"""
        if not self._registered:
            return

        try:
            if sys.platform == 'win32':
                import keyboard  # type: ignore
                # 只取消本应用注册的钩子，不影响其他钩子
                if self._press_hook is not None:
                    keyboard.unhook(self._press_hook)
                    self._press_hook = None
                if self._release_hook is not None:
                    keyboard.unhook(self._release_hook)
                    self._release_hook = None
            elif sys.platform == 'linux':
                if self._pynput_listener is not None:
                    self._pynput_listener.stop()
                    self._pynput_listener = None

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
