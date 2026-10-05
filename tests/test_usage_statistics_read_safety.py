from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from acs.usage_statistics import UsageStatisticsSnapshot, UsageStatisticsStore


def _payload(*, sessions_started: int = 1) -> str:
    return json.dumps(
        UsageStatisticsSnapshot(
            "install-1",
            sessions_started=sessions_started,
        ).as_dict(),
        sort_keys=True,
    )


class UsageStatisticsReadSafetyTests(unittest.TestCase):
    def test_missing_file_is_normal_empty_state_not_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = UsageStatisticsStore(Path(tmp) / "stats.json")
            self.assertEqual(store.load("install-1"), UsageStatisticsSnapshot("install-1"))
            self.assertFalse(store.recovered_invalid_data)

    def test_recursion_error_from_malformed_json_recovers_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            path.write_text(_payload(), encoding="utf-8")
            store = UsageStatisticsStore(path)
            with patch(
                "acs.usage_statistics.json.loads",
                side_effect=RecursionError("simulated deeply nested JSON"),
            ):
                recovered = store.load("install-1")
            self.assertEqual(recovered, UsageStatisticsSnapshot("install-1"))
            self.assertTrue(store.recovered_invalid_data)

    def test_path_substitution_between_inspection_and_open_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "stats.json"
            replacement = root / "replacement.json"
            original = root / "original.json"
            path.write_text(_payload(sessions_started=1), encoding="utf-8")
            replacement.write_text(_payload(sessions_started=9), encoding="utf-8")
            store = UsageStatisticsStore(path)
            real_open = os.open
            substituted = False

            def substitute_open(candidate: object, flags: int, *args: object, **kwargs: object) -> int:
                nonlocal substituted
                if Path(candidate) == path and not substituted:
                    substituted = True
                    os.replace(path, original)
                    os.replace(replacement, path)
                return real_open(candidate, flags, *args, **kwargs)

            with patch("acs.usage_statistics.os.open", side_effect=substitute_open):
                recovered = store.load("install-1")

            self.assertTrue(substituted)
            self.assertEqual(recovered, UsageStatisticsSnapshot("install-1"))
            self.assertTrue(store.recovered_invalid_data)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["sessions_started"],
                9,
            )

    @unittest.skipUnless(hasattr(os, "link"), "hard-link support is required")
    def test_hard_linked_statistics_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "stats.json"
            alias = root / "stats-alias.json"
            path.write_text(_payload(), encoding="utf-8")
            os.link(path, alias)
            store = UsageStatisticsStore(path)
            recovered = store.load("install-1")
            self.assertEqual(recovered, UsageStatisticsSnapshot("install-1"))
            self.assertTrue(store.recovered_invalid_data)

    def test_symlink_statistics_file_is_rejected_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target.json"
            path = root / "stats.json"
            target.write_text(_payload(sessions_started=7), encoding="utf-8")
            try:
                path.symlink_to(target)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            store = UsageStatisticsStore(path)
            recovered = store.load("install-1")
            self.assertEqual(recovered, UsageStatisticsSnapshot("install-1"))
            self.assertTrue(store.recovered_invalid_data)


if __name__ == "__main__":
    unittest.main()
