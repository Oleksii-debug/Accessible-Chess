import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import acs.logging_setup as logging_setup
from acs.security_redaction import REDACTED


class PersistedDiagnosticRedactionTests(unittest.TestCase):
    def test_plain_log_redacts_credentials_before_writing(self):
        secret = "abcdefghijklmnop"
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp)
            with patch.object(logging_setup, "REPORTS", reports):
                logging_setup.log(
                    "startup.log",
                    f"engine ready Authorization: Bearer {secret} access_token=url-secret-value",
                )

            text = (reports / "startup.log").read_text(encoding="utf-8")
            self.assertIn("engine ready", text)
            self.assertIn("Bearer " + REDACTED, text)
            self.assertIn("access_token=" + REDACTED, text)
            self.assertNotIn(secret, text)
            self.assertNotIn("url-secret-value", text)

    def test_crash_report_and_fatal_startup_entry_do_not_persist_secret_material(self):
        bearer_secret = "super-secret-bearer-token"
        password_secret = "hunter2"
        context_secret = "client_secret=context-secret-value"

        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp)
            with patch.object(logging_setup, "REPORTS", reports):
                try:
                    raise RuntimeError(
                        f"Authorization: Bearer {bearer_secret}; password={password_secret}"
                    )
                except RuntimeError as exc:
                    crash_path = logging_setup.write_crash(
                        type(exc), exc, exc.__traceback__, context=context_secret
                    )

            crash_text = crash_path.read_text(encoding="utf-8")
            startup_text = (reports / "startup.log").read_text(encoding="utf-8")

            for text in (crash_text, startup_text):
                self.assertNotIn(bearer_secret, text)
                self.assertNotIn(password_secret, text)
                self.assertNotIn("context-secret-value", text)
                self.assertIn(REDACTED, text)

            self.assertIn("RuntimeError", crash_text)
            self.assertIn("FATAL", startup_text)

    def test_non_secret_diagnostics_remain_useful(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp)
            with patch.object(logging_setup, "REPORTS", reports):
                try:
                    raise ValueError("illegal move e2e5 at depth=18")
                except ValueError as exc:
                    crash_path = logging_setup.write_crash(
                        type(exc), exc, exc.__traceback__, context="engine-analysis"
                    )

            text = crash_path.read_text(encoding="utf-8")
            self.assertIn("illegal move e2e5", text)
            self.assertIn("depth=18", text)
            self.assertIn("engine-analysis", text)


if __name__ == "__main__":
    unittest.main()
