from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from acs.stockfish_runtime import (
    StockfishInvalidExecutableError,
    StockfishRuntimeConfig,
    resolve_stockfish_path,
)


class Dev3StockfishRuntimePrivacyRepairValidationTests(unittest.TestCase):
    """Independent validation only; Product repair remains owned by DEV4/DEV5."""

    @staticmethod
    def _private_root(tmp: str) -> Path:
        return Path(tmp) / "Users" / "PrivateUser" / "Documents" / "AccessibleChess"

    def assert_private_parent_redacted(self, message: str) -> None:
        for forbidden in ("PrivateUser", "Users", "Documents", "AccessibleChess"):
            self.assertNotIn(forbidden, message)

    def test_resolution_failures_redact_untrusted_exception_text_and_chain_cause(self) -> None:
        private_path = Path(
            "C:/Users/PrivateUser/Documents/AccessibleChess/Engines/stockfish.exe"
        )
        failures = (
            OSError(f"cannot resolve {private_path}"),
            ValueError(f"invalid path {private_path}"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with patch.object(Path, "resolve", side_effect=failure):
                    with self.assertRaises(StockfishInvalidExecutableError) as raised:
                        resolve_stockfish_path(
                            StockfishRuntimeConfig(configured_path=private_path)
                        )
                self.assertEqual(
                    str(raised.exception),
                    "Cannot resolve configured Stockfish path",
                )
                self.assertIs(raised.exception.__cause__, failure)
                self.assert_private_parent_redacted(str(raised.exception))

    def test_packaged_resolution_failure_uses_typed_context_without_private_root(self) -> None:
        private_root = Path("C:/Users/PrivateUser/Documents/AccessibleChess")
        failure = OSError(f"cannot resolve {private_root / 'engines/stockfish/stockfish.exe'}")
        with patch.object(Path, "resolve", side_effect=failure):
            with self.assertRaises(StockfishInvalidExecutableError) as raised:
                resolve_stockfish_path(StockfishRuntimeConfig(application_dir=private_root))

        self.assertEqual(
            str(raised.exception),
            "Cannot resolve packaged Stockfish path",
        )
        self.assertIs(raised.exception.__cause__, failure)
        self.assert_private_parent_redacted(str(raised.exception))

    def test_directory_rejection_keeps_safe_basename_without_private_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = self._private_root(tmp) / "Engines" / "stockfish.exe"
            candidate.mkdir(parents=True)
            with self.assertRaises(StockfishInvalidExecutableError) as raised:
                resolve_stockfish_path(StockfishRuntimeConfig(configured_path=candidate))

        message = str(raised.exception)
        self.assertEqual(message, "Stockfish path is not a file: stockfish.exe")
        self.assert_private_parent_redacted(message)

    def test_valid_explicit_path_remains_authoritative_and_returns_real_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            configured = self._private_root(tmp) / "CustomEngines" / "stockfish.exe"
            configured.parent.mkdir(parents=True)
            configured.write_bytes(b"not-empty")
            expected = configured.resolve(strict=False)

            resolved = resolve_stockfish_path(
                StockfishRuntimeConfig(
                    configured_path=configured,
                    application_dir=Path(tmp) / "ignored-packaged-root",
                )
            )

        self.assertEqual(resolved, expected)


if __name__ == "__main__":
    unittest.main()
