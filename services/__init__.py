"""78HAM 业务服务模块"""

from importlib import import_module

__all__ = [
    'TalkService', 'RoomService', 'LocationService', 'TailToneService',
    'MDC1200Encoder', 'OP_PTT_ID', 'OP_EMERGENCY',
]

_EXPORTS = {
    'TalkService': ('services.talk_service', 'TalkService'),
    'RoomService': ('services.room_service', 'RoomService'),
    'LocationService': ('services.location_service', 'LocationService'),
    'TailToneService': ('services.tail_tone_service', 'TailToneService'),
    'MDC1200Encoder': ('services.mdc1200', 'MDC1200Encoder'),
    'OP_PTT_ID': ('services.mdc1200', 'OP_PTT_ID'),
    'OP_EMERGENCY': ('services.mdc1200', 'OP_EMERGENCY'),
}


def __getattr__(name):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
