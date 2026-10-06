from __future__ import annotations

import os
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.version2_upgrade_base import (
    UserDataLayout,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
    _UpgradeLock,
    _atomic_bytes,
    _sqlite_backup,
    _stable_copy,
)


class V2UpgradeGeneratedArtifactAuthenticationTests(unittest.TestCase):
    def _coordinator(self, root: Path) -> Version2UpgradeCoordinator:
        return Version2UpgradeCoordinator(UserDataLayout(root))

    def _assert_symlink_alias_fails_closed(self, relative: str) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            target = Path(td) / "outside-user-data.bin"
            target.write_bytes(b"outside-user-data")
            alias = root / relative
            alias.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.symlink(target, alias)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this runner")

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "symlink or reparse point",
            ):
                self._coordinator(root)._files()

            self.assertEqual(target.read_bytes(), b"outside-user-data")

    def test_missing_upgrade_lock_create_race_never_adopts_foreign_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            lock = root / ".v2-upgrade.lock"
            real_open = os.open
            injected = False
            foreign_bytes = b"foreign-lock-owner"

            def racing_open(path, flags, mode=0o777):
                nonlocal injected
                if Path(path) == lock and not injected:
                    lock.write_bytes(foreign_bytes)
                    injected = True
                return real_open(path, flags, mode)

            with mock.patch(
                "acs.version2_upgrade_base.os.open",
                side_effect=racing_open,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "upgrade lock could not be opened safely",
                ):
                    with _UpgradeLock(lock):
                        pass

            self.assertTrue(injected)
            self.assertEqual(lock.read_bytes(), foreign_bytes)

    def test_existing_upgrade_lock_replacement_race_fails_without_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            lock = root / ".v2-upgrade.lock"
            lock.write_bytes(b"\0")
            replacement = root / "foreign-lock-replacement.bin"
            replacement_bytes = b"foreign-lock-replacement"
            replacement.write_bytes(replacement_bytes)
            real_open = os.open
            injected = False

            def racing_open(path, flags, mode=0o777):
                nonlocal injected
                if Path(path) == lock and not injected:
                    os.replace(replacement, lock)
                    injected = True
                return real_open(path, flags, mode)

            with mock.patch(
                "acs.version2_upgrade_base.os.open",
                side_effect=racing_open,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "upgrade lock changed while opening",
                ):
                    with _UpgradeLock(lock):
                        pass

            self.assertTrue(injected)
            self.assertEqual(lock.read_bytes(), replacement_bytes)

    def test_atomic_publication_rejects_substituted_temp_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "state.json"
            substitute = root / "foreign-substitute.bin"
            substitute_bytes = b"foreign-preservation-bytes"
            substitute.write_bytes(substitute_bytes)
            real_mkstemp = tempfile.mkstemp
            real_lstat = os.lstat
            temp_path: Path | None = None
            injected = False

            def tracking_mkstemp(*args, **kwargs):
                nonlocal temp_path
                descriptor, name = real_mkstemp(*args, **kwargs)
                temp_path = Path(name)
                return descriptor, name

            def substituting_lstat(path, *args, **kwargs):
                nonlocal injected
                candidate = Path(path)
                if (
                    temp_path is not None
                    and candidate == temp_path
                    and not injected
                ):
                    os.replace(substitute, temp_path)
                    injected = True
                return real_lstat(path, *args, **kwargs)

            with mock.patch(
                "acs.version2_upgrade_base.tempfile.mkstemp",
                side_effect=tracking_mkstemp,
            ), mock.patch(
                "acs.version2_upgrade_base.os.lstat",
                side_effect=substituting_lstat,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "temporary file changed before publication",
                ):
                    _atomic_bytes(target, b"owned-publication")

            self.assertTrue(injected)
            self.assertFalse(target.exists())
            self.assertIsNotNone(temp_path)
            assert temp_path is not None
            self.assertTrue(temp_path.exists())
            self.assertEqual(temp_path.read_bytes(), substitute_bytes)

    def test_atomic_publication_rejects_hardlinked_temp_and_preserves_peer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "state.json"
            peer = root / "foreign-hardlink-peer.bin"
            real_mkstemp = tempfile.mkstemp
            real_lstat = os.lstat
            temp_path: Path | None = None
            injected = False

            def tracking_mkstemp(*args, **kwargs):
                nonlocal temp_path
                descriptor, name = real_mkstemp(*args, **kwargs)
                temp_path = Path(name)
                return descriptor, name

            def hardlinking_lstat(path, *args, **kwargs):
                nonlocal injected
                candidate = Path(path)
                if (
                    temp_path is not None
                    and candidate == temp_path
                    and not injected
                ):
                    try:
                        os.link(temp_path, peer)
                    except (OSError, NotImplementedError):
                        self.skipTest("hard-link creation is unavailable on this runner")
                    injected = True
                return real_lstat(path, *args, **kwargs)

            with mock.patch(
                "acs.version2_upgrade_base.tempfile.mkstemp",
                side_effect=tracking_mkstemp,
            ), mock.patch(
                "acs.version2_upgrade_base.os.lstat",
                side_effect=hardlinking_lstat,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "temporary file changed before publication",
                ):
                    _atomic_bytes(target, b"owned-publication")

            self.assertTrue(injected)
            self.assertFalse(target.exists())
            self.assertIsNotNone(temp_path)
            assert temp_path is not None
            self.assertTrue(temp_path.exists())
            self.assertTrue(peer.exists())
            self.assertEqual(temp_path.read_bytes(), b"owned-publication")
            self.assertEqual(peer.read_bytes(), b"owned-publication")

    def test_backup_copy_rejects_substituted_temp_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.bin"
            source.write_bytes(b"source-preservation-bytes")
            destination = root / "backup" / "source.bin"
            substitute = root / "foreign-backup-substitute.bin"
            substitute_bytes = b"foreign-backup-bytes"
            substitute.write_bytes(substitute_bytes)
            real_mkstemp = tempfile.mkstemp
            real_lstat = os.lstat
            temp_path: Path | None = None
            injected = False

            def tracking_mkstemp(*args, **kwargs):
                nonlocal temp_path
                descriptor, name = real_mkstemp(*args, **kwargs)
                temp_path = Path(name)
                return descriptor, name

            def substituting_lstat(path, *args, **kwargs):
                nonlocal injected
                candidate = Path(path)
                if (
                    temp_path is not None
                    and candidate == temp_path
                    and not injected
                ):
                    os.replace(substitute, temp_path)
                    injected = True
                return real_lstat(path, *args, **kwargs)

            with mock.patch(
                "acs.version2_upgrade_base.tempfile.mkstemp",
                side_effect=tracking_mkstemp,
            ), mock.patch(
                "acs.version2_upgrade_base.os.lstat",
                side_effect=substituting_lstat,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "backup copy temporary file changed before publication",
                ):
                    _stable_copy(source, destination)

            self.assertTrue(injected)
            self.assertEqual(source.read_bytes(), b"source-preservation-bytes")
            self.assertFalse(destination.exists())
            self.assertIsNotNone(temp_path)
            assert temp_path is not None
            self.assertTrue(temp_path.exists())
            self.assertEqual(temp_path.read_bytes(), substitute_bytes)

    def test_atomic_publication_rejects_same_bytes_temp_swap_at_replace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "state.json"
            real_replace = os.replace
            injected = False

            def replace_with_same_bytes_swap(source, destination):
                nonlocal injected
                source = Path(source)
                destination = Path(destination)
                if destination == target and not injected:
                    foreign = root / "foreign-same-bytes-atomic.tmp"
                    foreign.write_bytes(source.read_bytes())
                    real_replace(foreign, source)
                    injected = True
                return real_replace(source, destination)

            with mock.patch(
                "acs.version2_upgrade_base.os.replace",
                side_effect=replace_with_same_bytes_swap,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "atomic write publication changed before durability confirmation",
                ):
                    _atomic_bytes(target, b"owned-publication")

            self.assertTrue(injected)
            self.assertEqual(target.read_bytes(), b"owned-publication")

    def test_backup_copy_rejects_same_bytes_temp_swap_at_replace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.bin"
            source.write_bytes(b"source-preservation-bytes")
            destination = root / "backup" / "source.bin"
            real_replace = os.replace
            injected = False

            def replace_with_same_bytes_swap(candidate, published):
                nonlocal injected
                candidate = Path(candidate)
                published = Path(published)
                if published == destination and not injected:
                    foreign = root / "foreign-same-bytes-backup.tmp"
                    foreign.write_bytes(candidate.read_bytes())
                    real_replace(foreign, candidate)
                    injected = True
                return real_replace(candidate, published)

            with mock.patch(
                "acs.version2_upgrade_base.os.replace",
                side_effect=replace_with_same_bytes_swap,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "backup copy publication changed before durability confirmation",
                ):
                    _stable_copy(source, destination)

            self.assertTrue(injected)
            self.assertEqual(source.read_bytes(), b"source-preservation-bytes")
            self.assertEqual(destination.read_bytes(), b"source-preservation-bytes")

    def test_sqlite_backup_rejects_same_bytes_atomic_publication_swap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "library.acsdb"
            destination = root / "backup" / "library.acsdb"
            connection = sqlite3.connect(source)
            try:
                connection.execute("PRAGMA user_version=5")
                connection.execute("CREATE TABLE sample(value TEXT NOT NULL)")
                connection.execute("INSERT INTO sample(value) VALUES ('stable')")
                connection.commit()
            finally:
                connection.close()

            def validate(connection):
                row = connection.execute("PRAGMA user_version").fetchone()
                return int(row[0])

            real_replace = os.replace
            injected = False

            def replace_with_same_bytes_swap(candidate, published):
                nonlocal injected
                candidate = Path(candidate)
                published = Path(published)
                if published == destination and not injected:
                    foreign = root / "foreign-same-bytes-sqlite.tmp"
                    foreign.write_bytes(candidate.read_bytes())
                    real_replace(foreign, candidate)
                    injected = True
                return real_replace(candidate, published)

            with mock.patch(
                "acs.version2_upgrade_base.os.replace",
                side_effect=replace_with_same_bytes_swap,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "atomic write publication changed before durability confirmation",
                ):
                    _sqlite_backup(
                        source,
                        destination,
                        schema_validator=validate,
                    )

            self.assertTrue(injected)
            visible = sqlite3.connect(destination)
            try:
                self.assertEqual(
                    [("stable",)],
                    visible.execute("SELECT value FROM sample").fetchall(),
                )
            finally:
                visible.close()

    def test_sqlite_backup_uses_memory_snapshot_before_atomic_publication(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "library.acsdb"
            destination = root / "backup" / "library.acsdb"
            source_connection = sqlite3.connect(source)
            try:
                source_connection.execute("PRAGMA user_version=17")
                source_connection.execute("CREATE TABLE sample(value TEXT NOT NULL)")
                source_connection.execute(
                    "INSERT INTO sample(value) VALUES (?)",
                    ("canonical-state",),
                )
                source_connection.commit()
            finally:
                source_connection.close()

            real_connect = sqlite3.connect
            writable_targets: list[str] = []

            def validate(connection):
                row = connection.execute("PRAGMA user_version").fetchone()
                return int(row[0])

            def guarded_connect(database, *args, **kwargs):
                raw = os.fspath(database)
                if raw == str(source) or raw == ":memory:" or raw.startswith("file:"):
                    if raw == ":memory:":
                        writable_targets.append(raw)
                    return real_connect(database, *args, **kwargs)
                raise AssertionError(
                    "SQLite backup must not reopen a pre-created temp pathname"
                )

            with mock.patch(
                "acs.version2_upgrade_base.sqlite3.connect",
                side_effect=guarded_connect,
            ):
                size, digest, version, state_digest = _sqlite_backup(
                    source,
                    destination,
                    schema_validator=validate,
                )

            self.assertEqual([":memory:"], writable_targets)
            self.assertEqual(destination.stat().st_size, size)
            self.assertEqual(64, len(digest))
            self.assertEqual(17, version)
            self.assertEqual(64, len(state_digest))
            restored = sqlite3.connect(destination)
            try:
                self.assertEqual(
                    [("canonical-state",)],
                    restored.execute("SELECT value FROM sample").fetchall(),
                )
                self.assertEqual(
                    17,
                    restored.execute("PRAGMA user_version").fetchone()[0],
                )
            finally:
                restored.close()

    def test_sqlite_backup_holds_writer_lock_through_atomic_publication(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "library.acsdb"
            destination = root / "backup" / "library.acsdb"
            connection = sqlite3.connect(source)
            try:
                connection.execute("PRAGMA user_version=23")
                connection.execute("CREATE TABLE sample(value TEXT NOT NULL)")
                connection.execute(
                    "INSERT INTO sample(value) VALUES ('canonical')"
                )
                connection.commit()
            finally:
                connection.close()

            from acs import version2_upgrade_base as upgrade_base

            real_atomic_bytes = upgrade_base._atomic_bytes
            writer_attempted = False
            writer_blocked = False
            writer_committed = False

            def validate(connection):
                row = connection.execute("PRAGMA user_version").fetchone()
                return int(row[0])

            def racing_atomic_bytes(path, payload):
                nonlocal writer_attempted, writer_blocked, writer_committed
                writer_attempted = True
                writer = sqlite3.connect(source, timeout=0.0)
                try:
                    writer.execute("PRAGMA busy_timeout=0")
                    try:
                        writer.execute(
                            "INSERT INTO sample(value) VALUES ('racing-writer')"
                        )
                        writer.commit()
                        writer_committed = True
                    except sqlite3.OperationalError as exc:
                        writer.rollback()
                        if "locked" not in str(exc).lower():
                            raise
                        writer_blocked = True
                finally:
                    writer.close()
                real_atomic_bytes(path, payload)

            with mock.patch(
                "acs.version2_upgrade_base._atomic_bytes",
                side_effect=racing_atomic_bytes,
            ):
                _sqlite_backup(
                    source,
                    destination,
                    schema_validator=validate,
                )

            self.assertTrue(writer_attempted)
            self.assertTrue(
                writer_blocked,
                "cooperative SQLite writer was not fenced through backup publication",
            )
            self.assertFalse(writer_committed)

            visible_source = sqlite3.connect(source)
            visible_backup = sqlite3.connect(destination)
            try:
                expected = [("canonical",)]
                self.assertEqual(
                    expected,
                    visible_source.execute("SELECT value FROM sample").fetchall(),
                )
                self.assertEqual(
                    expected,
                    visible_backup.execute("SELECT value FROM sample").fetchall(),
                )
            finally:
                visible_backup.close()
                visible_source.close()

    @unittest.skipIf(
        os.name == "nt",
        "replacing an open SQLite source pathname is not portable on Windows",
    )
    def test_sqlite_backup_rejects_source_path_replacement_during_publication(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "library.acsdb"
            replacement = root / "replacement.acsdb"
            destination = root / "backup" / "library.acsdb"

            for path, value in ((source, "original"), (replacement, "replacement")):
                connection = sqlite3.connect(path)
                try:
                    connection.execute("PRAGMA user_version=29")
                    connection.execute("CREATE TABLE sample(value TEXT NOT NULL)")
                    connection.execute(
                        "INSERT INTO sample(value) VALUES (?)",
                        (value,),
                    )
                    connection.commit()
                finally:
                    connection.close()

            from acs import version2_upgrade_base as upgrade_base

            real_atomic_bytes = upgrade_base._atomic_bytes
            injected = False

            def validate(connection):
                row = connection.execute("PRAGMA user_version").fetchone()
                return int(row[0])

            def publishing_then_replacing_source(path, payload):
                nonlocal injected
                real_atomic_bytes(path, payload)
                os.replace(replacement, source)
                injected = True

            with mock.patch(
                "acs.version2_upgrade_base._atomic_bytes",
                side_effect=publishing_then_replacing_source,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "library source changed during backup",
                ):
                    _sqlite_backup(
                        source,
                        destination,
                        schema_validator=validate,
                    )

            self.assertTrue(injected)
            visible = sqlite3.connect(source)
            try:
                self.assertEqual(
                    [("replacement",)],
                    visible.execute("SELECT value FROM sample").fetchall(),
                )
            finally:
                visible.close()

    @unittest.skipIf(
        os.name == "nt",
        "replacing an open SQLite source pathname is not portable on Windows",
    )
    def test_sqlite_backup_rejects_source_path_replacement_during_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "library.acsdb"
            replacement = root / "replacement.acsdb"
            destination = root / "backup" / "library.acsdb"

            for path, value in ((source, "original"), (replacement, "replacement")):
                connection = sqlite3.connect(path)
                try:
                    connection.execute("PRAGMA user_version=9")
                    connection.execute("CREATE TABLE sample(value TEXT NOT NULL)")
                    connection.execute(
                        "INSERT INTO sample(value) VALUES (?)",
                        (value,),
                    )
                    connection.commit()
                finally:
                    connection.close()

            from acs import version2_upgrade_base as upgrade_base

            real_state_sha256 = upgrade_base._sqlite_state_sha256
            injected = False

            def racing_state_sha256(connection):
                nonlocal injected
                digest = real_state_sha256(connection)
                if not injected:
                    os.replace(replacement, source)
                    injected = True
                return digest

            def validate(connection):
                row = connection.execute("PRAGMA user_version").fetchone()
                return int(row[0])

            with mock.patch(
                "acs.version2_upgrade_base._sqlite_state_sha256",
                side_effect=racing_state_sha256,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "library source changed during backup",
                ):
                    _sqlite_backup(
                        source,
                        destination,
                        schema_validator=validate,
                    )

            self.assertTrue(injected)
            self.assertFalse(destination.exists())
            visible = sqlite3.connect(source)
            try:
                self.assertEqual(
                    [("replacement",)],
                    visible.execute("SELECT value FROM sample").fetchall(),
                )
            finally:
                visible.close()

    def test_sqlite_backup_inherits_atomic_temp_identity_rejection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "library.acsdb"
            destination = root / "backup" / "library.acsdb"
            source_connection = sqlite3.connect(source)
            try:
                source_connection.execute("PRAGMA user_version=3")
                source_connection.execute("CREATE TABLE sample(value INTEGER)")
                source_connection.execute("INSERT INTO sample(value) VALUES (7)")
                source_connection.commit()
            finally:
                source_connection.close()

            substitute = root / "foreign-sqlite-temp-substitute.bin"
            substitute_bytes = b"preserve-foreign-sqlite-temp"
            substitute.write_bytes(substitute_bytes)
            real_mkstemp = tempfile.mkstemp
            real_lstat = os.lstat
            temp_path: Path | None = None
            injected = False

            def validate(connection):
                row = connection.execute("PRAGMA user_version").fetchone()
                return int(row[0])

            def tracking_mkstemp(*args, **kwargs):
                nonlocal temp_path
                descriptor, name = real_mkstemp(*args, **kwargs)
                temp_path = Path(name)
                return descriptor, name

            def substituting_lstat(path, *args, **kwargs):
                nonlocal injected
                candidate = Path(path)
                if (
                    temp_path is not None
                    and candidate == temp_path
                    and not injected
                ):
                    os.replace(substitute, temp_path)
                    injected = True
                return real_lstat(path, *args, **kwargs)

            with mock.patch(
                "acs.version2_upgrade_base.tempfile.mkstemp",
                side_effect=tracking_mkstemp,
            ), mock.patch(
                "acs.version2_upgrade_base.os.lstat",
                side_effect=substituting_lstat,
            ):
                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "temporary file changed before publication",
                ):
                    _sqlite_backup(
                        source,
                        destination,
                        schema_validator=validate,
                    )

            self.assertTrue(injected)
            self.assertFalse(destination.exists())
            self.assertIsNotNone(temp_path)
            assert temp_path is not None
            self.assertTrue(temp_path.exists())
            self.assertEqual(substitute_bytes, temp_path.read_bytes())

    def test_control_name_directory_preserves_descendants_as_user_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            control_named_directory = root / "book-progress.json.lock"
            control_named_directory.mkdir()
            payload = control_named_directory / "keep.bin"
            payload.write_bytes(b"preserve-directory-user-data")

            files = {
                path.relative_to(root).as_posix()
                for path in self._coordinator(root)._files()
            }

            self.assertIn("book-progress.json.lock/keep.bin", files)
            self.assertEqual(payload.read_bytes(), b"preserve-directory-user-data")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_control_name_special_object_fails_closed(self):
        for relative in (
            ".v2-upgrade.lock",
            ".v2-upgrade-state.json",
            "book-progress.json.lock",
        ):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as td:
                root = Path(td) / "AccessibleChess"
                root.mkdir()
                os.mkfifo(root / relative)

                with self.assertRaisesRegex(
                    Version2UpgradeError,
                    "control entry must be a regular file",
                ):
                    self._coordinator(root)._files()

    def test_hardlinked_control_name_is_preservation_backed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            source = root / "important-user-data.bin"
            source.write_bytes(b"preserve-control-alias-source")
            control = root / "book-progress.json.lock"
            try:
                os.link(source, control)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")

            coordinator = self._coordinator(root)
            coordinator._ensure_roots()
            files = {
                path.relative_to(root).as_posix()
                for path in coordinator._files()
            }
            self.assertIn("important-user-data.bin", files)
            self.assertIn("book-progress.json.lock", files)

            backup, manifest = coordinator._create_backup(
                "hardlinked-control-preservation"
            )
            paths = {str(item["path"]) for item in manifest["entries"]}
            self.assertIn("important-user-data.bin", paths)
            self.assertIn("book-progress.json.lock", paths)
            self.assertEqual(
                (backup / "data" / "important-user-data.bin").read_bytes(),
                b"preserve-control-alias-source",
            )
            self.assertEqual(
                (backup / "data" / "book-progress.json.lock").read_bytes(),
                b"preserve-control-alias-source",
            )
            self.assertEqual(source.read_bytes(), b"preserve-control-alias-source")
            self.assertEqual(control.read_bytes(), b"preserve-control-alias-source")

    def test_exact_generated_runtime_aliases_fail_closed(self):
        digest = "a" * 64
        generated = (
            "gametree-resume.json.abcd_123.tmp",
            "gametree-resume.json.cas-abcd_123.bak",
            ".book-progress.json.abcd_123.tmp",
            ".book-progress.json.bak.abcd_123.tmp",
            ".education-workspace.json.abcd_123.tmp",
            f"training-progress/.{digest}.json.lock",
            f"training-progress/.{digest}.json.abcd_123.tmp",
            "settings.json.tmp",
            ".settings.json.abcd_123.tmp",
            "..v2-upgrade-state.json.abcd_123.tmp",
            ".settings.json.publish-guard-abcdef123456",
            ".library.acsdb.publish-guard-abcdef123456",
        )
        for relative in generated:
            with self.subTest(relative=relative):
                self._assert_symlink_alias_fails_closed(relative)

    def test_derived_runtime_descendant_aliases_fail_closed(self):
        for relative in (
            "sound-cache/cache-entry.wav",
            ".gametree-resume-discard/" + ("b" * 64) + ".guard",
        ):
            with self.subTest(relative=relative):
                self._assert_symlink_alias_fails_closed(relative)

    def test_hardlinked_private_generated_names_remain_preservation_backed(self):
        digest = "a" * 64
        generated = (
            "gametree-resume.json.abcd_123.tmp",
            "gametree-resume.json.cas-abcd_123.bak",
            ".book-progress.json.abcd_123.tmp",
            ".book-progress.json.bak.abcd_123.tmp",
            ".education-workspace.json.abcd_123.tmp",
            f"training-progress/.{digest}.json.lock",
            f"training-progress/.{digest}.json.abcd_123.tmp",
            "settings.json.tmp",
            ".settings.json.abcd_123.tmp",
            "..v2-upgrade-state.json.abcd_123.tmp",
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            source = root / "important-user-data.bin"
            source.write_bytes(b"preserve-this-inode")

            created: list[Path] = []
            try:
                for relative in generated:
                    alias = root / relative
                    alias.parent.mkdir(parents=True, exist_ok=True)
                    os.link(source, alias)
                    created.append(alias)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")

            files = {
                path.relative_to(root).as_posix()
                for path in self._coordinator(root)._files()
            }
            self.assertIn(source.name, files)
            for alias in created:
                self.assertIn(alias.relative_to(root).as_posix(), files)
                self.assertEqual(alias.read_bytes(), b"preserve-this-inode")

    def test_publication_guard_hardlink_remains_generated_coordination_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_bytes(b'{"schema_version":1}')
            guard = root / ".settings.json.publish-guard-abcdef123456"
            try:
                os.link(settings, guard)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")

            files = {
                path.relative_to(root).as_posix()
                for path in self._coordinator(root)._files()
            }
            self.assertIn("settings.json", files)
            self.assertNotIn(guard.name, files)
            self.assertEqual(guard.read_bytes(), settings.read_bytes())

    def test_private_publication_guard_lookalike_remains_preservation_backed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_bytes(b'{"schema_version":1}')
            guard = root / ".settings.json.publish-guard-abcdef123456"
            guard.write_bytes(b"user-owned-lookalike")

            files = {
                path.relative_to(root).as_posix()
                for path in self._coordinator(root)._files()
            }

            self.assertIn("settings.json", files)
            self.assertIn(guard.name, files)
            self.assertEqual(guard.read_bytes(), b"user-owned-lookalike")

    def test_publication_guard_hardlink_to_unrelated_inode_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            library.write_bytes(b"current-library")
            source = root / "important-user-data.bin"
            source.write_bytes(b"preserve-unrelated-hardlink")
            guard = root / ".library.acsdb.publish-guard-abcdef123456"
            try:
                os.link(source, guard)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")

            files = {
                path.relative_to(root).as_posix()
                for path in self._coordinator(root)._files()
            }

            self.assertIn("library.acsdb", files)
            self.assertIn(source.name, files)
            self.assertIn(guard.name, files)
            self.assertEqual(guard.read_bytes(), source.read_bytes())

    def test_stale_publication_guard_after_target_replace_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            settings = root / "settings.json"
            settings.write_bytes(b'{"schema_version":1,"old":true}')
            guard = root / ".settings.json.publish-guard-abcdef123456"
            try:
                os.link(settings, guard)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")
            replacement = root / "settings-replacement.json"
            replacement.write_bytes(b'{"schema_version":1,"new":true}')
            os.replace(replacement, settings)

            files = {
                path.relative_to(root).as_posix()
                for path in self._coordinator(root)._files()
            }

            self.assertIn("settings.json", files)
            self.assertIn(guard.name, files)
            self.assertEqual(guard.read_bytes(), b'{"schema_version":1,"old":true}')
            self.assertEqual(settings.read_bytes(), b'{"schema_version":1,"new":true}')

    def test_library_publication_guard_hardlink_to_current_target_is_generated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            library = root / "library.acsdb"
            library.write_bytes(b"current-library")
            guard = root / ".library.acsdb.publish-guard-abcdef123456"
            try:
                os.link(library, guard)
            except (OSError, NotImplementedError):
                self.skipTest("hard-link creation is unavailable on this runner")

            files = {
                path.relative_to(root).as_posix()
                for path in self._coordinator(root)._files()
            }

            self.assertIn("library.acsdb", files)
            self.assertNotIn(guard.name, files)
            self.assertEqual(guard.read_bytes(), library.read_bytes())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_generated_filename_special_object_is_not_silently_discarded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            fifo = root / "gametree-resume.json.abcd_123.tmp"
            os.mkfifo(fifo)

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "non-regular entry",
            ):
                self._coordinator(root)._files()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_derived_runtime_special_object_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            root.mkdir()
            cache = root / "sound-cache"
            cache.mkdir()
            fifo = cache / "cache-entry"
            os.mkfifo(fifo)

            with self.assertRaisesRegex(
                Version2UpgradeError,
                "regular file or directory",
            ):
                self._coordinator(root)._files()


if __name__ == "__main__":
    unittest.main()
