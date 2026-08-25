from __future__ import annotations

import json
from pathlib import Path
import unittest

from acs.release_preflight import ReleasePreflightError, inspect_release_package
from tests.test_release_preflight import ReleasePreflightTests


class Dev4ReleaseJsonCasefoldCanonicalityTests(ReleasePreflightTests):
    def _append_case_variant(
        self,
        root: Path,
        relative: str,
        *,
        variant_key: str,
        variant_value: object,
    ) -> None:
        path = root / relative
        raw = path.read_text(encoding="utf-8")
        self.assertTrue(raw.rstrip().endswith("}"))
        stripped = raw.rstrip()
        suffix = raw[len(stripped):]
        extension = (
            ","
            + json.dumps(variant_key, ensure_ascii=False)
            + ":"
            + json.dumps(variant_value, ensure_ascii=False)
        )
        path.write_text(stripped[:-1] + extension + "}" + suffix, encoding="utf-8")
        self.rewrite_checksums(root)

    def _require_casefold_collision_rejection(
        self,
        root: Path,
        relative: str,
        *,
        variant_key: str,
        variant_value: object,
    ) -> None:
        self._append_case_variant(
            root,
            relative,
            variant_key=variant_key,
            variant_value=variant_value,
        )
        with self.assertRaises(ReleasePreflightError) as caught:
            inspect_release_package(root)
        self.assertIn("duplicate object keys", str(caught.exception))

    def test_release_evidence_rejects_casefold_colliding_claim_keys(self) -> None:
        cases = (
            ("RELEASE_MANIFEST.json", "NVDA_VERIFIED", True),
            ("native-menu-self-diagnostic.json", "INSTALLED", False),
            ("packaged-uia-strict-summary.json", "EVIDENCE_COMPLETE", False),
        )
        for relative, variant_key, variant_value in cases:
            with self.subTest(relative=relative, variant_key=variant_key):
                self._require_casefold_collision_rejection(
                    self.make_package(),
                    relative,
                    variant_key=variant_key,
                    variant_value=variant_value,
                )

    def test_ignored_nested_extension_is_still_casefold_canonical(self) -> None:
        root = self.make_package()
        path = root / "RELEASE_MANIFEST.json"
        raw = path.read_text(encoding="utf-8").rstrip()
        extension = ',"ignored":{"claim":"safe","CLAIM":"conflicting"}'
        path.write_text(raw[:-1] + extension + "}", encoding="utf-8")
        self.rewrite_checksums(root)
        with self.assertRaises(ReleasePreflightError) as caught:
            inspect_release_package(root)
        self.assertEqual(
            str(caught.exception),
            "release manifest contains duplicate object keys",
        )


if __name__ == "__main__":
    unittest.main()
