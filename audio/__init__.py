"""78HAM 音频处理模块"""

from importlib import import_module

__all__ = ['AudioManager', 'VoiceProcessor', 'AudioHandler']

_EXPORTS = {
    'AudioManager': ('audio.audio_manager', 'AudioManager'),
    'VoiceProcessor': ('audio.voice_processor', 'VoiceProcessor'),
    'AudioHandler': ('audio.audio_handler', 'AudioHandler'),
}


def __getattr__(name):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
