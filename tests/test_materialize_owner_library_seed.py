from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import zipfile

from acs.user_library_seed import BUNDLE_KIND, SCHEMA_VERSION
from scripts.materialize_owner_library_seed import (
    OwnerLibrarySeedMaterializeError,
    materialize_owner_library_seed,
)


PGN = """[Event "Owner"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 *
"""


def _seed_files(count: int = 6) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    entries: list[dict[str, object]] = []
    for index in range(count):
        name = f"owner-{index + 1}.pgn"
        payload = PGN.replace('[Event "Owner"]', f'[Event "Owner {index + 1}"]').encode("utf-8")
        files[name] = payload
        entries.append(
            {
                "file": name,
                "display_name": f"Owner source {index + 1}",
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "bundle_kind": BUNDLE_KIND,
        "runtime_network_required": False,
        "ai_required": False,
        "files": entries,
    }
    files["manifest.json"] = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return files


def _zip(path: Path, files: dict[str, bytes]) -> str:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OwnerLibrarySeedMaterializerTests(unittest.TestCase):
    def test_exact_six_source_seed_materializes_after_canonical_import(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            source = work / "seed.zip"
            digest = _zip(source, _seed_files())
            destination = work / "published" / "user-library-seed"

            report = materialize_owner_library_seed(
                source,
                destination,
                expected_archive_sha256=digest,
                expected_source_count=6,
                expected_game_count=6,
            )

            self.assertEqual(report.archive_sha256, digest)
            self.assertEqual(report.source_count, 6)
            self.assertEqual(report.game_count, 6)
            self.assertTrue((destination / "manifest.json").is_file())
            self.assertEqual(len(tuple(destination.glob("*.pgn"))), 6)

    def test_wrong_archive_identity_fails_without_publishing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            source = work / "seed.zip"
            _zip(source, _seed_files())
            destination = work / "published"

            with self.assertRaisesRegex(
                OwnerLibrarySeedMaterializeError,
                "SHA-256 mismatch",
            ):
                materialize_owner_library_seed(
                    source,
                    destination,
                    expected_archive_sha256="0" * 64,
                    expected_source_count=6,
                    expected_game_count=6,
                )
            self.assertFalse(destination.exists())

    def test_nested_or_traversal_member_is_rejected(self) -> None:
        for hostile in ("nested/book.pgn", "../book.pgn", "C:book.pgn", "book.pgn "):
            with self.subTest(hostile=hostile), tempfile.TemporaryDirectory() as raw:
                work = Path(raw)
                source = work / "seed.zip"
                files = _seed_files()
                files[hostile] = files.pop("owner-1.pgn")
                digest = _zip(source, files)
                destination = work / "published"
                with self.assertRaisesRegex(
                    OwnerLibrarySeedMaterializeError,
                    "path is unsafe|root files only",
                ):
                    materialize_owner_library_seed(
                        source,
                        destination,
                        expected_archive_sha256=digest,
                        expected_source_count=6,
                        expected_game_count=6,
                    )
                self.assertFalse(destination.exists())

    def test_symlink_typed_zip_member_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            source = work / "seed.zip"
            files = _seed_files()
            link_payload = files.pop("owner-1.pgn")
            with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, payload in files.items():
                    archive.writestr(name, payload)
                info = zipfile.ZipInfo("owner-1.pgn")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, link_payload)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            destination = work / "published"

            with self.assertRaisesRegex(
                OwnerLibrarySeedMaterializeError,
                "links or special files",
            ):
                materialize_owner_library_seed(
                    source,
                    destination,
                    expected_archive_sha256=digest,
                    expected_source_count=6,
                    expected_game_count=6,
                )
            self.assertFalse(destination.exists())

    def test_manifest_byte_identity_tampering_is_rejected_canonically(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            files = _seed_files()
            files["owner-6.pgn"] = b'[Event "Tampered"]\n[Result "*"]\n\n*\n'
            source = work / "seed.zip"
            digest = _zip(source, files)
            destination = work / "published"

            with self.assertRaisesRegex(
                OwnerLibrarySeedMaterializeError,
                "canonical validation/import",
            ):
                materialize_owner_library_seed(
                    source,
                    destination,
                    expected_archive_sha256=digest,
                    expected_source_count=6,
                    expected_game_count=6,
                )
            self.assertFalse(destination.exists())

    def test_destination_appearing_after_qualification_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            source = work / "seed.zip"
            digest = _zip(source, _seed_files())
            destination = work / "published"
            real_qualify = __import__(
                "scripts.materialize_owner_library_seed",
                fromlist=["_qualify_seed"],
            )._qualify_seed

            def qualify_then_reserve(root: Path, **kwargs):
                result = real_qualify(root, **kwargs)
                destination.mkdir()
                (destination / "owner-marker.txt").write_text(
                    "must survive",
                    encoding="utf-8",
                )
                return result

            with mock.patch(
                "scripts.materialize_owner_library_seed._qualify_seed",
                side_effect=qualify_then_reserve,
            ):
                with self.assertRaisesRegex(
                    OwnerLibrarySeedMaterializeError,
                    "without replacement",
                ):
                    materialize_owner_library_seed(
                        source,
                        destination,
                        expected_archive_sha256=digest,
                        expected_source_count=6,
                        expected_game_count=6,
                    )

            self.assertEqual(
                (destination / "owner-marker.txt").read_text(encoding="utf-8"),
                "must survive",
            )
            self.assertFalse((destination / "manifest.json").exists())

    def test_exact_acceptance_counts_are_enforced_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            source = work / "seed.zip"
            digest = _zip(source, _seed_files())
            destination = work / "published"

            with self.assertRaisesRegex(
                OwnerLibrarySeedMaterializeError,
                "source count mismatch",
            ):
                materialize_owner_library_seed(
                    source,
                    destination,
                    expected_archive_sha256=digest,
                    expected_source_count=5,
                    expected_game_count=6,
                )
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
