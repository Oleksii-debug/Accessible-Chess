from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import acs.user_library_seed as seed_module
from acs.user_library_seed import (
    BUNDLE_KIND,
    SCHEMA_VERSION,
    UserLibrarySeedError,
    load_user_library_seed,
)


_PGN = """[Event "Private seed"]
[White "A"]
[Black "B"]
[Result "*"]

1. e4 e5 *
"""


class UserLibrarySeedParentSafetyTests(unittest.TestCase):
    def _write_seed(self, root: Path) -> None:
        root.mkdir()
        payload = _PGN.encode("utf-8")
        (root / "book.pgn").write_bytes(payload)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "bundle_kind": BUNDLE_KIND,
            "runtime_network_required": False,
            "ai_required": False,
            "files": [
                {
                    "file": "book.pgn",
                    "display_name": "Private seed",
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            ],
        }
        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def _set_display_name(self, root: Path, value: str) -> None:
        path = root / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["files"][0]["display_name"] = value
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def test_direct_parent_and_seed_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "release-content"
            parent.mkdir()
            root = parent / "user-library-seed"
            self._write_seed(root)

            loaded = load_user_library_seed(root)

            self.assertEqual(loaded.root, root)
            self.assertEqual(tuple(entry.file_name for entry in loaded.entries), ("book.pgn",))
            self.assertEqual(tuple(entry.display_name for entry in loaded.entries), ("Private seed",))

    def test_redirected_parent_is_rejected_before_manifest_ingress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            real_parent = base / "real-release-content"
            real_parent.mkdir()
            self._write_seed(real_parent / "user-library-seed")
            redirected_parent = base / "release-content"
            try:
                redirected_parent.symlink_to(real_parent, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlink unavailable on this host: {type(exc).__name__}")

            redirected_root = redirected_parent / "user-library-seed"
            self.assertTrue(redirected_root.is_dir())
            with self.assertRaisesRegex(
                UserLibrarySeedError,
                "user Library seed parent directory must be direct",
            ):
                load_user_library_seed(redirected_root)

    def test_display_name_is_not_silently_whitespace_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "release-content"
            parent.mkdir()
            root = parent / "user-library-seed"
            self._write_seed(root)
            self._set_display_name(root, " Private seed ")

            with self.assertRaisesRegex(UserLibrarySeedError, "display name is invalid"):
                load_user_library_seed(root)

    def test_display_name_rejects_multiline_control_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "release-content"
            parent.mkdir()
            root = parent / "user-library-seed"
            self._write_seed(root)
            self._set_display_name(root, "Private seed\nInjected label")

            with self.assertRaisesRegex(UserLibrarySeedError, "display name is invalid"):
                load_user_library_seed(root)

    def test_same_size_manifest_inode_swap_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "release-content"
            parent.mkdir()
            root = parent / "user-library-seed"
            self._write_seed(root)
            manifest_path = root / "manifest.json"
            original = manifest_path.read_bytes()
            replacement_path = root / "replacement.json"
            replacement = json.loads(original.decode("utf-8"))
            replacement["files"][0]["display_name"] = "Foreign seed"
            replacement_bytes = json.dumps(
                replacement,
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            self.assertEqual(
                len(original),
                len(replacement_bytes),
                "regression requires a same-size manifest replacement",
            )
            replacement_path.write_bytes(replacement_bytes)

            real_open = seed_module.Path.open
            injected = False

            def swap_before_open(candidate: Path, *args, **kwargs):
                nonlocal injected
                if candidate == manifest_path and not injected:
                    os.replace(replacement_path, manifest_path)
                    injected = True
                return real_open(candidate, *args, **kwargs)

            with mock.patch.object(
                seed_module.Path,
                "open",
                autospec=True,
                side_effect=swap_before_open,
            ):
                with self.assertRaisesRegex(
                    UserLibrarySeedError,
                    "manifest changed while reading",
                ):
                    load_user_library_seed(root)

            self.assertTrue(injected)
            self.assertEqual(
                "Foreign seed",
                json.loads(manifest_path.read_text(encoding="utf-8"))["files"][0]["display_name"],
                "foreign replacement was not preserved after rejection",
            )

    def test_same_inode_same_size_manifest_rewrite_during_open_read_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "release-content"
            parent.mkdir()
            root = parent / "user-library-seed"
            self._write_seed(root)
            manifest_path = root / "manifest.json"
            original = manifest_path.read_bytes()
            original_stat = manifest_path.stat()
            replacement = json.loads(original.decode("utf-8"))
            replacement["files"][0]["display_name"] = "Foreign seed"
            replacement_bytes = json.dumps(
                replacement,
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            self.assertEqual(
                len(original),
                len(replacement_bytes),
                "regression requires an in-place same-size manifest rewrite",
            )

            real_open = seed_module.Path.open
            injected = False

            class MutatingManifestHandle:
                def __init__(self, handle):
                    self._handle = handle
                    self._mutated = False

                def __enter__(self):
                    self._handle.__enter__()
                    return self

                def __exit__(self, exc_type, exc, traceback):
                    result = self._handle.__exit__(exc_type, exc, traceback)
                    if self._mutated:
                        os.utime(
                            manifest_path,
                            ns=(
                                original_stat.st_atime_ns,
                                original_stat.st_mtime_ns + 2_000_000_000,
                            ),
                        )
                    return result

                def fileno(self):
                    return self._handle.fileno()

                def read(self, size=-1):
                    nonlocal injected
                    if not self._mutated:
                        self._handle.seek(0)
                        self._handle.write(replacement_bytes)
                        self._handle.flush()
                        os.fsync(self._handle.fileno())
                        self._handle.seek(0)
                        self._mutated = True
                        injected = True
                    return self._handle.read(size)

            def mutate_during_read(candidate: Path, *args, **kwargs):
                if candidate == manifest_path and not injected:
                    return MutatingManifestHandle(real_open(candidate, "r+b"))
                return real_open(candidate, *args, **kwargs)

            with mock.patch.object(
                seed_module.Path,
                "open",
                autospec=True,
                side_effect=mutate_during_read,
            ):
                with self.assertRaisesRegex(
                    UserLibrarySeedError,
                    "manifest changed while reading",
                ):
                    load_user_library_seed(root)

            self.assertTrue(injected)
            rewritten_stat = manifest_path.stat()
            self.assertTrue(
                os.path.samestat(original_stat, rewritten_stat),
                "regression must mutate the original inode rather than replace it",
            )
            self.assertEqual(original_stat.st_size, rewritten_stat.st_size)
            self.assertEqual(
                "Foreign seed",
                json.loads(manifest_path.read_text(encoding="utf-8"))["files"][0]["display_name"],
            )

    def test_same_size_pgn_swap_before_open_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "release-content"
            parent.mkdir()
            root = parent / "user-library-seed"
            self._write_seed(root)
            loaded = load_user_library_seed(root)
            source_path = root / "book.pgn"
            original = source_path.read_bytes()
            replacement_path = root / "replacement.pgn"
            replacement = original.replace(b"e4", b"d4", 1)
            self.assertNotEqual(original, replacement)
            self.assertEqual(
                len(original),
                len(replacement),
                "regression requires a same-size PGN replacement",
            )
            replacement_path.write_bytes(replacement)

            real_open = seed_module.Path.open
            injected = False

            def swap_before_open(candidate: Path, *args, **kwargs):
                nonlocal injected
                if candidate == source_path and not injected:
                    os.replace(replacement_path, source_path)
                    injected = True
                return real_open(candidate, *args, **kwargs)

            with mock.patch.object(
                seed_module.Path,
                "open",
                autospec=True,
                side_effect=swap_before_open,
            ):
                with self.assertRaisesRegex(
                    UserLibrarySeedError,
                    "PGN changed while reading",
                ):
                    seed_module._verified_source_bytes(loaded, loaded.entries[0])

            self.assertTrue(injected)

    def test_identity_fallback_compares_only_complete_identities(self) -> None:
        with mock.patch.object(
            seed_module.os.path,
            "samestat",
            side_effect=OSError("identity unavailable"),
        ):
            self.assertTrue(
                seed_module._same_file_identity(
                    mock.Mock(st_dev=7, st_ino=11),
                    mock.Mock(st_dev=7, st_ino=11),
                )
            )
            self.assertFalse(
                seed_module._same_file_identity(
                    mock.Mock(st_dev=7, st_ino=11),
                    mock.Mock(st_dev=7, st_ino=12),
                )
            )

    def test_identity_fallback_fails_closed_without_stable_fields(self) -> None:
        with mock.patch.object(
            seed_module.os.path,
            "samestat",
            side_effect=OSError("identity unavailable"),
        ):
            self.assertFalse(seed_module._same_file_identity(object(), object()))

    def test_snapshot_comparison_fails_closed_without_change_metadata(self) -> None:
        first = mock.Mock(st_dev=7, st_ino=11, st_size=10)
        second = mock.Mock(st_dev=7, st_ino=11, st_size=10)
        with mock.patch.object(seed_module.os.path, "samestat", return_value=True):
            self.assertFalse(seed_module._same_file_snapshot(first, second))


if __name__ == "__main__":
    unittest.main()
