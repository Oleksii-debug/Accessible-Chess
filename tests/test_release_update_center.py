from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from acs.release_update_center import ReleaseUpdateCenter, ReleaseUpdateError, StagedUpdate

NOW = datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class Verifier:
    def sign(self, message):
        return hashlib.sha256(b"test-public-fixture" + message).digest()

    def verify(self, *, key_id, message, signature):
        return key_id == "release-2026" and signature == self.sign(message)


class Time:
    def utc_now(self):
        return NOW


class Channel:
    def __init__(self, candidate):
        self.candidate = candidate
        self.calls = []

    def stage(self, *, current_version):
        self.calls.append(current_version)
        return self.candidate


class Installer:
    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def install(self, *, version, stream):
        self.calls.append((version, stream.read()))
        return self.result


def make_metadata(package, verifier, *, url="https://updates.example.invalid/v2.1.0.zip", version="2.1.0"):
    signed = {
        "schema_version": 1,
        "product": "accessible-chess",
        "version": version,
        "minimum_current_version": "2.0.0",
        "published_at": "2026-10-07T19:00:00Z",
        "expires_at": "2026-10-08T19:00:00Z",
        "download_url": url,
        "package_sha256": hashlib.sha256(package).hexdigest(),
        "package_size": len(package),
        "key_id": "release-2026",
    }
    return canonical({
        "signed": signed,
        "signature": base64.b64encode(verifier.sign(canonical(signed))).decode("ascii"),
    })


class ReleaseUpdateCenterTests(unittest.TestCase):
    def build(self, root, package=b"verified-package", *, source_url=None, installer_result=True):
        verifier = Verifier()
        package_path = Path(root) / "candidate.zip"
        package_path.write_bytes(package)
        url = source_url or "https://updates.example.invalid/v2.1.0.zip"
        candidate = StagedUpdate(
            metadata=make_metadata(package, verifier),
            package_path=package_path,
            source_url=url,
        )
        channel = Channel(candidate)
        installer = Installer(installer_result)
        center = ReleaseUpdateCenter(
            current_version="2.0.0",
            channel=channel,
            verifier=verifier,
            time_source=Time(),
            installer=installer,
        )
        return center, channel, installer, package_path

    def test_check_mints_only_verified_candidate_and_hides_path(self):
        with tempfile.TemporaryDirectory() as root:
            center, channel, installer, path = self.build(root)
            result = center.check(language="uk")
            self.assertEqual(result.state, "ready")
            self.assertEqual(result.target_version, "2.1.0")
            self.assertEqual(channel.calls, ["2.0.0"])
            self.assertNotIn(str(path), json.dumps(result.to_mapping(), ensure_ascii=False))
            self.assertEqual(installer.calls, [])

    def test_apply_revalidates_exact_bytes_and_passes_only_open_stream(self):
        with tempfile.TemporaryDirectory() as root:
            center, _channel, installer, _path = self.build(root)
            center.check(language="en")
            result = center.apply(language="en")
            self.assertEqual(result.state, "installed")
            self.assertEqual(installer.calls, [("2.1.0", b"verified-package")])
            self.assertIsNone(center.target_version)

    def test_tamper_between_check_and_apply_fails_before_installer(self):
        with tempfile.TemporaryDirectory() as root:
            center, _channel, installer, path = self.build(root)
            center.check(language="en")
            path.write_bytes(b"tampered-package")
            with self.assertRaisesRegex(ReleaseUpdateError, "could not be installed safely"):
                center.apply(language="en")
            self.assertEqual(installer.calls, [])
            self.assertIsNone(center.target_version)

    def test_signed_source_url_mismatch_fails_closed_and_redacts_path(self):
        with tempfile.TemporaryDirectory() as root:
            center, _channel, installer, path = self.build(
                root, source_url="https://mirror.example.invalid/v2.1.0.zip"
            )
            with self.assertRaisesRegex(ReleaseUpdateError, "does not match signed metadata") as raised:
                center.check(language="en")
            self.assertNotIn(str(path), str(raised.exception))
            self.assertEqual(installer.calls, [])
            self.assertIsNone(center.target_version)

    def test_invalid_signature_never_reaches_installer(self):
        with tempfile.TemporaryDirectory() as root:
            center, channel, installer, _path = self.build(root)
            raw = json.loads(channel.candidate.metadata)
            raw["signature"] = base64.b64encode(b"forged").decode("ascii")
            channel.candidate = StagedUpdate(
                metadata=canonical(raw),
                package_path=channel.candidate.package_path,
                source_url=channel.candidate.source_url,
            )
            with self.assertRaisesRegex(ReleaseUpdateError, "security verification"):
                center.check(language="en")
            self.assertEqual(installer.calls, [])

    def test_equal_version_is_rejected_by_canonical_security_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            verifier = Verifier()
            package = b"payload"
            path = Path(root) / "candidate.zip"
            path.write_bytes(package)
            url = "https://updates.example.invalid/v2.0.0.zip"
            candidate = StagedUpdate(
                metadata=make_metadata(package, verifier, url=url, version="2.0.0"),
                package_path=path,
                source_url=url,
            )
            installer = Installer()
            center = ReleaseUpdateCenter(
                current_version="2.0.0",
                channel=Channel(candidate),
                verifier=verifier,
                time_source=Time(),
                installer=installer,
            )
            with self.assertRaisesRegex(ReleaseUpdateError, "security verification"):
                center.check(language="en")
            self.assertEqual(installer.calls, [])

    def test_no_update_returns_current_accessible_state(self):
        center = ReleaseUpdateCenter(
            current_version="2.0.0",
            channel=Channel(None),
            verifier=Verifier(),
            time_source=Time(),
            installer=Installer(),
        )
        result = center.check(language="uk")
        self.assertEqual(result.state, "current")
        self.assertIn("актуальну", result.announcement)

    def test_provider_exception_is_sanitized(self):
        class Broken:
            def stage(self, *, current_version):
                raise RuntimeError("C:/secret/token.txt API_KEY=bad")

        center = ReleaseUpdateCenter(
            current_version="2.0.0",
            channel=Broken(),
            verifier=Verifier(),
            time_source=Time(),
            installer=Installer(),
        )
        with self.assertRaises(ReleaseUpdateError) as raised:
            center.check(language="en")
        self.assertNotIn("secret", str(raised.exception).lower())
        self.assertNotIn("api_key", str(raised.exception).lower())

    def test_installer_refusal_is_not_success_and_requires_recheck(self):
        with tempfile.TemporaryDirectory() as root:
            center, _channel, installer, _path = self.build(root, installer_result=False)
            center.check(language="en")
            with self.assertRaisesRegex(ReleaseUpdateError, "did not confirm"):
                center.apply(language="en")
            self.assertEqual(len(installer.calls), 1)
            with self.assertRaisesRegex(ReleaseUpdateError, "Check for updates"):
                center.apply(language="en")

    def test_language_and_staged_candidate_contracts_are_strict(self):
        with self.assertRaises(ValueError):
            StagedUpdate(metadata=b"", package_path=Path("x"), source_url="https://x")
        with tempfile.TemporaryDirectory() as root:
            center, _channel, _installer, _path = self.build(root)
            with self.assertRaises(ValueError):
                center.snapshot(language="sk")


if __name__ == "__main__":
    unittest.main()
