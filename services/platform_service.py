"""
平台服务

封装官方 HTTP 接口：拉取平台服务器列表 (/platform/list)。
支持自动拉取、手动添加、智能合并。
"""
import logging
from typing import Optional, List, Dict

from network.api_client import ApiClient
from config.settings import Settings
from config.settings import ServerInfo

logger = logging.getLogger(__name__)


class PlatformService:
    """平台服务

    职责：
    - 从当前服务器拉取 /platform/list 获取平台列表
    - 将平台服务器合并到现有配置
    - 不提供登录/JWT 功能
    """

    def __init__(self, settings: Settings, source_url: Optional[str] = None):
        self._settings = settings
        self._source_url = source_url or getattr(settings, 'platform_url', '')
        self._api: Optional[ApiClient] = None

    def _get_api(self) -> ApiClient:
        """获取 ApiClient（使用当前服务器）"""
        if self._source_url:
            base_url = self._source_url.rstrip('/')
        else:
            server = self._settings.get_current_server()
            host = server.host if server else self._settings.server.host
            port = server.http_port if server else 9000
            scheme = server.scheme if server else 'http'
            base_url = f"{scheme}://{host}:{port}" if port not in (80, 443) else f"{scheme}://{host}"
        if self._api is None or self._api.base_url != base_url:
            if self._api is not None:
                self._api.close()
            self._api = ApiClient(base_url)
        return self._api

    @staticmethod
    def _server_url(server: ServerInfo) -> str:
        if server.api_url:
            return server.api_url.rstrip('/')
        scheme = server.scheme if server.scheme in {'http', 'https'} else 'http'
        port = server.http_port
        return f"{scheme}://{server.host}" if port in (80, 443) else f"{scheme}://{server.host}:{port}"

    def fetch_platform_servers(self) -> List[Dict]:
        """从当前服务器拉取平台列表

        Returns:
            服务器列表，每个元素包含 name/host/port 等字段
        """
        api = self._get_api()
        servers = api.get_platform_list()
        
        if not isinstance(servers, list):
            logger.warning(f"API 返回格式错误：{type(servers)}")
            return []
        
        # 兼容两种返回结构
        normalized = []
        for srv in servers:
            if not isinstance(srv, dict):
                continue
            
            name = srv.get('name') or srv.get('Name') or '平台服务器'
            host = srv.get('host') or srv.get('Host') or srv.get('ip_addr') or ''
            port = srv.get('port') or srv.get('Port') or srv.get('udp_port') or 60050
            
            try:
                port = int(port)
            except Exception:
                port = 60050
            
            normalized.append({
                'name': str(name),
                'host': str(host),
                'port': port,
                'online': int(srv.get('online', 0)) if 'online' in srv else 0,
                'total': int(srv.get('total', 0)) if 'total' in srv else 0,
                'api_url': str(srv.get('api_url') or ''),
            })
        
        current_host = self._settings.server.host
        logger.info(f"从 {current_host} 拉取到 {len(normalized)} 个平台服务器")
        return normalized

    def login_current_server(self, username: str, password: str) -> Optional[Dict]:
        """Log in to the selected server's Web API and retain its token."""
        server = self._settings.get_current_server()
        if server is None:
            return None
        api = ApiClient(self._server_url(server))
        result = api.login(username, password)
        if result is not None:
            api.close()
        if result is not None:
            server.username = username
            server.api_password = password
        return result

    def merge_platform_servers(self, platforms: List[Dict]) -> int:
        """合并平台服务器到现有列表
        
        Args:
            platforms: 平台服务器列表（fetch_platform_servers 返回的格式）
            
        Returns:
            新增的服务器数量
        """
        existing_keys = {(s.name, s.host, s.port) for s in self._settings.servers_list}
        added = 0
        
        for p in platforms:
            name = p['name']
            # 跳过已有服务器和特殊名称
            key = (name, p['host'], p['port'])
            if key in existing_keys or name == "默认服务器":
                continue
            
            self._settings.servers_list.append(ServerInfo(
                name=name,
                host=p['host'],
                port=p['port'],
                http_port=p.get('http_port', 9000),
                scheme=p.get('scheme', 'http'),
                password=p.get('password', ''),
                online=p.get('online', 0),
                total=p.get('total', 0),
            ))
            existing_keys.add(key)
            added += 1
        
        if added > 0:
            logger.info(f"已导入 {added} 个新平台服务器")
            self._settings.save_servers()
        
        return added

    def close(self):
        if self._api:
            self._api.close()
            self._api = None
