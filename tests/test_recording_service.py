import os
import tempfile
import threading
import time
import unittest
import wave
from types import SimpleNamespace

from services.recording_service import (
    DEFAULT_RECORDINGS_DIR,
    RecordingService,
)


def _make_settings(max_duration=0, save_dir=""):
    return SimpleNamespace(
        audio=SimpleNamespace(sample_rate=8000, channels=1),
        recording=SimpleNamespace(max_duration=max_duration, save_dir=save_dir),
    )


class RecordingServiceTests(unittest.TestCase):
    def test_records_software_pcm_to_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            service = RecordingService(_make_settings(), recordings_dir=directory)
            self.assertTrue(service.start_recording())
            service.append_pcm(b'\x01\x00' * 160)
            path = service.stop_recording()

            self.assertIsNotNone(path)
            with wave.open(path, 'rb') as wav_file:
                data = wav_file.readframes(wav_file.getnframes())
                self.assertEqual(wav_file.getframerate(), 8000)
                self.assertGreater(wav_file.getnframes(), 0)
                self.assertNotEqual(data, b'\x00' * len(data))

    def test_explicit_dir_overrides_configured_dir(self):
        with tempfile.TemporaryDirectory() as explicit, \
                tempfile.TemporaryDirectory() as configured:
            service = RecordingService(
                _make_settings(save_dir=configured), recordings_dir=explicit)
            self.assertEqual(service.recordings_dir, explicit)

    def test_configured_dir_used_when_no_explicit_dir(self):
        with tempfile.TemporaryDirectory() as configured:
            service = RecordingService(_make_settings(save_dir=configured))
            self.assertEqual(service.recordings_dir, configured)

    def test_invalid_dir_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as directory:
            blocker = os.path.join(directory, 'blocker')
            with open(blocker, 'w', encoding='utf-8') as stream:
                stream.write('x')
            invalid = os.path.join(blocker, 'sub')

            service = RecordingService(_make_settings(save_dir=invalid))

            self.assertEqual(service.recordings_dir, DEFAULT_RECORDINGS_DIR)

    def test_set_recordings_dir_rejects_invalid_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            service = RecordingService(_make_settings(), recordings_dir=directory)
            blocker = os.path.join(directory, 'blocker')
            with open(blocker, 'w', encoding='utf-8') as stream:
                stream.write('x')
            invalid = os.path.join(blocker, 'sub')

            self.assertFalse(service.set_recordings_dir(''))
            self.assertFalse(service.set_recordings_dir(invalid))
            self.assertEqual(service.recordings_dir, directory)

            valid = os.path.join(directory, 'new')
            self.assertTrue(service.set_recordings_dir(valid))
            self.assertEqual(service.recordings_dir, valid)
            self.assertTrue(os.path.isdir(valid))

    def test_list_recordings_returns_newest_first(self):
        with tempfile.TemporaryDirectory() as directory:
            service = RecordingService(_make_settings(), recordings_dir=directory)
            self.assertEqual(service.list_recordings(), [])

            self.assertTrue(service.start_recording())
            service.append_pcm(b'\x01\x00' * 160)
            first = service.stop_recording()
            time.sleep(0.02)
            self.assertTrue(service.start_recording())
            service.append_pcm(b'\x02\x00' * 160)
            second = service.stop_recording()

            self.assertEqual(service.list_recordings(), [second, first])

    def test_max_duration_auto_stop_fires_stopped_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            service = RecordingService(
                _make_settings(max_duration=0.2), recordings_dir=directory)
            done = threading.Event()
            results = {}
            service.on_recording_stopped = lambda path: (
                results.update(path=path), done.set())

            self.assertTrue(service.start_recording())
            service.append_pcm(b'\x01\x00' * 160)

            self.assertTrue(done.wait(5), 'auto-stop callback never fired')
            self.assertFalse(service.is_recording)
            self.assertTrue(os.path.isfile(results['path']))

    def test_empty_recording_reports_error_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            service = RecordingService(_make_settings(), recordings_dir=directory)
            errors = []
            service.on_recording_error = errors.append

            self.assertTrue(service.start_recording())
            self.assertIsNone(service.stop_recording())

            self.assertEqual(len(errors), 1)

    def test_stop_without_recording_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            service = RecordingService(_make_settings(), recordings_dir=directory)
            self.assertIsNone(service.stop_recording())


if __name__ == '__main__':
    unittest.main()
