import socket
import threading
import time
import unittest

from config.settings import Settings
from network.api_client import ApiClient
from network.connection_manager import ConnectionManager, ConnectionState
from network.udp_client import UdpClient


class _FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class NetworkTests(unittest.TestCase):
    def test_udp_connect_and_disconnect_release_threads(self):
        settings = Settings()
        settings.server.host = '127.0.0.1'
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        receiver.bind(('127.0.0.1', 0))
        settings.server.port = receiver.getsockname()[1]
        settings.network.heartbeat_interval = 60
        manager = ConnectionManager()
        client = UdpClient(settings, manager)
        try:
            self.assertTrue(client.connect())
            self.assertTrue(client.is_running)
            self.assertEqual(manager.state, ConnectionState.CONNECTED)

            client.disconnect()

            self.assertFalse(client.is_running)
            self.assertEqual(manager.state, ConnectionState.DISCONNECTED)
            self.assertIsNone(client._receive_thread)
            self.assertIsNone(client._heartbeat_thread)
        finally:
            client.disconnect()
            receiver.close()

    def test_reconnect_delay_can_be_cancelled_immediately(self):
        settings = Settings()
        manager = ConnectionManager(reconnect_delay=5.0)
        client = UdpClient(settings, manager)
        client._running_event.set()
        client._stop_event.clear()
        worker = threading.Thread(target=client._attempt_reconnect)
        worker.start()

        deadline = time.monotonic() + 1.0
        while manager.state != ConnectionState.RECONNECTING:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

        started = time.monotonic()
        client.disconnect()
        worker.join(timeout=1.0)

        self.assertFalse(worker.is_alive())
        self.assertLess(time.monotonic() - started, 1.0)

    def test_api_update_does_not_mutate_input_and_close_releases_session(self):
        client = ApiClient('https://example.test')
        captured = []
        client._request = lambda method, path, data=None, params=None: (
            captured.append(data) or {'ok': True}
        )
        source = {'name': 'radio'}

        self.assertTrue(client.update_device(7, source))
        self.assertEqual(source, {'name': 'radio'})
        self.assertEqual(captured[0], {'name': 'radio', 'id': 7})

        session = _FakeSession()
        client._session = session
        client.close()
        self.assertTrue(session.closed)
        self.assertIsNone(client._session)

    def test_platform_list_accepts_items_envelope(self):
        client = ApiClient('http://example.test:9000')
        captured = []
        client._request = lambda method, path, data=None, params=None: (
            captured.append((method, path, data)) or {
                'items': [{'Name': 'NRL', 'Host': 'nrlptt.com', 'Port': 60050}]
            }
        )

        self.assertEqual(client.get_platform_list(), [
            {'Name': 'NRL', 'Host': 'nrlptt.com', 'Port': 60050}
        ])
        self.assertEqual(captured, [('POST', '/platform/list', {})])

    def test_login_failure_code_is_not_success(self):
        client = ApiClient('http://example.test')
        client._request = lambda method, path, data=None, params=None: None
        self.assertIsNone(client.login('N0CALL', 'wrong'))


if __name__ == '__main__':
    unittest.main()
