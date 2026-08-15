from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile, ZipInfo

from acs.release_archive import verify_release_archive
from acs.release_manifest import build_release_manifest


class ReleaseArchiveTests(unittest.TestCase):
    def _package(self, root: Path):
        (root / "AccessibleChess.exe").write_bytes(b"binary")
        (root / "runtime").mkdir()
        (root / "runtime" / "WebView2Loader.dll").write_bytes(b"webview")
        manifest = build_release_manifest(root, version="0.4.0-test")
        (root / "RELEASE-MANIFEST.json").write_text(manifest.to_json(), encoding="utf-8")
        (root / "RELEASE-BUILD.txt").write_text(
            "version=0.4.0-test\nnvda_status=NVDA TEST CANDIDATE — WAITING FOR USER TEST\n",
            encoding="utf-8",
        )
        return manifest

    def _zip_tree(self, root: Path, archive_path: Path) -> None:
        with ZipFile(archive_path, "w") as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(root).as_posix())

    def test_exact_final_archive_passes(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "dist"
            root.mkdir()
            manifest = self._package(root)
            archive_path = Path(temp) / "release.zip"
            self._zip_tree(root, archive_path)
            self.assertEqual(
                verify_release_archive(
                    str(archive_path), manifest, expected_version="0.4.0-test"
                ),
                (),
            )

    def test_tampered_missing_and_injected_payload_fail_closed(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "dist"
            root.mkdir()
            manifest = self._package(root)
            archive_path = Path(temp) / "release.zip"
            with ZipFile(archive_path, "w") as archive:
                archive.writestr("AccessibleChess.exe", b"tampered")
                archive.writestr("runtime/injected.dll", b"injected")
                archive.writestr("RELEASE-MANIFEST.json", manifest.to_json())
                archive.writestr("RELEASE-BUILD.txt", "version=0.4.0-test\n")
            defects = verify_release_archive(str(archive_path), manifest)
            self.assertTrue(any("size mismatch" in item or "SHA-256 mismatch" in item for item in defects), defects)
            self.assertTrue(any("manifest file missing from archive: runtime/WebView2Loader.dll" in item for item in defects), defects)
            self.assertTrue(any("unexpected unmanifested archive file: runtime/injected.dll" in item for item in defects), defects)

    def test_embedded_manifest_must_match_verified_manifest(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "dist"
            root.mkdir()
            manifest = self._package(root)
            archive_path = Path(temp) / "release.zip"
            with ZipFile(archive_path, "w") as archive:
                archive.writestr("AccessibleChess.exe", b"binary")
                archive.writestr("runtime/WebView2Loader.dll", b"webview")
                wrong = build_release_manifest(root, version="9.9.9")
                archive.writestr("RELEASE-MANIFEST.json", wrong.to_json())
                archive.writestr("RELEASE-BUILD.txt", "version=0.4.0-test\n")
            defects = verify_release_archive(str(archive_path), manifest)
            self.assertIn("embedded release manifest does not match verified manifest", defects)

    def test_unsafe_and_case_colliding_paths_are_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "dist"
            root.mkdir()
            manifest = self._package(root)
            archive_path = Path(temp) / "release.zip"
            with ZipFile(archive_path, "w") as archive:
                archive.writestr("AccessibleChess.exe", b"binary")
                archive.writestr("accessiblechess.EXE", b"duplicate")
                archive.writestr("../escape.dll", b"escape")
                archive.writestr("runtime/WebView2Loader.dll", b"webview")
                archive.writestr("RELEASE-MANIFEST.json", manifest.to_json())
                archive.writestr("RELEASE-BUILD.txt", "version=0.4.0-test\n")
            defects = verify_release_archive(str(archive_path), manifest)
            self.assertTrue(any("duplicate case-insensitive archive path" in item for item in defects), defects)
            self.assertTrue(any("unsafe release archive path" in item for item in defects), defects)

    def test_symlink_entries_are_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "dist"
            root.mkdir()
            manifest = self._package(root)
            archive_path = Path(temp) / "release.zip"
            with ZipFile(archive_path, "w") as archive:
                archive.writestr("AccessibleChess.exe", b"binary")
                archive.writestr("runtime/WebView2Loader.dll", b"webview")
                archive.writestr("RELEASE-MANIFEST.json", manifest.to_json())
                archive.writestr("RELEASE-BUILD.txt", "version=0.4.0-test\n")
                info = ZipInfo("runtime/link.dll")
                info.create_system = 3
                info.external_attr = (0o120777 << 16)
                archive.writestr(info, "../outside.dll")
            defects = verify_release_archive(str(archive_path), manifest)
            self.assertTrue(any("release archive contains symlink" in item for item in defects), defects)

    def test_corrupt_or_missing_archive_fails_closed(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "dist"
            root.mkdir()
            manifest = self._package(root)
            corrupt = Path(temp) / "corrupt.zip"
            corrupt.write_bytes(b"not-a-zip")
            self.assertTrue(any("cannot be opened" in x for x in verify_release_archive(str(corrupt), manifest)))
            self.assertTrue(any("cannot be opened" in x for x in verify_release_archive(str(Path(temp) / 'missing.zip'), manifest)))


if __name__ == "__main__":
    unittest.main()
