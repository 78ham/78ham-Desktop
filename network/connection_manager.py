"""
连接状态机

管理 UDP 连接的生命周期和自动重连逻辑。
"""
import logging
import time
import threading
from enum import Enum
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


class ConnectionManager:
    """连接状态管理器

    职责：
    - 维护连接状态
    - 管理重连逻辑（最大重试次数、退避延迟）
    - 通过回调通知状态变更
    """

    def __init__(self, max_reconnect_attempts: int = 5,
                 reconnect_delay: float = 2.0):
        self._state = ConnectionState.DISCONNECTED
        self._lock = threading.Lock()
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self._reconnect_count = 0
        self._last_packet_time: float = 0.0

        # 回调
        self.on_state_changed: Optional[Callable[[ConnectionState], None]] = None

    @property
    def state(self) -> ConnectionState:
        with self._lock:
            return self._state

    @state.setter
    def state(self, new_state: ConnectionState):
        with self._lock:
            old_state = self._state
            self._state = new_state
        if old_state != new_state:
            logger.info(f"连接状态: {old_state.value} → {new_state.value}")
            if self.on_state_changed:
                try:
                    self.on_state_changed(new_state)
                except Exception as e:
                    logger.error(f"状态回调错误: {e}")

    @property
    def is_connected(self) -> bool:
        return self.state == ConnectionState.CONNECTED

    def mark_packet_received(self):
        """标记收到数据包（用于超时检测）"""
        with self._lock:
            self._last_packet_time = time.monotonic()
            self._reconnect_count = 0
            restore_connected = self._state != ConnectionState.CONNECTED
        if restore_connected:
            self.state = ConnectionState.CONNECTED

    def should_reconnect(self) -> bool:
        """是否应该尝试重连"""
        with self._lock:
            return self._reconnect_count < self.max_reconnect_attempts

    def begin_reconnect(self) -> bool:
        """开始一次重连尝试

        Returns:
            True 如果可以重连，False 如果已达到最大重试次数
        """
        with self._lock:
            if self._reconnect_count >= self.max_reconnect_attempts:
                can_reconnect = False
            else:
                self._reconnect_count += 1
                can_reconnect = True
            count = self._reconnect_count

        if not can_reconnect:
            logger.error(f"重连次数已达上限 ({self.max_reconnect_attempts})")
            self.state = ConnectionState.DISCONNECTED
            return False

        self.state = ConnectionState.RECONNECTING
        logger.info(f"重连尝试 {count}/{self.max_reconnect_attempts}")
        return True

    def reconnect_succeeded(self):
        """重连成功"""
        with self._lock:
            self._reconnect_count = 0
        self.state = ConnectionState.CONNECTED

    def reset(self):
        """重置状态"""
        with self._lock:
            self._reconnect_count = 0
            self._last_packet_time = 0.0
        self.state = ConnectionState.DISCONNECTED
