#!/usr/bin/env python3
"""Validate the append-only Data Factory -> Content QA -> Work handoff for Oxford 5000.

This build/development-time tool does not harvest words or judge translations. It only
proves that an automation batch is structurally safe to hand to the canonical Work
integrator:

* every Data Factory lexical identity is still present in the exact authoritative
  unaccounted ledger for the current WordDeck checkpoint;
* stable IDs, POS and CEFR are deterministic and match the authoritative identity;
* every candidate has exactly one Content QA verdict with intact provenance;
* only PASS rows with nonblank reviewed Ukrainian text are emitted as integration-ready;
* REJECT/BLOCKED rows remain fail-closed with an exact reason.

No network access is performed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import tempfile
from collections import Counter
from pathlib import Path

ALLOWED_LEVELS = {"B2", "C1"}
QA_DECISIONS = {"PASS", "REJECT", "BLOCKED"}

UNACCOUNTED_REQUIRED = {"entry_id", "source", "part_of_speech", "level"}
DATA_FACTORY_REQUIRED = {
    "data_factory_run_id",
    "entry_id",
    "source",
    "part_of_speech",
    "level",
    "official_source",
    "source_check",
    "ukrainian_candidate",
}
CONTENT_QA_REQUIRED = {
    "content_qa_run_id",
    "data_factory_run_id",
    "entry_id",
    "source",
    "part_of_speech",
    "level",
    "decision",
    "ukrainian",
    "qa_reason",
}


def lexical_entry_id(source: str, part_of_speech: str, level: str) -> str:
    identity = "\x1f".join(
        (
            source.strip().casefold(),
            part_of_speech.strip().casefold(),
            level.strip().casefold(),
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"ox5000-{digest}"


def identity(source: str, part_of_speech: str, level: str) -> tuple[str, str, str]:
    return (source.strip().casefold(), part_of_speech.strip().casefold(), level.strip().upper())


def read_tsv(path: Path, required_fields: set[str], label: str) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = set(reader.fieldnames or [])
        missing = sorted(required_fields - fields)
        if missing:
            raise ValueError(f"{label} is missing required columns: {', '.join(missing)}")
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def require(row: dict[str, str], field: str, label: str, row_number: int) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise ValueError(f"{label} row {row_number} has blank required field {field!r}")
    return value


def validate_level(level: str, label: str, row_number: int) -> str:
    normalized = level.strip().upper()
    if normalized not in ALLOWED_LEVELS:
        raise ValueError(
            f"{label} row {row_number} has unsupported CEFR {level!r}; expected B2 or C1"
        )
    return normalized


def validate_unique(rows: list[dict[str, str]], label: str) -> None:
    ids: set[str] = set()
    identities: set[tuple[str, str, str]] = set()
    for number, row in enumerate(rows, start=1):
        entry_id = require(row, "entry_id", label, number)
        source = require(row, "source", label, number)
        pos = require(row, "part_of_speech", label, number)
        level = validate_level(require(row, "level", label, number), label, number)
        lexical = identity(source, pos, level)
        if entry_id in ids:
            raise ValueError(f"{label} contains duplicate entry_id {entry_id!r}")
        if lexical in identities:
            raise ValueError(f"{label} contains duplicate lexical identity {lexical!r}")
        expected_id = lexical_entry_id(source, pos, level)
        if entry_id != expected_id:
            raise ValueError(
                f"{label} row {number} stable ID mismatch for {source!r}/{pos}/{level}: "
                f"{entry_id!r} != {expected_id!r}"
            )
        ids.add(entry_id)
        identities.add(lexical)


def build_unaccounted_index(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    validate_unique(rows, "unaccounted ledger")
    return {row["entry_id"]: row for row in rows}


def validate_data_factory(
    rows: list[dict[str, str]],
    unaccounted: dict[str, dict[str, str]],
) -> tuple[str, dict[str, dict[str, str]]]:
    if not rows:
        raise ValueError("Data Factory batch is empty")
    validate_unique(rows, "Data Factory batch")

    run_ids: set[str] = set()
    by_id: dict[str, dict[str, str]] = {}
    for number, row in enumerate(rows, start=1):
        run_id = require(row, "data_factory_run_id", "Data Factory batch", number)
        official_source = require(row, "official_source", "Data Factory batch", number)
        source_check = require(row, "source_check", "Data Factory batch", number)
        ukrainian_candidate = require(
            row, "ukrainian_candidate", "Data Factory batch", number
        )
        _ = official_source, source_check, ukrainian_candidate
        run_ids.add(run_id)

        entry_id = row["entry_id"]
        authoritative = unaccounted.get(entry_id)
        if authoritative is None:
            raise ValueError(
                f"Data Factory row {number} {entry_id!r} is not in the exact current "
                "Oxford 5000 unaccounted ledger"
            )
        candidate_identity = identity(row["source"], row["part_of_speech"], row["level"])
        authoritative_identity = identity(
            authoritative["source"],
            authoritative["part_of_speech"],
            authoritative["level"],
        )
        if candidate_identity != authoritative_identity:
            raise ValueError(
                f"Data Factory row {number} identity disagrees with authoritative "
                f"unaccounted row: {candidate_identity!r} != {authoritative_identity!r}"
            )
        by_id[entry_id] = row

    if len(run_ids) != 1:
        raise ValueError(
            "A single handoff must contain exactly one Data Factory run ID; "
            f"found {sorted(run_ids)!r}"
        )
    return next(iter(run_ids)), by_id


def validate_content_qa(
    rows: list[dict[str, str]],
    data_factory_run_id: str,
    candidates: dict[str, dict[str, str]],
) -> tuple[str, dict[str, dict[str, str]]]:
    if not rows:
        raise ValueError("Content QA batch is empty")

    qa_run_ids: set[str] = set()
    seen_ids: set[str] = set()
    by_id: dict[str, dict[str, str]] = {}
    for number, row in enumerate(rows, start=1):
        content_qa_run_id = require(row, "content_qa_run_id", "Content QA batch", number)
        qa_factory_run_id = require(
            row, "data_factory_run_id", "Content QA batch", number
        )
        if qa_factory_run_id != data_factory_run_id:
            raise ValueError(
                f"Content QA row {number} references Data Factory run "
                f"{qa_factory_run_id!r}, expected {data_factory_run_id!r}"
            )
        qa_run_ids.add(content_qa_run_id)

        entry_id = require(row, "entry_id", "Content QA batch", number)
        if entry_id in seen_ids:
            raise ValueError(f"Content QA contains duplicate entry_id {entry_id!r}")
        candidate = candidates.get(entry_id)
        if candidate is None:
            raise ValueError(
                f"Content QA row {number} {entry_id!r} has no matching Data Factory candidate"
            )

        source = require(row, "source", "Content QA batch", number)
        pos = require(row, "part_of_speech", "Content QA batch", number)
        level = validate_level(
            require(row, "level", "Content QA batch", number),
            "Content QA batch",
            number,
        )
        if lexical_entry_id(source, pos, level) != entry_id:
            raise ValueError(
                f"Content QA row {number} stable ID does not match its lexical identity"
            )
        if identity(source, pos, level) != identity(
            candidate["source"], candidate["part_of_speech"], candidate["level"]
        ):
            raise ValueError(
                f"Content QA row {number} lexical identity does not match Data Factory"
            )

        decision = require(row, "decision", "Content QA batch", number).upper()
        if decision not in QA_DECISIONS:
            raise ValueError(
                f"Content QA row {number} has unsupported decision {decision!r}; "
                "expected PASS, REJECT or BLOCKED"
            )
        qa_reason = require(row, "qa_reason", "Content QA batch", number)
        ukrainian = (row.get("ukrainian") or "").strip()
        if decision == "PASS" and not ukrainian:
            raise ValueError(
                f"Content QA row {number} PASS has blank reviewed Ukrainian translation"
            )
        _ = qa_reason

        normalized = dict(row)
        normalized["decision"] = decision
        normalized["level"] = level
        normalized["ukrainian"] = ukrainian
        by_id[entry_id] = normalized
        seen_ids.add(entry_id)

    missing_qa = sorted(set(candidates) - seen_ids)
    if missing_qa:
        raise ValueError(
            "Content QA does not cover every Data Factory candidate; missing entry IDs: "
            + ", ".join(missing_qa[:25])
            + ("" if len(missing_qa) <= 25 else f"; plus {len(missing_qa) - 25} more")
        )
    if len(qa_run_ids) != 1:
        raise ValueError(
            "A single handoff must contain exactly one Content QA run ID; "
            f"found {sorted(qa_run_ids)!r}"
        )
    return next(iter(qa_run_ids)), by_id


def source_order(row: dict[str, str], fallback: int) -> tuple[int, int]:
    raw = (row.get("source_index") or "").strip()
    try:
        return (0, int(raw))
    except ValueError:
        return (1, fallback)


def reconcile_handoff(
    unaccounted_rows: list[dict[str, str]],
    data_factory_rows: list[dict[str, str]],
    content_qa_rows: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, str]]:
    unaccounted = build_unaccounted_index(unaccounted_rows)
    data_factory_run_id, candidates = validate_data_factory(data_factory_rows, unaccounted)
    content_qa_run_id, qa_rows = validate_content_qa(
        content_qa_rows, data_factory_run_id, candidates
    )

    ready: list[dict[str, str]] = []
    unresolved: list[dict[str, str]] = []
    candidate_order = {row["entry_id"]: index for index, row in enumerate(data_factory_rows)}
    ordered_ids = sorted(
        candidates,
        key=lambda entry_id: source_order(
            unaccounted[entry_id],
            candidate_order[entry_id],
        ),
    )
    for entry_id in ordered_ids:
        candidate = candidates[entry_id]
        qa = qa_rows[entry_id]
        authoritative = unaccounted[entry_id]
        decision = qa["decision"]
        if decision == "PASS":
            ready.append(
                {
                    "entry_id": entry_id,
                    "source": authoritative["source"].strip(),
                    "part_of_speech": authoritative["part_of_speech"].strip(),
                    "level": authoritative["level"].strip().upper(),
                    "official_source": candidate["official_source"].strip(),
                    "status": "verified",
                    "ukrainian": qa["ukrainian"].strip(),
                    "source_check": candidate["source_check"].strip(),
                    "data_factory_run_id": data_factory_run_id,
                    "content_qa_run_id": content_qa_run_id,
                    "qa_reason": qa["qa_reason"].strip(),
                }
            )
        else:
            unresolved.append(
                {
                    "entry_id": entry_id,
                    "source": authoritative["source"].strip(),
                    "part_of_speech": authoritative["part_of_speech"].strip(),
                    "level": authoritative["level"].strip().upper(),
                    "status": "qa_rejected" if decision == "REJECT" else "qa_blocked",
                    "reason": qa["qa_reason"].strip(),
                    "ukrainian_candidate": candidate["ukrainian_candidate"].strip(),
                    "data_factory_run_id": data_factory_run_id,
                    "content_qa_run_id": content_qa_run_id,
                }
            )

    stats = Counter(row["decision"] for row in qa_rows.values())
    report = {
        "data_factory_run_id": data_factory_run_id,
        "content_qa_run_id": content_qa_run_id,
        "unaccounted_rows_at_input": str(len(unaccounted_rows)),
        "candidate_rows": str(len(data_factory_rows)),
        "qa_rows": str(len(content_qa_rows)),
        "qa_pass": str(stats["PASS"]),
        "qa_reject": str(stats["REJECT"]),
        "qa_blocked": str(stats["BLOCKED"]),
        "integration_ready": str(len(ready)),
        "fail_closed": str(len(unresolved)),
        "projected_remaining_after_ready_integration": str(
            len(unaccounted_rows) - len(ready)
        ),
    }
    return ready, unresolved, report


def write_tsv(rows: list[dict[str, str]], path: Path, fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            delimiter="\t",
            fieldnames=fields,
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_report(report: dict[str, str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["metric", "value"])
        writer.writerows(report.items())


def execute(
    unaccounted_path: Path,
    data_factory_path: Path,
    content_qa_path: Path,
    ready_path: Path | None = None,
    unresolved_path: Path | None = None,
    report_path: Path | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, str]]:
    unaccounted_rows = read_tsv(
        unaccounted_path, UNACCOUNTED_REQUIRED, "unaccounted ledger"
    )
    data_factory_rows = read_tsv(
        data_factory_path, DATA_FACTORY_REQUIRED, "Data Factory batch"
    )
    content_qa_rows = read_tsv(
        content_qa_path, CONTENT_QA_REQUIRED, "Content QA batch"
    )
    ready, unresolved, report = reconcile_handoff(
        unaccounted_rows, data_factory_rows, content_qa_rows
    )

    if ready_path is not None:
        write_tsv(
            ready,
            ready_path,
            [
                "entry_id",
                "source",
                "part_of_speech",
                "level",
                "official_source",
                "status",
                "ukrainian",
                "source_check",
                "data_factory_run_id",
                "content_qa_run_id",
                "qa_reason",
            ],
        )
    if unresolved_path is not None:
        write_tsv(
            unresolved,
            unresolved_path,
            [
                "entry_id",
                "source",
                "part_of_speech",
                "level",
                "status",
                "reason",
                "ukrainian_candidate",
                "data_factory_run_id",
                "content_qa_run_id",
            ],
        )
    if report_path is not None:
        write_report(report, report_path)
    return ready, unresolved, report


def write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    write_tsv(rows, path, fields)


def run_self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        entries = [
            ("alpha", "noun", "B2"),
            ("beta", "verb", "C1"),
            ("gamma", "adjective", "C1"),
        ]
        unaccounted_rows = []
        data_rows = []
        qa_rows = []
        for index, (source, pos, level) in enumerate(entries, start=1):
            entry_id = lexical_entry_id(source, pos, level)
            unaccounted_rows.append(
                {
                    "entry_id": entry_id,
                    "source_index": str(index),
                    "source": source,
                    "part_of_speech": pos,
                    "level": level,
                }
            )
            data_rows.append(
                {
                    "data_factory_run_id": "df-20260819T2000",
                    "entry_id": entry_id,
                    "source": source,
                    "part_of_speech": pos,
                    "level": level,
                    "official_source": "official-test-source",
                    "source_check": f"authoritative test evidence for {source}",
                    "ukrainian_candidate": f"кандидат-{source}",
                }
            )
        decisions = [
            ("PASS", "альфа", "semantic and source QA passed"),
            ("REJECT", "", "translation is too broad"),
            ("BLOCKED", "", "sense requires manual source resolution"),
        ]
        for (source, pos, level), (decision, ukrainian, reason) in zip(
            entries, decisions, strict=True
        ):
            qa_rows.append(
                {
                    "content_qa_run_id": "qa-20260819T2010",
                    "data_factory_run_id": "df-20260819T2000",
                    "entry_id": lexical_entry_id(source, pos, level),
                    "source": source,
                    "part_of_speech": pos,
                    "level": level,
                    "decision": decision,
                    "ukrainian": ukrainian,
                    "qa_reason": reason,
                }
            )

        unaccounted = root / "unaccounted.tsv"
        data_factory = root / "data.tsv"
        content_qa = root / "qa.tsv"
        ready_path = root / "ready.tsv"
        unresolved_path = root / "unresolved.tsv"
        report_path = root / "report.tsv"

        write_rows(
            unaccounted,
            ["entry_id", "source_index", "source", "part_of_speech", "level"],
            unaccounted_rows,
        )
        write_rows(data_factory, sorted(DATA_FACTORY_REQUIRED), data_rows)
        write_rows(content_qa, sorted(CONTENT_QA_REQUIRED), qa_rows)

        ready, unresolved, report = execute(
            unaccounted,
            data_factory,
            content_qa,
            ready_path,
            unresolved_path,
            report_path,
        )
        if len(ready) != 1 or len(unresolved) != 2:
            raise AssertionError("Self-test expected 1 ready and 2 fail-closed rows")
        if report["projected_remaining_after_ready_integration"] != "2":
            raise AssertionError("Self-test projected remaining count is wrong")
        if ready[0]["status"] != "verified" or ready[0]["ukrainian"] != "альфа":
            raise AssertionError("Self-test PASS row was not emitted correctly")
        if {row["status"] for row in unresolved} != {"qa_rejected", "qa_blocked"}:
            raise AssertionError("Self-test fail-closed statuses are wrong")
        if lexical_entry_id("deployment", "noun", "C1") != "ox5000-a2e2cc33789e9d3a823a":
            raise AssertionError("Stable lexical ID algorithm drifted from WordDeck canonical ID")

        def expect_failure(
            broken_data: list[dict[str, str]],
            broken_qa: list[dict[str, str]],
            needle: str,
        ) -> None:
            try:
                reconcile_handoff(unaccounted_rows, broken_data, broken_qa)
            except ValueError as exc:
                if needle.casefold() not in str(exc).casefold():
                    raise AssertionError(
                        f"Expected failure containing {needle!r}, got {exc!r}"
                    ) from exc
                return
            raise AssertionError(f"Expected fail-closed validation for {needle!r}")

        outside = [dict(row) for row in data_rows]
        outside[0] = dict(outside[0])
        outside[0]["source"] = "delta"
        outside[0]["entry_id"] = lexical_entry_id("delta", "noun", "B2")
        expect_failure(outside, qa_rows, "not in the exact current")

        bad_id = [dict(row) for row in data_rows]
        bad_id[0] = dict(bad_id[0])
        bad_id[0]["entry_id"] = "ox5000-deadbeefdeadbeefdead"
        expect_failure(bad_id, qa_rows, "stable ID mismatch")

        bad_provenance = [dict(row) for row in qa_rows]
        bad_provenance[0] = dict(bad_provenance[0])
        bad_provenance[0]["data_factory_run_id"] = "wrong-run"
        expect_failure(data_rows, bad_provenance, "references Data Factory run")

        blank_pass = [dict(row) for row in qa_rows]
        blank_pass[0] = dict(blank_pass[0])
        blank_pass[0]["ukrainian"] = ""
        expect_failure(data_rows, blank_pass, "PASS has blank")

        missing_qa = qa_rows[:-1]
        expect_failure(data_rows, missing_qa, "does not cover every")

        duplicate = data_rows + [dict(data_rows[0])]
        expect_failure(duplicate, qa_rows, "duplicate entry_id")

    print(
        "Oxford 5000 automation handoff self-test passed: provenance, exact-unaccounted "
        "membership, stable IDs, PASS-only integration and fail-closed QA paths are deterministic."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unaccounted", type=Path)
    parser.add_argument("--data-factory", type=Path)
    parser.add_argument("--content-qa", type=Path)
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--unresolved", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return 0
    if args.unaccounted is None or args.data_factory is None or args.content_qa is None:
        parser.error("--unaccounted, --data-factory and --content-qa are required")
    ready, unresolved, report = execute(
        args.unaccounted,
        args.data_factory,
        args.content_qa,
        args.ready,
        args.unresolved,
        args.report,
    )
    print(
        "Oxford 5000 automation handoff validated: "
        f"candidates={report['candidate_rows']}, integration_ready={len(ready)}, "
        f"fail_closed={len(unresolved)}, "
        f"projected_remaining={report['projected_remaining_after_ready_integration']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
