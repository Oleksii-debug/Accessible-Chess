import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from acs.chessbase_adapter import probe_chessbase_source


class _TrackingConnection:
    def __init__(self, connection):
        self._connection = connection
        self.closed = False

    @property
    def row_factory(self):
        return self._connection.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._connection.row_factory = value

    def execute(self, *args, **kwargs):
        return self._connection.execute(*args, **kwargs)

    def close(self):
        self.closed = True
        self._connection.close()


class WindowsDataReleaseRegressions(unittest.TestCase):
    def test_rejected_newer_schema_closes_sqlite_handle_without_rewrite(self):
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        future_version = ACSDB_SCHEMA_VERSION + 1
        try:
            conn = sqlite3.connect(path)
            conn.execute(f"PRAGMA user_version = {future_version}")
            conn.execute("CREATE TABLE future_marker(value TEXT NOT NULL)")
            conn.execute("INSERT INTO future_marker(value) VALUES('keep-me')")
            conn.commit()
            conn.close()

            original_connect = sqlite3.connect
            tracked = []

            def connect_with_tracking(*args, **kwargs):
                wrapper = _TrackingConnection(original_connect(*args, **kwargs))
                tracked.append(wrapper)
                return wrapper

            with mock.patch("acs.acsdb.sqlite3.connect", side_effect=connect_with_tracking):
                with self.assertRaisesRegex(RuntimeError, "newer than supported"):
                    AcsDatabase(path)

            self.assertEqual(len(tracked), 1)
            self.assertTrue(tracked[0].closed, "schema rejection must close SQLite handle")

            verify = sqlite3.connect(path)
            try:
                self.assertEqual(verify.execute("PRAGMA user_version").fetchone()[0], future_version)
                self.assertEqual(verify.execute("SELECT value FROM future_marker").fetchone()[0], "keep-me")
            finally:
                verify.close()
        finally:
            os.unlink(path)

    def test_chessbase_provenance_uses_portable_forward_slashes(self):
        report = probe_chessbase_source(r"incoming\Training Database.CBH").as_report_fields()
        self.assertEqual(report["source_path"], "incoming/Training Database.CBH")
        component_paths = [item["path"] for item in report["components"]]
        self.assertTrue(all("\\" not in path for path in component_paths))


if __name__ == "__main__":
    unittest.main()
