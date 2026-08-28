import struct
import threading
import unittest

from core.packet_factory import PacketFactory
from core.packet_parser import PacketParser
from core.protocol import HEADER_SIZE, NRLHeader, NRLPacket, PacketType, is_valid_callsign


class ProtocolTests(unittest.TestCase):
    def test_short_padded_callsign_is_valid_and_round_trips(self):
        self.assertTrue(is_valid_callsign(b'K1AB\x00\x00'))
        self.assertFalse(is_valid_callsign(b'K1-AB\x00'))

        packet = PacketFactory().create_text('K1AB', 2, '123456', b'hello')
        decoded = PacketParser.decode(PacketFactory.encode_packet(packet))

        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.header.get_callsign_str(), 'K1AB')
        self.assertEqual(decoded.data, b'hello')

    def test_password_is_encoded_in_the_fixed_header(self):
        packet = PacketFactory().create_heartbeat(
            'N0CALL', 1, password='secret'
        )
        encoded = PacketFactory.encode_packet(packet)
        decoded = PacketParser.decode(encoded)

        self.assertEqual(encoded[9:20], b'secret\x00\x00\x00\x00\x00')
        self.assertEqual(decoded.header.password.rstrip(b'\x00'), b'secret')

    def test_decimal_dmr_id_is_encoded_as_three_byte_integer(self):
        packet = PacketFactory().create_heartbeat('N0CALL', 1, '123456')
        self.assertEqual(packet.header.dmr_id, b'\x01\xe2\x40')

        hex_packet = PacketFactory().create_heartbeat('N0CALL', 1, '0x123456')
        self.assertEqual(hex_packet.header.dmr_id, b'\x12\x34\x56')

    def test_invalid_header_length_is_rejected(self):
        packet = PacketFactory().create_heartbeat('N0CALL', 1)
        encoded = bytearray(PacketFactory.encode_packet(packet))
        struct.pack_into('>H', encoded, 4, HEADER_SIZE - 1)
        self.assertIsNone(PacketParser.decode(bytes(encoded)))

    def test_oversized_packet_is_rejected(self):
        packet = NRLPacket(
            header=NRLHeader(packet_type=PacketType.TEXT, callsign=b'N0CALL'),
            data=b'x' * 65535,
        )
        with self.assertRaises(ValueError):
            PacketFactory.encode_packet(packet)

    def test_packet_counter_is_thread_safe(self):
        factory = PacketFactory()
        counts = []
        result_lock = threading.Lock()

        def create_packets():
            local = [factory.create_text('N0CALL', 1, '', b'x').header.count
                     for _ in range(100)]
            with result_lock:
                counts.extend(local)

        threads = [threading.Thread(target=create_packets) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(counts), 800)
        self.assertEqual(len(set(counts)), 800)


if __name__ == '__main__':
    unittest.main()
