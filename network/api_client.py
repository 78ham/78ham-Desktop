"""
HTTP REST API 客户端

与服务端 HTTP 接口通信，实现登录、房间列表、设备管理等功能。
参考安卓 ApiClient 和小程序 api.js 的实现。
"""
import logging
import time
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


class ApiClient:
    """HTTP REST API 客户端

    与 NRL 服务端的 HTTP 接口通信。
    Token 认证，自动重试。
    """

    def __init__(self, base_url: str):
        """
        Args:
            base_url: 服务器基础 URL（如 "https://nrlptt.com"）
        """
        self.base_url = base_url.rstrip('/')
        self.token: Optional[str] = None
        self._max_retries = 3
        self._timeout = 10
        self._session = None

    def _get_session(self):
        """获取共享 requests.Session（延迟初始化）"""
        if self._session is None:
            try:
                import requests as _req
                self._session = _req.Session()
            except ImportError:
                return None
        return self._session

    def _request(self, method: str, path: str, data: dict = None,
                 params: dict = None) -> Optional[Dict]:
        """发送 HTTP 请求（带重试和 Token）"""
        try:
            import requests  # type: ignore
        except ImportError:
            logger.error("requests 库未安装，无法使用 HTTP API")
            return None

        url = f"{self.base_url}{path}"
        headers = {}
        if self.token:
            headers['x-token'] = self.token

        session = self._get_session()
        if session is None:
            return None

        for attempt in range(self._max_retries):
            try:
                if method.upper() == 'GET':
                    resp = session.get(url, params=params, headers=headers,
                                       timeout=self._timeout)
                else:
                    resp = session.post(url, json=data, headers=headers,
                                        timeout=self._timeout)

                if resp.status_code == 200:
                    result = resp.json()
                    code = result.get('code', 0)
                    if code in (20000, 60204, 0):
                        return result.get('data', result)
                    else:
                        logger.warning(f"API 错误: {result.get('message', 'unknown')}")
                        return None
                else:
                    logger.warning(f"HTTP {resp.status_code}: {url}")

            except Exception as e:
                logger.debug(f"请求失败 (尝试 {attempt + 1}): {e}")
                if attempt < self._max_retries - 1:
                    time.sleep(1 + attempt)

        return None

    # ==================== 认证 ====================

    def login(self, callsign: str, password: str) -> Optional[Dict]:
        """用户登录

        Returns:
            成功返回 {"token": str, "user": dict}，失败返回 None
        """
        result = self._request('POST', '/user/login', data={
            'username': callsign,
            'password': password,
        })
        if result and 'token' in result:
            self.token = result['token']
            logger.info(f"登录成功: {callsign}")
        return result

    def get_user_info(self) -> Optional[Dict]:
        """获取当前用户信息"""
        return self._request('GET', '/user/info')

    def logout(self) -> bool:
        """登出"""
        result = self._request('POST', '/user/logout')
        self.token = None
        return result is not None

    # ==================== 房间 ====================

    def get_group_list(self) -> List[Dict]:
        """获取公共房间列表"""
        result = self._request('GET', '/group/list/mini')
        if result and isinstance(result, list):
            return result
        if result and 'list' in result:
            return result['list']
        return []

    def get_group_detail(self, group_id: int) -> Optional[Dict]:
        """获取房间详情"""
        return self._request('GET', '/group/get', params={'id': group_id})

    # ==================== 设备 ====================

    def get_device_list(self) -> List[Dict]:
        """获取设备列表"""
        result = self._request('GET', '/device/list')
        if result and isinstance(result, list):
            return result
        if result and 'list' in result:
            return result['list']
        return []

    def update_device(self, device_id: int, data: Dict) -> bool:
        """更新设备信息"""
        data['id'] = device_id
        result = self._request('POST', '/device/update', data=data)
        return result is not None

    # ==================== 平台 ====================

    def get_platform_list(self) -> List[Dict]:
        """获取平台服务器列表"""
        result = self._request('GET', '/platform/list')
        if result and isinstance(result, list):
            return result
        if result and 'list' in result:
            return result['list']
        return []

    def get_platform_info(self) -> Optional[Dict]:
        """获取平台信息"""
        return self._request('GET', '/platform/info')
