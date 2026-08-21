"""
HTTP REST API 客户端

与服务端 HTTP 接口通信，实现登录、房间列表、设备管理等功能。
参考安卓 ApiClient 和小程序 api.js 的实现。
"""
import logging
import time
import threading
from typing import Optional, Dict, List

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
        self._session_lock = threading.Lock()

    def _get_session(self):
        """获取共享 requests.Session（延迟初始化）"""
        if self._session is None:
            with self._session_lock:
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
        url = f"{self.base_url}{path}"
        headers = {}
        if self.token:
            headers['x-token'] = self.token

        session = self._get_session()
        if session is None:
            logger.error("requests 库未安装，无法使用 HTTP API")
            return None

        for attempt in range(self._max_retries):
            try:
                if method.upper() == 'GET':
                    resp = session.get(url, params=params, headers=headers,
                                       timeout=self._timeout)
                else:
                    resp = session.post(url, json=data, headers=headers,
                                        timeout=self._timeout)

                if resp.status_code != 200:
                    logger.warning(f"HTTP {resp.status_code}: {url}")
                    if resp.status_code < 500 and resp.status_code != 429:
                        return None
                else:
                    result = resp.json()
                    if not isinstance(result, dict):
                        logger.warning(f"API 返回格式错误: {url}")
                        return None
                    code = result.get('code')
                    # 60204 is the documented login failure code.  It must
                    # never be treated as a successful response.
                    if code in (20000, 20001):
                        return result.get('data', result)
                    logger.warning(f"API 错误: {result.get('message', 'unknown')}")
                    return None

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

    @staticmethod
    def _items(result) -> List[Dict]:
        """Normalize the list shapes used by nrllink HTTP responses."""
        if isinstance(result, list):
            return result
        if not isinstance(result, dict):
            return []
        items = result.get('items', result.get('list', []))
        if isinstance(items, dict):
            return list(items.values())
        return items if isinstance(items, list) else []

    def get_group_list(self) -> List[Dict]:
        """获取公共房间列表"""
        result = self._request('POST', '/group/list/mini', data={})
        return self._items(result)

    def get_group_detail(self, group_id: int) -> Optional[Dict]:
        """获取房间详情"""
        return self._request('POST', '/group/get', data={'group_id': str(group_id)})

    # ==================== 设备 ====================

    def get_device_list(self) -> List[Dict]:
        """获取设备列表"""
        result = self._request('POST', '/device/list', data={})
        return self._items(result)

    def update_device(self, device_id: int, data: Dict) -> bool:
        """更新设备信息"""
        payload = {**data, 'id': device_id}
        result = self._request('POST', '/device/update', data=payload)
        return result is not None

    # ==================== 平台 ====================

    def get_platform_list(self) -> List[Dict]:
        """获取平台服务器列表"""
        # nrllink-web calls this endpoint with POST and sends a query object.
        result = self._request('POST', '/platform/list', data={})
        return self._items(result)

    def get_platform_info(self) -> Optional[Dict]:
        """获取平台信息"""
        return self._request('GET', '/platform/info')

    def close(self):
        """Close the reusable HTTP connection pool."""
        with self._session_lock:
            session, self._session = self._session, None
        if session is not None:
            session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
