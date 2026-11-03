import struct
import unittest
from unittest.mock import patch
import zlib

import skill_tasks
from tools.make_preview import ROOT, make_preview


def png_content(png):
    """Compare lossless fixture data, independently of its deflate encoding."""
    if png[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Not a PNG')
    offset = 8
    compressed = []
    header = None
    while offset < len(png):
        size = struct.unpack('>I', png[offset:offset + 4])[0]
        kind = png[offset + 4:offset + 8]
        data = png[offset + 8:offset + 8 + size]
        if kind == b'IHDR':
            header = data
        if kind == b'IDAT':
            compressed.append(data)
        offset += size + 12
    return header, zlib.decompress(b''.join(compressed))


class PreviewTests(unittest.TestCase):
    def test_demo_assets_match_the_benchmark_scenes(self):
        for level in (1, 2, 3):
            with self.subTest(level=level):
                asset = (ROOT / 'docs/assets' / f'vision-{level}.png').read_bytes()
                self.assertEqual(png_content(asset), png_content(skill_tasks.png_scene(level)))

    def test_preview_does_not_depend_on_png_compression(self):
        before = make_preview()
        scene = skill_tasks.png_scene(1)
        compress = zlib.compress
        # Exercise different PNG bytes for the same pixels, as on CI's zlib.
        with patch('skill_tasks.zlib.compress', side_effect=lambda data: compress(data, 0)):
            different_encoding = skill_tasks.png_scene(1)
            self.assertNotEqual(scene, different_encoding)
            self.assertEqual(png_content(scene), png_content(different_encoding))
            self.assertEqual(before, make_preview())
