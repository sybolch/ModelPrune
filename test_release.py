import json
from pathlib import Path
import tempfile
import unittest
from tools.prepare_release import prepare


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.write_version('1.0.0')
        self.changelog('# Changelog\n\n## Unreleased\n\nFuture changes.\n\n## 1.0.0 — 2026-11-03\n\n- Initial release.\n\n## 0.9.0\n\nOlder changes.\n')

    def write_version(self, version):
        (self.root / 'runtime-versions.json').write_text(json.dumps({'package_version': version}))

    def changelog(self, content):
        (self.root / 'CHANGELOG.md').write_text(content)

    def test_extracts_only_matching_release_and_includes_installation(self):
        notes, prerelease = prepare('v1.0.0', self.root)
        self.assertIn('- Initial release.', notes)
        self.assertIn('./install.sh --open', notes)
        self.assertNotIn('Future changes', notes)
        self.assertNotIn('Older changes', notes)
        self.assertFalse(prerelease)

    def test_tag_must_match_manifest(self):
        with self.assertRaisesRegex(ValueError, 'does not match'):
            prepare('v1.0.1', self.root)

    def test_requires_a_valid_version_tag(self):
        for tag in ['main', '1.0.0', 'v1', 'v01.0.0', 'v1.0.0-rc.01', 'v1.0.0\n']:
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                prepare(tag, self.root)

    def test_marks_prerelease(self):
        self.write_version('1.1.0-rc.1')
        self.changelog('## 1.1.0-rc.1\n\n- Release candidate.\n')
        self.assertTrue(prepare('v1.1.0-rc.1', self.root)[1])

    def test_rejects_missing_duplicate_or_empty_changelog_sections(self):
        for text in ['## 1.1.0\n\nWrong release.\n', '## 1.0.0\n\n', '## 1.0.0\n\nFirst.\n\n## 1.0.0\n\nDuplicate.\n']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.changelog(text)
                prepare('v1.0.0', self.root)

    def test_two_part_tag_maps_to_zero_patch_version(self):
        self.assertEqual(prepare('v1.0', self.root), prepare('v1.0.0', self.root))
        self.write_version('1.0.1')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            prepare('v1.0', self.root)

    def test_two_part_prerelease_keeps_its_suffix(self):
        self.write_version('1.1.0-rc.1')
        self.changelog('## 1.1.0-rc.1\n\n- Release candidate.\n')
        self.assertEqual(prepare('v1.1-rc.1', self.root), prepare('v1.1.0-rc.1', self.root))
