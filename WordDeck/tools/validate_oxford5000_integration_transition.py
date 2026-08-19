#!/usr/bin/env python3
"""Validate an Oxford 5000 QA handoff against the exact post-integration state.

Build/development-time only. This tool does not harvest vocabulary, translate, or make
linguistic judgements. It closes the deterministic gap between a QA-qualified handoff
and the canonical runtime change by proving that one coherent Work integration:

* activates exactly the Content-QA PASS rows and no other Oxford 5000 rows;
* preserves every pre-existing runtime row byte-for-byte at the lexical-data level;
* removes exactly the PASS rows from the authoritative unaccounted ledger;
* keeps REJECT/BLOCKED candidates fail-closed in the post-integration unaccounted tail;
* preserves stable IDs, source, POS, CEFR and the reviewed Ukrainian translation.

The pre/post runtime ledgers and unaccounted ledgers are expected to be artifacts from
validate_oxford5000_runtime_ledger.py for the respective GitHub checkpoints.
No network access is performed.
"""
from __future__ import annotations

import argparse
import csv
import tempfile
from pathlib import Path

import validate_oxford5000_automation_handoff as handoff

RUNTIME_REQUIRED = {
    "entry_id",
    "source",
    "part_of_speech",
    "level",
    "ukrainian",
    "status",
}
UNACCOUNTED_REQUIRED = {"entry_id", "source", "part_of_speech", "level"}


def read_tsv(path: Path, required_fields: set[str], label: str) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        if not fields:
            raise ValueError(f"{label} has no header")
        if any(not (field or "").strip() for field in fields):
            raise ValueError(f"{label} has a blank column name")
        if len(fields) != len(set(fields)):
            raise ValueError(f"{label} has duplicate column names")
        missing = sorted(required_fields - set(fields))
        if missing:
            raise ValueError(f"{label} is missing required columns: {', '.join(missing)}")
        rows: list[dict[str, str]] = []
        for number, row in enumerate(reader, start=1):
            if None in row:
                raise ValueError(f"{label} row {number} is ragged or has extra columns")
            rows.append({key: (value or "").strip() for key, value in row.items()})
        return rows


def lexical_identity(row: dict[str, str]) -> tuple[str, str, str]:
    return handoff.identity(
        row.get("source", ""),
        row.get("part_of_speech", ""),
        row.get("level", ""),
    )


def validate_ledger_rows(
    rows: list[dict[str, str]],
    label: str,
    *,
    require_verified_translation: bool,
) -> dict[str, dict[str, str]]:
    handoff.validate_unique(rows, label)
    by_id: dict[str, dict[str, str]] = {}
    for number, row in enumerate(rows, start=1):
        entry_id = handoff.require(row, "entry_id", label, number)
        if require_verified_translation:
            status = handoff.require(row, "status", label, number)
            if status != "verified":
                raise ValueError(
                    f"{label} row {number} has non-verified runtime status {status!r}"
                )
            handoff.require(row, "ukrainian", label, number)
        by_id[entry_id] = row
    return by_id


def lexical_payload(row: dict[str, str]) -> tuple[str, str, str, str, str]:
    return (
        row.get("source", "").strip(),
        row.get("part_of_speech", "").strip(),
        row.get("level", "").strip().upper(),
        row.get("ukrainian", "").strip(),
        row.get("status", "").strip(),
    )


