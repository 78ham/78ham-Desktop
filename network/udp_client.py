"""
UDP 客户端

负责 UDP socket 管理、数据包收发、心跳维持。
不包含业务逻辑，只做网络 I/O。
"""
import socket
import select
import threading
import time
import logging
from typing import Optional, Callable

from core.protocol import NRLPacket, PacketType
from core.packet_factory import PacketFactory
from core.packet_parser import PacketParser
from config.settings import Settings
from .connection_manager import ConnectionManager, ConnectionState

logger = logging.getLogger(__name__)


class UdpClient:
    """UDP 网络客户端

    职责：
    - 管理 UDP socket 生命周期
    - 接收循环（select 轮询）
    - 心跳发送
    - 数据包发送
    - 自动重连
    """

    def __init__(self, settings: Settings, connection_mgr: ConnectionManager):
        self.settings = settings
        self.connection_mgr = connection_mgr
        self.packet_factory = PacketFactory()

        # Socket
        self._socket: Optional[socket.socket] = None
        self._socket_lock = threading.Lock()

        # 线程
        self._running = False
        self._receive_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None

        # 统计
        self.packets_sent = 0
        self.packets_received = 0

        # 回调：收到数据包时调用
        self.on_packet_received: Optional[Callable[[NRLPacket], None]] = None

    @property
    def is_running(self) -> bool:
        return self._running

    def connect(self) -> bool:
        """建立 UDP 连接并启动收发线程"""
        try:
            # 先停止旧线程
            self._stop_threads()

            # 关闭旧 socket
            self._close_socket()

            # 创建 UDP 套接字
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setblocking(False)

            try:
                self._socket.setsockopt(
                    socket.SOL_SOCKET, socket.SO_RCVBUF,
                    self.settings.network.buffer_size
                )
            except OSError:
                logger.warning("设置接收缓冲区失败，使用默认配置")

            # 发送注册包（心跳包作为初始注册）
            self._send_registration()

            # 标记连接成功
            self.connection_mgr.state = ConnectionState.CONNECTED
            self._running = True

            # 启动线程
            self._receive_thread = threading.Thread(
                target=self._receive_loop, daemon=True, name="udp-recv")
            self._receive_thread.start()

            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop, daemon=True, name="udp-hb")
            self._heartbeat_thread.start()

            logger.info(f"UDP 连接成功: {self.settings.server.host}:{self.settings.server.port}")
            return True

        except socket.error as e:
            logger.error(f"套接字错误: {e}")
            self.connection_mgr.state = ConnectionState.DISCONNECTED
            return False
        except Exception as e:
            logger.error(f"连接失败: {e}")
            self.connection_mgr.state = ConnectionState.DISCONNECTED
            return False

    def disconnect(self):
        """断开连接"""
        self._running = False
        self._stop_threads()
        self._close_socket()
        self.connection_mgr.reset()
        logger.info("UDP 已断开")

    def send_packet(self, packet: NRLPacket) -> bool:
        """发送数据包"""
        try:
            if not self._socket or not self.connection_mgr.is_connected:
                return False

            data = PacketFactory.encode_packet(packet)
            if not data:
                return False

            with self._socket_lock:
                self._socket.sendto(
                    data,
                    (self.settings.server.host, self.settings.server.port)
                )

            self.packets_sent += 1
            return True

        except BlockingIOError:
            logger.debug("发送缓冲区满，丢弃当前包")
            return False
        except socket.error as e:
            logger.error(f"发送失败: {e}")
            return False
        except Exception as e:
            logger.error(f"发送异常: {e}")
            return False

    def send_raw(self, data: bytes) -> bool:
        """发送原始字节数据"""
        try:
            if not self._socket:
                return False
            with self._socket_lock:
                self._socket.sendto(
                    data,
                    (self.settings.server.host, self.settings.server.port)
                )
            self.packets_sent += 1
            return True
        except (BlockingIOError, socket.error):
            return False

    # ==================== 内部方法 ====================

    def _send_registration(self):
        """发送注册包（心跳包作为初始注册）"""
        packet = self.packet_factory.create_heartbeat(
            self.settings.device.callsign,
            self.settings.device.ssid,
            self.settings.device.dmr_id,
            self.settings.device.model,
        )
        data = PacketFactory.encode_packet(packet)
        try:
            self._socket.sendto(
                data,
                (self.settings.server.host, self.settings.server.port)
            )
            logger.info(f"注册包已发送到 {self.settings.server.host}:{self.settings.server.port}")
        except BlockingIOError:
            logger.warning("注册包发送缓冲区满，将在心跳中重试")

    def _receive_loop(self):
        """接收数据循环（使用 select 避免忙等）"""
        consecutive_errors = 0
        max_errors = 5

        while self._running:
            try:
                if not self._socket:
                    time.sleep(0.1)
                    continue

                ready, _, _ = select.select([self._socket], [], [], 0.1)
                if not ready:
                    continue

                data, addr = self._socket.recvfrom(self.settings.network.buffer_size)

                if not data or len(data) < 48:
                    logger.warning(f"无效数据包（长度: {len(data)}）")
                    continue

                # 解析数据包
                packet = PacketParser.decode(data, addr)
                if not packet:
                    logger.debug(f"数据包解析失败: {addr}")
                    continue

                # 更新连接状态
                self.connection_mgr.mark_packet_received()
                self.packets_received += 1
                consecutive_errors = 0

                # 通知上层
                if self.on_packet_received:
                    self.on_packet_received(packet)

            except OSError as e:
                if not self._running:
                    break
                logger.error(f"接收错误: {e}")
                consecutive_errors += 1
            except Exception as e:
                if self._running:
                    logger.error(f"接收异常: {e}")
                    consecutive_errors += 1

            # 连续错误达到上限，尝试重连
            if consecutive_errors >= max_errors:
                logger.error(f"连续接收错误达到 {max_errors} 次，尝试重连")
                consecutive_errors = 0
                self._attempt_reconnect()

    def _heartbeat_loop(self):
        """心跳循环"""
        poll_interval = 0.5
        ticks_per_hb = max(1, int(self.settings.network.heartbeat_interval / poll_interval))
        tick = 0
        failures = 0
        max_failures = 3

        while self._running:
            try:
                if tick <= 0:
                    if self.connection_mgr.is_connected:
                        if not self._send_heartbeat():
                            failures += 1
                            if failures >= max_failures:
                                logger.warning("心跳失败次数过多，标记离线")
                                self.connection_mgr.state = ConnectionState.DISCONNECTED
                                failures = 0
                        else:
                            failures = 0
                    tick = ticks_per_hb

                tick -= 1
                time.sleep(poll_interval)

            except Exception as e:
                logger.error(f"心跳错误: {e}")
                failures += 1
                if failures >= max_failures:
                    self.connection_mgr.state = ConnectionState.DISCONNECTED
                    failures = 0
                tick = 0

    def _send_heartbeat(self) -> bool:
        """发送心跳包"""
        packet = self.packet_factory.create_heartbeat(
            self.settings.device.callsign,
            self.settings.device.ssid,
            self.settings.device.dmr_id,
            self.settings.device.model,
        )
        return self.send_packet(packet)

    def _attempt_reconnect(self):
        """尝试重连"""
        if not self.connection_mgr.begin_reconnect():
            return

        self._close_socket()
        time.sleep(self.connection_mgr.reconnect_delay)

        if not self._running:
            return

        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.setblocking(False)
            try:
                self._socket.setsockopt(
                    socket.SOL_SOCKET, socket.SO_RCVBUF,
                    self.settings.network.buffer_size
                )
            except OSError:
                pass

            self._send_registration()
            self.connection_mgr.reconnect_succeeded()
            logger.info(f"重连成功: {self.settings.server.host}:{self.settings.server.port}")

        except Exception as e:
            logger.error(f"重连失败: {e}")

    def _stop_threads(self):
        """停止所有后台线程"""
        self._running = False
        for t in (self._receive_thread, self._heartbeat_thread):
            if t and t.is_alive():
                t.join(timeout=1.0)
        self._receive_thread = None
        self._heartbeat_thread = None

    def _close_socket(self):
        """关闭 socket"""
        with self._socket_lock:
            if self._socket:
                try:
                    self._socket.close()
                except OSError:
                    pass
                self._socket = None
