from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.version2_upgrade_base import (
    UserDataLayout,
    Version2UpgradeCoordinator,
    _atomic_bytes,
    _atomic_json,
)


class V2UpgradeAtomicBytesCurrentTests(unittest.TestCase):
    def test_atomic_bytes_publishes_and_replaces_exact_payload_without_residue(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "state.bin"
            first = b"first-current-apex-payload\x00\r\n\x1a"
            second = b"second-current-apex-payload\xff\x00"

            _atomic_bytes(target, first)
            self.assertEqual(target.read_bytes(), first)

            _atomic_bytes(target, second)
            self.assertEqual(target.read_bytes(), second)
            self.assertEqual(
                [path.name for path in root.iterdir()],
                [target.name],
            )

    def test_atomic_json_round_trips_through_production_writer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "state.json"
            payload = {
                "schema_version": 1,
                "phase": "prepared",
                "nested": {"value": "тест"},
            }

            _atomic_json(target, payload)

            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")),
                payload,
            )

    def test_phase_journal_uses_atomic_writer_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "AccessibleChess"
            coordinator = Version2UpgradeCoordinator(UserDataLayout(root))
            coordinator._ensure_roots()
            upgrade_id = "v2-20261004T072627Z-atomicreg"

            coordinator._write_phase(
                upgrade_id,
                "prepared",
                recovered=False,
                notify=False,
            )

            self.assertTrue(coordinator.layout.journal_path.is_file())
            journal = coordinator._journal()
            self.assertEqual(journal["upgrade_id"], upgrade_id)
            self.assertEqual(journal["backup_name"], upgrade_id)
            self.assertEqual(journal["phase"], "prepared")
            self.assertEqual(journal["owned_states"], {})


if __name__ == "__main__":
    unittest.main()
