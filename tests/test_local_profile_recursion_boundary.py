from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.local_profile import (
    LocalProfileError,
    LocalProfileStore,
    MAX_PROFILE_BYTES,
    parse_local_profile_bytes,
)


def _deep_json_payload() -> bytes:
    # CPython's JSON decoder protects itself with the interpreter recursion limit.
    # Keep the payload comfortably under the product byte bound while exceeding
    # the normal decoder nesting limit used by supported Python runtimes.
    depth = 2_000
    payload = ("[" * depth + "0" + "]" * depth).encode("ascii")
    if len(payload) > MAX_PROFILE_BYTES:
        raise AssertionError("recursion oracle must remain inside the profile byte bound")
    return payload


class LocalProfileRecursionBoundaryTests(unittest.TestCase):
    def test_deep_json_is_normalized_to_local_profile_error(self) -> None:
        payload = _deep_json_payload()

        with self.assertRaisesRegex(LocalProfileError, "profile payload is not valid JSON"):
            parse_local_profile_bytes(payload)

    def test_deep_primary_uses_verified_backup_without_rewriting_primary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = LocalProfileStore(Path(temp) / "profile.json")
            original = store.create("Alice")
            store.rename(original, "Alice Two")
            backup_before = store.backup_path.read_bytes()
            payload = _deep_json_payload()
            store.path.write_bytes(payload)

            recovered = store.load()

            self.assertEqual(recovered, original)
            self.assertEqual(store.path.read_bytes(), payload)
            self.assertEqual(store.backup_path.read_bytes(), backup_before)

    def test_deep_primary_without_backup_fails_closed_and_preserves_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = LocalProfileStore(Path(temp) / "profile.json")
            payload = _deep_json_payload()
            store.path.write_bytes(payload)

            with self.assertRaisesRegex(
                LocalProfileError,
                "local profile is unreadable and has no recovery copy",
            ):
                store.load()

            self.assertEqual(store.path.read_bytes(), payload)
            self.assertFalse(store.backup_path.exists())


if __name__ == "__main__":
    unittest.main()
