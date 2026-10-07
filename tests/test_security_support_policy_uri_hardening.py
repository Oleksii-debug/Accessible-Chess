from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.generate_security_support_manifest import main


class SecuritySupportPolicyUriHardeningTests(unittest.TestCase):
    def _input(self) -> dict[str, str]:
        return {
            "version": "1.0.0",
            "market_release_date": "2027-01-15",
            "support_end_date": "2032-01-15",
            "vulnerability_contact": "mailto:security@example.invalid",
            "disclosure_policy_url": "https://example.invalid/security",
            "security_update_url": "https://example.invalid/updates",
        }

    def test_decoded_ascii_controls_fail_closed_without_output(self) -> None:
        cases = (
            ("vulnerability_contact", "https://security.example.invalid/re\nport"),
            ("disclosure_policy_url", "https://example.invalid/sec\turity"),
            ("security_update_url", "https://example.invalid/up\rdates"),
            ("security_update_url", "https://example.invalid/up\x7fdates"),
        )
        for field, value in cases:
            with self.subTest(field=field, value=repr(value)):
                with tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    source = root / "input.json"
                    output = root / "support.json"
                    payload = self._input()
                    payload[field] = value
                    source.write_text(json.dumps(payload), encoding="utf-8")
                    self.assertEqual(
                        main(["--input", str(source), "--output", str(output)]),
                        2,
                    )
                    self.assertFalse(output.exists())

    def test_ambiguous_or_encoded_security_uris_fail_closed(self) -> None:
        cases = (
            ("vulnerability_contact", "https://example.invalid\\@evil.invalid/report"),
            ("vulnerability_contact", "https://example.invalid:bad/report"),
            ("disclosure_policy_url", "https://example.invalid/security%0aheader"),
            ("security_update_url", "https://example.invalid:70000/updates"),
            ("security_update_url", "https://example.invalid/updates%7f"),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                with tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    source = root / "input.json"
                    output = root / "support.json"
                    payload = self._input()
                    payload[field] = value
                    source.write_text(json.dumps(payload), encoding="utf-8")
                    self.assertEqual(
                        main(["--input", str(source), "--output", str(output)]),
                        2,
                    )
                    self.assertFalse(output.exists())

    def test_clean_security_uris_still_generate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.json"
            output = root / "support.json"
            source.write_text(json.dumps(self._input()), encoding="utf-8")
            self.assertEqual(
                main(["--input", str(source), "--output", str(output)]),
                0,
            )
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
