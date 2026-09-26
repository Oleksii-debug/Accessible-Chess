from __future__ import annotations

"""Version 2 upgrade orchestration with exact legacy-Library integration.

The crash-recovery/CAS implementation lives byte-for-byte in
``version2_upgrade_base``. This module is the stable import surface and adds
only the D07-owned unversioned Library seam: exact schema recognition plus
conversion of an authenticated private working copy before the existing
publication transaction runs.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import sqlite3
from threading import RLock
from typing import Iterator, Mapping

from . import version2_upgrade_base as _base
from .acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase
from .legacy_library_migration import (
    LegacyLibraryMigrationError,
    _check_legacy_schema,
    migrate_legacy_library,
)

# Preserve the complete historical API, including intentionally used private
# helpers in focused recovery tests, while keeping one canonical coordinator.
for _name in dir(_base):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_base, _name)


_SCHEMA_SCOPE_LOCK = RLock()


def _canonical_library_schema(connection: sqlite3.Connection) -> int:
    """Recognize only current D07 schemas or the exact shipped legacy schema."""
    try:
        raw_row = connection.execute("PRAGMA user_version").fetchone()
        raw_version = raw_row[0] if raw_row is not None else None
        if raw_version == 0:
            try:
                _check_legacy_schema(connection)
            except LegacyLibraryMigrationError as exc:
                raise Version2UpgradeError("library validation failed") from exc
            return 0
        return AcsDatabase._check_sqlite_integrity(connection)
    except Version2UpgradeError:
        raise
    except RuntimeError as exc:
        if type(raw_version) is int and raw_version > ACSDB_SCHEMA_VERSION:
            raise Version2UpgradeError(
                "library schema is newer than this Version 2 build"
            ) from exc
        raise Version2UpgradeError("library validation failed") from exc
    except sqlite3.DatabaseError as exc:
        raise Version2UpgradeError("library validation failed") from exc


@contextmanager
def _legacy_schema_scope() -> Iterator[None]:
    """Temporarily route base helper validation through the D07 legacy seam.

    Base helper functions intentionally resolve ``_canonical_library_schema``
    from their defining module. The previous integration rebound that symbol at
    import time, permanently changing ``version2_upgrade_base`` for unrelated
    callers. Keep that compatibility seam strictly bounded to one upgrade or
    recovery transaction and restore the original authority even on failure.
    """

    with _SCHEMA_SCOPE_LOCK:
        original = _base._canonical_library_schema
        _base._canonical_library_schema = _canonical_library_schema
        try:
            yield
        finally:
            _base._canonical_library_schema = original


class Version2UpgradeCoordinator(_base.Version2UpgradeCoordinator):
    """Canonical coordinator with preservation-first schema-0 conversion."""

    def run(self):
        with _legacy_schema_scope():
            return super().run()

    def recover_interrupted(self) -> bool:
        with _legacy_schema_scope():
            return super().recover_interrupted()

    def _migrate_library(
        self,
        backup: Path | None = None,
        manifest: Mapping[str, object] | None = None,
        upgrade_id: str | None = None,
        *,
        recovered: bool = False,
    ) -> bool:
        before = self._library_schema()
        if before != 0:
            return super()._migrate_library(
                backup,
                manifest,
                upgrade_id,
                recovered=recovered,
            )

        original_factory = self.database_factory

        def legacy_private_factory(path: str | Path):
            work = Path(path)
            converted = work.parent / (
                f".{work.name}.legacy-current-{secrets.token_hex(4)}.acsdb"
            )
            try:
                result = migrate_legacy_library(work, converted)
                if result.schema_version != ACSDB_SCHEMA_VERSION:
                    raise Version2UpgradeError(
                        "legacy library migration did not reach the target schema"
                    )
                # Both paths are private, authenticated upgrade working files.
                # The live Library is still untouched; super() performs the
                # existing CAS/publication-guard transaction afterwards.
                os.replace(converted, work)
                _base._fsync_dir(work.parent)
                return original_factory(work)
            except Version2UpgradeError:
                raise
            except LegacyLibraryMigrationError as exc:
                raise Version2UpgradeError(
                    "legacy library migration validation failed"
                ) from exc
            finally:
                for candidate in (
                    converted,
                    Path(str(converted) + "-wal"),
                    Path(str(converted) + "-shm"),
                    Path(str(converted) + "-journal"),
                ):
                    if candidate.exists() or candidate.is_symlink():
                        try:
                            candidate.unlink()
                        except OSError:
                            pass

        self.database_factory = legacy_private_factory
        try:
            return super()._migrate_library(
                backup,
                manifest,
                upgrade_id,
                recovered=recovered,
            )
        finally:
            self.database_factory = original_factory
