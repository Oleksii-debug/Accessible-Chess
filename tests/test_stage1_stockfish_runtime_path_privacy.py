from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.stockfish_runtime import (
    StockfishInvalidExecutableError,
    StockfishNotFoundError,
    StockfishRuntimeConfig,
    resolve_stockfish_path,
)


class Stage1StockfishRuntimePathPrivacyTests(unittest.TestCase):
    @staticmethod
    def _private_root(tmp: str) -> Path:
        return Path(tmp) / "Users" / "PrivateUser" / "Documents" / "AccessibleChess"

    def assert_report_safe(self, message: str, safe_name: str) -> None:
        self.assertIn(safe_name, message)
        for forbidden in ("PrivateUser", "Users", "Documents", "AccessibleChess"):
            self.assertNotIn(forbidden, message)

    def test_missing_configured_engine_redacts_private_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            configured = self._private_root(tmp) / "CustomEngines" / "missing-stockfish.exe"
            with self.assertRaises(StockfishNotFoundError) as raised:
                resolve_stockfish_path(StockfishRuntimeConfig(configured_path=configured))
        message = str(raised.exception)
        self.assertIn("Stockfish executable not found", message)
        self.assert_report_safe(message, "missing-stockfish.exe")

    def test_missing_packaged_engine_redacts_application_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            application_dir = self._private_root(tmp)
            with self.assertRaises(StockfishNotFoundError) as raised:
                resolve_stockfish_path(StockfishRuntimeConfig(application_dir=application_dir))
        message = str(raised.exception)
        self.assertIn("Stockfish executable not found", message)
        self.assert_report_safe(message, "stockfish.exe")

    def test_empty_packaged_engine_redacts_private_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            application_dir = self._private_root(tmp)
            candidate = application_dir / "engines" / "stockfish" / "stockfish.exe"
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_bytes(b"")
            with self.assertRaises(StockfishInvalidExecutableError) as raised:
                resolve_stockfish_path(StockfishRuntimeConfig(application_dir=application_dir))
        message = str(raised.exception)
        self.assertIn("empty or corrupt", message)
        self.assert_report_safe(message, "stockfish.exe")

    def test_directory_instead_of_executable_redacts_private_parent_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            configured = self._private_root(tmp) / "CustomEngines" / "stockfish.exe"
            configured.mkdir(parents=True, exist_ok=True)
            with self.assertRaises(StockfishInvalidExecutableError) as raised:
                resolve_stockfish_path(StockfishRuntimeConfig(configured_path=configured))
        message = str(raised.exception)
        self.assertIn("Stockfish path is not a file", message)
        self.assert_report_safe(message, "stockfish.exe")


if __name__ == "__main__":
    unittest.main()
