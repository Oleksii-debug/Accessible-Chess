from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import acs.version2_portable_package as portable_module
from acs.version2_package_assembler import _write_checksums
from acs.version2_package_preflight import (
    CHECKSUMS_NAME,
    MANIFEST_NAME,
    V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
    V2_PACKAGE_PROFILE,
    Version2PackagePreflightError,
)
from acs.version2_portable_package import (
    PORTABLE_PACKAGE_PROFILE,
    PORTABLE_SOURCE_CHECKSUMS,
    PORTABLE_SOURCE_MANIFEST,
    PORTABLE_SOURCE_METADATA_DIR,
    Version2PortablePackageError,
    assemble_portable_oneclick_tree,
    validate_portable_oneclick_tree,
    write_portable_oneclick_zip,
)


_SHA = "a" * 40


def _pe(path: Path, size: int = 2048) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"MZ" + b"\0" * (size - 2))


def _portable_fixture(root: Path, *, with_seed: bool = False) -> None:
    _pe(root / "AccessibleChess.exe")
    _pe(root / "App" / "AccessibleChess.exe")
    (root / "App" / "AccessibleChess.exe.config").write_text("<configuration />", encoding="utf-8")
    (root / "THIRD_PARTY_NOTICES").mkdir(parents=True)
    (root / "THIRD_PARTY_NOTICES" / "NOTICE.txt").write_text("test notice", encoding="utf-8")
    (root / "Посібник.docx").write_bytes(b"doc-one")
    (root / "Опис.docx").write_bytes(b"doc-two")
    if with_seed:
        seed = root / "App" / "release-content" / "user-library-seed"
        seed.mkdir(parents=True)
        (seed / "manifest.json").write_text("{}", encoding="utf-8")
    source_metadata = root / PORTABLE_SOURCE_METADATA_DIR
    source_metadata.mkdir()
    source_manifest = {
        "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
        "product": "Accessible Chess",
        "package_profile": V2_PACKAGE_PROFILE,
        "integration_sha": _SHA,
    }
    source_manifest_path = source_metadata / MANIFEST_NAME
    source_manifest_path.write_text(
        json.dumps(source_manifest, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    source_entries = {
        MANIFEST_NAME: hashlib.sha256(source_manifest_path.read_bytes()).hexdigest(),
    }
    for path in (root / "App").rglob("*"):
        if path.is_file():
            relative = "AccessibleChess/" + path.relative_to(root / "App").as_posix()
            source_entries[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in (root / "THIRD_PARTY_NOTICES").rglob("*"):
        if path.is_file():
            relative = "THIRD_PARTY_NOTICES/" + path.relative_to(root / "THIRD_PARTY_NOTICES").as_posix()
            source_entries[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    source_checksums_path = source_metadata / CHECKSUMS_NAME
    source_checksums_path.write_text(
        "".join(
            f"{digest}  {relative}\n"
            for relative, digest in sorted(source_entries.items())
        ),
        encoding="utf-8",
    )

    manifest = {
        "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
        "product": "Accessible Chess",
        "package_profile": PORTABLE_PACKAGE_PROFILE,
        "source_package_profile": V2_PACKAGE_PROFILE,
        "source_manifest": PORTABLE_SOURCE_MANIFEST,
        "source_manifest_sha256": hashlib.sha256(source_manifest_path.read_bytes()).hexdigest(),
        "source_checksums": PORTABLE_SOURCE_CHECKSUMS,
        "source_checksums_sha256": hashlib.sha256(source_checksums_path.read_bytes()).hexdigest(),
        "integration_sha": _SHA,
        "launcher": "AccessibleChess.exe",
        "application_directory": "App",
        "application_executable": "App/AccessibleChess.exe",
        "package_local_appdata": "data/AccessibleChess",
        "launch_report": "launch-report.txt",
        "word_documents": ["Посібник.docx", "Опис.docx"],
        "human_tested": False,
        "nvda_verified": False,
    }
    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_checksums(root)


class PortableTreeTests(unittest.TestCase):
    def test_raw_portable_docx_filename_rejects_path_syntax_before_path_parsing(self) -> None:
        for name in (
            r"C:\\owner.docx",
            r"..\\owner.docx",
            "nested/owner.docx",
            r"\\server\\share\\owner.docx",
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "filename is unsafe",
                ):
                    portable_module._portable_docx_filename(name)

    def test_validator_rejects_raw_manifest_docx_path_before_root_join(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            manifest_path = root / MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["word_documents"][0] = r"C:\\owner.docx"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                Version2PortablePackageError,
                "filename is unsafe",
            ):
                validate_portable_oneclick_tree(
                    root,
                    expected_integration_sha=_SHA,
                )

    def test_portable_docx_name_accepts_win32_safe_unicode(self) -> None:
        name = "Доступні шахи — посібник.docx"
        with mock.patch.object(
            portable_module,
            "_relative_token",
            wraps=portable_module._relative_token,
        ) as authority:
            self.assertEqual(portable_module._portable_docx_name(Path(name)), name)
        authority.assert_called_once_with(
            name,
            label="portable Word document filename",
        )

    def test_portable_docx_name_rejects_win32_device_aliases(self) -> None:
        for name in (
            "CON.docx",
            "CON .docx",
            "nul.DOCX",
            "PrN.docx",
            "COM1.docx",
            "LPT9.docx",
            "COM¹.docx",
            "lpt³.docx",
            "CONIN$.docx",
            "conout$.docx",
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "filename is unsafe",
                ):
                    portable_module._portable_docx_name(Path(name))

    def test_portable_docx_name_rejects_win32_forbidden_and_malformed_unicode(self) -> None:
        invalid = [
            "owner?.docx",
            "owner<guide>.docx",
            "owner|guide.docx",
            "owner" + chr(31) + ".docx",
            "owner" + chr(0xD800) + ".docx",
        ]
        for name in invalid:
            with self.subTest(name=repr(name)):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "filename is unsafe",
                ):
                    portable_module._portable_docx_name(Path(name))

    def test_portable_docx_name_uses_utf16_component_limit(self) -> None:
        astral = chr(0x1F642)
        accepted = astral * 125 + ".docx"
        rejected = astral * 126 + ".docx"
        self.assertEqual(len(accepted.encode("utf-16-le")) // 2, 255)
        self.assertGreater(len(rejected.encode("utf-16-le")) // 2, 255)
        self.assertEqual(portable_module._portable_docx_name(Path(accepted)), accepted)
        with self.assertRaisesRegex(
            Version2PortablePackageError,
            "filename is unsafe",
        ):
            portable_module._portable_docx_name(Path(rejected))

    def _assert_same_inode_same_size_stable_read_rejected(self, reader) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "stable.bin"
            original = b"A" * 4096
            replacement = b"B" * len(original)
            path.write_bytes(original)
            original_stat = path.stat()
            real_open = portable_module.Path.open
            injected = False

            class MutatingHandle:
                def __init__(self, handle):
                    self._handle = handle
                    self._mutated = False

                def __enter__(self):
                    self._handle.__enter__()
                    return self

                def __exit__(self, exc_type, exc, traceback):
                    return self._handle.__exit__(exc_type, exc, traceback)

                def fileno(self):
                    return self._handle.fileno()

                def read(self, size=-1):
                    nonlocal injected
                    if not self._mutated:
                        self._handle.seek(0)
                        self._handle.write(replacement)
                        self._handle.flush()
                        os.fsync(self._handle.fileno())
                        os.utime(
                            path,
                            ns=(
                                original_stat.st_atime_ns,
                                original_stat.st_mtime_ns + 2_000_000_000,
                            ),
                        )
                        self._handle.seek(0)
                        self._mutated = True
                        injected = True
                    return self._handle.read(size)

            def mutate_during_read(candidate: Path, *args, **kwargs):
                if candidate == path and not injected:
                    return MutatingHandle(real_open(candidate, "r+b"))
                return real_open(candidate, *args, **kwargs)

            with mock.patch.object(
                portable_module.Path,
                "open",
                autospec=True,
                side_effect=mutate_during_read,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "stable test file changed while being read",
                ):
                    reader(path)

            self.assertTrue(injected)
            rewritten_stat = path.stat()
            self.assertTrue(
                os.path.samestat(original_stat, rewritten_stat),
                "regression must mutate the original inode rather than replace it",
            )
            self.assertEqual(original_stat.st_size, rewritten_stat.st_size)
            self.assertEqual(path.read_bytes(), replacement)

    def test_file_identity_fallback_rejects_unknown_or_zero_identity(self):
        valid = SimpleNamespace(st_dev=11, st_ino=22)
        same = SimpleNamespace(st_dev=11, st_ino=22)
        invalid_pairs = (
            (
                SimpleNamespace(st_dev=0, st_ino=0),
                SimpleNamespace(st_dev=0, st_ino=0),
            ),
            (
                SimpleNamespace(st_dev=11, st_ino=0),
                SimpleNamespace(st_dev=11, st_ino=0),
            ),
            (
                SimpleNamespace(st_dev=None, st_ino=None),
                SimpleNamespace(st_dev=None, st_ino=None),
            ),
            (
                SimpleNamespace(st_dev=True, st_ino=22),
                SimpleNamespace(st_dev=True, st_ino=22),
            ),
        )

        with mock.patch.object(
            portable_module.os.path,
            "samestat",
            side_effect=OSError("identity unavailable"),
        ):
            self.assertTrue(
                portable_module._complete_file_identity(valid, same)
            )
            for left, right in invalid_pairs:
                with self.subTest(left=left, right=right):
                    self.assertFalse(
                        portable_module._complete_file_identity(left, right)
                    )

    def test_stable_change_metadata_uses_platform_reliable_fields(self):
        sample = SimpleNamespace(st_mtime_ns=123, st_ctime_ns=456)

        with mock.patch.object(portable_module.os, "name", "nt"):
            self.assertEqual(
                portable_module._stable_change_metadata(sample),
                (123,),
            )

        with mock.patch.object(portable_module.os, "name", "posix"):
            self.assertEqual(
                portable_module._stable_change_metadata(sample),
                (123, 456),
            )

        incomplete = SimpleNamespace(st_mtime_ns=123, st_ctime_ns=None)
        with mock.patch.object(portable_module.os, "name", "posix"):
            self.assertIsNone(
                portable_module._stable_change_metadata(incomplete),
            )

    def test_snapshot_metadata_rejects_invalid_stat_scalars(self):
        stable = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
            st_ctime_ns=456,
        )
        invalid = (
            SimpleNamespace(
                st_dev=11,
                st_ino=22,
                st_size=-1,
                st_mtime_ns=123,
                st_ctime_ns=456,
            ),
            SimpleNamespace(
                st_dev=11,
                st_ino=22,
                st_size=True,
                st_mtime_ns=123,
                st_ctime_ns=456,
            ),
            SimpleNamespace(
                st_dev=11,
                st_ino=22,
                st_size=4096,
                st_mtime_ns=-1,
                st_ctime_ns=456,
            ),
            SimpleNamespace(
                st_dev=11,
                st_ino=22,
                st_size=4096,
                st_mtime_ns=True,
                st_ctime_ns=456,
            ),
        )
        with mock.patch.object(
            portable_module,
            "_complete_file_identity",
            return_value=True,
        ):
            for candidate in invalid:
                with self.subTest(candidate=candidate):
                    self.assertFalse(
                        portable_module._same_file_snapshot(stable, candidate),
                    )

        with mock.patch.object(portable_module.os, "name", "nt"):
            self.assertIsNone(
                portable_module._stable_change_metadata(
                    SimpleNamespace(st_mtime_ns=-1),
                )
            )
            self.assertIsNone(
                portable_module._stable_change_metadata(
                    SimpleNamespace(st_mtime_ns=True),
                )
            )

        with mock.patch.object(portable_module.os, "name", "posix"):
            self.assertIsNone(
                portable_module._stable_change_metadata(
                    SimpleNamespace(st_mtime_ns=123, st_ctime_ns=-1),
                )
            )
            self.assertIsNone(
                portable_module._stable_change_metadata(
                    SimpleNamespace(st_mtime_ns=123, st_ctime_ns=True),
                )
            )

    def test_windows_snapshot_uses_mtime_without_ctime_and_fails_closed_without_mtime(self):
        with mock.patch.object(portable_module.os, "name", "nt"):
            self.assertEqual(
                portable_module._stable_change_metadata(
                    SimpleNamespace(st_mtime_ns=123),
                ),
                (123,),
            )
            self.assertIsNone(
                portable_module._stable_change_metadata(
                    SimpleNamespace(st_mtime_ns=None, st_ctime_ns=456),
                ),
            )

    def test_windows_snapshot_ignores_creation_time_when_mtime_is_stable(self):
        first = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
            st_ctime_ns=456,
        )
        second = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
            st_ctime_ns=999,
        )

        with mock.patch.object(portable_module.os, "name", "nt"):
            with mock.patch.object(
                portable_module,
                "_complete_file_identity",
                return_value=True,
            ):
                self.assertTrue(
                    portable_module._same_file_snapshot(first, second),
                )

    def test_stable_bytes_accepts_windows_creation_time_drift(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "stable.bin"
            payload = b"windows-stable-read"
            path.write_bytes(payload)
            real_fstat = portable_module.os.fstat

            def drifted_fstat(fd):
                actual = real_fstat(fd)
                return SimpleNamespace(
                    st_mode=actual.st_mode,
                    st_dev=actual.st_dev,
                    st_ino=actual.st_ino,
                    st_size=actual.st_size,
                    st_mtime_ns=actual.st_mtime_ns,
                    st_ctime_ns=actual.st_ctime_ns + 1,
                )

            with mock.patch.object(portable_module.os, "name", "nt"):
                with mock.patch.object(
                    portable_module.os,
                    "fstat",
                    side_effect=drifted_fstat,
                ):
                    self.assertEqual(
                        portable_module._stable_bytes(
                            path,
                            label="stable test file",
                            maximum=8192,
                        ),
                        payload,
                    )

    def test_stable_digest_accepts_windows_creation_time_drift(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "stable.bin"
            payload = b"windows-stable-read"
            path.write_bytes(payload)
            real_fstat = portable_module.os.fstat

            def drifted_fstat(fd):
                actual = real_fstat(fd)
                return SimpleNamespace(
                    st_mode=actual.st_mode,
                    st_dev=actual.st_dev,
                    st_ino=actual.st_ino,
                    st_size=actual.st_size,
                    st_mtime_ns=actual.st_mtime_ns,
                    st_ctime_ns=actual.st_ctime_ns + 1,
                )

            with mock.patch.object(portable_module.os, "name", "nt"):
                with mock.patch.object(
                    portable_module.os,
                    "fstat",
                    side_effect=drifted_fstat,
                ):
                    self.assertEqual(
                        portable_module._stable_digest(
                            path,
                            label="stable test file",
                            maximum=8192,
                        ),
                        hashlib.sha256(payload).hexdigest(),
                    )

    def test_windows_stable_reads_accept_fstat_without_creation_time(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "stable.bin"
            payload = b"windows-stable-read"
            path.write_bytes(payload)
            real_fstat = portable_module.os.fstat

            def without_ctime(fd):
                actual = real_fstat(fd)
                return SimpleNamespace(
                    st_mode=actual.st_mode,
                    st_dev=actual.st_dev,
                    st_ino=actual.st_ino,
                    st_size=actual.st_size,
                    st_mtime_ns=actual.st_mtime_ns,
                )

            with mock.patch.object(portable_module.os, "name", "nt"):
                with mock.patch.object(
                    portable_module.os,
                    "fstat",
                    side_effect=without_ctime,
                ):
                    self.assertEqual(
                        portable_module._stable_bytes(
                            path,
                            label="stable test file",
                            maximum=8192,
                        ),
                        payload,
                    )
                    self.assertEqual(
                        portable_module._stable_digest(
                            path,
                            label="stable test file",
                            maximum=8192,
                        ),
                        hashlib.sha256(payload).hexdigest(),
                    )

    def test_windows_snapshot_rejects_mtime_change_even_when_creation_time_is_stable(self):
        first = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
            st_ctime_ns=456,
        )
        second = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=124,
            st_ctime_ns=456,
        )

        with mock.patch.object(portable_module.os, "name", "nt"):
            with mock.patch.object(
                portable_module,
                "_complete_file_identity",
                return_value=True,
            ):
                self.assertFalse(
                    portable_module._same_file_snapshot(first, second),
                )

    def test_publication_snapshot_ignores_namespace_ctime_but_requires_mtime(self):
        first = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
            st_ctime_ns=456,
        )
        ctime_drift = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=123,
            st_ctime_ns=999,
        )
        mtime_drift = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=124,
            st_ctime_ns=456,
        )
        missing_mtime = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_ctime_ns=456,
        )
        negative_mtime = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=-1,
            st_ctime_ns=456,
        )
        bool_mtime = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=4096,
            st_mtime_ns=True,
            st_ctime_ns=456,
        )
        negative_size = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=-1,
            st_mtime_ns=123,
            st_ctime_ns=456,
        )
        bool_size = SimpleNamespace(
            st_dev=11,
            st_ino=22,
            st_size=True,
            st_mtime_ns=123,
            st_ctime_ns=456,
        )

        self.assertTrue(
            portable_module._same_publication_snapshot(first, ctime_drift),
        )
        self.assertFalse(
            portable_module._same_publication_snapshot(first, mtime_drift),
        )
        self.assertFalse(
            portable_module._same_publication_snapshot(first, missing_mtime),
        )
        for candidate in (
            negative_mtime,
            bool_mtime,
            negative_size,
            bool_size,
        ):
            with self.subTest(candidate=candidate):
                self.assertFalse(
                    portable_module._same_publication_snapshot(first, candidate),
                )

    def test_stable_bytes_rejects_same_inode_same_size_in_place_rewrite(self):
        self._assert_same_inode_same_size_stable_read_rejected(
            lambda path: portable_module._stable_bytes(
                path,
                label="stable test file",
                maximum=8192,
            )
        )

    def test_stable_digest_rejects_same_inode_same_size_in_place_rewrite(self):
        self._assert_same_inode_same_size_stable_read_rejected(
            lambda path: portable_module._stable_digest(
                path,
                label="stable test file",
                maximum=8192,
            )
        )

    def test_stable_reads_fail_closed_without_change_metadata(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "stable.bin"
            path.write_bytes(b"canonical")
            with mock.patch.object(
                portable_module,
                "_stable_change_metadata",
                return_value=None,
            ):
                readers = (
                    lambda: portable_module._stable_bytes(
                        path,
                        label="stable test file",
                        maximum=8192,
                    ),
                    lambda: portable_module._stable_digest(
                        path,
                        label="stable test file",
                        maximum=8192,
                    ),
                )
                for reader in readers:
                    with self.subTest(reader=reader):
                        with self.assertRaisesRegex(
                            Version2PortablePackageError,
                            "stable test file changed while being read",
                        ):
                            reader()

    def test_manifest_and_launcher_authorities_use_stable_reads(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            real_stable_bytes = portable_module._stable_bytes

            with mock.patch.object(
                portable_module,
                "_stable_bytes",
                wraps=real_stable_bytes,
            ) as stable_bytes:
                validate_portable_oneclick_tree(
                    root,
                    expected_integration_sha=_SHA,
                )

            observed = {
                call.kwargs.get("label")
                for call in stable_bytes.call_args_list
            }
            self.assertIn("portable release manifest", observed)
            self.assertIn("portable launcher", observed)

    def test_checksum_paths_use_canonical_windows_safe_grammar(self):
        digest = "0" * 64
        entries = portable_module._checksum_entries(
            f"{digest}  folder\\file.txt\n".encode("utf-8"),
            label="test checksum inventory",
        )
        self.assertEqual(
            entries["folder/file.txt"],
            ("folder/file.txt", digest),
        )

        for unsafe in (
            "..\\escape.txt",
            "folder\\..\\escape.txt",
            "C:\\escape.txt",
            "AUX.txt",
        ):
            with self.subTest(unsafe=unsafe):
                payload = f"{digest}  {unsafe}\n".encode("utf-8")
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "test checksum inventory path is invalid",
                ):
                    portable_module._checksum_entries(
                        payload,
                        label="test checksum inventory",
                    )

        overlong = "\U0001f642" * 126 + "a.txt"
        self.assertGreater(len(overlong.encode("utf-16-le")) // 2, 255)
        with self.assertRaisesRegex(
            Version2PortablePackageError,
            "test checksum inventory path is invalid",
        ):
            portable_module._checksum_entries(
                f"{digest}  folder/{overlong}\n".encode("utf-8"),
                label="test checksum inventory",
            )

        duplicate = (
            f"{digest}  folder/file.txt\n"
            f"{digest}  folder\\file.txt\n"
        ).encode("utf-8")
        with self.assertRaisesRegex(
            Version2PortablePackageError,
            "duplicate path",
        ):
            portable_module._checksum_entries(
                duplicate,
                label="test checksum inventory",
            )

    def test_source_manifest_semantics_are_hash_bound_to_same_stable_snapshot(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            manifest = portable_module._manifest(root)
            inventory = portable_module._relative_files(root)
            source_manifest = root / PORTABLE_SOURCE_METADATA_DIR / MANIFEST_NAME
            raced_value = json.loads(source_manifest.read_text(encoding="utf-8"))
            raced_value["race_marker"] = "changed-between-digest-and-parse"
            raced_payload = (
                json.dumps(raced_value, sort_keys=True) + "\n"
            ).encode("utf-8")
            real_stable_bytes = portable_module._stable_bytes
            injected = False

            def mutate_then_read(path: Path, *args, **kwargs):
                nonlocal injected
                if (
                    path == source_manifest
                    and kwargs.get("label") == "canonical source release manifest"
                    and not injected
                ):
                    source_manifest.write_bytes(raced_payload)
                    injected = True
                return real_stable_bytes(path, *args, **kwargs)

            with mock.patch.object(
                portable_module,
                "_stable_bytes",
                side_effect=mutate_then_read,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "portable source-package metadata digest is invalid",
                ):
                    portable_module._validate_preflighted_source_binding(
                        root,
                        integration_sha=_SHA,
                        manifest=manifest,
                        inventory=inventory,
                    )

            self.assertTrue(injected)

    def test_source_checksums_semantics_are_hash_bound_to_same_stable_snapshot(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            manifest = portable_module._manifest(root)
            inventory = portable_module._relative_files(root)
            source_checksums = root / PORTABLE_SOURCE_METADATA_DIR / CHECKSUMS_NAME
            original_lines = source_checksums.read_text(encoding="utf-8").splitlines()
            self.assertGreater(len(original_lines), 1)
            raced_payload = ("\n".join(reversed(original_lines)) + "\n").encode("utf-8")
            self.assertNotEqual(source_checksums.read_bytes(), raced_payload)
            real_stable_bytes = portable_module._stable_bytes
            injected = False

            def mutate_then_read(path: Path, *args, **kwargs):
                nonlocal injected
                if (
                    path == source_checksums
                    and kwargs.get("label") == "canonical source checksum inventory"
                    and not injected
                ):
                    source_checksums.write_bytes(raced_payload)
                    injected = True
                return real_stable_bytes(path, *args, **kwargs)

            with mock.patch.object(
                portable_module,
                "_stable_bytes",
                side_effect=mutate_then_read,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "portable source-package metadata digest is invalid",
                ):
                    portable_module._validate_preflighted_source_binding(
                        root,
                        integration_sha=_SHA,
                        manifest=manifest,
                        inventory=inventory,
                    )

            self.assertTrue(injected)

    def test_launcher_pe_semantics_are_bound_to_checksum_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            launcher = root / "AccessibleChess.exe"
            original = launcher.read_bytes()
            replacement = b"NZ" + original[2:]
            self.assertEqual(len(original), len(replacement))

            replacement_digest = hashlib.sha256(replacement).hexdigest()
            checksum_path = root / CHECKSUMS_NAME
            lines = checksum_path.read_text(encoding="utf-8").splitlines()
            rewritten = []
            replaced = False
            for line in lines:
                if line.endswith("  AccessibleChess.exe"):
                    rewritten.append(
                        f"{replacement_digest}  AccessibleChess.exe"
                    )
                    replaced = True
                else:
                    rewritten.append(line)
            self.assertTrue(replaced)
            checksum_path.write_text(
                "\n".join(rewritten) + "\n",
                encoding="utf-8",
                newline="\n",
            )

            real_launcher_identity = portable_module._launcher_identity
            injected = False

            def identify_then_mutate(path: Path):
                nonlocal injected
                identity_digest = real_launcher_identity(path)
                if path == launcher and not injected:
                    launcher.write_bytes(replacement)
                    injected = True
                return identity_digest

            with mock.patch.object(
                portable_module,
                "_launcher_identity",
                side_effect=identify_then_mutate,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "portable launcher identity is not bound to checksum inventory",
                ):
                    validate_portable_oneclick_tree(
                        root,
                        expected_integration_sha=_SHA,
                    )

            self.assertTrue(injected)
            self.assertEqual(launcher.read_bytes(), replacement)

    def test_release_manifest_semantics_are_bound_to_checksum_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            manifest_path = root / MANIFEST_NAME
            original_payload = manifest_path.read_bytes()
            original_marker = f'"integration_sha": "{_SHA}"'.encode("utf-8")
            replacement_marker = b'"integration_sha": "' + (b"b" * 40) + b'"'
            self.assertIn(original_marker, original_payload)
            replacement_payload = original_payload.replace(
                original_marker,
                replacement_marker,
                1,
            )
            self.assertEqual(len(original_payload), len(replacement_payload))
            self.assertNotEqual(original_payload, replacement_payload)

            replacement_digest = hashlib.sha256(replacement_payload).hexdigest()
            checksum_path = root / CHECKSUMS_NAME
            lines = checksum_path.read_text(encoding="utf-8").splitlines()
            rewritten = []
            replaced = False
            for line in lines:
                if line.endswith(f"  {MANIFEST_NAME}"):
                    rewritten.append(f"{replacement_digest}  {MANIFEST_NAME}")
                    replaced = True
                else:
                    rewritten.append(line)
            self.assertTrue(replaced)
            checksum_path.write_text(
                "\n".join(rewritten) + "\n",
                encoding="utf-8",
                newline="\n",
            )

            real_manifest_snapshot = portable_module._manifest_snapshot
            injected = False

            def parse_then_mutate(candidate_root: Path):
                nonlocal injected
                value, digest = real_manifest_snapshot(candidate_root)
                if candidate_root == root and not injected:
                    manifest_path.write_bytes(replacement_payload)
                    injected = True
                return value, digest

            with mock.patch.object(
                portable_module,
                "_manifest_snapshot",
                side_effect=parse_then_mutate,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "portable release manifest semantics are not bound to checksum inventory",
                ):
                    validate_portable_oneclick_tree(
                        root,
                        expected_integration_sha=_SHA,
                    )

            self.assertTrue(injected)
            self.assertEqual(manifest_path.read_bytes(), replacement_payload)

    def test_accepts_exact_oneclick_topology_without_prebundled_user_state(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            report = validate_portable_oneclick_tree(root, expected_integration_sha=_SHA)
            self.assertEqual(report.integration_sha, _SHA)
            self.assertIn("AccessibleChess.exe", report.inventory)
            self.assertIn("App/AccessibleChess.exe", report.inventory)
            self.assertNotIn("launch-report.txt", report.inventory)
            self.assertFalse((root / "data").exists())

    def test_rejects_bundled_mutable_data_and_stale_launch_report(self):
        for relative in (Path("data") / "AccessibleChess" / "library.acsdb", Path("launch-report.txt")):
            with self.subTest(relative=str(relative)), tempfile.TemporaryDirectory() as raw:
                root = Path(raw) / "portable"
                root.mkdir()
                _portable_fixture(root)
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"stale")
                _write_checksums(root)
                with self.assertRaises(Version2PortablePackageError):
                    validate_portable_oneclick_tree(root, expected_integration_sha=_SHA)

    def test_root_docx_discovery_never_uses_following_is_file_probe(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            unexpected = root / "unexpected.docx"
            unexpected.write_bytes(b"unexpected-document")
            _write_checksums(root)

            real_is_file = Path.is_file

            def reject_follow_probe(path):
                if path == unexpected:
                    raise AssertionError(
                        "portable DOCX discovery followed an unexpected path entry"
                    )
                return real_is_file(path)

            with mock.patch.object(Path, "is_file", new=reject_follow_probe):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "exactly the declared two Word documents",
                ):
                    validate_portable_oneclick_tree(
                        root,
                        expected_integration_sha=_SHA,
                    )

    def test_requires_exact_declared_two_root_docx_files(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            (root / "extra.docx").write_bytes(b"unexpected")
            _write_checksums(root)
            with self.assertRaisesRegex(Version2PortablePackageError, "exactly the declared two"):
                validate_portable_oneclick_tree(root, expected_integration_sha=_SHA)

    def test_rejects_any_undeclared_root_file_even_if_checksummed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            (root / "unexpected.txt").write_text("not part of the user package contract", encoding="utf-8")
            _write_checksums(root)
            with self.assertRaisesRegex(Version2PortablePackageError, "unexpected file"):
                validate_portable_oneclick_tree(root, expected_integration_sha=_SHA)

    def test_checksum_readback_detects_post_assembly_mutation(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            (root / "App" / "AccessibleChess.exe.config").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(
                Version2PortablePackageError,
                "preflighted canonical source|checksum verification",
            ):
                validate_portable_oneclick_tree(root, expected_integration_sha=_SHA)

    def test_rejects_inner_mutation_even_if_outer_checksums_are_rewritten(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            (root / "App" / "AccessibleChess.exe.config").write_text(
                "changed",
                encoding="utf-8",
            )
            _write_checksums(root)
            with self.assertRaisesRegex(
                Version2PortablePackageError,
                "preflighted canonical source",
            ):
                validate_portable_oneclick_tree(root, expected_integration_sha=_SHA)

    def test_validator_terminal_revalidation_rejects_late_member_mutation(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            target = root / "Посібник.docx"
            real_checksum_inventory = portable_module._checksum_inventory
            calls = 0

            def validate_then_mutate(candidate_root, inventory):
                nonlocal calls
                calls += 1
                result = real_checksum_inventory(candidate_root, inventory)
                if calls == 1:
                    target.write_bytes(b"late-unqualified-document-bytes")
                return result

            with mock.patch.object(
                portable_module,
                "_checksum_inventory",
                side_effect=validate_then_mutate,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "portable package checksum verification failed",
                ):
                    validate_portable_oneclick_tree(
                        root,
                        expected_integration_sha=_SHA,
                    )

            self.assertEqual(calls, 2)

    def test_validator_terminal_revalidation_rejects_late_coherent_checksum_rewrite(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            target = root / "Посібник.docx"
            real_checksum_inventory = portable_module._checksum_inventory
            calls = 0

            def validate_then_rewrite_authority(candidate_root, inventory):
                nonlocal calls
                calls += 1
                result = real_checksum_inventory(candidate_root, inventory)
                if calls == 1:
                    target.write_bytes(b"late-but-coherently-checksummed-document")
                    _write_checksums(root)
                return result

            with mock.patch.object(
                portable_module,
                "_checksum_inventory",
                side_effect=validate_then_rewrite_authority,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "portable package checksum authority changed during validation",
                ):
                    validate_portable_oneclick_tree(
                        root,
                        expected_integration_sha=_SHA,
                    )

            self.assertEqual(calls, 2)

    def test_private_seed_requirement_is_explicit_and_package_local(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root, with_seed=True)
            report = validate_portable_oneclick_tree(
                root,
                expected_integration_sha=_SHA,
                require_user_seed=True,
            )
            self.assertGreater(report.total_bytes, 0)

    def test_assembler_reuses_canonical_inner_payload_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            canonical = work / "canonical"
            _pe(canonical / "AccessibleChess" / "AccessibleChess.exe")
            (canonical / "AccessibleChess" / "payload.dat").write_bytes(b"canonical-product-bytes")
            (canonical / "THIRD_PARTY_NOTICES").mkdir(parents=True)
            (canonical / "THIRD_PARTY_NOTICES" / "NOTICE.txt").write_text("notice", encoding="utf-8")
            canonical_manifest = {
                "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
                "product": "Accessible Chess",
                "package_profile": V2_PACKAGE_PROFILE,
                "integration_sha": _SHA,
            }
            (canonical / MANIFEST_NAME).write_text(
                json.dumps(canonical_manifest, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            _write_checksums(canonical)
            launcher = work / "launcher.exe"
            _pe(launcher)
            first = work / "Посібник.docx"
            second = work / "Опис.docx"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            output = work / "portable"

            with mock.patch(
                "acs.version2_portable_package.validate_version2_package_tree",
                return_value=object(),
            ) as canonical_validation:
                report = assemble_portable_oneclick_tree(
                    canonical,
                    launcher,
                    (first, second),
                    output,
                    integration_sha=_SHA,
                )

            self.assertEqual(canonical_validation.call_count, 2)
            first_validation = canonical_validation.call_args_list[0]
            second_validation = canonical_validation.call_args_list[1]
            self.assertEqual(first_validation.args, (canonical,))
            self.assertEqual(
                first_validation.kwargs,
                {"expected_integration_sha": _SHA},
            )
            snapshot_root = Path(second_validation.args[0])
            self.assertNotEqual(snapshot_root, canonical)
            self.assertEqual(
                second_validation.kwargs,
                {"expected_integration_sha": _SHA},
            )
            self.assertFalse(
                snapshot_root.exists(),
                "private canonical snapshot must be cleaned after assembly",
            )
            self.assertEqual((output / "App" / "payload.dat").read_bytes(), b"canonical-product-bytes")
            self.assertEqual((output / "AccessibleChess.exe").read_bytes(), launcher.read_bytes())
            self.assertTrue((output / PORTABLE_SOURCE_METADATA_DIR / MANIFEST_NAME).is_file())
            self.assertTrue((output / PORTABLE_SOURCE_METADATA_DIR / CHECKSUMS_NAME).is_file())
            self.assertFalse((output / "data").exists())
            self.assertEqual(report.integration_sha, _SHA)

    def test_assembler_rejects_launcher_rewrite_after_input_qualification(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            canonical = work / "canonical"
            _pe(canonical / "AccessibleChess" / "AccessibleChess.exe")
            (canonical / "THIRD_PARTY_NOTICES").mkdir(parents=True)
            (canonical / "THIRD_PARTY_NOTICES" / "NOTICE.txt").write_text(
                "notice",
                encoding="utf-8",
            )
            (canonical / MANIFEST_NAME).write_text(
                json.dumps(
                    {
                        "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
                        "product": "Accessible Chess",
                        "package_profile": V2_PACKAGE_PROFILE,
                        "integration_sha": _SHA,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            _write_checksums(canonical)
            launcher = work / "launcher.exe"
            _pe(launcher)
            first = work / "Посібник.docx"
            second = work / "Опис.docx"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            output = work / "portable"

            real_identity = portable_module._launcher_identity
            injected = False

            def qualify_then_mutate(path: Path):
                nonlocal injected
                digest = real_identity(path)
                if path == launcher and not injected:
                    payload = launcher.read_bytes()
                    launcher.write_bytes(b"MZ" + b"X" * (len(payload) - 2))
                    injected = True
                return digest

            with mock.patch(
                "acs.version2_portable_package.validate_version2_package_tree",
                return_value=object(),
            ), mock.patch.object(
                portable_module,
                "_launcher_identity",
                side_effect=qualify_then_mutate,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "portable launcher source changed after qualification",
                ):
                    assemble_portable_oneclick_tree(
                        canonical,
                        launcher,
                        (first, second),
                        output,
                        integration_sha=_SHA,
                    )

            self.assertTrue(injected)
            self.assertFalse(output.exists())

    def test_assembler_rejects_docx_rewrite_after_input_qualification(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            canonical = work / "canonical"
            _pe(canonical / "AccessibleChess" / "AccessibleChess.exe")
            (canonical / "THIRD_PARTY_NOTICES").mkdir(parents=True)
            (canonical / "THIRD_PARTY_NOTICES" / "NOTICE.txt").write_text(
                "notice",
                encoding="utf-8",
            )
            (canonical / MANIFEST_NAME).write_text(
                json.dumps(
                    {
                        "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
                        "product": "Accessible Chess",
                        "package_profile": V2_PACKAGE_PROFILE,
                        "integration_sha": _SHA,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            _write_checksums(canonical)
            launcher = work / "launcher.exe"
            _pe(launcher)
            first = work / "Посібник.docx"
            second = work / "Опис.docx"
            first.write_bytes(b"owner-doc-one")
            second.write_bytes(b"owner-doc-two")
            output = work / "portable"

            real_digest = portable_module._stable_digest
            injected = False

            def qualify_then_mutate(path: Path, *args, **kwargs):
                nonlocal injected
                digest = real_digest(path, *args, **kwargs)
                if (
                    path == first
                    and kwargs.get("label") == "portable Word document source"
                    and not injected
                ):
                    first.write_bytes(b"changed-doc!!")
                    injected = True
                return digest

            with mock.patch(
                "acs.version2_portable_package.validate_version2_package_tree",
                return_value=object(),
            ), mock.patch.object(
                portable_module,
                "_stable_digest",
                side_effect=qualify_then_mutate,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "portable Word document source changed after qualification",
                ):
                    assemble_portable_oneclick_tree(
                        canonical,
                        launcher,
                        (first, second),
                        output,
                        integration_sha=_SHA,
                    )

            self.assertTrue(injected)
            self.assertFalse(output.exists())

    def test_assembler_cleans_private_snapshot_if_staging_setup_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            canonical = work / "canonical"
            _pe(canonical / "AccessibleChess" / "AccessibleChess.exe")
            (canonical / "THIRD_PARTY_NOTICES").mkdir(parents=True)
            (canonical / "THIRD_PARTY_NOTICES" / "NOTICE.txt").write_text(
                "notice",
                encoding="utf-8",
            )
            (canonical / MANIFEST_NAME).write_text(
                json.dumps(
                    {
                        "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
                        "product": "Accessible Chess",
                        "package_profile": V2_PACKAGE_PROFILE,
                        "integration_sha": _SHA,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            _write_checksums(canonical)
            launcher = work / "launcher.exe"
            _pe(launcher)
            first = work / "Посібник.docx"
            second = work / "Опис.docx"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            output = work / "portable"

            real_mkdtemp = tempfile.mkdtemp
            created_snapshot: list[Path] = []

            def fail_staging(*args, **kwargs):
                if not created_snapshot:
                    path = Path(real_mkdtemp(*args, **kwargs))
                    created_snapshot.append(path)
                    return str(path)
                raise OSError("simulated staging setup failure")

            with mock.patch(
                "acs.version2_portable_package.validate_version2_package_tree",
                return_value=object(),
            ), mock.patch.object(
                portable_module.tempfile,
                "mkdtemp",
                side_effect=fail_staging,
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "simulated staging setup failure",
                ):
                    assemble_portable_oneclick_tree(
                        canonical,
                        launcher,
                        (first, second),
                        output,
                        integration_sha=_SHA,
                    )

            self.assertEqual(len(created_snapshot), 1)
            self.assertFalse(created_snapshot[0].exists())
            self.assertFalse(output.exists())

    def test_assembler_revalidates_private_snapshot_after_live_source_changes(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            canonical = work / "canonical"
            _pe(canonical / "AccessibleChess" / "AccessibleChess.exe")
            (canonical / "AccessibleChess" / "payload.dat").write_bytes(
                b"initial-qualified-payload"
            )
            (canonical / "THIRD_PARTY_NOTICES").mkdir(parents=True)
            (canonical / "THIRD_PARTY_NOTICES" / "NOTICE.txt").write_text(
                "notice",
                encoding="utf-8",
            )
            canonical_manifest = {
                "manifest_schema": V2_PACKAGE_MANIFEST_SCHEMA_VERSION,
                "product": "Accessible Chess",
                "package_profile": V2_PACKAGE_PROFILE,
                "integration_sha": _SHA,
            }
            (canonical / MANIFEST_NAME).write_text(
                json.dumps(canonical_manifest, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            _write_checksums(canonical)

            launcher = work / "launcher.exe"
            _pe(launcher)
            first = work / "Посібник.docx"
            second = work / "Опис.docx"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            output = work / "portable"

            calls = 0

            def validate_then_race(candidate, *, expected_integration_sha):
                nonlocal calls
                self.assertEqual(expected_integration_sha, _SHA)
                candidate = Path(candidate)
                calls += 1
                if calls == 1:
                    self.assertEqual(candidate, canonical)
                    # Simulate a coherent rewrite after the live source was
                    # declared valid.  The outer portable contract can bind
                    # these bytes and checksums, but the canonical policy must
                    # get a second chance to reject the newly bundled raw
                    # source before it becomes App/.
                    injected = canonical / "AccessibleChess" / "injected.py"
                    injected.write_text("print('must never ship')\n", encoding="utf-8")
                    _write_checksums(canonical)
                    return object()
                self.assertNotEqual(candidate, canonical)
                self.assertTrue(
                    (candidate / "AccessibleChess" / "injected.py").is_file()
                )
                raise Version2PackagePreflightError(
                    "raw source must not be bundled"
                )

            with mock.patch(
                "acs.version2_portable_package.validate_version2_package_tree",
                side_effect=validate_then_race,
            ):
                with self.assertRaisesRegex(
                    Version2PackagePreflightError,
                    "raw source must not be bundled",
                ):
                    assemble_portable_oneclick_tree(
                        canonical,
                        launcher,
                        (first, second),
                        output,
                        integration_sha=_SHA,
                    )

            self.assertEqual(calls, 2)
            self.assertFalse(output.exists())

    def test_zip_is_deterministic_and_byte_verified(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            root = work / "portable"
            root.mkdir()
            _portable_fixture(root)
            first = write_portable_oneclick_zip(root, work / "first.zip", expected_integration_sha=_SHA)
            second = write_portable_oneclick_zip(root, work / "second.zip", expected_integration_sha=_SHA)
            self.assertEqual(first.archive_sha256, second.archive_sha256)
            self.assertEqual((work / "first.zip").read_bytes(), (work / "second.zip").read_bytes())
            self.assertNotIn(CHECKSUMS_NAME + "/", first.inventory)

    def test_zip_publication_rejects_checksum_rewrite_after_external_qualification(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            root = work / "portable"
            root.mkdir()
            _portable_fixture(root)
            qualification = validate_portable_oneclick_tree(
                root,
                expected_integration_sha=_SHA,
            )
            self.assertIsNotNone(qualification.checksum_sha256)
            (root / "Посібник.docx").write_bytes(
                b"changed-after-owner-qualification"
            )
            _write_checksums(root)
            target = work / "candidate.zip"
            with self.assertRaisesRegex(
                Version2PortablePackageError,
                "changed after external qualification",
            ):
                write_portable_oneclick_zip(
                    root,
                    target,
                    expected_integration_sha=_SHA,
                    expected_checksum_sha256=qualification.checksum_sha256,
                )
            self.assertFalse(target.exists())

    def test_zip_readback_rejects_same_size_mutation_before_snapshot_binding(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            root = work / "portable"
            root.mkdir()
            _portable_fixture(root)
            target = work / "candidate.zip"
            real_safe_info = portable_module._safe_info
            readback_mtime_ns = None
            injected = False

            def safe_info_with_mutation(path, *, label, directory=None):
                nonlocal readback_mtime_ns, injected
                if label == "portable ZIP archive readback":
                    if readback_mtime_ns is None:
                        result = real_safe_info(
                            path,
                            label=label,
                            directory=directory,
                        )
                        readback_mtime_ns = result.st_mtime_ns
                        return result
                    if not injected:
                        candidate = Path(path)
                        with candidate.open("r+b") as handle:
                            first = handle.read(1)
                            handle.seek(0)
                            handle.write(b"X" if first != b"X" else b"Y")
                            handle.flush()
                            os.fsync(handle.fileno())
                        current = real_safe_info(
                            path,
                            label=label,
                            directory=directory,
                        )
                        os.utime(
                            candidate,
                            ns=(
                                current.st_atime_ns,
                                readback_mtime_ns + 2_000_000_000,
                            ),
                        )
                        injected = True
                return real_safe_info(path, label=label, directory=directory)

            with mock.patch.object(
                portable_module,
                "_safe_info",
                side_effect=safe_info_with_mutation,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "changed during readback",
                ):
                    write_portable_oneclick_zip(
                        root,
                        target,
                        expected_integration_sha=_SHA,
                    )

            self.assertTrue(injected)
            self.assertFalse(target.exists())

    def test_zip_durability_rejects_same_size_mutation_after_readback_snapshot(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            root = work / "portable"
            root.mkdir()
            _portable_fixture(root)
            target = work / "candidate.zip"
            real_sync = portable_module._fsync_file_snapshot
            injected = False

            def mutate_then_sync(path, *, expected, label):
                nonlocal injected
                if label == "verified portable ZIP archive" and not injected:
                    candidate = Path(path)
                    with candidate.open("r+b") as handle:
                        first = handle.read(1)
                        handle.seek(0)
                        handle.write(b"X" if first != b"X" else b"Y")
                        handle.flush()
                        os.fsync(handle.fileno())
                    current = candidate.stat()
                    os.utime(
                        candidate,
                        ns=(
                            current.st_atime_ns,
                            expected.st_mtime_ns + 2_000_000_000,
                        ),
                    )
                    injected = True
                return real_sync(path, expected=expected, label=label)

            with mock.patch.object(
                portable_module,
                "_fsync_file_snapshot",
                side_effect=mutate_then_sync,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "changed before durability confirmation",
                ):
                    write_portable_oneclick_zip(
                        root,
                        target,
                        expected_integration_sha=_SHA,
                    )

            self.assertTrue(injected)
            self.assertFalse(target.exists())

    def test_zip_digest_binding_rejects_same_size_mutation_after_durability(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            root = work / "portable"
            root.mkdir()
            _portable_fixture(root)
            target = work / "candidate.zip"
            real_sync = portable_module._fsync_file_snapshot
            injected = False

            def sync_then_mutate(path, *, expected, label):
                nonlocal injected
                result = real_sync(path, expected=expected, label=label)
                if label == "verified portable ZIP archive" and not injected:
                    candidate = Path(path)
                    with candidate.open("r+b") as handle:
                        first = handle.read(1)
                        handle.seek(0)
                        handle.write(b"X" if first != b"X" else b"Y")
                        handle.flush()
                        os.fsync(handle.fileno())
                    current = candidate.stat()
                    os.utime(
                        candidate,
                        ns=(
                            current.st_atime_ns,
                            result.st_mtime_ns + 2_000_000_000,
                        ),
                    )
                    injected = True
                return result

            with mock.patch.object(
                portable_module,
                "_fsync_file_snapshot",
                side_effect=sync_then_mutate,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "changed after durability confirmation",
                ):
                    write_portable_oneclick_zip(
                        root,
                        target,
                        expected_integration_sha=_SHA,
                    )

            self.assertTrue(injected)
            self.assertFalse(target.exists())

    def test_zip_temp_cleanup_does_not_replace_primary_verification_failure(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            root = work / "portable"
            root.mkdir()
            _portable_fixture(root)
            target = work / "candidate.zip"
            real_safe_info = portable_module._safe_info
            real_unlink = Path.unlink
            primary_injected = False
            cleanup_injected = False

            def fail_readback(path, *args, **kwargs):
                nonlocal primary_injected
                if (
                    not primary_injected
                    and kwargs.get("label") == "portable ZIP archive readback"
                ):
                    primary_injected = True
                    raise Version2PortablePackageError(
                        "simulated primary ZIP verification failure"
                    )
                return real_safe_info(path, *args, **kwargs)

            def fail_temp_cleanup(path, *args, **kwargs):
                nonlocal cleanup_injected
                if (
                    primary_injected
                    and not cleanup_injected
                    and Path(path).suffix == ".tmp"
                ):
                    cleanup_injected = True
                    raise PermissionError("simulated temporary cleanup failure")
                return real_unlink(path, *args, **kwargs)

            with mock.patch.object(
                portable_module,
                "_safe_info",
                side_effect=fail_readback,
            ), mock.patch.object(
                Path,
                "unlink",
                new=fail_temp_cleanup,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "simulated primary ZIP verification failure",
                ):
                    write_portable_oneclick_zip(
                        root,
                        target,
                        expected_integration_sha=_SHA,
                    )

            self.assertTrue(primary_injected)
            self.assertTrue(cleanup_injected)
            self.assertFalse(target.exists())

    def test_zip_publication_cleans_owned_link_if_post_link_stat_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            root = work / "portable"
            root.mkdir()
            _portable_fixture(root)
            target = work / "candidate.zip"
            real_link = portable_module.os.link
            real_safe_info = portable_module._safe_info
            link_created = False
            injected = False

            def link_then_mark(source, destination, *args, **kwargs):
                nonlocal link_created
                real_link(source, destination, *args, **kwargs)
                if Path(destination) == target:
                    link_created = True

            def fail_first_post_link_stat(path, *args, **kwargs):
                nonlocal injected
                label = kwargs.get("label")
                if (
                    link_created
                    and not injected
                    and label == "verified portable ZIP archive"
                ):
                    injected = True
                    raise Version2PortablePackageError(
                        "simulated post-link stat failure"
                    )
                return real_safe_info(path, *args, **kwargs)

            with mock.patch.object(
                portable_module.os,
                "link",
                side_effect=link_then_mark,
            ), mock.patch.object(
                portable_module,
                "_safe_info",
                side_effect=fail_first_post_link_stat,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "simulated post-link stat failure",
                ):
                    write_portable_oneclick_zip(
                        root,
                        target,
                        expected_integration_sha=_SHA,
                    )

            self.assertTrue(link_created)
            self.assertTrue(injected)
            self.assertFalse(target.exists())

    def test_zip_publication_rejects_same_inode_mutation_after_link(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            root = work / "portable"
            root.mkdir()
            _portable_fixture(root)
            target = work / "candidate.zip"
            real_link = os.link
            injected = False

            def link_then_mutate(source, destination, *args, **kwargs):
                nonlocal injected
                real_link(source, destination, *args, **kwargs)
                if Path(destination) == target and not injected:
                    with target.open("r+b") as handle:
                        first = handle.read(1)
                        handle.seek(0)
                        handle.write(b"X" if first != b"X" else b"Y")
                        handle.flush()
                        os.fsync(handle.fileno())
                    current = target.stat()
                    os.utime(
                        target,
                        ns=(
                            current.st_atime_ns,
                            current.st_mtime_ns + 2_000_000_000,
                        ),
                    )
                    injected = True

            with mock.patch.object(
                portable_module.os,
                "link",
                side_effect=link_then_mutate,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "portable ZIP publication is not the verified archive snapshot",
                ):
                    write_portable_oneclick_zip(
                        root,
                        target,
                        expected_integration_sha=_SHA,
                    )

            self.assertTrue(injected)
            self.assertFalse(target.exists())

    def test_zip_publication_rejects_same_byte_foreign_inode_after_link(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            root = work / "portable"
            root.mkdir()
            _portable_fixture(root)
            target = work / "candidate.zip"
            real_link = os.link
            injected = False

            def link_then_replace(source, destination, *args, **kwargs):
                nonlocal injected
                real_link(source, destination, *args, **kwargs)
                if Path(destination) == target and not injected:
                    payload = Path(source).read_bytes()
                    target.unlink()
                    target.write_bytes(payload)
                    injected = True

            with mock.patch.object(
                portable_module.os,
                "link",
                side_effect=link_then_replace,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "not the verified archive snapshot",
                ):
                    write_portable_oneclick_zip(
                        root,
                        target,
                        expected_integration_sha=_SHA,
                    )

            self.assertTrue(injected)
            # The raced-in foreign inode is deliberately preserved; cleanup is
            # allowed to remove only the exact inode published by this writer.
            self.assertTrue(target.exists())

    def test_zip_publication_rejects_mutation_after_durability_before_final_digest(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            root = work / "portable"
            root.mkdir()
            _portable_fixture(root)
            target = work / "candidate.zip"
            real_sync = portable_module._sync_published_zip_namespace
            injected = False

            def sync_then_mutate(path, *, expected):
                nonlocal injected
                snapshot = real_sync(path, expected=expected)
                if not injected:
                    candidate = Path(path)
                    with candidate.open("r+b") as handle:
                        first = handle.read(1)
                        handle.seek(0)
                        handle.write(b"X" if first != b"X" else b"Y")
                        handle.flush()
                        os.fsync(handle.fileno())
                    current = candidate.stat()
                    os.utime(
                        candidate,
                        ns=(
                            current.st_atime_ns,
                            current.st_mtime_ns + 2_000_000_000,
                        ),
                    )
                    injected = True
                return snapshot

            with mock.patch.object(
                portable_module,
                "_sync_published_zip_namespace",
                side_effect=sync_then_mutate,
            ):
                with self.assertRaisesRegex(
                    Version2PortablePackageError,
                    "published portable ZIP bytes differ from the verified archive",
                ):
                    write_portable_oneclick_zip(
                        root,
                        target,
                        expected_integration_sha=_SHA,
                    )

            self.assertTrue(injected)
            self.assertFalse(target.exists())

    def test_zip_publication_uses_durability_barrier_before_return(self):
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            root = work / "portable"
            root.mkdir()
            _portable_fixture(root)
            target = work / "candidate.zip"
            real_sync = portable_module._sync_published_zip_namespace

            with mock.patch.object(
                portable_module,
                "_sync_published_zip_namespace",
                wraps=real_sync,
            ) as sync:
                report = write_portable_oneclick_zip(
                    root,
                    target,
                    expected_integration_sha=_SHA,
                )

            self.assertEqual(sync.call_count, 1)
            self.assertEqual(report.archive_sha256, hashlib.sha256(target.read_bytes()).hexdigest())

    def test_zip_output_cannot_mutate_the_package_tree(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "portable"
            root.mkdir()
            _portable_fixture(root)
            with self.assertRaisesRegex(Version2PortablePackageError, "outside the package tree"):
                write_portable_oneclick_zip(
                    root,
                    root / "candidate.zip",
                    expected_integration_sha=_SHA,
                )
            self.assertFalse((root / "candidate.zip").exists())

    def test_assembler_rejects_derived_document_tuple_before_container_hooks(self) -> None:
        touched: list[str] = []

        class ActiveTuple(tuple):
            def __len__(self):
                touched.append("len")
                raise AssertionError("derived tuple len hook executed")

            def __iter__(self):
                touched.append("iter")
                raise AssertionError("derived tuple iteration hook executed")

        documents = ActiveTuple(("first.docx", "second.docx"))
        with mock.patch.object(
            portable_module,
            "validate_version2_package_tree",
            side_effect=AssertionError("package preflight must not start"),
        ) as preflight_authority:
            with self.assertRaisesRegex(TypeError, "exact two-item tuple"):
                assemble_portable_oneclick_tree(
                    "unused-canonical",
                    "unused-launcher.exe",
                    documents,
                    "unused-output",
                    integration_sha=_SHA,
                )
        preflight_authority.assert_not_called()
        self.assertEqual(touched, [])



    def test_require_user_seed_rejects_active_truthiness_before_work(self) -> None:
        touched: list[str] = []

        class ActiveFlag:
            def __bool__(self):
                touched.append("bool")
                raise AssertionError("active require_user_seed truthiness executed")

        flag = ActiveFlag()

        with mock.patch.object(
            portable_module,
            "_safe_info",
            side_effect=AssertionError("tree inspection must not start"),
        ) as inspect:
            with self.assertRaisesRegex(TypeError, "exact bool"):
                validate_portable_oneclick_tree(
                    "unused-portable",
                    expected_integration_sha=_SHA,
                    require_user_seed=flag,
                )
        inspect.assert_not_called()
        self.assertEqual(touched, [])

        with mock.patch.object(
            portable_module,
            "_sha40",
            side_effect=AssertionError("assembly authority must not start"),
        ) as sha_authority:
            with self.assertRaisesRegex(TypeError, "exact bool"):
                assemble_portable_oneclick_tree(
                    "unused-canonical",
                    "unused-launcher.exe",
                    ("first.docx", "second.docx"),
                    "unused-output",
                    integration_sha=_SHA,
                    require_user_seed=flag,
                )
        sha_authority.assert_not_called()
        self.assertEqual(touched, [])

        with mock.patch.object(
            portable_module,
            "Path",
            side_effect=AssertionError("ZIP path parsing must not start"),
        ) as path_authority:
            with self.assertRaisesRegex(TypeError, "exact bool"):
                write_portable_oneclick_zip(
                    "unused-portable",
                    "unused.zip",
                    expected_integration_sha=_SHA,
                    require_user_seed=flag,
                )
        path_authority.assert_not_called()
        self.assertEqual(touched, [])



    def test_portable_path_controls_reject_active_pathlike_before_hooks(self) -> None:
        touched: list[str] = []

        class ActivePath:
            def __fspath__(self):
                touched.append("fspath")
                raise AssertionError("active path hook executed")

        active = ActivePath()

        with mock.patch.object(
            portable_module,
            "_safe_info",
            side_effect=AssertionError("portable tree inspection must not start"),
        ) as inspect:
            with self.assertRaisesRegex(TypeError, "exact str or platform Path"):
                validate_portable_oneclick_tree(
                    active,
                    expected_integration_sha=_SHA,
                )
        inspect.assert_not_called()
        self.assertEqual(touched, [])

        assemble_cases = (
            (active, "launcher.exe", ("first.docx", "second.docx"), "output"),
            ("canonical", active, ("first.docx", "second.docx"), "output"),
            ("canonical", "launcher.exe", ("first.docx", "second.docx"), active),
            ("canonical", "launcher.exe", (active, "second.docx"), "output"),
        )
        for canonical, launcher, documents, output in assemble_cases:
            with self.subTest(
                canonical=type(canonical).__name__,
                launcher=type(launcher).__name__,
                output=type(output).__name__,
                first_document=type(documents[0]).__name__,
            ):
                with mock.patch.object(
                    portable_module,
                    "validate_version2_package_tree",
                    side_effect=AssertionError("package preflight must not start"),
                ) as preflight_authority:
                    with self.assertRaisesRegex(TypeError, "exact str or platform Path"):
                        assemble_portable_oneclick_tree(
                            canonical,
                            launcher,
                            documents,
                            output,
                            integration_sha=_SHA,
                        )
                preflight_authority.assert_not_called()
                self.assertEqual(touched, [])

        for package_root, zip_path in (
            (active, "candidate.zip"),
            ("portable", active),
        ):
            with self.subTest(
                package_root=type(package_root).__name__,
                zip_path=type(zip_path).__name__,
            ):
                with mock.patch.object(
                    portable_module,
                    "validate_portable_oneclick_tree",
                    side_effect=AssertionError("portable validation must not start"),
                ) as validation:
                    with self.assertRaisesRegex(TypeError, "exact str or platform Path"):
                        write_portable_oneclick_zip(
                            package_root,
                            zip_path,
                            expected_integration_sha=_SHA,
                        )
                validation.assert_not_called()
                self.assertEqual(touched, [])




if __name__ == "__main__":
    unittest.main()
