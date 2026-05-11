"""
APRS 位置上报服务

整合 LocationService 和 AprsClient，实现定时 APRS 位置上报。
参考小程序 pages/aprs/aprs.js 的 60 秒上报间隔。
"""
import logging
import threading
import time
from typing import Optional

from config.settings import Settings
from network.aprs_client import AprsClient
from services.location_service import LocationService

logger = logging.getLogger(__name__)

# 默认上报间隔（秒）
DEFAULT_REPORT_INTERVAL = 60


class AprsService:
    """APRS 位置上报服务

    功能：
    - 连接 APRS-IS 服务器
    - 定时获取位置并上报
    - 支持手动触发上报
    """

    def __init__(self, settings: Settings,
                 location_service: LocationService):
        self._settings = settings
        self._location = location_service
        self._client: Optional[AprsClient] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval = DEFAULT_REPORT_INTERVAL

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected if self._client else False

    def start(self, server: str = "aprs.tv", port: int = 14580,
              interval: int = DEFAULT_REPORT_INTERVAL) -> bool:
        """启动 APRS 上报服务

        Args:
            server: APRS-IS 服务器地址
            port: 端口
            interval: 上报间隔（秒）

        Returns:
            是否启动成功
        """
        if self._running:
            return True

        self._interval = interval
        callsign = self._settings.device.callsign

        self._client = AprsClient(
            callsign=callsign,
            ssid=5,
            server=server,
            port=port,
        )

        if not self._client.connect():
            logger.error("APRS-IS 连接失败")
            return False

        self._running = True
        self._thread = threading.Thread(
            target=self._report_loop, daemon=True, name="aprs-report")
        self._thread.start()
        logger.info(f"APRS 上报服务已启动 (间隔 {interval}s)")
        return True

    def stop(self):
        """停止 APRS 上报服务"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if self._client:
            self._client.disconnect()
            self._client = None
        logger.info("APRS 上报服务已停止")

    def report_now(self) -> bool:
        """立即上报一次位置"""
        return self._do_report()

    def _report_loop(self):
        """定时上报循环"""
        # 立即上报一次
        self._do_report()

        while self._running:
            # 分段 sleep 以便快速退出
            for _ in range(int(self._interval / 0.5)):
                if not self._running:
                    return
                time.sleep(0.5)

            if self._running:
                self._do_report()

    def _do_report(self) -> bool:
        """执行一次位置上报"""
        try:
            lat, lng, source = self._location.get_location()
            if lat == 0.0 and lng == 0.0:
                logger.debug("APRS 上报跳过：无可用位置")
                return False

            server = self._settings.get_current_server()
            comment = f"@udp://{server.host}:{server.port},NRLLink-Desktop"

            if self._client and self._client.send_position(lat, lng, comment=comment):
                logger.info(f"APRS 位置已上报: {lat:.6f},{lng:.6f} (来源: {source})")
                return True
            return False

        except Exception as e:
            logger.error(f"APRS 上报异常: {e}")
            return False
