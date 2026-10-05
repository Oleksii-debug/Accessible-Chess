from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from acs.application_update import (
    ApplicationUpdateError,
    ApplicationUpdateManifest,
    SemVer,
    UPDATE_MANIFEST_SCHEMA,
    verify_artifact_bytes,
    verify_local_update,
)


class ApplicationUpdateReuseTests(unittest.TestCase):
    SOURCE = "a" * 40

    @staticmethod
    def _manifest_for(
        artifact: bytes,
        *,
        name: str = "AccessibleChess-2.0.0.zip",
        version: str = "2.0.0",
        product: str = "accessible-chess",
        platform: str = "windows-x64",
    ) -> ApplicationUpdateManifest:
        return ApplicationUpdateManifest.from_mapping(
            {
                "schema": UPDATE_MANIFEST_SCHEMA,
                "product_id": product,
                "target_platform": platform,
                "target_version": version,
                "source_head": ApplicationUpdateReuseTests.SOURCE,
                "artifact_name": name,
                "artifact_size": len(artifact),
                "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
            }
        )

    def test_semver_precedence(self):
        self.assertGreater(
            SemVer.parse("2.0.0").compare_precedence(SemVer.parse("1.9.9")),
            0,
        )
        self.assertLess(
            SemVer.parse("2.0.0-rc.1").compare_precedence(SemVer.parse("2.0.0")),
            0,
        )
        self.assertLess(
            SemVer.parse("2.0.0-1").compare_precedence(SemVer.parse("2.0.0-alpha")),
            0,
        )

    def test_verify_artifact_bytes(self):
        artifact = b"accessible-chess-update"
        manifest = self._manifest_for(artifact)
        verified = verify_artifact_bytes(
            manifest,
            artifact,
            current_version="1.9.0",
        )
        self.assertEqual(verified.target_version, "2.0.0")
        self.assertEqual(verified.artifact_sha256, hashlib.sha256(artifact).hexdigest())

    def test_wrong_hash_fails_closed(self):
        artifact = b"good"
        manifest = self._manifest_for(artifact)
        with self.assertRaises(ApplicationUpdateError):
            verify_artifact_bytes(
                manifest,
                b"evil",
                current_version="1.0.0",
            )

    def test_wrong_product_and_platform_fail_closed(self):
        artifact = b"package"
        with self.assertRaises(ApplicationUpdateError):
            verify_artifact_bytes(
                self._manifest_for(artifact, product="other-product"),
                artifact,
                current_version="1.0.0",
            )
        with self.assertRaises(ApplicationUpdateError):
            verify_artifact_bytes(
                self._manifest_for(artifact, platform="linux-x64"),
                artifact,
                current_version="1.0.0",
            )

    def test_equal_version_and_downgrade_are_rejected(self):
        artifact = b"package"
        manifest = self._manifest_for(artifact, version="2.0.0")
        with self.assertRaises(ApplicationUpdateError):
            verify_artifact_bytes(manifest, artifact, current_version="2.0.0")
        with self.assertRaises(ApplicationUpdateError):
            verify_artifact_bytes(manifest, artifact, current_version="3.0.0")

    def test_duplicate_manifest_key_is_rejected(self):
        payload = (
            "{"
            f'"schema":"{UPDATE_MANIFEST_SCHEMA}",'
            '"product_id":"accessible-chess",'
            '"product_id":"accessible-chess",'
            '"target_platform":"windows-x64",'
            '"target_version":"2.0.0",'
            f'"source_head":"{self.SOURCE}",'
            '"artifact_name":"AccessibleChess-2.0.0.zip",'
            '"artifact_size":1,'
            f'"artifact_sha256":"{hashlib.sha256(b"x").hexdigest()}"'
            "}"
        )
        with self.assertRaises(ApplicationUpdateError):
            ApplicationUpdateManifest.from_json(payload)

    def test_nonfinite_json_is_rejected(self):
        payload = json.dumps(
            {
                "schema": UPDATE_MANIFEST_SCHEMA,
                "product_id": "accessible-chess",
                "target_platform": "windows-x64",
                "target_version": "2.0.0",
                "source_head": self.SOURCE,
                "artifact_name": "AccessibleChess-2.0.0.zip",
                "artifact_size": 1,
                "artifact_sha256": hashlib.sha256(b"x").hexdigest(),
            }
        ).replace('"artifact_size": 1', '"artifact_size": NaN')
        with self.assertRaises(ApplicationUpdateError):
            ApplicationUpdateManifest.from_json(payload)

    def test_windows_reserved_artifact_name_is_rejected(self):
        artifact = b"x"
        with self.assertRaises(ApplicationUpdateError):
            self._manifest_for(artifact, name="CON.zip")

    def test_local_update_verification(self):
        artifact = b"zip-bytes"
        manifest = self._manifest_for(artifact)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / manifest.artifact_name
            path.write_bytes(artifact)
            verified = verify_local_update(
                manifest,
                path,
                current_version="1.0.0",
            )
            self.assertEqual(verified.artifact_size, len(artifact))

    def test_local_update_requires_exact_file_name(self):
        artifact = b"zip-bytes"
        manifest = self._manifest_for(artifact)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "renamed.zip"
            path.write_bytes(artifact)
            with self.assertRaises(ApplicationUpdateError):
                verify_local_update(
                    manifest,
                    path,
                    current_version="1.0.0",
                )

    def test_local_symlink_is_rejected_when_supported(self):
        artifact = b"zip-bytes"
        manifest = self._manifest_for(artifact)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real.zip"
            link = root / manifest.artifact_name
            real.write_bytes(artifact)
            try:
                os.symlink(real, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")
            with self.assertRaises(ApplicationUpdateError):
                verify_local_update(
                    manifest,
                    link,
                    current_version="1.0.0",
                )


if __name__ == "__main__":
    unittest.main()
