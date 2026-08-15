from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.release_preflight import scan_release_source_tree


class ReleaseSourcePreflightTests(unittest.TestCase):
    def _tree(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "acs").mkdir()
        (root / "VERSION.txt").write_text("0.4.0\n", encoding="utf-8")
        return temp, root

    def test_clean_tree_passes(self):
        temp, root = self._tree()
        self.addCleanup(temp.cleanup)
        (root / "acs" / "entitlements.py").write_text(
            "class EntitlementState: pass\nclass FeatureGate: pass\nclass BillingProvider: pass\n",
            encoding="utf-8",
        )
        self.assertEqual(scan_release_source_tree(root), ())

    def test_duplicate_entitlement_contract_ownership_is_rejected(self):
        temp, root = self._tree()
        self.addCleanup(temp.cleanup)
        (root / "acs" / "entitlements.py").write_text("class FeatureGate: pass\n", encoding="utf-8")
        (root / "acs" / "security_contracts.py").write_text("class FeatureGate: pass\n", encoding="utf-8")
        defects = scan_release_source_tree(root)
        self.assertTrue(any(item.code == "DUPLICATE_SECURITY_OWNER" for item in defects))

    def test_literal_client_secret_is_rejected_but_placeholder_is_not(self):
        temp, root = self._tree()
        self.addCleanup(temp.cleanup)
        module = root / "acs" / "config.py"
        module.write_text('client_secret = "super-secret-production-value"\n', encoding="utf-8")
        defects = scan_release_source_tree(root)
        self.assertTrue(any(item.code == "HARDCODED_SECRET" for item in defects))

        module.write_text('client_secret = ""\n', encoding="utf-8")
        self.assertFalse(any(item.code == "HARDCODED_SECRET" for item in scan_release_source_tree(root)))

    def test_private_key_material_and_key_container_are_rejected(self):
        temp, root = self._tree()
        self.addCleanup(temp.cleanup)
        (root / "acs" / "bad.py").write_text(
            'blob = "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----"\n',
            encoding="utf-8",
        )
        (root / "release-signing.pfx").write_bytes(b"not-a-real-key")
        defects = scan_release_source_tree(root)
        self.assertTrue(any(item.code == "PRIVATE_KEY_LITERAL" for item in defects))
        self.assertTrue(any(item.code == "SECRET_FILE" for item in defects))

    def test_missing_version_is_release_blocker(self):
        temp, root = self._tree()
        self.addCleanup(temp.cleanup)
        (root / "VERSION.txt").unlink()
        defects = scan_release_source_tree(root)
        self.assertTrue(any(item.code == "VERSION_MISSING" for item in defects))

    def test_syntax_error_is_not_silently_skipped(self):
        temp, root = self._tree()
        self.addCleanup(temp.cleanup)
        (root / "acs" / "broken.py").write_text("def broken(:\n", encoding="utf-8")
        defects = scan_release_source_tree(root)
        self.assertTrue(any(item.code == "PYTHON_PARSE" for item in defects))


if __name__ == "__main__":
    unittest.main()
