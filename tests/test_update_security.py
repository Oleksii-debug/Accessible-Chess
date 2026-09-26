import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from acs.update_security import UpdateSecurityError, verify_update_package


_NOW = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)


def _canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


class _TestVerifier:
    def __init__(self, key=b"public-test-fixture"):
        self.key = key

    def sign(self, message: bytes) -> bytes:
        return hashlib.sha256(self.key + message).digest()

    def verify(self, *, key_id: str, message: bytes, signature: bytes) -> bool:
        return key_id == "release-2026" and signature == self.sign(message)


def _metadata(package: bytes, **changes) -> bytes:
    signed = {
        "schema_version": 1,
        "product": "accessible-chess",
        "version": "2.1.0",
        "minimum_current_version": "2.0.0",
        "published_at": "2026-09-26T17:00:00Z",
        "expires_at": "2026-10-03T17:00:00Z",
        "download_url": "https://updates.example.invalid/releases/2.1.0/AccessibleChess.exe",
        "package_sha256": hashlib.sha256(package).hexdigest(),
        "package_size": len(package),
        "key_id": "release-2026",
    }
    signed.update(changes)
    verifier = _TestVerifier()
    return json.dumps(
        {
            "signed": signed,
            "signature": base64.b64encode(verifier.sign(_canonical(signed))).decode("ascii"),
        },
        separators=(",", ":"),
    ).encode("utf-8")


