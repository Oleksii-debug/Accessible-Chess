from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from acs.v1_runtime_bridge import (
    V1RuntimeBridgeCoordinator,
    V1RuntimeBridgeError,
)
from acs.version2_upgrade import UserDataLayout


class V1RuntimeBridgeBackupPathSecurityTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, UserDataLayout]:
        install = root / "installed"
        data = install / "data"
        data.mkdir(parents=True)
        executable = install / "AccessibleChess.exe"
        executable.write_bytes(b"MZ-test-fixture")
        (data / "settings.json").write_text(
            json.dumps({"language": "en", "volume": 22}) + "\n",
            encoding="utf-8",
        )
        return executable, UserDataLayout(
            root / "localappdata" / "AccessibleChess"
        )

    @staticmethod
    def _poison_target(layout: UserDataLayout, poisoned_name: str) -> Path:
        if os.name == "nt" or poisoned_name.startswith("../"):
            return layout.backup_root.parent / "outside-backup"
        return layout.backup_root / poisoned_name

    def _copy_poisoned_backup(
        self,
        layout: UserDataLayout,
        record: dict[str, object],
        poisoned_name: str,
        *,
        target: Path | None = None,
    ) -> Path:
        original = layout.backup_root / str(record["backup_name"])
        destination = target or self._poison_target(layout, poisoned_name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(original, destination)
        manifest_path = destination / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["backup_name"] = poisoned_name
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination

    def test_interrupted_journal_rejects_posix_and_windows_traversal_backup_names(self) -> None:
        for poisoned_name in ("../outside-backup", "..\\outside-backup"):
            with self.subTest(poisoned_name=poisoned_name), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                executable, layout = self._fixture(root)

                def crash(phase: str) -> None:
                    if phase == "prepared":
                        raise RuntimeError("stop after durable prepare")

                with self.assertRaises(RuntimeError):
                    V1RuntimeBridgeCoordinator(
                        layout, executable, phase_hook=crash
                    ).run()

                journal_path = layout.backup_root / ".v1-runtime-bridge-state.json"
                journal = json.loads(journal_path.read_text(encoding="utf-8"))
                self._copy_poisoned_backup(layout, journal, poisoned_name)
                journal["backup_name"] = poisoned_name
                journal_path.write_text(
                    json.dumps(journal, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8",
                )

                with self.assertRaises(V1RuntimeBridgeError):
                    V1RuntimeBridgeCoordinator(layout, executable).run()

                self.assertFalse(layout.settings_path.exists())

    def test_interrupted_journal_rejects_valid_looking_backup_for_wrong_bridge_id(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, layout = self._fixture(root)

            def crash(phase: str) -> None:
                if phase == "prepared":
                    raise RuntimeError("stop after durable prepare")

            with self.assertRaises(RuntimeError):
                V1RuntimeBridgeCoordinator(
                    layout, executable, phase_hook=crash
                ).run()

            journal_path = layout.backup_root / ".v1-runtime-bridge-state.json"
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            poisoned_name = "v1-20000101T000000Z-deadbeef-legacy-runtime"
            self.assertNotEqual(poisoned_name, journal["backup_name"])
            self._copy_poisoned_backup(
                layout,
                journal,
                poisoned_name,
                target=layout.backup_root / poisoned_name,
            )
            journal["backup_name"] = poisoned_name
            journal_path.write_text(
                json.dumps(journal, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(V1RuntimeBridgeError):
                V1RuntimeBridgeCoordinator(layout, executable).run()

            self.assertFalse(layout.settings_path.exists())

    def test_completion_marker_rejects_traversal_backup_name(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            executable, layout = self._fixture(root)
            V1RuntimeBridgeCoordinator(layout, executable).run()

            marker_path = layout.backup_root / ".v1-runtime-bridge-completed.json"
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            poisoned_name = "../outside-backup"
            self._copy_poisoned_backup(layout, marker, poisoned_name)
            marker["backup_name"] = poisoned_name
            marker_path.write_text(
                json.dumps(marker, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(V1RuntimeBridgeError):
                V1RuntimeBridgeCoordinator(layout, executable).run()


if __name__ == "__main__":
    unittest.main()
