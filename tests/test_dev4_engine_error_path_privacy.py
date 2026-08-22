from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.engine_play_service import EnginePlayService
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI


class Dev4EngineErrorPathPrivacyTests(unittest.TestCase):
    """QA gate: low-level engine paths must not reach WebView/NVDA messages."""

    def test_engine_provider_exception_path_is_redacted_at_release_api_boundary(self) -> None:
        private_path = r"C:\\Users\\qa-user\\secret-build\\stockfish.exe"

        def failing_provider():
            raise RuntimeError(f"Unable to start Stockfish at {private_path}")

        service = EnginePlayService(failing_provider, owns_engine=False)
        with tempfile.TemporaryDirectory() as directory:
            api = Stage1ReleaseAccessibleChessAPI(
                keymap_path=Path(directory) / "keymap.json",
                engine_play_service=service,
            )
            result = api.start_engine_game(human_side="black", level=5)

        self.assertFalse(result.get("ok"))
        rendered = str(result)
        self.assertNotIn(private_path, rendered)
        self.assertNotIn("secret-build", rendered)
        self.assertNotIn("qa-user", rendered)
        self.assertIn("Stockfish", rendered)


if __name__ == "__main__":
    unittest.main()
