from __future__ import annotations

import inspect
from pathlib import Path
import unittest
from unittest.mock import patch

from acs.version2_portable_package import Version2PortablePackageError
from scripts import build_owner_portable_candidate as candidate


class OwnerPortableCandidateStableReadTests(unittest.TestCase):
    def test_owner_document_digest_reuses_canonical_stable_digest(self) -> None:
        path = Path("Owner Document.docx")
        expected = "a" * 64
        with patch.object(candidate, "_stable_digest", return_value=expected) as stable:
            self.assertEqual(candidate._file_sha256(path), expected)
        stable.assert_called_once_with(
            path,
            label="owner candidate file Owner Document.docx",
        )

    def test_owner_document_digest_fails_closed_on_unstable_snapshot(self) -> None:
        path = Path("Owner Document.docx")
        with patch.object(
            candidate,
            "_stable_digest",
            side_effect=Version2PortablePackageError("changed while being read"),
        ):
            with self.assertRaisesRegex(
                candidate.OwnerPortableCandidateError,
                "candidate file cannot be hashed safely",
            ):
                candidate._file_sha256(path)

    def test_owner_json_uses_bounded_canonical_stable_snapshot(self) -> None:
        path = Path("inventory.json")
        payload = b'{"schema_version":1}'
        with patch.object(candidate, "_stable_bytes", return_value=payload) as stable:
            self.assertEqual(
                candidate._strict_json_object(path, label="owner sound inventory"),
                {"schema_version": 1},
            )
        stable.assert_called_once_with(
            path,
            label="owner sound inventory",
            maximum=candidate._OWNER_JSON_MAX_BYTES,
        )

    def test_owner_json_fails_closed_on_unstable_snapshot(self) -> None:
        with patch.object(
            candidate,
            "_stable_bytes",
            side_effect=Version2PortablePackageError("changed while being read"),
        ):
            with self.assertRaisesRegex(
                candidate.OwnerPortableCandidateError,
                "owner sound inventory cannot be read safely",
            ):
                candidate._strict_json_object(
                    Path("inventory.json"),
                    label="owner sound inventory",
                )

    def test_sound_bytes_are_not_verified_by_stat_then_second_read(self) -> None:
        source = inspect.getsource(candidate._validate_owner_sound_pack)
        self.assertIn("_stable_bytes(", source)
        self.assertIn("maximum=expected_size", source)
        self.assertIn("hashlib.sha256(payload).hexdigest()", source)
        self.assertNotIn("path.stat().st_size", source)
        self.assertNotIn("_file_sha256(path)", source)


if __name__ == "__main__":
    unittest.main()
