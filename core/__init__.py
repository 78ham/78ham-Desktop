"""78HAM 核心协议模块"""

from importlib import import_module

__all__ = [
    'NRLHeader', 'NRLPacket', 'PacketType', 'VoiceCodec', 'G711Codec',
    'OpusCodec', 'get_codec', 'register_codec', 'list_codecs',
    'PacketFactory', 'PacketParser',
]

_EXPORTS = {
    'NRLHeader': ('core.protocol', 'NRLHeader'),
    'NRLPacket': ('core.protocol', 'NRLPacket'),
    'PacketType': ('core.protocol', 'PacketType'),
    'VoiceCodec': ('core.codec', 'VoiceCodec'),
    'G711Codec': ('core.codec', 'G711Codec'),
    'OpusCodec': ('core.codec', 'OpusCodec'),
    'get_codec': ('core.codec', 'get_codec'),
    'register_codec': ('core.codec', 'register_codec'),
    'list_codecs': ('core.codec', 'list_codecs'),
    'PacketFactory': ('core.packet_factory', 'PacketFactory'),
    'PacketParser': ('core.packet_parser', 'PacketParser'),
}


def __getattr__(name):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value