class UpdateSecurityTests(unittest.TestCase):
    def _package(self, root: Path, payload=b"MZ-accessible-chess-update") -> Path:
        path = root / "AccessibleChess-update.exe"
        path.write_bytes(payload)
        return path

    def test_authentic_forward_update_returns_verified_capability(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = b"MZ-accessible-chess-update"
            package = self._package(root, payload)
            verified = verify_update_package(
                _metadata(payload),
                package,
                current_version="2.0.0",
                verifier=_TestVerifier(),
                now=_NOW,
            )
            self.assertEqual(verified.version, "2.1.0")
            self.assertEqual(verified.package_path, package)
            self.assertEqual(
                verified.download_url,
                "https://updates.example.invalid/releases/2.1.0/AccessibleChess.exe",
            )
            self.assertEqual(verified.package_sha256, hashlib.sha256(payload).hexdigest())
            self.assertEqual(verified.key_id, "release-2026")

    def test_unsigned_or_bad_signature_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = b"MZ-update"
            package = self._package(root, payload)
            envelope = json.loads(_metadata(payload))
            envelope["signature"] = ""
            with self.assertRaisesRegex(UpdateSecurityError, "signature is missing"):
                verify_update_package(
                    json.dumps(envelope).encode(), package,
                    current_version="2.0.0", verifier=_TestVerifier(), now=_NOW,
                )
            envelope = json.loads(_metadata(payload))
            envelope["signature"] = base64.b64encode(b"forged").decode()
            with self.assertRaisesRegex(UpdateSecurityError, "signature verification failed"):
                verify_update_package(
                    json.dumps(envelope).encode(), package,
                    current_version="2.0.0", verifier=_TestVerifier(), now=_NOW,
                )

    def test_signed_metadata_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            payload = b"MZ-update"
            package = self._package(Path(td), payload)
            envelope = json.loads(_metadata(payload))
            envelope["signed"]["version"] = "9.9.9"
            with self.assertRaisesRegex(UpdateSecurityError, "signature verification failed"):
                verify_update_package(
                    json.dumps(envelope).encode(), package,
                    current_version="2.0.0", verifier=_TestVerifier(), now=_NOW,
                )

    def test_payload_tamper_is_detected_after_authentic_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = b"MZ-original"
            package = self._package(root, b"MZ-tampered")
            with self.assertRaisesRegex(UpdateSecurityError, "size mismatch|digest mismatch"):
                verify_update_package(
                    _metadata(original), package,
                    current_version="2.0.0", verifier=_TestVerifier(), now=_NOW,
                )

    def test_equal_version_downgrade_and_too_old_source_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = b"MZ-update"
            package = self._package(root, payload)
            for current in ("2.1.0", "2.2.0"):
                with self.subTest(current=current):
                    with self.assertRaisesRegex(UpdateSecurityError, "would not advance"):
                        verify_update_package(
                            _metadata(payload), package,
                            current_version=current, verifier=_TestVerifier(), now=_NOW,
                        )
            with self.assertRaisesRegex(UpdateSecurityError, "too old"):
                verify_update_package(
                    _metadata(payload), package,
                    current_version="1.9.9", verifier=_TestVerifier(), now=_NOW,
                )

    def test_expired_or_future_metadata_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            payload = b"MZ-update"
            package = self._package(Path(td), payload)
            expired = _metadata(payload, expires_at="2026-09-26T17:30:00Z")
            with self.assertRaisesRegex(UpdateSecurityError, "expired"):
                verify_update_package(
                    expired, package, current_version="2.0.0",
                    verifier=_TestVerifier(), now=_NOW,
                )
            future = _metadata(payload, published_at="2026-09-26T19:00:00Z")
            with self.assertRaisesRegex(UpdateSecurityError, "not yet valid"):
                verify_update_package(
                    future, package, current_version="2.0.0",
                    verifier=_TestVerifier(), now=_NOW,
                )

    def test_download_url_is_signed_https_only_and_unambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            payload = b"MZ-update"
            package = self._package(Path(td), payload)
            invalid_urls = (
                "http://updates.example.invalid/update.exe",
                "https://user:secret@updates.example.invalid/update.exe",
                "https://updates.example.invalid/update.exe#fragment",
                "https://updates.example.invalid\\update.exe",
                "HTTPS://updates.example.invalid/update.exe",
            )
            for value in invalid_urls:
                with self.subTest(download_url=value):
                    with self.assertRaisesRegex(UpdateSecurityError, "download URL"):
                        verify_update_package(
                            _metadata(payload, download_url=value),
                            package,
                            current_version="2.0.0",
                            verifier=_TestVerifier(),
                            now=_NOW,
                        )

    def test_download_url_tamper_breaks_signature(self):
        with tempfile.TemporaryDirectory() as td:
            payload = b"MZ-update"
            package = self._package(Path(td), payload)
            envelope = json.loads(_metadata(payload))
            envelope["signed"]["download_url"] = "https://mirror.example.invalid/update.exe"
            with self.assertRaisesRegex(UpdateSecurityError, "signature verification failed"):
                verify_update_package(
                    json.dumps(envelope).encode(),
                    package,
                    current_version="2.0.0",
                    verifier=_TestVerifier(),
                    now=_NOW,
                )

    def test_extra_fields_and_duplicate_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            payload = b"MZ-update"
            package = self._package(Path(td), payload)
            envelope = json.loads(_metadata(payload))
            envelope["signed"]["unexpected"] = "https://attacker.invalid/update"
            with self.assertRaisesRegex(UpdateSecurityError, "signed update metadata is invalid"):
                verify_update_package(
                    json.dumps(envelope).encode(), package,
                    current_version="2.0.0", verifier=_TestVerifier(), now=_NOW,
                )
            duplicate = b'{"signed":{},"signed":{},"signature":"x"}'
            with self.assertRaisesRegex(UpdateSecurityError, "metadata is invalid"):
                verify_update_package(
                    duplicate, package, current_version="2.0.0",
                    verifier=_TestVerifier(), now=_NOW,
                )

    def test_symlink_package_is_rejected(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = b"MZ-update"
            real = self._package(root, payload)
            link = root / "candidate.exe"
            try:
                os.symlink(real, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(UpdateSecurityError, "regular non-reparse"):
                verify_update_package(
                    _metadata(payload), link, current_version="2.0.0",
                    verifier=_TestVerifier(), now=_NOW,
                )


if __name__ == "__main__":
    unittest.main()
