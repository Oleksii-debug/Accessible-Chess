from __future__ import annotations

from pathlib import Path
import unittest


class LegacyReleaseWorkflowSafetyTests(unittest.TestCase):
    LEGACY_WORKFLOWS = (
        Path('.github/workflows/publish-stage1-release.yml'),
        Path('.github/workflows/windows-stage1-build.yml'),
        Path('.github/workflows/windows-stage1-webview-build.yml'),
    )

    def test_legacy_candidate_workflows_are_fail_closed_tombstones(self) -> None:
        forbidden = (
            'actions/upload-artifact',
            'gh release',
            'Compress-Archive',
            'PyInstaller',
            'python -m nuitka',
            'Copy-Item \'acs\'',
            'Stockfish-18-source.zip',
        )
        for path in self.LEGACY_WORKFLOWS:
            with self.subTest(path=str(path)):
                text = path.read_text(encoding='utf-8')
                self.assertIn('LEGACY_RELEASE_PATH_DISABLED', text)
                self.assertIn('permissions:\n  contents: read', text)
                self.assertIn('exit 1', text)
                for token in forbidden:
                    self.assertNotIn(token, text)

    def test_legacy_workflows_cannot_publish_or_upload_anything(self) -> None:
        for path in self.LEGACY_WORKFLOWS:
            with self.subTest(path=str(path)):
                text = path.read_text(encoding='utf-8').lower()
                self.assertNotIn('contents: write', text)
                self.assertNotIn('upload-artifact', text)
                self.assertNotIn('release upload', text)
                self.assertNotIn('release create', text)


if __name__ == '__main__':
    unittest.main()
