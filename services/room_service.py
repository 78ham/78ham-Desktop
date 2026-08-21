"""
房间管理服务

负责房间列表获取、房间切换、房间状态维护。
"""
import time
import logging
import threading
from typing import Optional, Callable, List, Dict

from core.packet_factory import PacketFactory
from core.packet_parser import PacketParser
from config.settings import Settings
from network.udp_client import UdpClient

logger = logging.getLogger(__name__)


class RoomService:
    """房间管理服务

    职责：
    - 请求/缓存房间列表
    - 切换房间
    - 维护当前房间状态
    """

    def __init__(self, settings: Settings, udp_client: UdpClient):
        self.settings = settings
        self.udp_client = udp_client
        self._packet_factory = PacketFactory()
        self._lock = threading.Lock()

        # 房间状态
        self.current_group_id: int = 0
        self.current_group_name: str = "公共大厅"
        self.group_list: List[Dict] = []

        # 请求状态
        self._list_pending = False
        self._join_pending = False
        self._list_timeout = 3.0
        self._join_timeout = 3.0
        self._list_requested_at = 0.0
        self._join_requested_at = 0.0

        # 回调
        self.on_group_list: Optional[Callable[[List[Dict]], None]] = None
        self.on_group_changed: Optional[Callable[[int, str], None]] = None

    def request_group_list(self) -> bool:
        """请求服务器房间列表"""
        if not self.udp_client.connection_mgr.is_connected:
            logger.warning("未连接，无法请求房间列表")
            return False

        now = time.monotonic()
        with self._lock:
            if self._list_pending:
                if now - self._list_requested_at < self._list_timeout:
                    return False
                logger.warning("房间列表请求超时，重新发送")
            # 先占位，防止多个调用者同时发送重复请求。
            self._list_pending = True
            self._list_requested_at = now

        try:
            packet = self._packet_factory.create_group_list_request(
                self.settings.device.callsign,
                self.settings.device.ssid,
                self.settings.device.dmr_id,
                self.settings.device.model,
                password=self.settings.device.password,
            )
        except ValueError as e:
            with self._lock:
                self._list_pending = False
                self._list_requested_at = 0.0
            logger.warning(str(e))
            return False
        if self.udp_client.send_packet(packet):
            logger.info("已发送房间列表请求")
            return True
        with self._lock:
            self._list_pending = False
            self._list_requested_at = 0.0
        return False

    def join_group(self, group_id: int) -> bool:
        """加入/切换到指定房间"""
        if not self.udp_client.connection_mgr.is_connected:
            logger.warning("未连接，无法切换房间")
            return False

        now = time.monotonic()
        with self._lock:
            if self._join_pending:
                if now - self._join_requested_at < self._join_timeout:
                    return False
                logger.warning("房间切换请求超时，重新发送")
            self._join_pending = True
            self._join_requested_at = now

        try:
            packet = self._packet_factory.create_join_group(
                self.settings.device.callsign,
                self.settings.device.ssid,
                self.settings.device.dmr_id,
                group_id,
                self.settings.device.model,
                password=self.settings.device.password,
            )
        except ValueError as e:
            with self._lock:
                self._join_pending = False
                self._join_requested_at = 0.0
            logger.warning(str(e))
            return False
        if self.udp_client.send_packet(packet):
            logger.info(f"已发送加入房间请求: {group_id}")
            return True
        with self._lock:
            self._join_pending = False
            self._join_requested_at = 0.0
        return False

    def handle_group_response(self, data: bytes):
        """处理房间操作响应包

        由 TalkService 转发调用。
        """
        if not data or len(data) < 1:
            return

        subtype = data[0]

        with self._lock:
            if subtype == 2 and self._list_pending:
                # 房间列表响应
                self._list_pending = False
                self._list_requested_at = 0.0
                self.group_list = PacketParser.parse_group_list_response(data)
                logger.info(f"收到房间列表: 共 {len(self.group_list)} 个房间")
                callback = self.on_group_list
                group_list = list(self.group_list)
            elif subtype == 1 and self._join_pending:
                # 加入房间响应
                self._join_pending = False
                self._join_requested_at = 0.0
                group_id, group_name = PacketParser.parse_join_group_response(data)
                if group_name == "error":
                    logger.warning(f"加入房间 {group_id} 失败")
                    callback = self.on_group_changed
                    args = (-1, "error")
                else:
                    self.current_group_id = group_id
                    self.current_group_name = group_name
                    logger.info(f"已切换到房间: {group_id}-{group_name}")
                    callback = self.on_group_changed
                    args = (group_id, group_name)
            else:
                return

        # 在锁外调用回调（变量已在锁内捕获）
        if subtype == 2 and callback:
            callback(group_list)
        elif subtype == 1 and callback:
            callback(*args)
