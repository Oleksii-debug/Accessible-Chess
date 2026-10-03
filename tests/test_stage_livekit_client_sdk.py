from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest import mock

from acs import version2_package_preflight as package_preflight
from acs import version2_release_payload as release_payload
from scripts import stage_livekit_client_sdk as sdk


class LiveKitClientSdkStageTests(unittest.TestCase):
    def test_pin_identity_matches_release_payload_and_final_preflight(self) -> None:
        self.assertEqual(
            (
                sdk.LIVEKIT_CLIENT_VERSION,
                sdk.LIVEKIT_CLIENT_LICENSE_ID,
                sdk.LIVEKIT_CLIENT_NPM_TARBALL_URL,
                sdk.LIVEKIT_CLIENT_NPM_INTEGRITY,
            ),
            (
                release_payload._LIVEKIT_CLIENT_VERSION,
                release_payload._LIVEKIT_CLIENT_LICENSE_ID,
                release_payload._LIVEKIT_CLIENT_NPM_TARBALL_URL,
                release_payload._LIVEKIT_CLIENT_NPM_INTEGRITY,
            ),
        )
        self.assertEqual(
            (
                sdk.LIVEKIT_CLIENT_VERSION,
                sdk.LIVEKIT_CLIENT_LICENSE_ID,
                sdk.LIVEKIT_CLIENT_NPM_TARBALL_URL,
                sdk.LIVEKIT_CLIENT_NPM_INTEGRITY,
            ),
            (
                package_preflight._LIVEKIT_CLIENT_VERSION,
                package_preflight._LIVEKIT_CLIENT_LICENSE_ID,
                package_preflight._LIVEKIT_CLIENT_SOURCE,
                package_preflight._LIVEKIT_CLIENT_INTEGRITY,
            ),
        )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "livekit.tgz"
        self.output = self.root / "out"
        self.bundle = b"/* UMD */ LivekitClient Room " + (b"x" * 120_000)
        self.license = b"Apache License\nVersion 2.0\n" + (b"license\n" * 900)
        self.package = {
            "name": "livekit-client",
            "version": sdk.LIVEKIT_CLIENT_VERSION,
            "license": "Apache-2.0",
            "main": "./dist/livekit-client.umd.js",
            "unpkg": "./dist/livekit-client.umd.js",
        }
        self._write_archive()

    def _write_archive(
        self,
        *,
        members: list[tuple[str, bytes]] | None = None,
    ) -> None:
        entries = members or [
            ("package/package.json", json.dumps(self.package).encode("utf-8")),
            ("package/dist/livekit-client.umd.js", self.bundle),
            ("package/LICENSE", self.license),
        ]
        with tarfile.open(self.archive, "w:gz") as archive:
            for name, data in entries:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))

    def _integrity(self) -> str:
        digest = hashlib.sha512(self.archive.read_bytes()).digest()
        return "sha512-" + base64.b64encode(digest).decode("ascii")

    def _stage(self) -> Path:
        return sdk.stage_livekit_client_sdk(
            self.archive,
            self.output,
            expected_integrity=self._integrity(),
        )

    def test_stages_exact_bundle_license_notice_and_provenance(self) -> None:
        result = self._stage()
        self.assertEqual(result, self.output)
        self.assertEqual((result / "livekit-client.umd.js").read_bytes(), self.bundle)
        self.assertEqual((result / "LICENSE").read_bytes(), self.license)
        self.assertIn("LiveKit, Inc.", (result / "NOTICE").read_text(encoding="utf-8"))

        provenance = json.loads(
            (result / "provenance.json").read_text(encoding="utf-8")
        )
        self.assertEqual(provenance["version"], sdk.LIVEKIT_CLIENT_VERSION)
        self.assertEqual(provenance["npm_integrity"], self._integrity())
        self.assertEqual(
            provenance["bundle_sha256"],
            hashlib.sha256(self.bundle).hexdigest(),
        )

    def test_verified_stage_is_byte_derived_from_source_archive(self) -> None:
        staged = self._stage()
        verified = sdk.verify_staged_livekit_client_sdk(
            self.archive,
            staged,
            expected_integrity=self._integrity(),
        )
        self.assertEqual(verified, staged)

    def test_verifier_rejects_bundle_substitution_even_with_valid_archive(self) -> None:
        staged = self._stage()
        bundle = staged / "livekit-client.umd.js"
        bundle.write_bytes(bundle.read_bytes() + b"substitution")
        with self.assertRaisesRegex(
            sdk.LiveKitClientSdkStageError,
            "does not match pinned npm archive",
        ):
            sdk.verify_staged_livekit_client_sdk(
                self.archive,
                staged,
                expected_integrity=self._integrity(),
            )

    def test_verifier_rejects_rewritten_provenance(self) -> None:
        staged = self._stage()
        provenance = staged / "provenance.json"
        data = json.loads(provenance.read_text(encoding="utf-8"))
        data["bundle_sha256"] = "0" * 64
        provenance.write_text(
            json.dumps(data, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            sdk.LiveKitClientSdkStageError,
            "staged LiveKit provenance does not match pinned npm archive",
        ):
            sdk.verify_staged_livekit_client_sdk(
                self.archive,
                staged,
                expected_integrity=self._integrity(),
            )

    def test_verifier_rejects_extra_staged_file(self) -> None:
        staged = self._stage()
        (staged / "unexpected.js").write_text("extra\n", encoding="utf-8")
        with self.assertRaisesRegex(
            sdk.LiveKitClientSdkStageError,
            "inventory does not match pinned release",
        ):
            sdk.verify_staged_livekit_client_sdk(
                self.archive,
                staged,
                expected_integrity=self._integrity(),
            )

    def test_integrity_mismatch_is_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            sdk.LiveKitClientSdkStageError,
            "integrity mismatch",
        ):
            sdk.stage_livekit_client_sdk(
                self.archive,
                self.output,
                expected_integrity="sha512-bad",
            )
        self.assertFalse(self.output.exists())

    def test_traversal_member_is_rejected(self) -> None:
        self._write_archive(members=[("../escape", b"x")])
        with self.assertRaisesRegex(
            sdk.LiveKitClientSdkStageError,
            "unsafe member|package root",
        ):
            self._stage()
        self.assertFalse(self.output.exists())

    def test_redundant_dot_member_is_rejected(self) -> None:
        self._write_archive(
            members=[
                ("package/./package.json", json.dumps(self.package).encode("utf-8")),
                ("package/dist/livekit-client.umd.js", self.bundle),
                ("package/LICENSE", self.license),
            ]
        )
        with self.assertRaisesRegex(
            sdk.LiveKitClientSdkStageError,
            "unsafe member",
        ):
            self._stage()
        self.assertFalse(self.output.exists())

    def test_redundant_separator_member_is_rejected(self) -> None:
        self._write_archive(
            members=[
                ("package//package.json", json.dumps(self.package).encode("utf-8")),
                ("package/dist/livekit-client.umd.js", self.bundle),
                ("package/LICENSE", self.license),
            ]
        )
        with self.assertRaisesRegex(
            sdk.LiveKitClientSdkStageError,
            "unsafe member",
        ):
            self._stage()
        self.assertFalse(self.output.exists())

    def test_windows_unsafe_member_names_are_rejected(self) -> None:
        unsafe_names = (
            "package/CON.txt",
            "package/COM¹.txt",
            "package/LPT³.bin",
            "package/CONIN$.txt",
            "package/conout$.bin",
            "package/trailing./file.txt",
            "package/drive:C/file.txt",
            "package/control\x1f/file.txt",
        )
        for index, name in enumerate(unsafe_names):
            with self.subTest(name=name):
                self.output = self.root / f"unsafe-{index}"
                self._write_archive(members=[(name, b"x")])
                with self.assertRaisesRegex(
                    sdk.LiveKitClientSdkStageError,
                    "Windows-unsafe member name",
                ):
                    self._stage()
                self.assertFalse(self.output.exists())

    def test_archive_link_is_rejected_before_read(self) -> None:
        original_lstat = Path.lstat

        def fake_lstat(path: Path):
            if path == self.archive:
                return mock.Mock(st_mode=stat.S_IFLNK, st_file_attributes=0)
            return original_lstat(path)

        with mock.patch.object(Path, "lstat", autospec=True, side_effect=fake_lstat):
            with self.assertRaisesRegex(
                sdk.LiveKitClientSdkStageError,
                "regular file, not a link",
            ):
                self._stage()
        self.assertFalse(self.output.exists())

    def test_archive_reparse_point_is_rejected_before_read(self) -> None:
        original_lstat = Path.lstat

        def fake_lstat(path: Path):
            if path == self.archive:
                return mock.Mock(
                    st_mode=stat.S_IFREG,
                    st_file_attributes=getattr(
                        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
                    ),
                )
            return original_lstat(path)

        with mock.patch.object(Path, "lstat", autospec=True, side_effect=fake_lstat):
            with self.assertRaisesRegex(
                sdk.LiveKitClientSdkStageError,
                "reparse point",
            ):
                self._stage()
        self.assertFalse(self.output.exists())

    def test_archive_metadata_change_during_snapshot_is_rejected(self) -> None:
        original_lstat = Path.lstat
        initial = original_lstat(self.archive)
        archive_checks = 0

        def fake_lstat(path: Path):
            nonlocal archive_checks
            if path != self.archive:
                return original_lstat(path)
            archive_checks += 1
            if archive_checks == 1:
                return initial
            return mock.Mock(
                st_mode=initial.st_mode,
                st_dev=initial.st_dev,
                st_ino=initial.st_ino,
                st_size=initial.st_size,
                st_mtime_ns=initial.st_mtime_ns + 1,
                st_file_attributes=getattr(initial, "st_file_attributes", 0),
            )

        with mock.patch.object(Path, "lstat", autospec=True, side_effect=fake_lstat):
            with self.assertRaisesRegex(
                sdk.LiveKitClientSdkStageError,
                "changed while it was being read",
            ):
                self._stage()
        self.assertFalse(self.output.exists())

    def test_symlink_is_rejected(self) -> None:
        with tarfile.open(self.archive, "w:gz") as archive:
            info = tarfile.TarInfo("package/package.json")
            info.type = tarfile.SYMTYPE
            info.linkname = "target"
            archive.addfile(info)
        with self.assertRaisesRegex(
            sdk.LiveKitClientSdkStageError,
            "link or special",
        ):
            self._stage()
        self.assertFalse(self.output.exists())

    def test_member_count_limit_stops_archive_scan(self) -> None:
        self._write_archive(
            members=[
                ("package/package.json", json.dumps(self.package).encode("utf-8")),
                ("package/dist/livekit-client.umd.js", self.bundle),
                ("package/LICENSE", self.license),
                ("package/extra.txt", b"x"),
            ]
        )
        with (
            mock.patch.object(sdk, "_MAX_MEMBERS", 3),
            self.assertRaisesRegex(
                sdk.LiveKitClientSdkStageError,
                "member-count limit",
            ),
        ):
            self._stage()
        self.assertFalse(self.output.exists())

    def test_casefold_duplicate_is_rejected(self) -> None:
        self._write_archive(
            members=[
                ("package/package.json", json.dumps(self.package).encode("utf-8")),
                ("package/PACKAGE.JSON", b"{}"),
                ("package/dist/livekit-client.umd.js", self.bundle),
                ("package/LICENSE", self.license),
            ]
        )
        with self.assertRaisesRegex(
            sdk.LiveKitClientSdkStageError,
            "duplicate member",
        ):
            self._stage()

    def test_noncanonical_metadata_is_rejected(self) -> None:
        self.package["version"] = "9.9.9"
        self._write_archive()
        with self.assertRaisesRegex(
            sdk.LiveKitClientSdkStageError,
            "version is not canonical",
        ):
            self._stage()

    def test_bundle_marker_contract_is_required(self) -> None:
        self.bundle = b"x" * 120_000
        self._write_archive()
        with self.assertRaisesRegex(
            sdk.LiveKitClientSdkStageError,
            "browser API markers",
        ):
            self._stage()

    def test_broken_output_entry_is_rejected_before_validation(self) -> None:
        original_lexists = sdk.os.path.lexists

        def fake_lexists(path: object) -> bool:
            if Path(path) == self.output:
                return True
            return original_lexists(path)

        with mock.patch.object(sdk.os.path, "lexists", side_effect=fake_lexists):
            with self.assertRaisesRegex(
                sdk.LiveKitClientSdkStageError,
                "output directory already exists",
            ):
                self._stage()
        self.assertFalse(self.output.exists())

    def test_symlinked_output_ancestor_is_rejected(self) -> None:
        linked_ancestor = self.root / "linked"
        self.output = linked_ancestor / "nested" / "out"
        original_lexists = sdk.os.path.lexists
        original_lstat = Path.lstat

        def fake_lexists(path: object) -> bool:
            if Path(path) == linked_ancestor:
                return True
            return original_lexists(path)

        def fake_lstat(path: Path):
            if path == linked_ancestor:
                return mock.Mock(st_mode=stat.S_IFLNK, st_file_attributes=0)
            return original_lstat(path)

        with (
            mock.patch.object(sdk.os.path, "lexists", side_effect=fake_lexists),
            mock.patch.object(Path, "lstat", autospec=True, side_effect=fake_lstat),
        ):
            with self.assertRaisesRegex(
                sdk.LiveKitClientSdkStageError,
                "must not traverse a symlink",
            ):
                self._stage()
        self.assertFalse(self.output.exists())

    def test_reparse_output_ancestor_is_rejected(self) -> None:
        linked_ancestor = self.root / "junction"
        self.output = linked_ancestor / "nested" / "out"
        original_lexists = sdk.os.path.lexists
        original_lstat = Path.lstat

        def fake_lexists(path: object) -> bool:
            if Path(path) == linked_ancestor:
                return True
            return original_lexists(path)

        def fake_lstat(path: Path):
            if path == linked_ancestor:
                return mock.Mock(
                    st_mode=stat.S_IFDIR,
                    st_file_attributes=getattr(
                        stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
                    ),
                )
            return original_lstat(path)

        with (
            mock.patch.object(sdk.os.path, "lexists", side_effect=fake_lexists),
            mock.patch.object(Path, "lstat", autospec=True, side_effect=fake_lstat),
        ):
            with self.assertRaisesRegex(
                sdk.LiveKitClientSdkStageError,
                "reparse point",
            ):
                self._stage()
        self.assertFalse(self.output.exists())

    def test_non_directory_output_ancestor_is_rejected(self) -> None:
        blocked = self.root / "blocked"
        blocked.write_text("not a directory", encoding="utf-8")
        self.output = blocked / "out"
        with self.assertRaisesRegex(
            sdk.LiveKitClientSdkStageError,
            "ancestor must be a directory",
        ):
            self._stage()
        self.assertFalse(self.output.exists())

    def test_output_appearing_during_staging_is_not_overwritten(self) -> None:
        original_lexists = sdk.os.path.lexists
        output_checks = 0

        def fake_lexists(path: object) -> bool:
            nonlocal output_checks
            if Path(path) == self.output:
                output_checks += 1
                return output_checks >= 2
            return original_lexists(path)

        with mock.patch.object(sdk.os.path, "lexists", side_effect=fake_lexists):
            with self.assertRaisesRegex(
                sdk.LiveKitClientSdkStageError,
                "appeared during staging",
            ):
                self._stage()

        self.assertFalse(self.output.exists())
        self.assertEqual(
            list(self.output.parent.glob(f".{self.output.name}.stage-*")),
            [],
        )

    def test_write_failure_leaves_no_partial_output_or_staging_directory(self) -> None:
        with mock.patch.object(Path, "write_text", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self._stage()

        self.assertFalse(self.output.exists())
        self.assertEqual(
            list(self.output.parent.glob(f".{self.output.name}.stage-*")),
            [],
        )

    def test_existing_output_is_not_overwritten(self) -> None:
        self.output.mkdir()
        sentinel = self.output / "keep"
        sentinel.write_text("x", encoding="utf-8")
        with self.assertRaisesRegex(
            sdk.LiveKitClientSdkStageError,
            "already exists",
        ):
            self._stage()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "x")

    def test_archive_notice_is_preserved_when_present(self) -> None:
        notice = b"Copyright LiveKit\nApache License\nupstream notice\n"
        self._write_archive(
            members=[
                ("package/package.json", json.dumps(self.package).encode("utf-8")),
                ("package/dist/livekit-client.umd.js", self.bundle),
                ("package/LICENSE", self.license),
                ("package/NOTICE", notice),
            ]
        )
        self._stage()
        self.assertEqual((self.output / "NOTICE").read_bytes(), notice)


if __name__ == "__main__":
    unittest.main()
