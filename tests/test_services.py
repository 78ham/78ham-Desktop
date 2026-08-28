import time
import unittest

from config.settings import Settings
from core.protocol import MAX_TEXT_LENGTH
from network.connection_manager import ConnectionManager, ConnectionState
from services.room_service import RoomService
from services.talk_service import TalkService


class _FakeUdpClient:
    def __init__(self):
        self.connection_mgr = ConnectionManager()
        self.connection_mgr.state = ConnectionState.CONNECTED
        self.sent_packets = []

    def send_packet(self, packet):
        self.sent_packets.append(packet)
        return True


class ServiceTests(unittest.TestCase):
    def test_room_request_can_retry_after_timeout(self):
        udp_client = _FakeUdpClient()
        service = RoomService(Settings(), udp_client)

        self.assertTrue(service.request_group_list())
        self.assertFalse(service.request_group_list())
        service._list_requested_at = time.monotonic() - service._list_timeout - 0.1
        self.assertTrue(service.request_group_list())
        self.assertEqual(len(udp_client.sent_packets), 2)

    def test_text_truncation_preserves_utf8_boundary(self):
        settings = Settings()
        settings.device.password = 'secret'
        service = TalkService(settings)
        service.connection_mgr.state = ConnectionState.CONNECTED
        packets = []
        service.udp_client.send_packet = lambda packet: packets.append(packet) or True

        self.assertTrue(service.send_text_message('你' * 1000))
        payload = packets[0].data

        self.assertLessEqual(len(payload), MAX_TEXT_LENGTH)
        payload.decode('utf-8')
        self.assertEqual(packets[0].header.password.rstrip(b'\x00'), b'secret')

    def test_location_rejects_non_finite_and_out_of_range_values(self):
        service = TalkService(Settings())
        self.assertFalse(service.send_location(float('nan'), 10.0))
        self.assertFalse(service.send_location(91.0, 10.0))
        self.assertFalse(service.send_location(0.0, 0.0))


if __name__ == '__main__':
    unittest.main()
