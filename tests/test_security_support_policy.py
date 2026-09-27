from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

from acs.security_support_policy import (
    MINIMUM_SUPPORT_YEARS,
    SecuritySupportError,
    SecuritySupportPolicy,
    build_security_support_manifest,
    canonical_security_support_json,
    generate_security_support_manifest,
    load_security_support_input,
    support_status,
    validate_security_support_manifest,
)
from tools.generate_security_support_manifest import main


class SecuritySupportPolicyTests(unittest.TestCase):
    def policy(self, **overrides):
        values = {
            "version": "1.0.0",
            "market_release_date": date(2027, 1, 15),
            "support_end_date": date(2032, 1, 15),
            "vulnerability_contact": "https://security.example.invalid/report",
            "disclosure_policy_url": "https://security.example.invalid/policy",
            "security_update_url": "https://security.example.invalid/updates",
        }
        values.update(overrides)
        return SecuritySupportPolicy(**values)

    def input(self):
        return {
            "version": "1.0.0",
            "market_release_date": "2027-01-15",
            "support_end_date": "2032-01-15",
            "vulnerability_contact": "mailto:security@example.invalid",
            "disclosure_policy_url": "https://example.invalid/security",
            "security_update_url": "https://example.invalid/updates",
        }

    def test_five_year_minimum_and_canonical_manifest(self):
        policy = self.policy()
        self.assertEqual(MINIMUM_SUPPORT_YEARS, 5)
        self.assertEqual(
            policy.minimum_support_end_date,
            date(2032, 1, 15),
        )
        raw = canonical_security_support_json(policy)
        manifest = json.loads(raw)
        self.assertEqual(
            manifest["cra_reporting_contract"]["early_warning_hours"],
            24,
        )
        self.assertEqual(
            manifest["cra_reporting_contract"]["notification_hours"],
            72,
        )
        self.assertEqual(
            manifest["cra_reporting_contract"][
                "actively_exploited_vulnerability_final_days_after_corrective"
            ],
            14,
        )
        self.assertEqual(
            manifest["cra_reporting_contract"][
                "severe_incident_final_months_after_notification"
            ],
            1,
        )
        validate_security_support_manifest(manifest)

    def test_shorter_than_five_years_fails_closed(self):
        with self.assertRaisesRegex(SecuritySupportError, "no earlier"):
            self.policy(support_end_date=date(2032, 1, 14))

    def test_leap_day_minimum_is_calendar_safe(self):
        policy = self.policy(
            market_release_date=date(2028, 2, 29),
            support_end_date=date(2033, 2, 28),
        )
        self.assertEqual(
            policy.minimum_support_end_date,
            date(2033, 2, 28),
        )

    def test_security_promises_must_be_true(self):
        for key in (
            "security_updates_free",
            "separate_security_updates_when_feasible",
            "end_of_support_notice_required",
        ):
            with self.subTest(key=key):
                with self.assertRaises(SecuritySupportError):
                    self.policy(**{key: False})

    def test_contact_and_https_urls_are_strict(self):
        for value in (
            "http://example.invalid/report",
            "mailto:no-at",
            "file:///tmp/x",
        ):
            with self.subTest(value=value):
                with self.assertRaises(SecuritySupportError):
                    self.policy(vulnerability_contact=value)
        with self.assertRaises(SecuritySupportError):
            self.policy(
                disclosure_policy_url="http://example.invalid/policy"
            )
        accepted = self.policy(
            vulnerability_contact="mailto:security@example.invalid"
        )
        self.assertEqual(
            accepted.vulnerability_contact,
            "mailto:security@example.invalid",
        )

    def test_manifest_tampering_is_rejected(self):
        manifest = self.policy().to_manifest()
        bad = deepcopy(manifest)
        bad["security_updates_free"] = False
        with self.assertRaises(SecuritySupportError):
            validate_security_support_manifest(bad)

        bad = deepcopy(manifest)
        bad["cra_reporting_contract"]["notification_hours"] = 96
        with self.assertRaisesRegex(
            SecuritySupportError,
            "reporting contract",
        ):
            validate_security_support_manifest(bad)

        bad = deepcopy(manifest)
        bad["unexpected"] = 1
        with self.assertRaises(SecuritySupportError):
            validate_security_support_manifest(bad)

    def test_release_author_input_normalizes_to_complete_manifest(self):
        manifest = build_security_support_manifest(self.input())
        self.assertEqual(manifest["product"], "Accessible Chess")
        self.assertTrue(manifest["security_updates_free"])
        self.assertTrue(
            manifest["separate_security_updates_when_feasible"]
        )
        self.assertTrue(manifest["end_of_support_notice_required"])
        validate_security_support_manifest(manifest)

    def test_support_status_has_no_implicit_grace(self):
        policy = self.policy()
        self.assertEqual(
            support_status(policy, on_date=date(2032, 1, 15)),
            "active",
        )
        self.assertEqual(
            support_status(policy, on_date=date(2032, 1, 16)),
            "ended",
        )

    def test_file_generation_is_deterministic_and_symlink_safe(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "input.json"
            output_path = root / "support.json"
            input_path.write_text(
                json.dumps(self.input()),
                encoding="utf-8",
            )
            first = generate_security_support_manifest(
                input_path,
                output_path,
            )
            second = generate_security_support_manifest(
                input_path,
                output_path,
            )
            self.assertEqual(first, second)
            self.assertEqual(
                first,
                output_path.read_text(encoding="utf-8"),
            )

            duplicate = root / "duplicate.json"
            duplicate.write_text(
                '{"version":"1","version":"2"}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                SecuritySupportError,
                "duplicate JSON key",
            ):
                load_security_support_input(duplicate)

            link = root / "linked.json"
            try:
                link.symlink_to(input_path.name)
            except (OSError, NotImplementedError):
                return
            with self.assertRaisesRegex(
                SecuritySupportError,
                "non-symlink",
            ):
                load_security_support_input(link)

    def test_direct_script_execution_resolves_repo_package(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "input.json"
            output_path = root / "support.json"
            input_path.write_text(json.dumps(self.input()), encoding="utf-8")
            repo_root = Path(__file__).resolve().parents[1]
            completed = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "tools" / "generate_security_support_manifest.py"),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(output_path.is_file())
            manifest = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["product"], "Accessible Chess")

    def test_cli_fails_closed_without_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = self.input()
            value["support_end_date"] = "2030-01-15"
            input_path = root / "input.json"
            output_path = root / "support.json"
            input_path.write_text(
                json.dumps(value),
                encoding="utf-8",
            )
            self.assertEqual(
                main(
                    [
                        "--input",
                        str(input_path),
                        "--output",
                        str(output_path),
                    ]
                ),
                2,
            )
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