def validate_transition(
    pre_unaccounted_rows: list[dict[str, str]],
    data_factory_rows: list[dict[str, str]],
    content_qa_rows: list[dict[str, str]],
    pre_runtime_rows: list[dict[str, str]],
    post_runtime_rows: list[dict[str, str]],
    post_unaccounted_rows: list[dict[str, str]],
) -> dict[str, str]:
    ready, unresolved, handoff_report = handoff.reconcile_handoff(
        pre_unaccounted_rows,
        data_factory_rows,
        content_qa_rows,
    )
    if not ready:
        raise ValueError(
            "Integration transition has no QA-PASS rows; there is nothing to activate"
        )

    pre_unaccounted = validate_ledger_rows(
        pre_unaccounted_rows,
        "pre-integration unaccounted ledger",
        require_verified_translation=False,
    )
    post_unaccounted = validate_ledger_rows(
        post_unaccounted_rows,
        "post-integration unaccounted ledger",
        require_verified_translation=False,
    )
    pre_runtime = validate_ledger_rows(
        pre_runtime_rows,
        "pre-integration runtime ledger",
        require_verified_translation=True,
    )
    post_runtime = validate_ledger_rows(
        post_runtime_rows,
        "post-integration runtime ledger",
        require_verified_translation=True,
    )

    ready_by_id = {row["entry_id"]: row for row in ready}
    unresolved_ids = {row["entry_id"] for row in unresolved}
    ready_ids = set(ready_by_id)
    pre_unaccounted_ids = set(pre_unaccounted)
    post_unaccounted_ids = set(post_unaccounted)
    pre_runtime_ids = set(pre_runtime)
    post_runtime_ids = set(post_runtime)

    overlap = pre_unaccounted_ids & pre_runtime_ids
    if overlap:
        sample = ", ".join(sorted(overlap)[:10])
        raise ValueError(
            "Pre-integration runtime and unaccounted ledgers overlap; "
            f"checkpoint evidence is inconsistent: {sample}"
        )

    expected_post_unaccounted = pre_unaccounted_ids - ready_ids
    if post_unaccounted_ids != expected_post_unaccounted:
        missing = sorted(expected_post_unaccounted - post_unaccounted_ids)
        unexpected = sorted(post_unaccounted_ids - expected_post_unaccounted)
        raise ValueError(
            "Post-integration unaccounted ledger is not the exact pre-ledger minus "
            f"QA-PASS rows; missing={missing[:10]!r}, unexpected={unexpected[:10]!r}"
        )

    expected_post_runtime = pre_runtime_ids | ready_ids
    if post_runtime_ids != expected_post_runtime:
        missing = sorted(expected_post_runtime - post_runtime_ids)
        unexpected = sorted(post_runtime_ids - expected_post_runtime)
        raise ValueError(
            "Post-integration runtime ledger is not the exact pre-runtime plus "
            f"QA-PASS rows; missing={missing[:10]!r}, unexpected={unexpected[:10]!r}"
        )

    for entry_id, before in pre_runtime.items():
        after = post_runtime[entry_id]
        if lexical_payload(after) != lexical_payload(before):
            raise ValueError(
                f"Pre-existing runtime row {entry_id!r} changed during lexical integration"
            )

    for entry_id, ready_row in ready_by_id.items():
        runtime_row = post_runtime[entry_id]
        expected_identity = lexical_identity(ready_row)
        actual_identity = lexical_identity(runtime_row)
        if actual_identity != expected_identity:
            raise ValueError(
                f"Activated QA-PASS row {entry_id!r} identity changed during integration: "
                f"{actual_identity!r} != {expected_identity!r}"
            )
        if runtime_row["ukrainian"].strip() != ready_row["ukrainian"].strip():
            raise ValueError(
                f"Activated QA-PASS row {entry_id!r} Ukrainian translation differs "
                "from Content-QA reviewed text"
            )
        if runtime_row["status"].strip() != "verified":
            raise ValueError(
                f"Activated QA-PASS row {entry_id!r} is not verified at runtime"
            )

    leaked_unresolved = unresolved_ids - post_unaccounted_ids
    if leaked_unresolved:
        raise ValueError(
            "REJECT/BLOCKED rows escaped the fail-closed unaccounted ledger: "
            + ", ".join(sorted(leaked_unresolved)[:10])
        )

    return {
        "data_factory_run_id": handoff_report["data_factory_run_id"],
        "content_qa_run_id": handoff_report["content_qa_run_id"],
        "pre_runtime_rows": str(len(pre_runtime_rows)),
        "post_runtime_rows": str(len(post_runtime_rows)),
        "pre_unaccounted_rows": str(len(pre_unaccounted_rows)),
        "post_unaccounted_rows": str(len(post_unaccounted_rows)),
        "qa_pass_activated": str(len(ready)),
        "qa_fail_closed": str(len(unresolved)),
        "runtime_delta": str(len(post_runtime_rows) - len(pre_runtime_rows)),
        "unaccounted_delta": str(len(pre_unaccounted_rows) - len(post_unaccounted_rows)),
        "transition_verdict": "PASS",
    }


