from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.version2_upgrade_base import (
    UserDataLayout,
    Version2UpgradeCoordinator,
    _atomic_bytes,
)


class V2UpgradeAtomicBytesCurrentTests(unittest.TestCase):
    def test_atomic_bytes_publishes_and_replaces_exact_payload_without_residue(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "state.json"
            first = b"first-current-apex-payload"
            second = b"second-current-apex-payload"

            _atomic_bytes(target, first)
            self.assertEqual(first, target.read_bytes())
            _atomic_bytes(target, second)
            self.assertEqual(second, target.read_bytes())
            self.assertEqual(
                [],
                [
                    path.name
                    for path in root.iterdir()
                    if path.name != target.name
                ],
            )

    def test_phase_journal_uses_production_atomic_writer_and_round_trips(self):
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
            raw = json.loads(
                coordinator.layout.journal_path.read_text(encoding="utf-8")
            )
            self.assertEqual(upgrade_id, raw["upgrade_id"])
            self.assertEqual("prepared", raw["phase"])
            self.assertEqual({}, raw["owned_states"])
            self.assertEqual(upgrade_id, coordinator._journal()["upgrade_id"])


if __name__ == "__main__":
    unittest.main()
