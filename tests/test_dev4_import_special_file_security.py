from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from acs.import_contract import fingerprint


@unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO support required")
class Dev4ImportSpecialFileSecurityTests(unittest.TestCase):
    """QA gate for non-regular external import sources.

    External import provenance must fail closed before reading special files.
    FIFOs can block indefinitely and device-like files can trigger side effects;
    they must never be treated as ordinary chess database/PGN input.
    """

    def test_fingerprint_rejects_fifo_before_opening_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / "submitted.pgn"
            os.mkfifo(fifo)

            real_open = Path.open

            def guarded_open(path_self: Path, *args, **kwargs):
                if path_self == fifo:
                    raise AssertionError("fingerprint attempted to open a FIFO payload")
                return real_open(path_self, *args, **kwargs)

            with mock.patch.object(Path, "open", guarded_open):
                with self.assertRaises((ValueError, OSError, RuntimeError)):
                    fingerprint(fifo)


if __name__ == "__main__":
    unittest.main()
