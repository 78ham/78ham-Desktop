import sys
import threading
import types
import unittest
from unittest.mock import patch

from audio.audio_manager import AudioManager


class _FakeVoiceProcessor:
    def __init__(self):
        self.codec_type = 'g711'

    def set_codec(self, codec_type):
        self.codec_type = codec_type


class _FakeHandler:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.input_device_index = None
        self.output_device_index = None
        self.recording = False
        self.playing = False
        self.closed = False
        self.__class__.instances.append(self)

    def is_recording_active(self):
        return self.recording

    def is_playback_active(self):
        return self.playing

    def stop_recording(self):
        self.recording = False

    def stop_playback(self):
        self.playing = False

    def start_playback(self):
        self.playing = True

    def close(self):
        self.closed = True


class AudioManagerTests(unittest.TestCase):
    def test_codec_switch_preserves_devices_and_playback_state(self):
        old_handler = _FakeHandler(sample_rate=8000)
        old_handler.input_device_index = 2
        old_handler.output_device_index = 3
        old_handler.playing = True
        manager = AudioManager.__new__(AudioManager)
        manager._channels = 1
        manager._format_str = 'paInt16'
        manager._lock = threading.RLock()
        manager._handler = old_handler
        manager._voice_processor = _FakeVoiceProcessor()
        manager._codec_type = 'g711'

        fake_module = types.ModuleType('audio.audio_handler')
        fake_module.AudioHandler = _FakeHandler
        with patch.dict(sys.modules, {'audio.audio_handler': fake_module}):
            self.assertTrue(manager.set_codec('opus', 16000))

        new_handler = manager._handler
        self.assertTrue(old_handler.closed)
        self.assertEqual(new_handler.input_device_index, 2)
        self.assertEqual(new_handler.output_device_index, 3)
        self.assertTrue(new_handler.playing)
        self.assertEqual(new_handler.kwargs['chunk_size'], 640)
        self.assertEqual(manager._voice_processor.codec_type, 'opus')


if __name__ == '__main__':
    unittest.main()
