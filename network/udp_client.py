"""
UDP 客户端

负责 UDP socket 管理、数据包收发、心跳维持。
不包含业务逻辑，只做网络 I/O。
"""
import socket
import select
import threading
import logging
from typing import Optional, Callable

from core.protocol import NRLPacket
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

    # 配置常量
    MAX_BUFFER_SIZE = 65535
    MAX_CONSECUTIVE_ERRORS = 5
    MAX_HEARTBEAT_FAILURES = 3
    THREAD_JOIN_TIMEOUT = 3.0

    def __init__(self, settings: Settings, connection_mgr: ConnectionManager):
        self.settings = settings
        self.connection_mgr = connection_mgr
        self.packet_factory = PacketFactory()

        # Socket
        self._socket: Optional[socket.socket] = None
        self._socket_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._reconnect_lock = threading.Lock()

        # 线程
        self._running_event = threading.Event()
        self._stop_event = threading.Event()
        self._receive_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None

        # 统计（线程安全）
        self._stats_lock = threading.Lock()
        self.packets_sent = 0
        self.packets_received = 0

        # 回调：收到数据包时调用
        self.on_packet_received: Optional[Callable[[NRLPacket], None]] = None

    @property
    def is_running(self) -> bool:
        return self._running_event.is_set()

    def connect(self) -> bool:
        """建立 UDP 连接并启动收发线程"""
        with self._lifecycle_lock:
            return self._connect_locked()

    def _connect_locked(self) -> bool:
        try:
            # 先停止旧线程
            self._stop_threads()

            # 关闭旧 socket
            self._close_socket()
            self.connection_mgr.state = ConnectionState.CONNECTING

            # 创建 UDP 套接字
            self._replace_socket(self._create_socket())

            # 发送注册包（心跳包作为初始注册）
            if not self._send_registration():
                raise OSError("注册包发送失败")

            # 标记连接成功
            self.connection_mgr.state = ConnectionState.CONNECTED
            self._stop_event.clear()
            self._running_event.set()

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
            self._close_socket()
            self.connection_mgr.state = ConnectionState.DISCONNECTED
            return False
        except Exception as e:
            logger.error(f"连接失败: {e}")
            self._close_socket()
            self.connection_mgr.state = ConnectionState.DISCONNECTED
            return False

    def disconnect(self):
        """断开连接"""
        # Signal first so a reconnect wait wakes before lifecycle cleanup begins.
        self._running_event.clear()
        self._stop_event.set()
        with self._lifecycle_lock:
            self._disconnect_locked()

    def _disconnect_locked(self):
        # 先关闭 socket，立即唤醒阻塞中的 select/recv。
        self._close_socket()
        self._stop_threads()
        self.connection_mgr.reset()
        logger.info("UDP 已断开")

    def send_packet(self, packet: NRLPacket) -> bool:
        """发送数据包"""
        try:
            if not self.connection_mgr.is_connected:
                return False

            data = PacketFactory.encode_packet(packet)
            if not data:
                return False

            self._send_bytes(data)

            with self._stats_lock:
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
        if not data:
            return False
        try:
            self._send_bytes(data)
            with self._stats_lock:
                self.packets_sent += 1
            return True
        except (BlockingIOError, socket.error):
            return False

    def get_stats(self) -> dict:
        """Return a consistent snapshot of packet counters."""
        with self._stats_lock:
            return {
                'packets_sent': self.packets_sent,
                'packets_received': self.packets_received,
            }

    # ==================== 内部方法 ====================

    def _send_registration(self) -> bool:
        """发送注册包（心跳包作为初始注册）"""
        packet = self.packet_factory.create_heartbeat(
            self.settings.device.callsign,
            self.settings.device.ssid,
            self.settings.device.dmr_id,
            self.settings.device.model,
            password=self.settings.get_current_password(),
        )
        data = PacketFactory.encode_packet(packet)
        try:
            self._send_bytes(data)
            logger.info(f"注册包已发送到 {self.settings.server.host}:{self.settings.server.port}")
            return True
        except BlockingIOError:
            logger.warning("注册包发送缓冲区满，将在心跳中重试")
            return False
        except OSError as e:
            logger.warning(f"注册包发送失败: {e}")
            return False

    def _receive_loop(self):
        """接收数据循环（使用 select 避免忙等）"""
        consecutive_errors = 0

        while self.is_running:
            try:
                with self._socket_lock:
                    current_socket = self._socket
                if current_socket is None:
                    self._stop_event.wait(0.05)
                    continue

                ready, _, _ = select.select([current_socket], [], [], 0.25)
                if not ready:
                    continue

                data, addr = current_socket.recvfrom(self.MAX_BUFFER_SIZE)

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
                with self._stats_lock:
                    self.packets_received += 1
                consecutive_errors = 0

                # 通知上层
                if self.on_packet_received:
                    try:
                        self.on_packet_received(packet)
                    except Exception:
                        logger.exception("数据包回调异常")

            except OSError as e:
                if not self.is_running:
                    break
                logger.error(f"接收错误: {e}")
                consecutive_errors += 1
            except Exception as e:
                if self.is_running:
                    logger.error(f"接收异常: {e}")
                    consecutive_errors += 1

            # 连续错误达到上限，尝试重连
            if consecutive_errors >= self.MAX_CONSECUTIVE_ERRORS:
                logger.error(f"连续接收错误达到 {self.MAX_CONSECUTIVE_ERRORS} 次，尝试重连")
                consecutive_errors = 0
                self._attempt_reconnect()

    def _heartbeat_loop(self):
        """心跳循环"""
        failures = 0

        while self.is_running:
            try:
                if self.connection_mgr.is_connected:
                    if not self._send_heartbeat():
                        failures += 1
                        if failures >= self.MAX_HEARTBEAT_FAILURES:
                            logger.warning("心跳失败次数过多，尝试重连")
                            failures = 0
                            self._attempt_reconnect()
                    else:
                        failures = 0
                elif self.connection_mgr.should_reconnect():
                    self._attempt_reconnect()

                interval = max(0.1, float(self.settings.network.heartbeat_interval))
                if self._stop_event.wait(interval):
                    break

            except Exception as e:
                logger.error(f"心跳错误: {e}")
                failures += 1
                if failures >= self.MAX_HEARTBEAT_FAILURES:
                    failures = 0
                    self._attempt_reconnect()

    def _send_heartbeat(self) -> bool:
        """发送心跳包"""
        packet = self.packet_factory.create_heartbeat(
            self.settings.device.callsign,
            self.settings.device.ssid,
            self.settings.device.dmr_id,
            self.settings.device.model,
            password=self.settings.get_current_password(),
        )
        return self.send_packet(packet)

    def _attempt_reconnect(self):
        """尝试重连"""
        if not self._reconnect_lock.acquire(blocking=False):
            return
        try:
            if not self.connection_mgr.begin_reconnect():
                return

            self._close_socket()
            if self._stop_event.wait(self.connection_mgr.reconnect_delay):
                return
            if not self.is_running:
                return

            new_socket = self._create_socket()
            with self._lifecycle_lock:
                if not self.is_running or self._stop_event.is_set():
                    new_socket.close()
                    return
                self._replace_socket(new_socket)
                if not self._send_registration():
                    raise OSError("重连注册包发送失败")
                self.connection_mgr.reconnect_succeeded()
            logger.info(f"重连成功: {self.settings.server.host}:{self.settings.server.port}")

        except Exception as e:
            logger.error(f"重连失败: {e}")
            self._close_socket()
            self.connection_mgr.state = ConnectionState.DISCONNECTED
        finally:
            self._reconnect_lock.release()

    def _stop_threads(self):
        """停止所有后台线程"""
        self._running_event.clear()
        self._stop_event.set()
        current = threading.current_thread()
        for t in (self._receive_thread, self._heartbeat_thread):
            if t and t is not current and t.is_alive():
                t.join(timeout=self.THREAD_JOIN_TIMEOUT)
        self._receive_thread = None
        self._heartbeat_thread = None

    def _create_socket(self) -> socket.socket:
        """Create and configure a non-blocking UDP socket."""
        new_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            new_socket.setblocking(False)
            buf_size = min(self.settings.network.buffer_size, self.MAX_BUFFER_SIZE)
            try:
                new_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buf_size)
            except OSError:
                logger.warning("设置接收缓冲区失败，使用默认配置")
            return new_socket
        except Exception:
            new_socket.close()
            raise

    def _replace_socket(self, new_socket: socket.socket):
        """Swap the shared socket while excluding concurrent send operations."""
        with self._socket_lock:
            old_socket = self._socket
            self._socket = new_socket
            if old_socket:
                try:
                    old_socket.close()
                except OSError:
                    pass

    def _send_bytes(self, data: bytes):
        with self._socket_lock:
            if self._socket is None:
                raise OSError("UDP socket 未连接")
            self._socket.sendto(
                data,
                (self.settings.server.host, self.settings.server.port),
            )

    def _close_socket(self):
        """关闭 socket"""
        with self._socket_lock:
            if self._socket:
                try:
                    self._socket.close()
                except OSError:
                    pass
                self._socket = None
