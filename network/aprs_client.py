"""
APRS-IS 客户端

通过 TCP 连接 APRS-IS 服务器，上报位置信息。
参考小程序 pages/aprs/aprs.js 和 utils/tcp.js 实现。

APRS-IS 协议：
- 服务器: aprs.tv:14580
- 登录: "user CALL pass PASSCODE vers NRLLink-Desktop 1.0\n"
- 位置: "CALL-5>NRLPC,TCPIP*:!DDMM.HHN/DDDMM.HHE IA{alt} comment\n"
"""
import socket
import logging
import threading
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# 默认 APRS-IS 服务器
DEFAULT_APRS_SERVER = "aprs.tv"
DEFAULT_APRS_PORT = 14580
DEFAULT_SSID = 5  # APRS SSID


def generate_aprs_passcode(callsign: str) -> int:
    """生成 APRS-IS 验证码

    算法：对呼号（不含 SSID）逐对字符做 XOR
    """
    callsign = callsign.split('-')[0].upper()
    passcode = 29666
    i = 0
    while i < len(callsign):
        passcode ^= ord(callsign[i]) * 256
        if i + 1 < len(callsign):
            passcode ^= ord(callsign[i + 1])
        i += 2
    passcode &= 0x7FFF
    return passcode


def format_latitude(lat: float) -> str:
    """将十进制纬度转为 APRS 格式 DDMM.HHN/S"""
    direction = 'N' if lat >= 0 else 'S'
    abs_lat = abs(lat)
    degrees = int(abs_lat)
    minutes = (abs_lat - degrees) * 60
    return f"{degrees:02d}{minutes:05.2f}{direction}"


def format_longitude(lon: float) -> str:
    """将十进制经度转为 APRS 格式 DDDMM.HHE/W"""
    direction = 'E' if lon >= 0 else 'W'
    abs_lon = abs(lon)
    degrees = int(abs_lon)
    minutes = (abs_lon - degrees) * 60
    return f"{degrees:03d}{minutes:05.2f}{direction}"


class AprsClient:
    """APRS-IS TCP 客户端

    功能：
    - 连接 APRS-IS 服务器
    - 登录验证
    - 发送位置报告
    - 自动重连
    """

    def __init__(self, callsign: str, ssid: int = DEFAULT_SSID,
                 server: str = DEFAULT_APRS_SERVER,
                 port: int = DEFAULT_APRS_PORT,
                 passcode: Optional[int] = None):
        self.callsign = callsign.upper()
        self.ssid = ssid
        self.server = server
        self.port = port
        self.passcode = passcode or generate_aprs_passcode(self.callsign)

        self._socket: Optional[socket.socket] = None
        self._connected = False
        self._lock = threading.Lock()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        """连接到 APRS-IS 服务器"""
        with self._lock:
            if self._connected:
                return True
            try:
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._socket.settimeout(10)
                self._socket.connect((self.server, self.port))

                # 读取服务器欢迎消息
                welcome = self._socket.recv(512).decode('ascii', errors='ignore')
                logger.debug(f"APRS-IS: {welcome.strip()}")

                # 发送登录
                login_str = (
                    f"user {self.callsign} pass {self.passcode} "
                    f"vers NRLLink-Desktop 1.0\n"
                )
                self._socket.sendall(login_str.encode('ascii'))

                # 读取登录响应
                resp = self._socket.recv(512).decode('ascii', errors='ignore')
                logger.debug(f"APRS-IS login: {resp.strip()}")

                if 'verified' in resp.lower() or 'logresp' in resp.lower():
                    self._connected = True
                    logger.info(f"APRS-IS 已连接: {self.server}:{self.port}")
                    return True
                else:
                    logger.warning(f"APRS-IS 登录失败: {resp.strip()}")
                    self._close_socket()
                    return False

            except Exception as e:
                logger.error(f"APRS-IS 连接失败: {e}")
                self._close_socket()
                return False

    def disconnect(self):
        """断开连接"""
        with self._lock:
            self._close_socket()
            self._connected = False
            logger.info("APRS-IS 已断开")

    def send_position(self, lat: float, lon: float,
                      altitude: float = 0.0,
                      comment: str = "") -> bool:
        """发送位置报告

        Args:
            lat: 纬度（十进制）
            lon: 经度（十进制）
            altitude: 海拔（米，会转为英尺）
            comment: 附加注释

        Returns:
            是否发送成功
        """
        if not self._connected:
            if not self.connect():
                return False

        lat_str = format_latitude(lat)
        lon_str = format_longitude(lon)

        # 构建位置报告
        # 格式: CALL-SSID>NRLPC,TCPIP*:!DDMM.HHN/DDDMM.HHE comment
        source = f"{self.callsign}-{self.ssid}"
        info = f"!{lat_str}/{lon_str}"

        if altitude > 0:
            alt_feet = int(altitude * 3.28084)
            info += f" /A={alt_feet:06d}"

        if comment:
            info += f" {comment}"

        packet = f"{source}>NRLPC,TCPIP*:{info}\n"

        try:
            with self._lock:
                if self._socket:
                    self._socket.sendall(packet.encode('ascii'))
                    logger.info(f"APRS 位置已发送: {lat:.6f},{lon:.6f}")
                    return True
        except Exception as e:
            logger.error(f"APRS 发送失败: {e}")
            self._connected = False
            self._close_socket()

        return False

    def _close_socket(self):
        """关闭 socket"""
        try:
            if self._socket:
                self._socket.close()
        except Exception:
            pass
        self._socket = None
