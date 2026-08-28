import unittest

from config.settings import ServerInfo, Settings
from services.platform_service import PlatformService


class PlatformServiceTests(unittest.TestCase):
    def test_platform_endpoint_and_merge_use_server_objects(self):
        settings = Settings()
        settings.platform_url = ''
        settings.servers_list = [ServerInfo(
            name='主站', host='nrlptt.com', port=60050, http_port=9000,
        )]
        service = PlatformService(settings)
        self.assertEqual(service._get_api().base_url, 'http://nrlptt.com:9000')

        self.assertEqual(service.merge_platform_servers([{
            'name': '分站', 'host': 'branch.nrlptt.com', 'port': 60050,
        }]), 1)
        self.assertIsInstance(settings.servers_list[1], ServerInfo)
        self.assertEqual(settings.to_dict()['servers'][1]['name'], '分站')

    def test_api_client_changes_when_server_changes(self):
        settings = Settings()
        settings.platform_url = ''
        settings.servers_list = [
            ServerInfo(name='A', host='a.test'),
            ServerInfo(name='B', host='b.test'),
        ]
        service = PlatformService(settings)
        self.assertEqual(service._get_api().base_url, 'http://a.test:9000')
        settings.switch_server(1)
        self.assertEqual(service._get_api().base_url, 'http://b.test:9000')

    def test_platform_source_is_separate_from_udp_server(self):
        settings = Settings()
        settings.platform_url = 'https://directory.example'
        settings.servers_list = [ServerInfo(name='A', host='udp.example')]
        service = PlatformService(settings)
        self.assertEqual(service._get_api().base_url, 'https://directory.example')


if __name__ == '__main__':
    unittest.main()
