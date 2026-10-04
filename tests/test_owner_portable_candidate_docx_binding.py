from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.version2_portable_package import Version2PortablePackageReport
import scripts.build_owner_portable_candidate as owner_candidate


_SHA = "a" * 40
_ARCHIVE_SHA = "b" * 64
_PACKAGE_CHECKSUM_SHA = "e" * 64


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _portable_report(root: Path) -> Version2PortablePackageReport:
    return Version2PortablePackageReport(
        package_root=root,
        integration_sha=_SHA,
        inventory=(),
        total_bytes=1,
        checksum_sha256=_PACKAGE_CHECKSUM_SHA,
    )


class OwnerDocumentBindingRegressionTests(unittest.TestCase):
    def test_document_rewrite_during_owner_qualification_cannot_reach_zip_publication(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            work = Path(raw)
            root = work / "candidate-tree"
            root.mkdir()
            first = work / "Інструкція з користування Доступними Шахами.docx"
            second = work / "Посібник по Доступним Шахам.docx"
            first_payload = b"first-authorized-document"
            second_payload = b"second-authorized-document"
            first.write_bytes(first_payload)
            second.write_bytes(second_payload)
            (root / first.name).write_bytes(first_payload)
            (root / second.name).write_bytes(second_payload)

            qualification = {
                "sound_archive_sha256": _ARCHIVE_SHA,
                "sound_inventory_sha256": "d" * 64,
                "sound_wav_count": 330,
                "package_checksum_sha256": _PACKAGE_CHECKSUM_SHA,
                "seed_source_count": 6,
                "seed_game_count": 3738,
            }

            def qualify_then_rewrite(*args, **kwargs):
                (root / second.name).write_bytes(b"rewritten-after-early-doc-check")
                return qualification

            with (
                mock.patch.object(
                    owner_candidate,
                    "assemble_portable_oneclick_tree",
                    return_value=_portable_report(root),
                ),
                mock.patch.object(
                    owner_candidate,
                    "validate_owner_portable_candidate_tree",
                    side_effect=qualify_then_rewrite,
                ),
                mock.patch.object(
                    owner_candidate,
                    "write_portable_oneclick_zip",
                ) as write_zip,
            ):
                with self.assertRaisesRegex(
                    owner_candidate.OwnerPortableCandidateError,
                    "changed after owner qualification",
                ):
                    owner_candidate.assemble_owner_portable_candidate(
                        work / "canonical",
                        work / "launcher.exe",
                        (first, second),
                        root,
                        work / "candidate.zip",
                        integration_sha=_SHA,
                        expected_document_sha256=(
                            _digest(first_payload),
                            _digest(second_payload),
                        ),
                        expected_sound_archive_sha256=_ARCHIVE_SHA,
                    )

            write_zip.assert_not_called()


if __name__ == "__main__":
    unittest.main()
