from __future__ import annotations

import threading
import unittest

from acs.version2_application import Version2Application


class _Files:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.timeouts: list[float | None] = []

    def shutdown(self, timeout: float | None = None) -> bool:
        self.timeouts.append(timeout)
        return self.result


class _Database:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1


class Version2ShutdownTests(unittest.TestCase):
    def make_application(self, files: _Files) -> tuple[Version2Application, _Database]:
        application = Version2Application.__new__(Version2Application)
        application._thread = threading.get_ident()
        application._files = files
        application.reader = None
        application.database = _Database()
        return application, application.database

    def test_default_shutdown_waits_for_import_worker_contract(self) -> None:
        files = _Files(True)
        application, database = self.make_application(files)

        self.assertTrue(application.shutdown())
        self.assertEqual(files.timeouts, [None])
        self.assertEqual(database.closed, 1)

    def test_bounded_shutdown_keeps_database_open_when_worker_is_alive(self) -> None:
        files = _Files(False)
        application, database = self.make_application(files)

        self.assertFalse(application.shutdown(timeout=0.01))
        self.assertEqual(files.timeouts, [0.01])
        self.assertEqual(database.closed, 0)


if __name__ == "__main__":
    unittest.main()
