from __future__ import annotations

"""Version 2 upgrade orchestration with exact legacy-Library integration.

The crash-recovery/CAS implementation lives byte-for-byte in
``version2_upgrade_base``. This module is the stable import surface and adds
only the D07-owned unversioned Library seam: exact schema recognition plus
conversion of an authenticated private working copy before the existing
publication transaction runs.
"""

import os
from pathlib import Path
import secrets
import sqlite3
from typing import Mapping

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




class Version2UpgradeCoordinator(_base.Version2UpgradeCoordinator):
    """Canonical coordinator with preservation-first schema-0 conversion."""

    def _validate_library_schema(self, connection: sqlite3.Connection) -> int:
        """Use D07 legacy recognition only for this coordinator instance."""
        return _canonical_library_schema(connection)

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
