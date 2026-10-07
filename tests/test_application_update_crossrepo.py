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


class ActiveDict(dict):
    def keys(self):
        raise AssertionError("active manifest mapping must not be inspected")

    def __getitem__(self, key):
        raise AssertionError("active manifest mapping must not be indexed")


class ActiveText(str):
    def __eq__(self, other):
        raise AssertionError("active text must not be compared")

    def strip(self, *args, **kwargs):
        raise AssertionError("active text must not be normalized")


class ActiveInt(int):
    def __le__(self, other):
        raise AssertionError("active integer must not be compared")


class ActiveBytes(bytes):
    def __bytes__(self):
        raise AssertionError("active bytes subclass must not be converted")

    def decode(self, *args, **kwargs):
        raise AssertionError("active bytes subclass must not be decoded")


class ActivePathLike:
    def __fspath__(self):
        raise AssertionError("active path-like must not be resolved")


class DerivedManifest(ApplicationUpdateManifest):
    pass


class DerivedSemVer(SemVer):
    pass


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

    def test_manifest_mapping_rejects_active_container_before_hooks(self):
        raw = ActiveDict(
            {
                "schema": UPDATE_MANIFEST_SCHEMA,
                "product_id": "accessible-chess",
            }
        )
        with self.assertRaises(ApplicationUpdateError):
            ApplicationUpdateManifest.from_mapping(raw)

    def test_manifest_rejects_active_scalar_subclasses_before_hooks(self):
        artifact = b"x"
        base = {
            "schema": UPDATE_MANIFEST_SCHEMA,
            "product_id": "accessible-chess",
            "target_platform": "windows-x64",
            "target_version": "2.0.0",
            "source_head": self.SOURCE,
            "artifact_name": "AccessibleChess-2.0.0.zip",
            "artifact_size": len(artifact),
            "artifact_sha256": hashlib.sha256(artifact).hexdigest(),
        }

        for field, value in (
            ("schema", ActiveText(UPDATE_MANIFEST_SCHEMA)),
            ("product_id", ActiveText("accessible-chess")),
            ("artifact_size", ActiveInt(1)),
        ):
            with self.subTest(field=field):
                raw = dict(base)
                raw[field] = value
                with self.assertRaises(ApplicationUpdateError):
                    ApplicationUpdateManifest.from_mapping(raw)

    def test_semver_rejects_active_text_and_derived_values(self):
        with self.assertRaises(ApplicationUpdateError):
            SemVer.parse(ActiveText("2.0.0"))
        with self.assertRaises(TypeError):
            DerivedSemVer.parse("2.0.0")

        exact = SemVer.parse("2.0.0")
        derived = DerivedSemVer(2, 0, 1)
        with self.assertRaises(TypeError):
            exact.compare_precedence(derived)
        with self.assertRaises(TypeError):
            derived.compare_precedence(exact)

    def test_json_manifest_rejects_active_text_and_bytes_before_hooks(self):
        exact_payload = json.dumps(
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
        )
        for payload in (
            ActiveText(exact_payload),
            ActiveBytes(exact_payload.encode("utf-8")),
        ):
            with self.subTest(kind=type(payload).__name__):
                with self.assertRaises(ApplicationUpdateError):
                    ApplicationUpdateManifest.from_json(payload)

    def test_manifest_parser_rejects_derived_parser_class(self):
        with self.assertRaises(TypeError):
            DerivedManifest.from_mapping({})
        with self.assertRaises(TypeError):
            DerivedManifest.from_json("{}")

    def test_verifier_rejects_derived_manifest_before_field_access(self):
        artifact = b"x"
        exact = self._manifest_for(artifact)
        derived = DerivedManifest(
            product_id=exact.product_id,
            target_platform=exact.target_platform,
            target_version=exact.target_version,
            source_head=exact.source_head,
            artifact_name=exact.artifact_name,
            artifact_size=exact.artifact_size,
            artifact_sha256=exact.artifact_sha256,
            schema=exact.schema,
        )
        with self.assertRaises(ApplicationUpdateError):
            verify_artifact_bytes(
                derived,
                artifact,
                current_version="1.0.0",
            )

    def test_in_memory_verifier_rejects_active_bytes_subclass(self):
        artifact = b"x"
        manifest = self._manifest_for(artifact)
        with self.assertRaises(ApplicationUpdateError):
            verify_artifact_bytes(
                manifest,
                ActiveBytes(artifact),
                current_version="1.0.0",
            )

    def test_local_verifier_rejects_active_pathlike_before_fspath(self):
        artifact = b"x"
        manifest = self._manifest_for(artifact)
        with self.assertRaises(ApplicationUpdateError):
            verify_local_update(
                manifest,
                ActivePathLike(),
                current_version="1.0.0",
            )

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
