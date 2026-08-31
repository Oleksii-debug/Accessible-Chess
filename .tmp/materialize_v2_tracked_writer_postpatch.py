from pathlib import Path

path = Path("acs/version2_upgrade.py")
text = path.read_text(encoding="utf-8")
original = text


def once(old: str, new: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"postpatch anchor count {count}, expected 1: {old[:120]!r}")
    text = text.replace(old, new, 1)


once(
    '        self._owned_states: dict[str, str] = {}\n',
    '        self._owned_states: dict[str, str] = {}\n        self._last_backup: Path | None = None\n        self._last_manifest: dict[str, object] | None = None\n',
)

once(
    '            _fsync_dir(self.layout.backup_root)\n            return final, manifest\n',
    '            _fsync_dir(self.layout.backup_root)\n            self._last_backup = final\n            self._last_manifest = manifest\n            return final, manifest\n',
)

start = text.index('    def _assert_library_publication_quiescent(self) -> None:\n')
end = text.index('    def _restore(self, upgrade_id: str) -> int:\n', start)
text = text[:start] + '''    def _prepare_library_publication(self, expected_original: str) -> None:\n        """Normalize a quiescent live SQLite file before atomic publication.\n\n        The logical state must still equal the pre-upgrade snapshot. A zero-timeout\n        checkpoint/IMMEDIATE probe converts ordinary closed WAL state into a\n        self-contained main database while failing closed on an active writer.\n        """\n        if not _is_sha256(expected_original):\n            raise Version2UpgradeError(\n                "library backup tracked-state metadata is invalid"\n            )\n        connection = None\n        try:\n            connection = sqlite3.connect(\n                str(self.layout.library_path), timeout=0.0\n            )\n            connection.execute("PRAGMA busy_timeout=0")\n            _canonical_library_schema(connection)\n            if _sqlite_state_sha256(connection) != expected_original:\n                raise Version2UpgradeError(\n                    "tracked user data changed after the upgrade snapshot"\n                )\n            mode_row = connection.execute("PRAGMA journal_mode").fetchone()\n            mode = str(mode_row[0]).casefold() if mode_row else ""\n            if mode == "wal":\n                checkpoint = connection.execute(\n                    "PRAGMA wal_checkpoint(TRUNCATE)"\n                ).fetchone()\n                if checkpoint and int(checkpoint[0]) != 0:\n                    raise Version2UpgradeBusy(\n                        "library is busy during upgrade publication"\n                    )\n            connection.execute("BEGIN IMMEDIATE")\n            if _sqlite_state_sha256(connection) != expected_original:\n                connection.rollback()\n                raise Version2UpgradeError(\n                    "tracked user data changed after the upgrade snapshot"\n                )\n            connection.rollback()\n        except Version2UpgradeError:\n            raise\n        except sqlite3.OperationalError as exc:\n            raise Version2UpgradeBusy(\n                "library is busy during upgrade publication"\n            ) from exc\n        except sqlite3.DatabaseError as exc:\n            raise Version2UpgradeError(\n                "library publication validation failed"\n            ) from exc\n        finally:\n            if connection is not None:\n                connection.close()\n\n        if _library_state_sha256(self.layout.library_path) != expected_original:\n            raise Version2UpgradeError(\n                "tracked user data changed after the upgrade snapshot"\n            )\n        # No writer held the SQLite write lock and WAL has been checkpointed.\n        # Remove now-stale sidecars before replacing the main file so they cannot\n        # be replayed against the migrated publication.\n        self._clear_library_sidecars()\n\n''' + text[end:]

once(
    '''    def _migrate_settings(\n        self,\n        manifest: Mapping[str, object],\n        upgrade_id: str,\n        *,\n        recovered: bool,\n    ) -> bool:\n''',
    '''    def _migrate_settings(\n        self,\n        manifest: Mapping[str, object] | None = None,\n        upgrade_id: str | None = None,\n        *,\n        recovered: bool = False,\n    ) -> bool:\n''',
)

once(
    '''        self._assert_tracked_original(manifest, self.layout.settings_name)\n        expected = hashlib.sha256(payload).hexdigest()\n        self._plan_owned_state(\n            upgrade_id,\n            "migrating",\n            self.layout.settings_name,\n            expected,\n            recovered=recovered,\n        )\n        self._assert_tracked_original(manifest, self.layout.settings_name)\n''',
    '''        if manifest is None:\n            manifest = self._last_manifest\n        if manifest is not None:\n            self._assert_tracked_original(\n                manifest, self.layout.settings_name\n            )\n        expected = hashlib.sha256(payload).hexdigest()\n        if upgrade_id is not None:\n            if manifest is None:\n                raise ValueError(\n                    "upgrade manifest is required with an upgrade identifier"\n                )\n            self._plan_owned_state(\n                upgrade_id,\n                "migrating",\n                self.layout.settings_name,\n                expected,\n                recovered=recovered,\n            )\n            self._assert_tracked_original(\n                manifest, self.layout.settings_name\n            )\n''',
)

once(
    '''    def _migrate_library(\n        self,\n        backup: Path,\n        manifest: Mapping[str, object],\n        upgrade_id: str,\n        *,\n        recovered: bool,\n    ) -> bool:\n''',
    '''    def _migrate_library(\n        self,\n        backup: Path | None = None,\n        manifest: Mapping[str, object] | None = None,\n        upgrade_id: str | None = None,\n        *,\n        recovered: bool = False,\n    ) -> bool:\n''',
)

once(
    '''        entry = self._manifest_tracked_entry(\n            manifest, self.layout.library_name\n        )\n''',
    '''        if backup is None:\n            backup = self._last_backup\n        if manifest is None:\n            manifest = self._last_manifest\n        if backup is None or manifest is None:\n            raise ValueError(\n                "a pre-migration backup is required for library migration"\n            )\n        entry = self._manifest_tracked_entry(\n            manifest, self.layout.library_name\n        )\n''',
)

once(
    '''            self._assert_tracked_original(\n                manifest, self.layout.library_name\n            )\n            self._assert_library_publication_quiescent()\n            self._plan_owned_state(\n                upgrade_id,\n                "migrating",\n                self.layout.library_name,\n                publish_state,\n                recovered=recovered,\n            )\n            # Close the compare/publication window as much as the filesystem\n            # permits: re-authenticate immediately before atomic replacement.\n            self._assert_tracked_original(\n                manifest, self.layout.library_name\n            )\n            self._assert_library_publication_quiescent()\n''',
    '''            self._assert_tracked_original(\n                manifest, self.layout.library_name\n            )\n            self._prepare_library_publication(str(original_state))\n            if upgrade_id is not None:\n                self._plan_owned_state(\n                    upgrade_id,\n                    "migrating",\n                    self.layout.library_name,\n                    publish_state,\n                    recovered=recovered,\n                )\n            # Close the compare/publication window as much as the filesystem\n            # permits: re-authenticate immediately before atomic replacement.\n            self._assert_tracked_original(\n                manifest, self.layout.library_name\n            )\n            self._prepare_library_publication(str(original_state))\n''',
)

if text == original:
    raise SystemExit("no compatibility postpatch materialized")
path.write_text(text, encoding="utf-8", newline="\n")
