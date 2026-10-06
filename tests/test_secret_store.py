from __future__ import annotations

from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
from unittest import mock

import acs.secret_store as secret_store
from acs.secret_store import SecretStoreError, WindowsDpapiSecretStore


class SecretStoreContractTests(unittest.TestCase):
    def test_module_imports_on_every_platform_and_non_windows_fails_closed(self) -> None:
        store = WindowsDpapiSecretStore(Path("unused"))
        if sys.platform != "win32":
            with self.assertRaisesRegex(SecretStoreError, "DPAPI is unavailable"):
                store.write("refresh-token", b"secret")

    def test_slot_names_are_hashed_and_hostile_objects_are_not_stringified(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = WindowsDpapiSecretStore(Path(td))
            target = store._path("refresh-token")
            self.assertTrue(target.name.endswith(".dpapi"))
            self.assertNotIn("refresh", target.name)
            self.assertNotIn("token", target.name)

            conversions: list[str] = []

            class DangerousName:
                def __str__(self) -> str:
                    conversions.append("str")
                    raise AssertionError("secret slot must not invoke __str__")

            with self.assertRaisesRegex(SecretStoreError, "safe stable identifier"):
                store._path(DangerousName())  # type: ignore[arg-type]
            self.assertEqual(conversions, [])

    def test_simulated_dpapi_round_trip_is_atomic_ciphertext_only_and_deletable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = WindowsDpapiSecretStore(Path(td) / "secure")
            secret = b"refresh-token-value-that-must-not-hit-disk"

            def protect(value: bytes, *, entropy: bytes) -> bytes:
                binding = hashlib.sha256(entropy).digest()
                return b"DPAPI-FIXTURE:" + binding + value[::-1]

            def unprotect(value: bytes, *, entropy: bytes) -> bytes:
                prefix = b"DPAPI-FIXTURE:" + hashlib.sha256(entropy).digest()
                if not value.startswith(prefix):
                    raise SecretStoreError("fixture ciphertext rejected")
                return value[len(prefix):][::-1]

            with (
                mock.patch.object(secret_store.sys, "platform", "win32"),
                mock.patch.object(secret_store, "_dpapi_protect", side_effect=protect),
                mock.patch.object(secret_store, "_dpapi_unprotect", side_effect=unprotect),
            ):
                store.write("refresh-token", secret)
                target = store._path("refresh-token")
                ciphertext = target.read_bytes()
                self.assertNotEqual(ciphertext, secret)
                self.assertNotIn(secret, ciphertext)
                self.assertEqual(store.read("refresh-token"), secret)
                self.assertTrue(store.delete("refresh-token"))
                self.assertFalse(store.delete("refresh-token"))
                self.assertIsNone(store.read("refresh-token"))

    def test_ciphertext_cannot_be_swapped_between_logical_slots(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = WindowsDpapiSecretStore(Path(td) / "secure")

            def protect(value: bytes, *, entropy: bytes) -> bytes:
                return b"BOUND:" + hashlib.sha256(entropy).digest() + value

            def unprotect(value: bytes, *, entropy: bytes) -> bytes:
                prefix = b"BOUND:" + hashlib.sha256(entropy).digest()
                if not value.startswith(prefix):
                    raise SecretStoreError("fixture slot binding rejected")
                return value[len(prefix):]

            with (
                mock.patch.object(secret_store.sys, "platform", "win32"),
                mock.patch.object(secret_store, "_dpapi_protect", side_effect=protect),
                mock.patch.object(secret_store, "_dpapi_unprotect", side_effect=unprotect),
            ):
                store.write("refresh-token", b"refresh-secret")
                store.write("access-token", b"access-secret")
                refresh_path = store._path("refresh-token")
                access_path = store._path("access-token")
                refresh_cipher = refresh_path.read_bytes()
                access_cipher = access_path.read_bytes()
                refresh_path.write_bytes(access_cipher)
                access_path.write_bytes(refresh_cipher)

                with self.assertRaisesRegex(SecretStoreError, "slot binding rejected"):
                    store.read("refresh-token")
                with self.assertRaisesRegex(SecretStoreError, "slot binding rejected"):
                    store.read("access-token")

    def test_empty_plaintext_fails_closed_on_write_and_read(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = WindowsDpapiSecretStore(Path(td) / "secure")
            with (
                mock.patch.object(secret_store.sys, "platform", "win32"),
                mock.patch.object(secret_store, "_dpapi_protect") as protect,
            ):
                with self.assertRaisesRegex(SecretStoreError, "must not be empty"):
                    store.write("refresh-token", b"")
                protect.assert_not_called()

            store._prepare_root()
            target = store._path("refresh-token")
            target.write_bytes(b"non-empty-ciphertext")
            with (
                mock.patch.object(secret_store.sys, "platform", "win32"),
                mock.patch.object(secret_store, "_dpapi_unprotect", return_value=b""),
            ):
                with self.assertRaisesRegex(SecretStoreError, "unprotected secret is empty"):
                    store.read("refresh-token")

    def test_secret_and_ciphertext_size_limits_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = WindowsDpapiSecretStore(Path(td) / "secure")
            with (
                mock.patch.object(secret_store.sys, "platform", "win32"),
                mock.patch.object(secret_store, "_dpapi_protect", return_value=b"cipher"),
            ):
                with self.assertRaisesRegex(SecretStoreError, "secret value exceeds size limit"):
                    store.write("refresh-token", b"x" * (secret_store._MAX_SECRET_BYTES + 1))

                store._prepare_root()
                target = store._path("refresh-token")
                target.write_bytes(b"x" * (secret_store._MAX_CIPHERTEXT_BYTES + 1))
                with self.assertRaisesRegex(SecretStoreError, "ciphertext exceeds size limit"):
                    store.read("refresh-token")

    def test_symlink_secret_file_is_rejected_before_read_or_replace(self) -> None:
        if not hasattr(Path, "symlink_to"):
            self.skipTest("symlinks unsupported")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "secure"
            root.mkdir()
            store = WindowsDpapiSecretStore(root)
            target = store._path("refresh-token")
            elsewhere = Path(td) / "elsewhere"
            elsewhere.write_bytes(b"not-a-secret")
            try:
                target.symlink_to(elsewhere)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with mock.patch.object(secret_store.sys, "platform", "win32"):
                with self.assertRaisesRegex(SecretStoreError, "symlink or reparse point"):
                    store.read("refresh-token")

    def test_read_rejects_target_swapped_to_symlink_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "secure"
            root.mkdir()
            store = WindowsDpapiSecretStore(root)
            target = store._path("refresh-token")
            target.write_bytes(b"original-ciphertext")
            external = Path(td) / "external-ciphertext"
            external.write_bytes(b"valid-but-replayed-ciphertext")
            original_open = Path.open
            raced = {"done": False}

            def racing_open(path: Path, *args, **kwargs):
                mode = args[0] if args else kwargs.get("mode", "r")
                if path == target and mode == "rb" and not raced["done"]:
                    raced["done"] = True
                    target.unlink()
                    try:
                        target.symlink_to(external)
                    except (OSError, NotImplementedError) as exc:
                        self.skipTest(f"symlink creation unavailable: {type(exc).__name__}")
                return original_open(path, *args, **kwargs)

            with (
                mock.patch.object(secret_store.sys, "platform", "win32"),
                mock.patch.object(Path, "open", new=racing_open),
                mock.patch.object(secret_store, "_dpapi_unprotect") as unprotect,
            ):
                with self.assertRaisesRegex(
                    SecretStoreError,
                    "changed before verified read|regular non-reparse file",
                ):
                    store.read("refresh-token")
            self.assertTrue(raced["done"])
            unprotect.assert_not_called()

    def test_symlink_ancestor_is_rejected_before_store_creation_or_dpapi(self) -> None:
        if not hasattr(Path, "symlink_to"):
            self.skipTest("symlinks unsupported")
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            outside = base / "outside"
            outside.mkdir()
            redirected_parent = base / "app"
            try:
                redirected_parent.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlink creation unavailable")
            store = WindowsDpapiSecretStore(redirected_parent / "secure")
            with (
                mock.patch.object(secret_store.sys, "platform", "win32"),
                mock.patch.object(secret_store, "_dpapi_protect") as protect,
            ):
                with self.assertRaisesRegex(SecretStoreError, "symlink or reparse point"):
                    store.write("refresh-token", b"must-not-redirect")
            protect.assert_not_called()
            self.assertFalse((outside / "secure").exists())


@unittest.skipUnless(sys.platform == "win32", "real DPAPI qualification requires Windows")
class WindowsDpapiIntegrationTests(unittest.TestCase):
    def test_current_user_dpapi_round_trip_does_not_persist_plaintext(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = WindowsDpapiSecretStore(Path(td) / "secure")
            secret = b"accessible-chess-real-dpapi-round-trip-secret"
            store.write("refresh-token", secret)
            target = store._path("refresh-token")
            ciphertext = target.read_bytes()
            self.assertGreater(len(ciphertext), 0)
            self.assertNotEqual(ciphertext, secret)
            self.assertNotIn(secret, ciphertext)
            self.assertEqual(store.read("refresh-token"), secret)
            self.assertTrue(store.delete("refresh-token"))
            self.assertIsNone(store.read("refresh-token"))


if __name__ == "__main__":
    unittest.main()
