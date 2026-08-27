from __future__ import annotations

import unittest

from acs.engine import UCIEngine


class Dev3Stage1EngineStartPathPrivacyTests(unittest.TestCase):
    """Accepted Stage1 engine startup diagnostics must not expose local paths."""

    PRIVATE_PATH = r"C:\Users\PrivateUser\Documents\Engines\stockfish.exe"

    def _assert_private_path_redacted(self, error: RuntimeError) -> None:
        message = str(error)
        self.assertIn("Unable to start Stockfish", message)
        self.assertNotIn("PrivateUser", message)
        self.assertNotIn("Documents", message)
        self.assertNotIn("Users", message)
        self.assertNotIn(self.PRIVATE_PATH, message)

    def test_start_oserror_does_not_expose_private_executable_path(self) -> None:
        def failing_factory(*args, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", self.PRIVATE_PATH)

        engine = UCIEngine(self.PRIVATE_PATH, process_factory=failing_factory)
        with self.assertRaises(RuntimeError) as raised:
            engine.start()

        self._assert_private_path_redacted(raised.exception)

    def test_start_valueerror_does_not_republish_private_provider_detail(self) -> None:
        def failing_factory(*args, **kwargs):
            raise ValueError(f"invalid executable path: {self.PRIVATE_PATH}")

        engine = UCIEngine(self.PRIVATE_PATH, process_factory=failing_factory)
        with self.assertRaises(RuntimeError) as raised:
            engine.start()

        self._assert_private_path_redacted(raised.exception)


if __name__ == "__main__":
    unittest.main()
