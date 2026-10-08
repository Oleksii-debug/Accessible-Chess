from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.user_library_seed import BUNDLE_KIND, SCHEMA_VERSION
from acs.version2_portable_package import Version2PortablePackageReport
import scripts.build_owner_portable_candidate as owner_candidate


_SHA = "a" * 40
_ARCHIVE_SHA = "b" * 64
_PACKAGE_CHECKSUM_SHA = "e" * 64


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _seed(root: Path, *, source_count: int = 6) -> Path:
    root.mkdir(parents=True)
    files: list[dict[str, object]] = []
    for index in range(source_count):
        name = f"owner-{index + 1}.pgn"
        text = (
            f'[Event "Owner seed {index + 1}"]\n'
            '[White "White"]\n'
            '[Black "Black"]\n'
            '[Result "*"]\n\n'
            '1. e4 e5 2. Nf3 Nc6 *\n'
        )
        payload = text.encode("utf-8")
        (root / name).write_bytes(payload)
        files.append(
            {
                "file": name,
                "display_name": f"Owner source {index + 1}",
                "bytes": len(payload),
                "sha256": _digest(payload),
            }
        )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "bundle_kind": BUNDLE_KIND,
        "runtime_network_required": False,
        "ai_required": False,
        "files": files,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return root


def _sound_pack(root: Path, *, archive_sha256: str = _ARCHIVE_SHA) -> str:
    library = root / "library" / "Test"
    library.mkdir(parents=True)
    rows: list[tuple[str, bytes]] = []
    files: list[dict[str, object]] = []
    for index in range(330):
        relative = f"Test/{index:03d}.wav"
        packaged = f"library/{relative}"
        payload = b"WAV" + index.to_bytes(2, "little")
        path = root / packaged
        path.write_bytes(payload)
        digest = _digest(payload)
        files.append(
            {
                "file": packaged,
                "sha256": digest,
                "bytes": len(payload),
            }
        )
        rows.append(
            (
                relative.casefold(),
                f"{relative}\0{digest}\n".encode("utf-8"),
            )
        )
    fingerprint = hashlib.sha256(
        b"".join(row for _folded, row in sorted(rows, key=lambda item: item[0]))
    ).hexdigest()
    inventory = {
        "schema_version": 1,
        "source": owner_candidate.PROVENANCE_SOURCE,
        "license_id": owner_candidate.PROVENANCE_LICENSE,
        "creator": owner_candidate.PROVENANCE_CREATOR,
        "file_count": 330,
        "source_inventory_sha256": fingerprint,
        "source_archive_sha256": archive_sha256,
        "source_archive_bytes": 123456,
        "files": files,
    }
    (root / "inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return fingerprint


def _owner_tree(root: Path) -> str:
    sound_root = root / "App" / "assets" / "sounds"
    fingerprint = _sound_pack(sound_root)
    _seed(root / "App" / "release-content" / "user-library-seed")
    return fingerprint


def _portable_report(root: Path) -> Version2PortablePackageReport:
    return Version2PortablePackageReport(
        package_root=root,
        integration_sha=_SHA,
        inventory=(),
        total_bytes=1,
        checksum_sha256=_PACKAGE_CHECKSUM_SHA,
    )


class OwnerPortableCandidateValidationTests(unittest.TestCase):
    def test_public_validation_controls_are_passive_before_package_work(self) -> None:
        touched: list[str] = []

        class ActivePath:
            def __fspath__(self):
                touched.append("fspath")
                raise AssertionError("active path hook executed")

        class ActiveCount(int):
            def __le__(self, other):
                touched.append("count")
                raise AssertionError("active count hook executed")

        with mock.patch.object(
            owner_candidate,
            "validate_portable_oneclick_tree",
            side_effect=AssertionError("portable validation must not start"),
        ) as portable:
            with self.assertRaisesRegex(TypeError, "exact str or platform Path"):
                owner_candidate.validate_owner_portable_candidate_tree(
                    ActivePath(),
                    expected_integration_sha=_SHA,
                    expected_sound_archive_sha256=_ARCHIVE_SHA,
                )
        portable.assert_not_called()
        self.assertEqual(touched, [])

        for source_count, game_count in ((ActiveCount(6), 3738), (6, ActiveCount(3738))):
            with self.subTest(
                source_count=type(source_count).__name__,
                game_count=type(game_count).__name__,
            ):
                with mock.patch.object(
                    owner_candidate,
                    "validate_portable_oneclick_tree",
                    side_effect=AssertionError("portable validation must not start"),
                ) as portable:
                    with self.assertRaisesRegex(
                        owner_candidate.OwnerPortableCandidateError,
                        "count is invalid",
                    ):
                        owner_candidate.validate_owner_portable_candidate_tree(
                            "unused-package",
                            expected_integration_sha=_SHA,
                            expected_sound_archive_sha256=_ARCHIVE_SHA,
                            expected_seed_source_count=source_count,
                            expected_seed_game_count=game_count,
                        )
                portable.assert_not_called()
                self.assertEqual(touched, [])

    def test_exact_sound_and_canonical_seed_pass_owner_gate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "candidate"
            fingerprint = _owner_tree(root)
            with (
                mock.patch.object(
                    owner_candidate,
                    "validate_portable_oneclick_tree",
                    return_value=_portable_report(root),
                ) as portable,
                mock.patch.object(
                    owner_candidate,
                    "EXPECTED_SOURCE_INVENTORY_SHA256",
                    fingerprint,
                ),
            ):
                report = owner_candidate.validate_owner_portable_candidate_tree(
                    root,
                    expected_integration_sha=_SHA,
                    expected_sound_archive_sha256=_ARCHIVE_SHA,
                    expected_seed_source_count=6,
                    expected_seed_game_count=6,
                )

            portable.assert_called_once_with(
                root,
                expected_integration_sha=_SHA,
                require_user_seed=True,
            )
            self.assertEqual(report["sound_wav_count"], 330)
            self.assertEqual(report["sound_inventory_sha256"], fingerprint)
            self.assertEqual(report["package_checksum_sha256"], _PACKAGE_CHECKSUM_SHA)
            self.assertEqual(report["seed_source_count"], 6)
            self.assertEqual(report["seed_game_count"], 6)

    def test_empty_seed_manifest_cannot_hide_behind_generic_seed_presence_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "candidate"
            fingerprint = _owner_tree(root)
            (root / "App" / "release-content" / "user-library-seed" / "manifest.json").write_text(
                "{}",
                encoding="utf-8",
            )
            with (
                mock.patch.object(
                    owner_candidate,
                    "validate_portable_oneclick_tree",
                    return_value=_portable_report(root),
                ),
                mock.patch.object(
                    owner_candidate,
                    "EXPECTED_SOURCE_INVENTORY_SHA256",
                    fingerprint,
                ),
            ):
                with self.assertRaisesRegex(
                    owner_candidate.OwnerPortableCandidateError,
                    "failed canonical validation",
                ):
                    owner_candidate.validate_owner_portable_candidate_tree(
                        root,
                        expected_integration_sha=_SHA,
                        expected_sound_archive_sha256=_ARCHIVE_SHA,
                        expected_seed_source_count=6,
                        expected_seed_game_count=6,
                    )

    def test_seed_byte_tampering_fails_canonical_import_qualification(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "candidate"
            fingerprint = _owner_tree(root)
            seed = root / "App" / "release-content" / "user-library-seed"
            (seed / "owner-6.pgn").write_text("[Event \"tampered\"]\n\n*\n", encoding="utf-8")
            with (
                mock.patch.object(
                    owner_candidate,
                    "validate_portable_oneclick_tree",
                    return_value=_portable_report(root),
                ),
                mock.patch.object(
                    owner_candidate,
                    "EXPECTED_SOURCE_INVENTORY_SHA256",
                    fingerprint,
                ),
            ):
                with self.assertRaisesRegex(
                    owner_candidate.OwnerPortableCandidateError,
                    "canonical import qualification",
                ):
                    owner_candidate.validate_owner_portable_candidate_tree(
                        root,
                        expected_integration_sha=_SHA,
                        expected_sound_archive_sha256=_ARCHIVE_SHA,
                        expected_seed_source_count=6,
                        expected_seed_game_count=6,
                    )

    def test_seed_source_and_game_counts_are_exact_acceptance_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "candidate"
            fingerprint = _owner_tree(root)
            with (
                mock.patch.object(
                    owner_candidate,
                    "validate_portable_oneclick_tree",
                    return_value=_portable_report(root),
                ),
                mock.patch.object(
                    owner_candidate,
                    "EXPECTED_SOURCE_INVENTORY_SHA256",
                    fingerprint,
                ),
            ):
                with self.assertRaisesRegex(
                    owner_candidate.OwnerPortableCandidateError,
                    "source count mismatch",
                ):
                    owner_candidate.validate_owner_portable_candidate_tree(
                        root,
                        expected_integration_sha=_SHA,
                        expected_sound_archive_sha256=_ARCHIVE_SHA,
                        expected_seed_source_count=7,
                        expected_seed_game_count=6,
                    )

                with self.assertRaisesRegex(
                    owner_candidate.OwnerPortableCandidateError,
                    "game count mismatch",
                ):
                    owner_candidate.validate_owner_portable_candidate_tree(
                        root,
                        expected_integration_sha=_SHA,
                        expected_sound_archive_sha256=_ARCHIVE_SHA,
                        expected_seed_source_count=6,
                        expected_seed_game_count=7,
                    )

    def test_sound_archive_identity_is_explicit_not_inferred_from_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "candidate"
            fingerprint = _owner_tree(root)
            with (
                mock.patch.object(
                    owner_candidate,
                    "validate_portable_oneclick_tree",
                    return_value=_portable_report(root),
                ),
                mock.patch.object(
                    owner_candidate,
                    "EXPECTED_SOURCE_INVENTORY_SHA256",
                    fingerprint,
                ),
            ):
                with self.assertRaisesRegex(
                    owner_candidate.OwnerPortableCandidateError,
                    "authorized input",
                ):
                    owner_candidate.validate_owner_portable_candidate_tree(
                        root,
                        expected_integration_sha=_SHA,
                        expected_sound_archive_sha256="c" * 64,
                        expected_seed_source_count=6,
                        expected_seed_game_count=6,
                    )

    def test_sound_wav_mutation_fails_even_when_inventory_document_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "candidate"
            fingerprint = _owner_tree(root)
            target = root / "App" / "assets" / "sounds" / "library" / "Test" / "329.wav"
            target.write_bytes(b"BAD" + (329).to_bytes(2, "little"))
            with (
                mock.patch.object(
                    owner_candidate,
                    "validate_portable_oneclick_tree",
                    return_value=_portable_report(root),
                ),
                mock.patch.object(
                    owner_candidate,
                    "EXPECTED_SOURCE_INVENTORY_SHA256",
                    fingerprint,
                ),
            ):
                with self.assertRaisesRegex(
                    owner_candidate.OwnerPortableCandidateError,
                    "bytes do not match inventory",
                ):
                    owner_candidate.validate_owner_portable_candidate_tree(
                        root,
                        expected_integration_sha=_SHA,
                        expected_sound_archive_sha256=_ARCHIVE_SHA,
                        expected_seed_source_count=6,
                        expected_seed_game_count=6,
                    )


    def test_owner_gate_requires_canonical_checksum_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "candidate"
            fingerprint = _owner_tree(root)
            unpinned = Version2PortablePackageReport(
                package_root=root,
                integration_sha=_SHA,
                inventory=(),
                total_bytes=1,
            )
            with (
                mock.patch.object(
                    owner_candidate,
                    "validate_portable_oneclick_tree",
                    return_value=unpinned,
                ),
                mock.patch.object(
                    owner_candidate,
                    "EXPECTED_SOURCE_INVENTORY_SHA256",
                    fingerprint,
                ),
            ):
                with self.assertRaisesRegex(
                    owner_candidate.OwnerPortableCandidateError,
                    "checksum snapshot SHA-256 is invalid",
                ):
                    owner_candidate.validate_owner_portable_candidate_tree(
                        root,
                        expected_integration_sha=_SHA,
                        expected_sound_archive_sha256=_ARCHIVE_SHA,
                        expected_seed_source_count=6,
                        expected_seed_game_count=6,
                    )


class OwnerPortableCandidateAssemblyTests(unittest.TestCase):
    def test_builder_rejects_active_containers_paths_and_counts_before_package_work(self) -> None:
        touched: list[str] = []

        class ActiveTuple(tuple):
            def __len__(self):
                touched.append("len")
                raise AssertionError("active tuple len hook executed")

            def __iter__(self):
                touched.append("iter")
                raise AssertionError("active tuple iteration hook executed")

        class ActivePath:
            def __fspath__(self):
                touched.append("fspath")
                raise AssertionError("active path hook executed")

        class ActiveCount(int):
            def __le__(self, other):
                touched.append("count")
                raise AssertionError("active count hook executed")

        active_tuple = ActiveTuple(("first.docx", "second.docx"))
        with mock.patch.object(
            owner_candidate,
            "assemble_portable_oneclick_tree",
            side_effect=AssertionError("portable assembly must not start"),
        ) as assemble:
            with self.assertRaisesRegex(TypeError, "exact two-item tuple"):
                owner_candidate.assemble_owner_portable_candidate(
                    "canonical",
                    "launcher.exe",
                    active_tuple,
                    "output",
                    "candidate.zip",
                    integration_sha=_SHA,
                    expected_document_sha256=("1" * 64, "2" * 64),
                    expected_sound_archive_sha256=_ARCHIVE_SHA,
                )
        assemble.assert_not_called()
        self.assertEqual(touched, [])

        with mock.patch.object(
            owner_candidate,
            "assemble_portable_oneclick_tree",
            side_effect=AssertionError("portable assembly must not start"),
        ) as assemble:
            with self.assertRaisesRegex(TypeError, "exact two-item tuple"):
                owner_candidate.assemble_owner_portable_candidate(
                    "canonical",
                    "launcher.exe",
                    ("first.docx", "second.docx"),
                    "output",
                    "candidate.zip",
                    integration_sha=_SHA,
                    expected_document_sha256=active_tuple,
                    expected_sound_archive_sha256=_ARCHIVE_SHA,
                )
        assemble.assert_not_called()
        self.assertEqual(touched, [])

        path_cases = (
            (ActivePath(), "launcher.exe", ("first.docx", "second.docx"), "output", "candidate.zip"),
            ("canonical", ActivePath(), ("first.docx", "second.docx"), "output", "candidate.zip"),
            ("canonical", "launcher.exe", (ActivePath(), "second.docx"), "output", "candidate.zip"),
            ("canonical", "launcher.exe", ("first.docx", "second.docx"), ActivePath(), "candidate.zip"),
            ("canonical", "launcher.exe", ("first.docx", "second.docx"), "output", ActivePath()),
        )
        for canonical, launcher, documents, output, archive in path_cases:
            with self.subTest(
                canonical=type(canonical).__name__,
                launcher=type(launcher).__name__,
                first_document=type(documents[0]).__name__,
                output=type(output).__name__,
                archive=type(archive).__name__,
            ):
                with mock.patch.object(
                    owner_candidate,
                    "assemble_portable_oneclick_tree",
                    side_effect=AssertionError("portable assembly must not start"),
                ) as assemble:
                    with self.assertRaisesRegex(TypeError, "exact str or platform Path"):
                        owner_candidate.assemble_owner_portable_candidate(
                            canonical,
                            launcher,
                            documents,
                            output,
                            archive,
                            integration_sha=_SHA,
                            expected_document_sha256=("1" * 64, "2" * 64),
                            expected_sound_archive_sha256=_ARCHIVE_SHA,
                        )
                assemble.assert_not_called()
                self.assertEqual(touched, [])

        for source_count, game_count in ((ActiveCount(6), 3738), (6, ActiveCount(3738))):
            with self.subTest(
                source_count=type(source_count).__name__,
                game_count=type(game_count).__name__,
            ):
                with mock.patch.object(
                    owner_candidate,
                    "assemble_portable_oneclick_tree",
                    side_effect=AssertionError("portable assembly must not start"),
                ) as assemble:
                    with self.assertRaisesRegex(
                        owner_candidate.OwnerPortableCandidateError,
                        "count is invalid",
                    ):
                        owner_candidate.assemble_owner_portable_candidate(
                            "canonical",
                            "launcher.exe",
                            ("first.docx", "second.docx"),
                            "output",
                            "candidate.zip",
                            integration_sha=_SHA,
                            expected_document_sha256=("1" * 64, "2" * 64),
                            expected_sound_archive_sha256=_ARCHIVE_SHA,
                            expected_seed_source_count=source_count,
                            expected_seed_game_count=game_count,
                        )
                assemble.assert_not_called()
                self.assertEqual(touched, [])

    def test_builder_binds_doc_hashes_and_requires_seed_in_both_package_stages(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            root = work / "candidate-tree"
            root.mkdir()
            first = work / "Посібник.docx"
            second = work / "Опис.docx"
            first_payload = b"first-authorized-document"
            second_payload = b"second-authorized-document"
            first.write_bytes(first_payload)
            second.write_bytes(second_payload)
            (root / first.name).write_bytes(first_payload)
            (root / second.name).write_bytes(second_payload)
            archive = work / "candidate.zip"
            archive.write_bytes(b"zip")
            assembled = _portable_report(root)
            archived = Version2PortablePackageReport(
                package_root=root,
                integration_sha=_SHA,
                inventory=(),
                total_bytes=1,
                archive_path=archive,
                archive_sha256=_digest(b"zip"),
            )
            qualification = {
                "sound_archive_sha256": _ARCHIVE_SHA,
                "sound_inventory_sha256": "d" * 64,
                "sound_wav_count": 330,
                "package_checksum_sha256": _PACKAGE_CHECKSUM_SHA,
                "seed_source_count": 6,
                "seed_game_count": 3738,
            }

            with (
                mock.patch.object(
                    owner_candidate,
                    "assemble_portable_oneclick_tree",
                    return_value=assembled,
                ) as assemble,
                mock.patch.object(
                    owner_candidate,
                    "validate_owner_portable_candidate_tree",
                    return_value=qualification,
                ) as qualify,
                mock.patch.object(
                    owner_candidate,
                    "write_portable_oneclick_zip",
                    return_value=archived,
                ) as write_zip,
            ):
                report = owner_candidate.assemble_owner_portable_candidate(
                    work / "canonical",
                    work / "launcher.exe",
                    (first, second),
                    root,
                    archive,
                    integration_sha=_SHA,
                    expected_document_sha256=(
                        _digest(first_payload),
                        _digest(second_payload),
                    ),
                    expected_sound_archive_sha256=_ARCHIVE_SHA,
                )

            assemble.assert_called_once_with(
                work / "canonical",
                work / "launcher.exe",
                (first, second),
                root,
                integration_sha=_SHA,
                require_user_seed=True,
            )
            qualify.assert_called_once_with(
                root,
                expected_integration_sha=_SHA,
                expected_sound_archive_sha256=_ARCHIVE_SHA,
                expected_seed_source_count=6,
                expected_seed_game_count=3738,
            )
            write_zip.assert_called_once_with(
                root,
                archive,
                expected_integration_sha=_SHA,
                require_user_seed=True,
                expected_checksum_sha256=_PACKAGE_CHECKSUM_SHA,
            )
            self.assertEqual(report.archive_sha256, _digest(b"zip"))
            self.assertEqual(report.package_checksum_sha256, _PACKAGE_CHECKSUM_SHA)
            self.assertEqual(report.sound_wav_count, 330)
            self.assertEqual(report.seed_game_count, 3738)

    def test_builder_rejects_wrong_authorized_document_hash_before_zip_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            root = work / "candidate-tree"
            root.mkdir()
            first = work / "first.docx"
            second = work / "second.docx"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            (root / first.name).write_bytes(b"one")
            (root / second.name).write_bytes(b"changed-after-authorization")

            with (
                mock.patch.object(
                    owner_candidate,
                    "assemble_portable_oneclick_tree",
                    return_value=_portable_report(root),
                ),
                mock.patch.object(
                    owner_candidate,
                    "write_portable_oneclick_zip",
                ) as write_zip,
            ):
                with self.assertRaisesRegex(
                    owner_candidate.OwnerPortableCandidateError,
                    "authorized SHA-256",
                ):
                    owner_candidate.assemble_owner_portable_candidate(
                        work / "canonical",
                        work / "launcher.exe",
                        (first, second),
                        root,
                        work / "candidate.zip",
                        integration_sha=_SHA,
                        expected_document_sha256=(
                            _digest(b"one"),
                            _digest(b"two"),
                        ),
                        expected_sound_archive_sha256=_ARCHIVE_SHA,
                    )
            write_zip.assert_not_called()


if __name__ == "__main__":
    unittest.main()
