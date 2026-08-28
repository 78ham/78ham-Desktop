"""
配置管理模块

从 YAML 文件加载配置，提供类型安全的配置数据结构。
"""
import os
import math
import logging
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional

import yaml  # type: ignore

from core.protocol import get_default_dev_model

logger = logging.getLogger(__name__)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """Return a mapping for YAML sections, treating malformed sections as empty."""
    return value if isinstance(value, Mapping) else {}


def _as_text(value: Any, default: str = "") -> str:
    return default if value is None else str(value)


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


def _as_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return min(maximum, max(minimum, parsed))


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


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
    http_port: int = 9000
    scheme: str = "http"
    password: str = ""
    username: str = ""
    api_password: str = ""
    api_url: str = ""
    online: int = 0
    total: int = 0

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> "ServerInfo":
        """从配置字典创建，兼容新旧格式"""
        return cls(
            name=str(cfg.get('name') or '服务器'),
            host=_as_text(cfg.get('host'), '127.0.0.1'),
            port=_as_int(cfg.get('port'), 60050, 1, 65535),
            http_port=_as_int(cfg.get('http_port', cfg.get('api_port')), 9000, 1, 65535),
            password=str(cfg.get('password') or ''),
            username=str(cfg.get('username') or cfg.get('account') or ''),
            api_password=str(cfg.get('api_password') or cfg.get('login_password') or ''),
            api_url=str(cfg.get('api_url') or ''),
            scheme=str(cfg.get('scheme') or 'http').lower() if str(cfg.get('scheme') or 'http').lower() in {'http', 'https'} else 'http',
            online=_as_int(cfg.get('online'), 0, 0, 2**31 - 1),
            total=_as_int(cfg.get('total'), 0, 0, 2**31 - 1),
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
    heartbeat_interval: float = 2.0  # 秒（与安卓/小程序一致）



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
class RecordingConfig:
    """录音配置"""
    enabled: bool = True            # 是否启用录音功能
    auto_save: bool = True          # 是否自动保存录音
    max_duration: int = 3600        # 最大录音时长（秒），0表示无限制
    output_format: str = "wav"      # 输出格式：wav
    save_dir: str = ""              # 录音保存目录，空表示使用默认目录


@dataclass
class Settings:
    """应用全局配置"""
    device: DeviceConfig = field(default_factory=DeviceConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    location: LocationConfig = field(default_factory=LocationConfig)
    tail_tone: TailToneConfig = field(default_factory=TailToneConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    servers_list: list = field(default_factory=list)
    current_server_index: int = 0
    platform_url: str = "https://nrlptt.com"

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

        if not isinstance(data, dict):
            raise ValueError("配置文件顶层必须是 YAML 映射")

        settings.platform_url = str(
            data.get('platform_url') or data.get('nrl_url') or 'https://nrlptt.com'
        ).rstrip('/')

        # 设备配置
        dev = _as_mapping(data.get('device'))
        settings.device = DeviceConfig(
            callsign=str(dev.get('callsign') or 'N0CALL').strip().upper()[:6],
            ssid=_as_int(dev.get('ssid'), 1, 0, 15),
            dmr_id=str(dev.get('dmr_id') or '123456'),
            password=str(dev.get('password') or ''),
            model=_as_int(dev.get('model'), get_default_dev_model(), 0, 255),
        )

        # 服务器配置
        srv = _as_mapping(data.get('server'))
        settings.server = ServerConfig(
            host=_as_text(srv.get('host'), '127.0.0.1'),
            port=_as_int(srv.get('port'), 60050, 1, 65535),
        )

        # 服务器列表
        servers_cfg = data.get('servers', []) or data.get('PlatformList', [])
        current_idx = _as_int(data.get('current_server'), 0, 0, 2**31 - 1)

        if isinstance(servers_cfg, list) and servers_cfg:
            settings.servers_list = [
                ServerInfo.from_config(_as_mapping(server)) for server in servers_cfg
            ]
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
        audio = _as_mapping(data.get('audio'))
        codec = str(audio.get('tx_codec', audio.get('codec', 'g711'))).lower()
        if codec not in {'g711', 'opus'}:
            logger.warning("不支持的音频编码 %r，回退到 g711", codec)
            codec = 'g711'
        default_rate = 16000 if codec == 'opus' else 8000
        settings.audio = AudioConfig(
            sample_rate=_as_int(audio.get('sample_rate'), default_rate, 8000, 48000),
            channels=_as_int(audio.get('channels'), 1, 1, 2),
            codec=codec,
            format=str(audio.get('format') or 'paInt16'),
            opus_bitrate=_as_int(audio.get('opus_bitrate'), 36000, 6000, 510000),
        )

        # 网络配置
        net = _as_mapping(data.get('network'))
        settings.network = NetworkConfig(
            buffer_size=_as_int(net.get('buffer_size'), 1460, 48, 65535),
            heartbeat_interval=_as_float(net.get('heartbeat_interval'), 2.0, 0.1, 3600.0),
        )

        # 位置配置

        # 位置配置
        loc = _as_mapping(data.get('location'))
        settings.location = LocationConfig(
            default_lat=_as_float(loc.get('default_lat'), 0.0, -90.0, 90.0),
            default_lng=_as_float(loc.get('default_lng'), 0.0, -180.0, 180.0),
            auto_report=_as_bool(loc.get('auto_report')),
            report_interval=_as_int(loc.get('report_interval'), 600, 1, 86400),
        )

        # 尾音配置
        tt = _as_mapping(data.get('tail_tone'))
        tail_type = str(tt.get('tail_type') or 'default').lower()
        if tail_type not in {'default', 'custom', 'mdc'}:
            tail_type = 'default'
        settings.tail_tone = TailToneConfig(
            enabled=_as_bool(tt.get('enabled')),
            tail_type=tail_type,
            custom_file=str(tt.get('custom_file') or ''),
            mdc_id=_as_int(tt.get('mdc_id'), 0, 0, 65535),
            amplitude=_as_float(tt.get('amplitude'), 0.2, 0.05, 1.0),
        )
        
        # 录音配置
        rec = _as_mapping(data.get('recording'))
        output_format = str(rec.get('output_format') or 'wav').lower()
        if output_format not in {'wav'}:
            output_format = 'wav'
        settings.recording = RecordingConfig(
            enabled=_as_bool(rec.get('enabled'), True),
            auto_save=_as_bool(rec.get('auto_save'), True),
            max_duration=_as_int(rec.get('max_duration'), 3600, 0, 86400),
            output_format=output_format,
            save_dir=str(rec.get('save_dir') or ''),
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
                'http_port': 9000,
                'scheme': 'http',
                'password': '',
            }],
            'platform_url': 'https://nrlptt.com',
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
            self._write_config_data(default, config_file)
            logger.info(f"已创建默认配置: {config_file}")
        except Exception as e:
            logger.error(f"创建默认配置失败: {e}")

    @staticmethod
    def _write_config_data(data: Dict[str, Any], config_file: str):
        """Atomically write a YAML mapping so interrupted saves cannot corrupt it."""
        destination = os.path.abspath(config_file)
        directory = os.path.dirname(destination)
        os.makedirs(directory, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=f".{os.path.basename(destination)}.", suffix=".tmp", dir=directory
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
                yaml.safe_dump(
                    data,
                    stream,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def _update_config(self, field_name: str,
                       update: Callable[[Dict[str, Any]], None]) -> bool:
        """Load, mutate and atomically persist the configured YAML mapping."""
        with self._save_lock:
            try:
                try:
                    with open(self._config_file, 'r', encoding='utf-8') as stream:
                        data = yaml.safe_load(stream) or {}
                except FileNotFoundError:
                    data = {}
                if not isinstance(data, dict):
                    raise ValueError("配置文件顶层必须是 YAML 映射")
                update(data)
                self._write_config_data(data, self._config_file)
                return True
            except Exception as e:
                logger.error(f"保存配置字段 {field_name} 失败: {e}")
                return False

    def save_codec(self) -> bool:
        """保存当前发射编码与对应采样率。"""
        def update(data: Dict[str, Any]):
            audio = data.get('audio')
            if not isinstance(audio, dict):
                audio = {}
                data['audio'] = audio
            audio.update({
                'codec': self.audio.codec,
                'tx_codec': self.audio.codec,
                'sample_rate': self.audio.sample_rate,
            })

        saved = self._update_config('codec', update)
        if saved:
            logger.info(f"发射编码已保存: {self.audio.codec}")
        return saved

    def save_opus_bitrate(self) -> bool:
        """保存 Opus 码率。"""
        def update(data: Dict[str, Any]):
            audio = data.get('audio')
            if not isinstance(audio, dict):
                audio = {}
                data['audio'] = audio
            audio['opus_bitrate'] = self.audio.opus_bitrate

        saved = self._update_config('opus_bitrate', update)
        if saved:
            logger.info(f"Opus 码率已保存: {self.audio.opus_bitrate}")
        return saved

    def save_tail_tone(self) -> bool:
        """保存尾音配置，不影响其他 YAML 段落中的同名字段。"""
        tt = self.tail_tone
        def update(data: Dict[str, Any]):
            section = data.get('tail_tone')
            if not isinstance(section, dict):
                section = {}
                data['tail_tone'] = section
            section.update({
                'enabled': tt.enabled,
                'tail_type': tt.tail_type,
                'custom_file': tt.custom_file,
                'mdc_id': tt.mdc_id,
                'amplitude': tt.amplitude,
            })

        saved = self._update_config('tail_tone', update)
        if saved:
            logger.info(f"尾音配置已保存: type={tt.tail_type}, enabled={tt.enabled}")
        return saved
    
    def save_recording(self) -> bool:
        """保存录音配置"""
        rec = self.recording
        def update(data: Dict[str, Any]):
            section = data.get('recording')
            if not isinstance(section, dict):
                section = {}
                data['recording'] = section
            section.update({
                'enabled': rec.enabled,
                'auto_save': rec.auto_save,
                'max_duration': rec.max_duration,
                'output_format': rec.output_format,
                'save_dir': rec.save_dir,
            })

        saved = self._update_config('recording', update)
        if saved:
            logger.info(f"录音配置已保存: enabled={rec.enabled}")
        return saved
    def save_current_server(self) -> bool:
        """保存当前服务器索引。"""
        saved = self._update_config(
            'current_server',
            lambda data: data.__setitem__('current_server', self.current_server_index),
        )
        if saved:
            logger.info(f"当前服务器索引已保存: {self.current_server_index}")
        return saved

    def save_servers(self) -> bool:
        """Persist the server list without replacing unrelated configuration."""
        servers = list(self.servers_list)
        return self._update_config(
            'servers',
            lambda data: data.__setitem__('servers', [
                {
                    'name': server.name,
                    'host': server.host,
                    'port': server.port,
                    'http_port': server.http_port,
                    'scheme': server.scheme,
                    'password': server.password,
                    'username': server.username,
                    'api_password': server.api_password,
                    'api_url': server.api_url,
                    'online': server.online,
                    'total': server.total,
                }
                for server in servers
            ]),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a serializable snapshot for configuration editors."""
        return {
            'servers': [
                {
                    'name': server.name,
                    'host': server.host,
                    'port': server.port,
                    'http_port': server.http_port,
                    'scheme': server.scheme,
                    'password': server.password,
                    'username': server.username,
                    'api_password': server.api_password,
                    'api_url': server.api_url,
                    'online': server.online,
                    'total': server.total,
                }
                for server in self.servers_list
            ],
            'current_server': self.current_server_index,
            'platform_url': self.platform_url,
            'device': {
                'callsign': self.device.callsign,
                'ssid': self.device.ssid,
                'dmr_id': self.device.dmr_id,
                'password': self.device.password,
                'model': int(self.device.model),
            },
            'audio': {
                'codec': self.audio.codec,
                'tx_codec': self.audio.codec,
                'sample_rate': self.audio.sample_rate,
                'channels': self.audio.channels,
                'format': self.audio.format,
                'opus_bitrate': self.audio.opus_bitrate,
            },
            'network': {
                'buffer_size': self.network.buffer_size,
                'heartbeat_interval': self.network.heartbeat_interval,
            },            'location': {
                'default_lat': self.location.default_lat,
                'default_lng': self.location.default_lng,
                'auto_report': self.location.auto_report,
                'report_interval': self.location.report_interval,
            },
            'tail_tone': {
                'enabled': self.tail_tone.enabled,
                'tail_type': self.tail_tone.tail_type,
                'custom_file': self.tail_tone.custom_file,
                'mdc_id': self.tail_tone.mdc_id,
                'amplitude': self.tail_tone.amplitude,
            },
            'recording': {
                'enabled': self.recording.enabled,
                'auto_save': self.recording.auto_save,
                'max_duration': self.recording.max_duration,
                'output_format': self.recording.output_format,
                'save_dir': self.recording.save_dir,
            },        }

    def save_updates(self, updates: Mapping[str, Any]) -> bool:
        """Deep-merge editor updates while preserving unexposed configuration."""
        def merge(target: Dict[str, Any], source: Mapping[str, Any]):
            for key, value in source.items():
                current = target.get(key)
                if isinstance(current, dict) and isinstance(value, Mapping):
                    merge(current, value)
                else:
                    target[key] = value

        return self._update_config('configuration', lambda data: merge(data, updates))

    def get_current_server(self) -> Optional[ServerInfo]:
        """获取当前服务器信息"""
        if 0 <= self.current_server_index < len(self.servers_list):
            return self.servers_list[self.current_server_index]
        return None

    def get_current_password(self) -> str:
        """Return the device password used in NRL UDP headers."""
        return self.device.password

    def set_current_password(self, password: str):
        """Update the device password used in NRL UDP headers."""
        self.device.password = password

    def switch_server(self, index: int) -> bool:
        """切换服务器索引并更新连接配置"""
        if not (0 <= index < len(self.servers_list)):
            return False
        self.current_server_index = index
        srv = self.servers_list[index]
        self.server.host = srv.host
        self.server.port = srv.port
        # The UDP protocol carries one credential field, so keep it aligned
        # with the selected server when switching away from legacy config.
        return True
