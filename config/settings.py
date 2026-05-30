"""
配置管理模块

从 YAML 文件加载配置，提供类型安全的配置数据结构。
"""
import os
import re
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

import yaml  # type: ignore

from core.protocol import get_default_dev_model

logger = logging.getLogger(__name__)


@dataclass
class DeviceConfig:
    """设备配置"""
    callsign: str = "N0CALL"
    ssid: int = 1
    dmr_id: str = "123456"
    password: str = ""
    model: int = field(default_factory=get_default_dev_model)


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
    def from_config(cls, cfg: Dict[str, Any]) -> "ServerInfo":
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
    opus_bitrate: int = 36000  # Opus 码率 (bps)

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
class TailToneConfig:
    """尾音配置"""
    enabled: bool = False           # 是否启用尾音
    tail_type: str = "default"      # "default" / "custom" / "mdc"
    custom_file: str = ""           # 自定义尾音文件路径
    mdc_id: int = 0                 # MDC 设备 ID（0 表示使用 device.dmr_id）
    amplitude: float = 0.2          # MDC 尾音音量 (0.05-1.0)


@dataclass
class Settings:
    """应用全局配置"""
    device: DeviceConfig = field(default_factory=DeviceConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    location: LocationConfig = field(default_factory=LocationConfig)
    tail_tone: TailToneConfig = field(default_factory=TailToneConfig)
    servers_list: list = field(default_factory=list)
    current_server_index: int = 0

    _config_file: str = "config.yaml"
    _save_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def load(cls, config_file: str = "config.yaml") -> "Settings":
        """从 YAML 文件加载配置"""
        settings = cls()
        settings._config_file = config_file

        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.warning(f"配置文件不存在: {config_file}，自动创建默认配置")
            settings._create_default_config(config_file)
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
            model=dev.get('model', get_default_dev_model()),
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
            opus_bitrate=audio.get('opus_bitrate', 36000),
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

        # 尾音配置
        tt = data.get('tail_tone', {})
        settings.tail_tone = TailToneConfig(
            enabled=tt.get('enabled', False),
            tail_type=tt.get('tail_type', 'default'),
            custom_file=tt.get('custom_file', ''),
            mdc_id=tt.get('mdc_id', 0),
            amplitude=tt.get('amplitude', 0.2),
        )

        logger.info(f"配置加载成功: {config_file}")
        logger.info(f"  服务器: {settings.server.host}:{settings.server.port}")
        logger.info(f"  呼号: {settings.device.callsign}-{settings.device.ssid}")
        logger.info(f"  编码: {settings.audio.codec}")

        return settings

    def _create_default_config(self, config_file: str):
        """创建默认配置文件"""
        default = {
            'servers': [{
                'name': '示例服务器',
                'host': '',
                'port': 60050,
                'password': '',
            }],
            'device': {
                'callsign': 'N0CALL',
                'ssid': 1,
                'dmr_id': '123456',
                'password': '',
            },
            'audio': {
                'codec': 'g711',
                'sample_rate': 8000,
            },
            'tail_tone': {
                'enabled': False,
                'tail_type': 'default',
                'custom_file': '',
                'mdc_id': 0,
                'amplitude': 0.2,
            },
            'network': {
                'heartbeat_interval': 2,
                'buffer_size': 4096,
            },
            'location': {
                'auto_report': True,
                'report_interval': 120,
                'default_lat': 0.0,
                'default_lng': 0.0,
            },
        }
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                yaml.dump(default, f, allow_unicode=True,
                          default_flow_style=False, sort_keys=False)
            logger.info(f"已创建默认配置: {config_file}")
        except Exception as e:
            logger.error(f"创建默认配置失败: {e}")

    def _save_config_field(self, field_name: str, pattern: str, replacement: str,
                          append_template: Optional[str] = None):
        """通用配置保存方法（保留注释和格式）"""
        with self._save_lock:
            try:
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                if re.search(pattern, content, re.MULTILINE):
                    content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
                elif append_template:
                    content = content.rstrip('\n') + append_template

                with open(self._config_file, 'w', encoding='utf-8') as f:
                    f.write(content)
            except Exception as e:
                logger.error(f"保存配置字段 {field_name} 失败: {e}")

    def save_codec(self):
        """保存当前发射编码到配置文件（保留注释和格式）"""
        codec_value = self.audio.codec
        
        pattern = r'^(\s*tx_codec:\s*)["\']?\w+["\']?'
        replacement = rf'\g<1>"{codec_value}"'
        append_template = None
        
        try:
            with open(self._config_file, "r", encoding="utf-8") as f:
                cfg_content = f.read()
        except Exception:
            cfg_content = ''
        if 'tx_codec:' not in cfg_content:
            append_template = f"\n  tx_codec: \"{codec_value}\"\n"
        
        self._save_config_field('codec', pattern, replacement, append_template)
        logger.info(f"发射编码已保存: {codec_value}")

    def save_opus_bitrate(self):
        """保存 Opus 码率到配置文件（保留注释和格式）"""
        bitrate_value = self.audio.opus_bitrate
        
        pattern = r'^(\s*opus_bitrate:\s*)\d+'
        replacement = rf'\g<1>{bitrate_value}'
        append_template = None
        try:
            with open(self._config_file, "r", encoding="utf-8") as f:
                cfg_content = f.read()
            if 'opus_bitrate:' not in cfg_content:
                append_template = f"\n  opus_bitrate: {bitrate_value}\n"
        except Exception:
            append_template = f"\n  opus_bitrate: {bitrate_value}\n"
        self._save_config_field('opus_bitrate', pattern, replacement, append_template)
        logger.info(f"Opus 码率已保存: {bitrate_value}")

    def save_tail_tone(self):
        """保存尾音配置到配置文件（保留注释和格式）"""
        tt = self.tail_tone
        
        try:
            with open(self._config_file, 'r', encoding='utf-8') as f:
                file_content = f.read()
        except Exception:
            file_content = ''
        if 'tail_tone:' in file_content:
            # 更新已有配置段
            def _replace_field(text, key, value):
                if isinstance(value, bool):
                    val_str = "true" if value else "false"
                elif isinstance(value, str):
                    val_str = f'"{value}"'
                else:
                    val_str = str(value)
                if f'{key}:' in text:
                    return re.sub(
                        rf'^(\s*{key}:\s*).+',
                        rf'\g<1>{val_str}',
                        text,
                        flags=re.MULTILINE,
                    )
                return text

            with self._save_lock:
                try:
                    with open(self._config_file, 'r', encoding='utf-8') as f:
                        content = f.read()

                    content = _replace_field(content, 'enabled', tt.enabled)
                    content = _replace_field(content, 'tail_type', tt.tail_type)
                    content = _replace_field(content, 'custom_file', tt.custom_file)
                    content = _replace_field(content, 'mdc_id', tt.mdc_id)
                    content = _replace_field(content, 'amplitude', tt.amplitude)

                    with open(self._config_file, 'w', encoding='utf-8') as f:
                        f.write(content)
                except Exception as e:
                    logger.error(f"保存尾音配置失败: {e}")
        else:
            # 在文件末尾追加
            block = (
                f'\ntail_tone:\n'
                f'  enabled: {"true" if tt.enabled else "false"}\n'
                f'  tail_type: "{tt.tail_type}"\n'
                f'  custom_file: "{tt.custom_file}"\n'
                f'  mdc_id: {tt.mdc_id}\n'
                f'  amplitude: {tt.amplitude}\n'
            )
            with self._save_lock:
                try:
                    with open(self._config_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    with open(self._config_file, 'w', encoding='utf-8') as f:
                        f.write(content.rstrip('\n') + block)
                except Exception as e:
                    logger.error(f"保存尾音配置失败: {e}")
        
        logger.info(f"尾音配置已保存: type={tt.tail_type}, enabled={tt.enabled}")

    def save_current_server(self):
        """保存当前服务器索引到配置文件（保留注释和格式）"""
        idx = self.current_server_index
        
        pattern = r'^(\s*current_server:\s*)\d+'
        replacement = rf'\g<1>{idx}'
        append_template = None
        try:
            with open(self._config_file, "r", encoding="utf-8") as f:
                cfg_content = f.read()
            if 'current_server:' not in cfg_content:
                append_template = f"\ncurrent_server: {idx}\n"
        except Exception:
            append_template = f"\ncurrent_server: {idx}\n"
        self._save_config_field('current_server', pattern, replacement, append_template)
        logger.info(f"当前服务器索引已保存: {idx}")

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
