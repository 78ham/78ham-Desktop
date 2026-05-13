"""
位置服务

多级定位（Windows GPS → IP 地理定位 → 默认配置）和自动上报。
"""
import os
import time
import logging
import threading
from typing import Optional, Callable, Tuple

from config.settings import Settings

logger = logging.getLogger(__name__)


class LocationService:
    """位置服务

    职责：
    - 获取当前位置（多级回退）
    - 自动定时上报位置
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._running = threading.Event()
        self._report_thread: Optional[threading.Thread] = None

        # 回调：发送位置消息
        self.on_send_location: Optional[Callable[[float, float], bool]] = None

    def get_location(self) -> Tuple[float, float, str]:
        """获取当前位置

        返回: (lat, lng, source)
        source: "gps" / "ip" / "default" / "unavailable"
        """
        # 1. 尝试 Windows Location API
        result = self._try_winrt_gps()
        if result:
            return (result[0], result[1], "gps")

        # 2. 尝试 IP 地理定位
        result = self._try_ip_geolocation()
        if result:
            return (result[0], result[1], "ip")

        # 3. 使用默认配置
        if self.settings.location.default_lat != 0.0 or self.settings.location.default_lng != 0.0:
            return (self.settings.location.default_lat,
                    self.settings.location.default_lng, "default")

        return (0.0, 0.0, "unavailable")

    def start_auto_report(self):
        """启动自动位置上报"""
        if not self.settings.location.auto_report:
            return
        # 防止重复启动
        if self._report_thread and self._report_thread.is_alive():
            return
        self._running.set()
        self._report_thread = threading.Thread(
            target=self._report_loop, daemon=True, name="loc-report")
        self._report_thread.start()
        logger.info(f"自动位置上报已启动，间隔 {self.settings.location.report_interval} 秒")

    def stop_auto_report(self):
        """停止自动位置上报"""
        self._running.clear()
        if self._report_thread and self._report_thread.is_alive():
            self._report_thread.join(timeout=3.0)

    def _report_loop(self):
        """自动上报循环"""
        # 连接后立即上报一次
        self._do_report()

        while self._running.is_set():
            # 拆分 sleep 以便快速退出
            poll_interval = 0.5
            ticks = max(1, int(self.settings.location.report_interval / poll_interval))
            for _ in range(ticks):
                if not self._running.is_set():
                    return
                time.sleep(poll_interval)

            if self._running.is_set():
                self._do_report()

    def _do_report(self):
        """执行一次位置上报"""
        try:
            lat, lng, source = self.get_location()
            # 实时定位失败时，使用 config 中的指定位置
            if lat == 0.0 and lng == 0.0:
                cfg_lat = self.settings.location.default_lat
                cfg_lng = self.settings.location.default_lng
                if cfg_lat != 0.0 or cfg_lng != 0.0:
                    lat, lng, source = cfg_lat, cfg_lng, "config"
                else:
                    logger.warning("自动上报位置失败：无可用位置")
                    return
            if self.on_send_location:
                if self.on_send_location(lat, lng):
                    logger.info(f"自动上报位置: {lat:.6f},{lng:.6f} (来源: {source})")
        except Exception as e:
            logger.error(f"自动上报位置异常: {e}")

    @staticmethod
    def _try_winrt_gps() -> Optional[Tuple[float, float]]:
        """尝试通过 Windows Location API 获取坐标"""
        if os.name != "nt":
            return None
        try:
            import asyncio
            from winrt.windows.devices.geolocation import Geolocator  # type: ignore

            async def _get_pos():
                locator = Geolocator()
                pos = await locator.get_geopoint_async()
                coord = pos.coordinate
                return (coord.latitude, coord.longitude)

            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(_get_pos())
            finally:
                loop.close()
        except ImportError:
            logger.debug("winrt 未安装，跳过 GPS 定位")
        except Exception as e:
            logger.debug(f"Windows GPS 定位失败: {e}")
        return None

    @staticmethod
    def _try_ip_geolocation() -> Optional[Tuple[float, float]]:
        """尝试通过 IP 地址获取大致位置"""
        try:
            import requests  # type: ignore
            import math
            resp = requests.get("https://ip-api.com/json/?fields=lat,lon,status", timeout=5)
            data = resp.json()
            if data.get("status") == "success":
                lat = float(data["lat"])
                lon = float(data["lon"])
                # 验证坐标有效性和合理范围
                if math.isfinite(lat) and math.isfinite(lon) and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                    return (lat, lon)
        except ImportError:
            logger.debug("requests 未安装，跳过 IP 定位")
        except Exception as e:
            logger.debug(f"IP 定位失败: {e}")
        return None
