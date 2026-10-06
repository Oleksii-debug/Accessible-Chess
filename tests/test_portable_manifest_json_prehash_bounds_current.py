from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import acs.version2_package_assembler as assembler
import acs.version2_package_preflight as preflight
import acs.version2_portable_package as portable
from acs.version2_package_preflight import Version2PackagePreflightError
from acs.version2_portable_package import Version2PortablePackageError


class _HashBombKey(str):
    def __hash__(self) -> int:
        raise AssertionError("object key was hashed before the resource guard")


class PortableManifestJsonPrehashBoundsTests(unittest.TestCase):
    def test_small_manifest_object_still_parses(self) -> None:
        payload = json.dumps(
            {"product": "Accessible Chess", "nested": {"ok": True}},
            separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(
            portable._strict_json_bytes(payload),
            {"product": "Accessible Chess", "nested": {"ok": True}},
        )

    def test_duplicate_manifest_key_remains_rejected(self) -> None:
        with self.assertRaisesRegex(
            Version2PortablePackageError,
            "duplicate keys",
        ):
            portable._strict_json_bytes(b'{"product":1,"product":2}')

    def test_overlong_manifest_key_is_rejected(self) -> None:
        oversized = "k" * (portable._PORTABLE_MANIFEST_MAX_KEY_CHARS + 1)
        payload = json.dumps({oversized: 1}, separators=(",", ":")).encode("utf-8")
        with self.assertRaisesRegex(
            Version2PortablePackageError,
            "object key is too long",
        ):
            portable._strict_json_bytes(payload)

    def test_manifest_object_member_count_is_bounded(self) -> None:
        payload = json.dumps(
            {
                f"field-{index}": index
                for index in range(portable._PORTABLE_MANIFEST_MAX_OBJECT_MEMBERS + 1)
            },
            separators=(",", ":"),
        ).encode("utf-8")
        with self.assertRaisesRegex(
            Version2PortablePackageError,
            "too many object members",
        ):
            portable._strict_json_bytes(payload)

    def test_decoder_recursion_failure_is_fail_closed(self) -> None:
        with mock.patch.object(
            portable.json,
            "loads",
            side_effect=RecursionError("maximum recursion depth exceeded"),
        ):
            with self.assertRaisesRegex(
                Version2PortablePackageError,
                "invalid: RecursionError",
            ):
                portable._strict_json_bytes(b"{}")

    def test_key_length_guard_runs_before_first_hash(self) -> None:
        hostile = _HashBombKey(
            "x" * (portable._PORTABLE_MANIFEST_MAX_KEY_CHARS + 1)
        )
        with self.assertRaisesRegex(
            Version2PortablePackageError,
            "object key is too long",
        ):
            portable._strict_json_object_pairs([(hostile, 1)])

    def test_member_count_guard_runs_before_next_key_hash(self) -> None:
        pairs = [
            (f"field-{index}", index)
            for index in range(portable._PORTABLE_MANIFEST_MAX_OBJECT_MEMBERS)
        ]
        pairs.append((_HashBombKey("overflow"), 1))
        with self.assertRaisesRegex(
            Version2PortablePackageError,
            "too many object members",
        ):
            portable._strict_json_object_pairs(pairs)

    def test_exact_resource_limits_remain_accepted(self) -> None:
        key = "k" * portable._PORTABLE_MANIFEST_MAX_KEY_CHARS
        pairs = [(key, 0)] + [
            (f"field-{index}", index)
            for index in range(portable._PORTABLE_MANIFEST_MAX_OBJECT_MEMBERS - 1)
        ]
        result = portable._strict_json_object_pairs(pairs)
        self.assertEqual(len(result), portable._PORTABLE_MANIFEST_MAX_OBJECT_MEMBERS)
        self.assertEqual(result[key], 0)

    def test_canonical_release_manifest_key_length_is_bounded(self) -> None:
        oversized = "k" * (preflight._RELEASE_MANIFEST_MAX_KEY_CHARS + 1)
        text = json.dumps({oversized: 1}, separators=(",", ":"))
        with self.assertRaisesRegex(
            Version2PackagePreflightError,
            "release manifest JSON key is too long",
        ):
            preflight._json_no_duplicates(
                text,
                label="release manifest",
                max_object_members=preflight._RELEASE_MANIFEST_MAX_OBJECT_MEMBERS,
                max_key_chars=preflight._RELEASE_MANIFEST_MAX_KEY_CHARS,
            )

    def test_canonical_release_manifest_member_count_is_bounded(self) -> None:
        text = json.dumps(
            {
                f"field-{index}": index
                for index in range(preflight._RELEASE_MANIFEST_MAX_OBJECT_MEMBERS + 1)
            },
            separators=(",", ":"),
        )
        with self.assertRaisesRegex(
            Version2PackagePreflightError,
            "release manifest contains too many JSON object members",
        ):
            preflight._json_no_duplicates(
                text,
                label="release manifest",
                max_object_members=preflight._RELEASE_MANIFEST_MAX_OBJECT_MEMBERS,
                max_key_chars=preflight._RELEASE_MANIFEST_MAX_KEY_CHARS,
            )

    def test_canonical_release_manifest_read_is_byte_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / preflight.MANIFEST_NAME).write_bytes(
                b" " * (preflight._MAX_RELEASE_MANIFEST_BYTES + 1)
            )
            with self.assertRaisesRegex(
                Version2PackagePreflightError,
                "release manifest exceeds archive byte limit",
            ):
                preflight._manifest(root)

    def test_canonical_release_manifest_normal_writer_still_round_trips(self) -> None:
        integration_sha = "a" * 40
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            assembler._write_manifest(root, integration_sha)
            actual_sha, document = preflight._manifest(root)
        self.assertEqual(actual_sha, integration_sha)
        self.assertEqual(document["product"], "Accessible Chess")
        self.assertFalse(document["human_tested"])
        self.assertFalse(document["nvda_verified"])


if __name__ == "__main__":
    unittest.main()
