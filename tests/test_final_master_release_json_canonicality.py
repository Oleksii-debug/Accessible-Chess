from __future__ import annotations

import json
from pathlib import Path

from acs.release_preflight import ReleasePreflightError, inspect_release_package
from tests.test_release_preflight import ReleasePreflightTests


class FinalMasterReleaseJsonCanonicalityTests(ReleasePreflightTests):
    def _prepend_duplicate(
        self,
        root: Path,
        relative: str,
        *,
        key: str,
        first_value: object,
    ) -> ReleasePreflightError:
        path = root / relative
        raw = path.read_text(encoding="utf-8")
        marker = json.dumps(key, ensure_ascii=False) + ":"
        index = raw.index(marker)
        duplicate = (
            json.dumps(key, ensure_ascii=False)
            + ":"
            + json.dumps(first_value, ensure_ascii=False)
            + ","
        )
        path.write_text(raw[:index] + duplicate + raw[index:], encoding="utf-8")
        self.rewrite_checksums(root)
        with self.assertRaises(ReleasePreflightError) as caught:
            inspect_release_package(root)
        return caught.exception

    def test_every_release_evidence_document_rejects_duplicate_keys(self) -> None:
        cases = (
            ("RELEASE_MANIFEST.json", "nvda_verified", True),
            ("native-menu-self-diagnostic.json", "installed", False),
            ("packaged-uia-strict-summary.json", "evidence_complete", False),
            ("AccessibleChess/assets/sounds/manifest.json", "move", "other.wav"),
        )
        for relative, key, first_value in cases:
            with self.subTest(relative=relative, key=key):
                error = self._prepend_duplicate(
                    self.make_package(),
                    relative,
                    key=key,
                    first_value=first_value,
                )
                self.assertIn("duplicate object keys", str(error))

    def test_duplicate_key_in_ignored_deep_extension_is_rejected(self) -> None:
        root = self.make_package()
        path = root / "RELEASE_MANIFEST.json"
        raw = path.read_text(encoding="utf-8")
        extension = ',"ignored":{"nested":{"claim":"first","claim":"second"}}'
        path.write_text(raw[:-1] + extension + "}", encoding="utf-8")
        self.rewrite_checksums(root)
        with self.assertRaises(ReleasePreflightError) as caught:
            inspect_release_package(root)
        self.assertEqual(str(caught.exception), "release manifest contains duplicate object keys")

    def test_duplicate_error_does_not_expose_key_or_private_path(self) -> None:
        private_key = "C:/Users/PrivateUser/Documents/secret-claim"
        root = self.make_package()
        path = root / "RELEASE_MANIFEST.json"
        raw = path.read_text(encoding="utf-8")
        extension = (
            ","
            + json.dumps(private_key)
            + ":true,"
            + json.dumps(private_key)
            + ":false"
        )
        path.write_text(raw[:-1] + extension + "}", encoding="utf-8")
        self.rewrite_checksums(root)
        with self.assertRaises(ReleasePreflightError) as caught:
            inspect_release_package(root)
        message = str(caught.exception)
        self.assertEqual(message, "release manifest contains duplicate object keys")
        self.assertNotIn("PrivateUser", message)
        self.assertNotIn("secret-claim", message)


if __name__ == "__main__":
    import unittest

    unittest.main()
