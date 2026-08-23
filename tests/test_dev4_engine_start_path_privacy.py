from __future__ import annotations

import unittest

from acs.engine import UCIEngine


class Dev4EngineStartPathPrivacyTests(unittest.TestCase):
    """Engine startup failures must not expose workstation directories."""

    PRIVATE_PATH = r"C:\Users\PrivateUser\Documents\Engines\stockfish.exe"

    def test_engine_start_oserror_does_not_expose_private_executable_path(self) -> None:
        def failing_factory(*args, **kwargs):
            raise FileNotFoundError(2, "No such file or directory", self.PRIVATE_PATH)

        engine = UCIEngine(self.PRIVATE_PATH, process_factory=failing_factory)
        with self.assertRaises(RuntimeError) as raised:
            engine.start()

        message = str(raised.exception)
        self.assertIn("Unable to start Stockfish", message)
        self.assertNotIn("PrivateUser", message)
        self.assertNotIn("Documents", message)
        self.assertNotIn("Users", message)
        self.assertNotIn(self.PRIVATE_PATH, message)


if __name__ == "__main__":
    unittest.main()
