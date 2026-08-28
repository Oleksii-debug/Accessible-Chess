from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from acs.acsdb import ACSDB_SCHEMA_VERSION
from acs.settings import SCHEMA_VERSION as SETTINGS_SCHEMA_VERSION
from acs.version2_package_preflight import (
    CHECKSUMS_NAME,
    MANIFEST_NAME,
    PackageLimits,
    V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
    V2_PACKAGE_PROFILE,
    Version2PackagePreflightError,
    validate_version2_package_tree,
    validate_version2_package_zip,
)
from acs.version2_upgrade import UPGRADE_JOURNAL_SCHEMA_VERSION


_SHA = "a" * 40


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_checksums(root: Path) -> None:
    rows = []
    for path in sorted(
        (item for item in root.rglob("*") if item.is_file() and item.name != CHECKSUMS_NAME),
        key=lambda item: item.relative_to(root).as_posix().casefold(),
    ):
        relative = path.relative_to(root).as_posix()
        rows.append(f"{_sha256(path)}  {relative}")
    (root / CHECKSUMS_NAME).write_text("\n".join(rows) + "\n", encoding="utf-8")


def _make_tree(root: Path) -> None:
    product = root / "AccessibleChess"
    product.mkdir(parents=True)
    (product / "AccessibleChess.exe").write_bytes(b"MZ\x00V2")
    (product / "assets").mkdir()
    (product / "assets" / "content.dat").write_bytes(b"canonical-v2-content")
    manifest = {
        "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
        "product": "Accessible Chess",
        "package_profile": V2_PACKAGE_PROFILE,
        "integration_sha": _SHA,
        "nvda_verified": False,
        "upgrade_from_version1": True,
        "upgrade_journal_schema": UPGRADE_JOURNAL_SCHEMA_VERSION,
        "settings_schema": SETTINGS_SCHEMA_VERSION,
        "acsdb_schema": ACSDB_SCHEMA_VERSION,
        "user_data_bundled": False,
        "raw_source_bundled": False,
        "optional_external_backends_bundled": False,
    }
    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_checksums(root)


def _zip_tree(root: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())


