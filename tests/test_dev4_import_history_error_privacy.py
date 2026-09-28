from __future__ import annotations

import unittest
from unittest import mock

from acs.acsdb import AcsDatabase
from acs.import_history_service import ImportHistoryQuery, ImportHistoryService


class Dev4ImportHistoryErrorPrivacyTests(unittest.TestCase):
    """QA gate for persisted/application-facing import failure details."""

    def test_parser_exception_does_not_persist_private_path_or_secret_detail(self) -> None:
        """Import history must not preserve raw provider/parser exception details.

        ``AcsDatabase.import_pgn_text`` persists failed attempts and
        ``ImportHistoryService`` exposes them to application callers.  A
        low-level parser/provider exception may contain local workstation paths
        or credential-like diagnostic values; those details must not cross this
        persisted reporting boundary verbatim.
        """

        private_path = r"C:\Users\Alice\Private Chess\secret-source.pgn"
        secret_detail = "provider_token=qa-do-not-persist-12345"
        raw_error = RuntimeError(f"decoder failed at {private_path}; {secret_detail}")

        with AcsDatabase(":memory:") as database:
            with mock.patch("acs.acsdb.parse_pgn_text", side_effect=raw_error):
                with self.assertRaises(RuntimeError):
                    database.import_pgn_text(
                        '[Event "Safe visible name"]\n[Result "*"]\n\n*\n',
                        source_name="safe-visible-name.pgn",
                    )

            page = ImportHistoryService(database).search(
                ImportHistoryQuery(status="failed", limit=10)
            )
            self.assertEqual(len(page.items), 1)
            item = page.items[0]
            self.assertEqual(item.status, "failed")
            self.assertIsNotNone(item.error_message)

            visible_error = item.error_message or ""
            self.assertNotIn(private_path, visible_error)
            self.assertNotIn(r"C:\Users\Alice", visible_error)
            self.assertNotIn("Private Chess", visible_error)
            self.assertNotIn(secret_detail, visible_error)
            self.assertNotIn("qa-do-not-persist-12345", visible_error)


if __name__ == "__main__":
    unittest.main()
