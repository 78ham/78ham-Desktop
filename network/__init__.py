"""78HAM 网络通信模块"""

from importlib import import_module

__all__ = ['UdpClient', 'ConnectionManager', 'ConnectionState', 'ApiClient']

_EXPORTS = {
    'UdpClient': ('network.udp_client', 'UdpClient'),
    'ConnectionManager': ('network.connection_manager', 'ConnectionManager'),
    'ConnectionState': ('network.connection_manager', 'ConnectionState'),
    'ApiClient': ('network.api_client', 'ApiClient'),
}


def __getattr__(name):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
