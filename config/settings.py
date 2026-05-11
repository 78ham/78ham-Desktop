"""
配置管理模块

从 YAML 文件加载配置，提供类型安全的配置数据结构。
"""
import os
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

import yaml  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class DeviceConfig:
    """设备配置"""
    callsign: str = "N0CALL"
    ssid: int = 1
    dmr_id: str = "123456"
    password: str = ""
    model: int = 103  # DevModel.WINDOWS


@dataclass
class ServerInfo:
    """服务器信息"""
    name: str = "服务器"
    host: str = "127.0.0.1"
    port: int = 60050
    password: str = ""
    online: int = 0
    total: int = 0

    @classmethod
    def from_config(cls, cfg: dict) -> "ServerInfo":
        """从配置字典创建，兼容新旧格式"""
        port_val = cfg.get('port', 60050)
        if isinstance(port_val, str):
            try:
                port_val = int(port_val)
            except (ValueError, TypeError):
                port_val = 60050
        return cls(
            name=cfg.get('name', '服务器'),
            host=cfg.get('host', '127.0.0.1'),
            port=port_val,
            password=cfg.get('password', ''),
            online=cfg.get('online', 0),
            total=cfg.get('total', 0),
        )


@dataclass
class ServerConfig:
    """当前服务器连接配置"""
    host: str = "127.0.0.1"
    port: int = 60050


@dataclass
class AudioConfig:
    """音频配置"""
    sample_rate: int = 8000
    channels: int = 1
    codec: str = "g711"     # "g711" 或 "opus"
    format: str = "paInt16"

    def __post_init__(self):
        """根据编码格式自动修正采样率"""
        if self.codec == 'opus' and self.sample_rate != 16000:
            self.sample_rate = 16000
        elif self.codec == 'g711' and self.sample_rate != 8000:
            self.sample_rate = 8000

    @property
    def chunk_size(self) -> int:
        """PCM 帧字节数"""
        if self.codec == 'opus':
            return 640  # 320 samples * 2 bytes @ 16kHz = 20ms
        return 320      # 160 samples * 2 bytes @ 8kHz = 20ms


@dataclass
class NetworkConfig:
    """网络配置"""
    buffer_size: int = 1460
    heartbeat_interval: int = 2  # 秒（与安卓/小程序一致）


@dataclass
class LocationConfig:
    """位置配置"""
    default_lat: float = 0.0
    default_lng: float = 0.0
    auto_report: bool = False
    report_interval: int = 600  # 秒


@dataclass
class Settings:
    """应用全局配置"""
    device: DeviceConfig = field(default_factory=DeviceConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    location: LocationConfig = field(default_factory=LocationConfig)
    servers_list: list = field(default_factory=list)
    current_server_index: int = 0

    _config_file: str = "config.yaml"

    @classmethod
    def load(cls, config_file: str = "config.yaml") -> "Settings":
        """从 YAML 文件加载配置"""
        settings = cls()
        settings._config_file = config_file

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.warning(f"配置文件不存在: {config_file}，使用默认配置")
            return settings
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            raise

        # 设备配置
        dev = data.get('device', {})
        settings.device = DeviceConfig(
            callsign=dev.get('callsign', 'N0CALL'),
            ssid=dev.get('ssid', 1),
            dmr_id=dev.get('dmr_id', '123456'),
            password=dev.get('password', ''),
            model=dev.get('model', 103),
        )

        # 服务器配置
        srv = data.get('server', {})
        settings.server = ServerConfig(
            host=srv.get('host', '127.0.0.1'),
            port=srv.get('port', 60050),
        )

        # 服务器列表
        servers_cfg = data.get('servers', []) or data.get('PlatformList', [])
        current_idx = data.get('current_server', 0)

        if servers_cfg:
            settings.servers_list = [ServerInfo.from_config(s) for s in servers_cfg]
            if 0 <= current_idx < len(settings.servers_list):
                settings.current_server_index = current_idx
            else:
                settings.current_server_index = 0
            # 使用当前选择的服务器
            current = settings.servers_list[settings.current_server_index]
            settings.server.host = current.host
            settings.server.port = current.port
        else:
            settings.servers_list = [ServerInfo(
                name="默认服务器",
                host=settings.server.host,
                port=settings.server.port,
            )]
            settings.current_server_index = 0

        # 音频配置
        audio = data.get('audio', {})
        codec = audio.get('tx_codec', audio.get('codec', 'g711'))
        default_rate = 16000 if codec == 'opus' else 8000
        settings.audio = AudioConfig(
            sample_rate=audio.get('sample_rate', default_rate),
            channels=audio.get('channels', 1),
            codec=codec,
            format=audio.get('format', 'paInt16'),
        )

        # 网络配置
        net = data.get('network', {})
        settings.network = NetworkConfig(
            buffer_size=net.get('buffer_size', 1460),
            heartbeat_interval=net.get('heartbeat_interval', 2),
        )

        # 位置配置
        loc = data.get('location', {})
        settings.location = LocationConfig(
            default_lat=loc.get('default_lat', 0.0),
            default_lng=loc.get('default_lng', 0.0),
            auto_report=loc.get('auto_report', False),
            report_interval=loc.get('report_interval', 600),
        )

        logger.info(f"配置加载成功: {config_file}")
        logger.info(f"  服务器: {settings.server.host}:{settings.server.port}")
        logger.info(f"  呼号: {settings.device.callsign}-{settings.device.ssid}")
        logger.info(f"  编码: {settings.audio.codec}")

        return settings

    def save_codec(self):
        """保存当前发射编码到配置文件（保留注释和格式）"""
        try:
            with open(self._config_file, 'r', encoding='utf-8') as f:
                content = f.read()

            codec_value = self.audio.codec

            if 'tx_codec:' in content:
                content = re.sub(
                    r'(tx_codec:\s*)["\']?\w+["\']?',
                    rf'\g<1>"{codec_value}"',
                    content
                )
            elif 'codec:' in content:
                content = re.sub(
                    r'(codec:\s*)["\']?\w+["\']?',
                    rf'tx_codec: "{codec_value}"',
                    content
                )
            else:
                content = re.sub(
                    r'(audio:\s*\n(?:\s+\S.*\n)*)',
                    lambda m: m.group(0).rstrip('\n') + f'\n  tx_codec: "{codec_value}"\n',
                    content
                )

            with open(self._config_file, 'w', encoding='utf-8') as f:
                f.write(content)

            logger.info(f"发射编码已保存: {codec_value}")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")

    def get_current_server(self) -> Optional[ServerInfo]:
        """获取当前服务器信息"""
        if 0 <= self.current_server_index < len(self.servers_list):
            return self.servers_list[self.current_server_index]
        return None

    def switch_server(self, index: int) -> bool:
        """切换服务器索引并更新连接配置"""
        if not (0 <= index < len(self.servers_list)):
            return False
        self.current_server_index = index
        srv = self.servers_list[index]
        self.server.host = srv.host
        self.server.port = srv.port
        return True
