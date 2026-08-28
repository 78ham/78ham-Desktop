import struct
import unittest

from core.codec import G711Codec
from core.packet_factory import PacketFactory


class CodecTests(unittest.TestCase):
    def test_g711_silence_uses_the_alaw_zero_level_code(self):
        codec = G711Codec()
        encoded = codec.encode(b'\x00' * 320)
        decoded = codec.decode(encoded)
        samples = struct.unpack('<160h', decoded)

        self.assertEqual(encoded, b'\xD5' * 160)
        self.assertLessEqual(max(abs(sample) for sample in samples), 8)
        self.assertEqual(PacketFactory._pad_voice_data(b''), b'\xD5' * 160)


if __name__ == '__main__':
    unittest.main()