class Version2PackagePreflightTests(unittest.TestCase):
    def test_valid_tree_and_zip_post_build_readback(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "package"
            root.mkdir()
            _make_tree(root)

            tree = validate_version2_package_tree(root)
            self.assertEqual(tree.integration_sha, _SHA)
            self.assertGreaterEqual(tree.checksums_verified, 3)
            self.assertIsNone(tree.archive_sha256)

            archive = base / "Accessible-Chess-V2.zip"
            _zip_tree(root, archive)
            readback = validate_version2_package_zip(archive)
            self.assertEqual(readback.integration_sha, _SHA)
            self.assertEqual(readback.inventory, tree.inventory)
            self.assertEqual(readback.checksums_verified, tree.checksums_verified)
            self.assertEqual(len(readback.archive_sha256 or ""), 64)

    def test_manifest_and_checksum_tamper_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            manifest_path = root / MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["nvda_verified"] = True
            manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError, "manifest contract mismatch"
            ):
                validate_version2_package_tree(root)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            (root / "AccessibleChess" / "assets" / "content.dat").write_bytes(b"tampered")
            with self.assertRaisesRegex(
                Version2PackagePreflightError, "checksum mismatch"
            ):
                validate_version2_package_tree(root)

    def test_duplicate_manifest_key_and_checksum_path_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
            body = json.dumps(manifest)
            body = body[:-1] + ', "product": "Accessible Chess"}'
            (root / MANIFEST_NAME).write_text(body, encoding="utf-8")
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PackagePreflightError, "duplicate JSON keys"
            ):
                validate_version2_package_tree(root)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            checksum_path = root / CHECKSUMS_NAME
            rows = checksum_path.read_text(encoding="utf-8").splitlines()
            checksum_path.write_text(
                "\n".join(rows + [rows[0]]) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(
                Version2PackagePreflightError, "duplicate paths"
            ):
                validate_version2_package_tree(root)

    def test_user_state_raw_source_secret_and_optional_backend_are_rejected(self):
        cases = (
            ("settings.json", b"{}", "user state"),
            ("debug.py", b"print('x')", "raw source"),
            ("token.json", b"{}", "secret-bearing"),
            ("uncbv.exe", b"MZ", "optional external backend"),
            ("libcbh.dll", b"MZ", "optional external backend"),
        )
        for name, payload, expected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                root = Path(td) / "package"
                root.mkdir()
                _make_tree(root)
                (root / "AccessibleChess" / name).write_bytes(payload)
                _write_checksums(root)
                with self.assertRaisesRegex(Version2PackagePreflightError, expected):
                    validate_version2_package_tree(root)

    def test_private_paths_and_credentials_in_text_are_rejected_without_echo(self):
        samples = (
            b"diagnostic=C:\\Users\\Developer\\secret\\build",
            b"token=github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456",
        )
        for payload in samples:
            with self.subTest(payload=payload[:10]), tempfile.TemporaryDirectory() as td:
                root = Path(td) / "package"
                root.mkdir()
                _make_tree(root)
                leak = root / "AccessibleChess" / "diagnostic.txt"
                leak.write_bytes(payload)
                _write_checksums(root)
                with self.assertRaises(Version2PackagePreflightError) as captured:
                    validate_version2_package_tree(root)
                self.assertNotIn("Developer", str(captured.exception))
                self.assertNotIn("github_pat_", str(captured.exception))

    def test_tree_bounds_fail_before_trusting_checksums(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "package"
            root.mkdir()
            _make_tree(root)
            with self.assertRaisesRegex(Version2PackagePreflightError, "byte limit"):
                validate_version2_package_tree(
                    root,
                    limits=PackageLimits(
                        max_files=50,
                        max_bytes=8,
                        max_archive_bytes=1000,
                        max_member_bytes=1000,
                        max_compression_ratio=200,
                        max_text_scan_bytes=1000,
                    ),
                )

    def test_zip_rejects_traversal_case_collision_symlink_and_member_bounds(self):
        builders = []

        def traversal(archive):
            archive.writestr("../escape.txt", b"x")

        builders.append((traversal, "unsafe"))

        def collision(archive):
            archive.writestr("AccessibleChess/A.txt", b"a")
            archive.writestr("AccessibleChess/a.txt", b"b")

        builders.append((collision, "case-folding"))

        def symlink(archive):
            info = zipfile.ZipInfo("AccessibleChess/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "target")

        builders.append((symlink, "symbolic links"))

        for builder, expected in builders:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as td:
                archive_path = Path(td) / "bad.zip"
                with zipfile.ZipFile(archive_path, "w") as archive:
                    builder(archive)
                with self.assertRaisesRegex(Version2PackagePreflightError, expected):
                    validate_version2_package_zip(archive_path)

        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "large.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("big.bin", b"x" * 16)
            with self.assertRaisesRegex(
                Version2PackagePreflightError, "member exceeds"
            ):
                validate_version2_package_zip(
                    archive_path,
                    limits=PackageLimits(
                        max_files=50,
                        max_bytes=100,
                        max_archive_bytes=1000,
                        max_member_bytes=8,
                        max_compression_ratio=200,
                        max_text_scan_bytes=100,
                    ),
                )

    def test_zip_readback_rejects_accidental_user_data(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "package"
            root.mkdir()
            _make_tree(root)
            (root / "AccessibleChess" / "library.acsdb").write_bytes(b"private-user-db")
            _write_checksums(root)
            archive_path = base / "bad-user-data.zip"
            _zip_tree(root, archive_path)
            with self.assertRaisesRegex(Version2PackagePreflightError, "user state"):
                validate_version2_package_zip(archive_path)


if __name__ == "__main__":
    unittest.main()
