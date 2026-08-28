import tempfile
import unittest
from pathlib import Path

import yaml

from config.settings import ServerInfo, Settings


class SettingsTests(unittest.TestCase):
    def test_load_normalizes_malformed_values(self):
        source = {
            'device': {'callsign': 'ba1abc-extra', 'ssid': '999'},
            'servers': [{'name': 'A', 'host': 'example.test', 'port': '70000'}],
            'current_server': '99',
            'audio': {'codec': 'unknown', 'opus_bitrate': 'invalid'},
            'network': {'buffer_size': '12', 'heartbeat_interval': '0'},
            'location': {'default_lat': 120, 'default_lng': -250, 'auto_report': 'yes'},
            'tail_tone': {'tail_type': 'invalid', 'amplitude': 5},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.yaml'
            path.write_text(yaml.safe_dump(source), encoding='utf-8')

            settings = Settings.load(str(path))

        self.assertEqual(settings.device.callsign, 'BA1ABC')
        self.assertEqual(settings.device.ssid, 15)
        self.assertEqual(settings.server.port, 65535)
        self.assertEqual(settings.current_server_index, 0)
        self.assertEqual(settings.audio.codec, 'g711')
        self.assertEqual(settings.audio.opus_bitrate, 36000)
        self.assertEqual(settings.network.buffer_size, 48)
        self.assertEqual(settings.network.heartbeat_interval, 0.1)
        self.assertEqual(settings.location.default_lat, 90.0)
        self.assertEqual(settings.location.default_lng, -180.0)
        self.assertTrue(settings.location.auto_report)
        self.assertEqual(settings.tail_tone.tail_type, 'default')
        self.assertEqual(settings.tail_tone.amplitude, 1.0)

    def test_saves_update_only_the_requested_yaml_sections(self):
        source = {
            'audio': {'codec': 'g711', 'custom': 'keep'},
            'tail_tone': {'enabled': False},
            'feature': {'enabled': True, 'amplitude': 99},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.yaml'
            path.write_text(yaml.safe_dump(source), encoding='utf-8')
            settings = Settings.load(str(path))

            settings.audio.codec = 'opus'
            settings.audio.sample_rate = 16000
            settings.audio.opus_bitrate = 48000
            settings.tail_tone.enabled = True
            settings.tail_tone.tail_type = 'mdc'
            settings.tail_tone.amplitude = 0.4
            settings.current_server_index = 0

            self.assertTrue(settings.save_codec())
            self.assertTrue(settings.save_opus_bitrate())
            self.assertTrue(settings.save_tail_tone())
            self.assertTrue(settings.save_current_server())
            saved = yaml.safe_load(path.read_text(encoding='utf-8'))

            self.assertEqual(saved['audio']['codec'], 'opus')
            self.assertEqual(saved['audio']['tx_codec'], 'opus')
            self.assertEqual(saved['audio']['opus_bitrate'], 48000)
            self.assertEqual(saved['audio']['custom'], 'keep')
            self.assertTrue(saved['tail_tone']['enabled'])
            self.assertEqual(saved['tail_tone']['tail_type'], 'mdc')
            self.assertEqual(saved['feature'], source['feature'])
            self.assertEqual(list(Path(directory).glob('*.tmp')), [])

    def test_editor_updates_are_deep_merged(self):
        source = {
            'device': {'callsign': 'N0CALL', 'password': 'keep'},
            'network': {'buffer_size': 4096},
            'custom': {'value': 7},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.yaml'
            path.write_text(yaml.safe_dump(source), encoding='utf-8')
            settings = Settings.load(str(path))

            yaml.safe_dump(settings.to_dict())

            self.assertTrue(settings.save_updates({
                'device': {'callsign': 'K1ABC'},
                'network': {'heartbeat_interval': 3},
            }))
            saved = yaml.safe_load(path.read_text(encoding='utf-8'))

        self.assertEqual(saved['device']['callsign'], 'K1ABC')
        self.assertEqual(saved['device']['password'], 'keep')
        self.assertEqual(saved['network']['buffer_size'], 4096)
        self.assertEqual(saved['network']['heartbeat_interval'], 3)
        self.assertEqual(saved['custom'], {'value': 7})

    def test_recording_save_dir_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.yaml'
            settings = Settings.load(str(path))

            settings.recording.save_dir = str(Path(directory) / 'recs')
            self.assertTrue(settings.save_recording())

            loaded = Settings.load(str(path))
            self.assertEqual(loaded.recording.save_dir,
                             str(Path(directory) / 'recs'))

    def test_current_server_password_is_used(self):
        settings = Settings()
        settings.device.password = 'device-secret'
        settings.servers_list = [
            ServerInfo(name='A', host='a.test', password='a-secret'),
            ServerInfo(name='B', host='b.test', password='b-secret'),
        ]
        self.assertEqual(settings.get_current_password(), 'device-secret')
        settings.switch_server(1)
        self.assertEqual(settings.get_current_password(), 'device-secret')


if __name__ == '__main__':
    unittest.main()
