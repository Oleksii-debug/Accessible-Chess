from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.stockfish_runtime import (
    PACKAGED_STOCKFISH_RELATIVE_PATH,
    StockfishInvalidExecutableError,
    StockfishRuntimeConfig,
    resolve_stockfish_path,
)


class Dev3RealStockfishPrivacyRepairValidationTests(unittest.TestCase):
    """Non-Product contract checks paired with the real Stockfish 18 CI smoke."""

    def test_valid_explicit_path_remains_authoritative_and_unredacted_internally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = (
                Path(tmp)
                / "Users"
                / "PrivateUser"
                / "Documents"
                / "Engines"
                / "stockfish.exe"
            )
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"non-empty executable placeholder")

            resolved = resolve_stockfish_path(
                StockfishRuntimeConfig(configured_path=executable)
            )

            self.assertEqual(resolved, executable.resolve(strict=False))

    def test_packaged_relative_path_contract_is_preserved_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "AccessibleChess"
            executable = root / PACKAGED_STOCKFISH_RELATIVE_PATH
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"non-empty executable placeholder")

            resolved = resolve_stockfish_path(
                StockfishRuntimeConfig(application_dir=root)
            )

            self.assertEqual(resolved, executable.resolve(strict=False))
            self.assertEqual(
                PACKAGED_STOCKFISH_RELATIVE_PATH.as_posix(),
                "engines/stockfish/stockfish.exe",
            )

    def test_invalid_directory_diagnostic_redacts_private_parent_but_keeps_basename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            candidate = (
                Path(tmp)
                / "Users"
                / "PrivateUser"
                / "Documents"
                / "stockfish.exe"
            )
            candidate.mkdir(parents=True)

            with self.assertRaises(StockfishInvalidExecutableError) as raised:
                resolve_stockfish_path(
                    StockfishRuntimeConfig(configured_path=candidate)
                )

        message = str(raised.exception)
        self.assertEqual(message, "Stockfish path is not a file: stockfish.exe")
        for private_component in ("PrivateUser", "Users", "Documents", tmp):
            self.assertNotIn(private_component, message)


if __name__ == "__main__":
    unittest.main()
