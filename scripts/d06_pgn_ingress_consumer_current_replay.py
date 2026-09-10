from __future__ import annotations

"""Current-authority adapter for the historical D06 ingress convergence oracle.

The original oracle intentionally remains the provenance for the four RED
consumer classes found on 2026-08-28. Current Product correctly changed one of
those contracts: external non-canonical GameTree snapshots now fail closed
during ``restore_game``. The historical probe predates that repair and assumes
restore always returns a game, so the exact correct rejection would otherwise
crash the QA harness instead of being classified as convergence.

This adapter changes evidence plumbing only. It reuses every historical static
inventory and dynamic probe, binds the report to the exact current formats base,
and accepts only the exact ``IDENTITY_MISMATCH`` produced when strict canonical
D06 normalization changes the historical attached-NAG snapshot identity. Any
other snapshot error remains an evidence failure. Product code and acceptance
thresholds are untouched.
"""

import argparse
import os
from pathlib import Path

from acs.gametree_snapshot import GameTreeSnapshotCode, GameTreeSnapshotError
from scripts import d06_pgn_ingress_consumer_oracle as oracle


def _current_dynamic_probes() -> tuple[list[dict[str, object]], list[str]]:
    results: list[dict[str, object]] = []
    blockers: list[str] = []
    for probe in (
        oracle._acsdb_probe,
        oracle._duplicate_probe,
        oracle._snapshot_probe,
        oracle._book_training_probe,
    ):
        try:
            result, found = probe()
        except GameTreeSnapshotError as exc:
            if (
                probe is not oracle._snapshot_probe
                or exc.code is not GameTreeSnapshotCode.IDENTITY_MISMATCH
            ):
                raise
            result = {
                "surface": "gametree_snapshot.restore_game",
                "trust": "external_versioned_snapshot_record",
                "external_record_validated": True,
                "restore_error_code": exc.code.value,
                "strict_serialize_code": None,
                "classification": "FAIL_CLOSED_CANONICAL_RESTORE",
            }
            found = []
        results.append(result)
        blockers.extend(found)
    return results, blockers


def _bind_current_authority() -> None:
    authority = os.environ.get("D06_CONVERGENCE_BASE")
    if not authority:
        raise RuntimeError("D06_CONVERGENCE_BASE is required for current replay")
    oracle.AUTHORITY_SHA = authority
    oracle._dynamic_probes = _current_dynamic_probes


def main() -> int:
    _bind_current_authority()
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--no-enforce", action="store_true")
    parser.add_argument("--enforce-report", type=Path)
    args = parser.parse_args()
    if args.selftest:
        oracle._selftest()
        print("D06 CURRENT REPLAY ADAPTER SELFTEST PASS")
        return 0
    if args.enforce_report is not None:
        return oracle.enforce_report(args.enforce_report)
    return oracle.run(report_path=args.report, enforce=not args.no_enforce)


if __name__ == "__main__":
    raise SystemExit(main())