def write_report(report: dict[str, str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["metric", "value"])
        writer.writerows(report.items())


def run_self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        entries = [
            ("alpha", "noun", "B2"),
            ("beta", "verb", "C1"),
            ("gamma", "adjective", "C1"),
        ]
        ids = {
            source: handoff.lexical_entry_id(source, pos, level)
            for source, pos, level in entries
        }
        pre_unaccounted = [
            {
                "entry_id": ids[source],
                "source": source,
                "part_of_speech": pos,
                "level": level,
            }
            for source, pos, level in entries
        ]
        data_factory = [
            {
                "data_factory_run_id": "df-transition-test",
                "entry_id": ids[source],
                "source": source,
                "part_of_speech": pos,
                "level": level,
                "official_source": "official-test-source",
                "source_check": f"source evidence for {source}",
                "ukrainian_candidate": f"candidate-{source}",
            }
            for source, pos, level in entries
        ]
        decisions = {
            "alpha": ("PASS", "альфа", "reviewed exact sense"),
            "beta": ("REJECT", "", "translation too broad"),
            "gamma": ("BLOCKED", "", "sense evidence incomplete"),
        }
        content_qa = []
        for source, pos, level in entries:
            decision, ukrainian, reason = decisions[source]
            content_qa.append(
                {
                    "content_qa_run_id": "qa-transition-test",
                    "data_factory_run_id": "df-transition-test",
                    "entry_id": ids[source],
                    "source": source,
                    "part_of_speech": pos,
                    "level": level,
                    "decision": decision,
                    "ukrainian": ukrainian,
                    "qa_reason": reason,
                }
            )

        existing_id = handoff.lexical_entry_id("existing", "noun", "C1")
        pre_runtime = [
            {
                "entry_id": existing_id,
                "source": "existing",
                "part_of_speech": "noun",
                "level": "C1",
                "ukrainian": "наявний",
                "status": "verified",
            }
        ]
        post_runtime = pre_runtime + [
            {
                "entry_id": ids["alpha"],
                "source": "alpha",
                "part_of_speech": "noun",
                "level": "B2",
                "ukrainian": "альфа",
                "status": "verified",
            }
        ]
        post_unaccounted = [
            row for row in pre_unaccounted if row["entry_id"] != ids["alpha"]
        ]

        report = validate_transition(
            pre_unaccounted,
            data_factory,
            content_qa,
            pre_runtime,
            post_runtime,
            post_unaccounted,
        )
        if report["qa_pass_activated"] != "1" or report["qa_fail_closed"] != "2":
            raise AssertionError("Valid transition self-test counts are wrong")
        if report["runtime_delta"] != "1" or report["unaccounted_delta"] != "1":
            raise AssertionError("Valid transition deltas are wrong")

        def expect_failure(
            broken_post_runtime: list[dict[str, str]],
            broken_post_unaccounted: list[dict[str, str]],
            needle: str,
        ) -> None:
            try:
                validate_transition(
                    pre_unaccounted,
                    data_factory,
                    content_qa,
                    pre_runtime,
                    broken_post_runtime,
                    broken_post_unaccounted,
                )
            except ValueError as exc:
                if needle.casefold() not in str(exc).casefold():
                    raise AssertionError(
                        f"Expected failure containing {needle!r}, got {exc!r}"
                    ) from exc
                return
            raise AssertionError(f"Expected fail-closed transition error for {needle!r}")

        expect_failure(pre_runtime, post_unaccounted, "exact pre-runtime plus")

        extra_id = handoff.lexical_entry_id("unauthorized", "noun", "C1")
        unauthorized_runtime = post_runtime + [
            {
                "entry_id": extra_id,
                "source": "unauthorized",
                "part_of_speech": "noun",
                "level": "C1",
                "ukrainian": "несанкціонований",
                "status": "verified",
            }
        ]
        expect_failure(unauthorized_runtime, post_unaccounted, "exact pre-runtime plus")

        mutated_runtime = [dict(row) for row in post_runtime]
        mutated_runtime[0]["ukrainian"] = "змінений"
        expect_failure(mutated_runtime, post_unaccounted, "changed during lexical integration")

        leaked_unaccounted = [
            row for row in post_unaccounted if row["entry_id"] != ids["beta"]
        ]
        expect_failure(post_runtime, leaked_unaccounted, "exact pre-ledger minus")

    print(
        "Oxford 5000 integration-transition self-test passed: exactly QA-PASS rows "
        "activate, existing runtime is immutable, and REJECT/BLOCKED rows stay fail-closed."
    )


def execute(args: argparse.Namespace) -> dict[str, str]:
    pre_unaccounted = read_tsv(
        args.pre_unaccounted,
        UNACCOUNTED_REQUIRED,
        "pre-integration unaccounted ledger",
    )
    data_factory = handoff.read_tsv(
        args.data_factory,
        handoff.DATA_FACTORY_REQUIRED,
        "Data Factory batch",
    )
    content_qa = handoff.read_tsv(
        args.content_qa,
        handoff.CONTENT_QA_REQUIRED,
        "Content QA batch",
    )
    pre_runtime = read_tsv(
        args.pre_runtime,
        RUNTIME_REQUIRED,
        "pre-integration runtime ledger",
    )
    post_runtime = read_tsv(
        args.post_runtime,
        RUNTIME_REQUIRED,
        "post-integration runtime ledger",
    )
    post_unaccounted = read_tsv(
        args.post_unaccounted,
        UNACCOUNTED_REQUIRED,
        "post-integration unaccounted ledger",
    )
    report = validate_transition(
        pre_unaccounted,
        data_factory,
        content_qa,
        pre_runtime,
        post_runtime,
        post_unaccounted,
    )
    if args.report is not None:
        write_report(report, args.report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-unaccounted", type=Path)
    parser.add_argument("--data-factory", type=Path)
    parser.add_argument("--content-qa", type=Path)
    parser.add_argument("--pre-runtime", type=Path)
    parser.add_argument("--post-runtime", type=Path)
    parser.add_argument("--post-unaccounted", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return 0
    required = {
        "--pre-unaccounted": args.pre_unaccounted,
        "--data-factory": args.data_factory,
        "--content-qa": args.content_qa,
        "--pre-runtime": args.pre_runtime,
        "--post-runtime": args.post_runtime,
        "--post-unaccounted": args.post_unaccounted,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        parser.error("required for transition validation: " + ", ".join(missing))
    report = execute(args)
    print(
        "Oxford 5000 integration transition validated: "
        f"qa_pass_activated={report['qa_pass_activated']}, "
        f"qa_fail_closed={report['qa_fail_closed']}, "
        f"runtime_delta={report['runtime_delta']}, "
        f"unaccounted_delta={report['unaccounted_delta']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
