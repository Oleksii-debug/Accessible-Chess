from __future__ import annotations

import json
import unittest

from acs.release_preflight import ReleasePreflightError, inspect_release_package
from tests.test_release_preflight import ReleasePreflightTests


class Dev4ReleaseJsonDuplicateKeyTests(ReleasePreflightTests):
    """Release evidence JSON must have one unambiguous value per key."""

    def _write_duplicate_manifest(self, duplicate_field: str, first_value: object) -> None:
        root = self.make_package()
        path = root / "RELEASE_MANIFEST.json"
        canonical = json.loads(path.read_text(encoding="utf-8"))
        pairs: list[tuple[str, object]] = []
        for key, value in canonical.items():
            if key == duplicate_field:
                pairs.append((key, first_value))
            pairs.append((key, value))
        raw = "{" + ",".join(
            f"{json.dumps(key, ensure_ascii=False)}:{json.dumps(value, ensure_ascii=False)}"
            for key, value in pairs
        ) + "}"
        path.write_text(raw, encoding="utf-8")
        self.rewrite_checksums(root)
        with self.assertRaises(ReleasePreflightError) as caught:
            inspect_release_package(root)
        self.assertIn("duplicate", str(caught.exception).casefold())

    def test_duplicate_nvda_verified_true_then_false_is_rejected(self) -> None:
        self._write_duplicate_manifest("nvda_verified", True)

    def test_duplicate_human_only_gate_pass_then_unproven_is_rejected(self) -> None:
        self._write_duplicate_manifest("nvda_menu_usability", "PASS")


if __name__ == "__main__":
    unittest.main()
