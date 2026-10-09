from __future__ import annotations

"""Section 51 owner data transfer using the canonical Version2 upgrade authority.

A transfer is a directory, not an untrusted archive. Export serializes the
existing upgrade backup snapshot under its standard *.upgrade-backups parent.
Import verifies every manifest entry before touching a NEW destination, runs
the canonical migration on private staging, then publishes with the existing
atomic no-replace directory primitive. No live profile is overwritten.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import stat
import tempfile

from .version2_package_assembler import (\n    Version2PackageAssemblyError,\n    _publish_directory_no_replace,\n)
from .version2_upgrade import (
    UserDataLayout,
    Version2UpgradeCoordinator,
    Version2UpgradeError,
    Version2UpgradeRecoveryError,
    _UpgradeLock,
    _fsync_dir,
    _safe_stat,
    _stable_copy,
)

_BACKUP_SUFFIX = ".upgrade-backups"
_EXPORT_PREFIX = "owner-transfer-"


class UserDataTransferError(RuntimeError):
    """Safe, nonsecret error exposed by the owner transfer command."""


def _plain_directory(path: Path, *, label: str) -> None:
    try:
        info = _safe_stat(path, label)
    except (OSError, Version2UpgradeError) as exc:
        raise UserDataTransferError(f"{label} is not a safe directory") from exc
    if not stat.S_ISDIR(info.st_mode):
        raise UserDataTransferError(f"{label} must be a directory")


def _absent(path: Path, *, label: str) -> None:
    # lexists rejects a dangling symlink as well as a regular file/dir.
    if os.path.lexists(path):
        raise UserDataTransferError(f"{label} already exists; refusing overwrite")


def export_owner_profile(layout: UserDataLayout) -> Path:
    """Create a checksum-verified immutable transfer snapshot of ALL owned data.

    The application must be closed for a complete cross-domain consistency
    snapshot; the canonical upgrade lock protects its own upgrade writer, not
    every independent Media/Training/Classroom writer.
    """

    if not isinstance(layout, UserDataLayout):
        raise TypeError("layout must be UserDataLayout")
    _plain_directory(layout.root, label="user data root")
    coordinator = Version2UpgradeCoordinator(layout)
    coordinator._ensure_roots()
    try:
        with _UpgradeLock(layout.lock_path) as lock:
            coordinator._active_upgrade_lock = lock
            try:
                if os.path.lexists(layout.journal_path):
                    journal = coordinator._journal()
                    if journal["phase"] not in {"committed", "rolled_back"}:
                        raise UserDataTransferError(
                            "an interrupted upgrade must be recovered before export"
                        )
                export_id = (
                    _EXPORT_PREFIX
                    + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
                    + secrets.token_hex(6)
                )
                snapshot, _ = coordinator._create_backup(export_id)
                coordinator._manifest(export_id)
                return snapshot
            finally:
                coordinator._active_upgrade_lock = None
    except (OSError, Version2UpgradeError, Version2UpgradeRecoveryError) as exc:
        raise UserDataTransferError("profile export failed validation") from exc


def _source_manifest(backup: Path) -> tuple[Path, dict[str, object]]:
    _plain_directory(backup, label="transfer snapshot")
    parent = backup.parent
    _plain_directory(parent, label="transfer snapshot parent")
    if not parent.name.endswith(_BACKUP_SUFFIX):
        raise UserDataTransferError(
            "transfer snapshot must remain inside a *.upgrade-backups directory"
        )
    if not backup.name.startswith(_EXPORT_PREFIX):
        raise UserDataTransferError("this is not an owner-transfer snapshot")
    owning_name = parent.name[: -len(_BACKUP_SUFFIX)]
    if not owning_name:
        raise UserDataTransferError("transfer snapshot owner is invalid")
    verification_root = parent.parent / owning_name
    verifier = Version2UpgradeCoordinator(UserDataLayout(verification_root))
    try:
        verified_path, manifest = verifier._manifest(backup.name)
    except (OSError, Version2UpgradeError, Version2UpgradeRecoveryError) as exc:
        raise UserDataTransferError("transfer manifest or file digest is invalid") from exc
    return verified_path, manifest


def import_owner_profile(backup: str | Path, destination: str | Path) -> str:
    """Install a verified snapshot into a never-existing profile directory.

    Migration runs on staging before publication. Backup history is published
    under the final data-root name, so canonical rollback journal references
    continue to resolve after the transfer. Pre-existing data is never replaced.
    """

    source, manifest = _source_manifest(Path(backup))
    target = Path(destination)
    _plain_directory(target.parent, label="target parent")
    _absent(target, label="target profile")
    final_backup_root = target.parent / (target.name + _BACKUP_SUFFIX)
    _absent(final_backup_root, label="target backup history")

    stage = Path(
        tempfile.mkdtemp(prefix=".owner-transfer-import-", dir=target.parent)
    )
    stage_backup_root = stage.parent / (stage.name + _BACKUP_SUFFIX)
    backup_published = False
    profile_published = False
    try:
        data = source / "data"
        count = 0
        for entry in manifest["entries"]:
            relative = PurePosixPath(entry["path"])
            copied = stage.joinpath(*relative.parts)
            source_file = data.joinpath(*relative.parts)
            # Check every parent component, not merely the leaf file: a
            # symlink/reparse directory must not redirect an owner's export.
            parents = [data]
            for component in relative.parts[:-1]:
                parents.append(parents[-1] / component)
            before = []
            for parent in parents:
                _plain_directory(parent, label="transfer data parent")
                info = _safe_stat(parent, "transfer data parent")
                before.append((info.st_dev, info.st_ino))
            _stable_copy(
                source_file,
                copied,
                expected_size=entry["size"],
                expected_sha256=entry["sha256"],
            )
            for parent, identity in zip(parents, before):
                _plain_directory(parent, label="transfer data parent")
                info = _safe_stat(parent, "transfer data parent")
                if (info.st_dev, info.st_ino) != identity:
                    raise UserDataTransferError(
                        "transfer source directories changed during import"
                    )

        # This executes precisely the product's existing Settings/ACSDB upgrade
        # logic, including its checksum-guarded backup and crash recovery.
        migrated = Version2UpgradeCoordinator(UserDataLayout(stage)).run()
        if migrated.status not in {"upgraded", "already_current"}:
            raise UserDataTransferError("staged data migration did not finish")
        # If a stage upgrade created a rollback backup, retain it under the
        # eventual canonical backup root before exposing the profile.
        _plain_directory(stage_backup_root, label="staged backup history")
        _absent(target, label="target profile")
        _absent(final_backup_root, label="target backup history")
        _publish_directory_no_replace(stage_backup_root, final_backup_root)
        backup_published = True
        _publish_directory_no_replace(stage, target)
        profile_published = True
        _fsync_dir(target.parent)
        return migrated.status
    except (OSError, Version2UpgradeError, Version2UpgradeRecoveryError) as exc:
        raise UserDataTransferError("profile import failed; existing data was not replaced") from exc
    finally:
        if not profile_published:
            # Never touch an existing destination profile on failure. Staging
            # cleanup is narrowly scoped to our newly generated private paths.
            shutil.rmtree(stage, ignore_errors=True)
        if not backup_published:
            shutil.rmtree(stage_backup_root, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Accessible Chess: verified owner backup and safe transfer to an empty profile"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="Create an owner-data backup snapshot")
    export.add_argument("--root", type=Path, default=None, help="Existing user-data folder")
    imported = commands.add_parser("import", help="Restore to a NEW empty profile only")
    imported.add_argument("--backup", type=Path, required=True, help="Verified owner-transfer directory")
    imported.add_argument("--target", type=Path, required=True, help="Nonexistent new profile directory")
    args = parser.parse_args()
    try:
        if args.command == "export":
            layout = (
                UserDataLayout(args.root)
                if args.root is not None
                else UserDataLayout.from_environment()
            )
            result = {"status": "exported", "snapshot": str(export_owner_profile(layout))}
        else:
            result = {
                "status": "imported",
                "migration": import_owner_profile(args.backup, args.target),
            }
    except UserDataTransferError as exc:
        parser.exit(1, f"Transfer refused: {exc}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
