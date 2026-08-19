#!/usr/bin/env python3
"""Strict provenance wrapper for the Oxford 5000 automation handoff.

This tool performs no harvesting and no linguistic judgement. It strengthens the
Data Factory -> Content QA -> Work integration gate by:

* rejecting malformed/ragged TSV input before semantic validation;
* rejecting blank or duplicate column names;
* requiring the same structural columns as the canonical handoff validator;
* running the canonical validate_oxford5000_automation_handoff checks;
* recording SHA-256 and byte size for all three immutable input files.

No network access is performed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import tempfile
from pathlib import Path

import validate_oxford5000_automation_handoff as handoff


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def strict_tsv_shape(path: Path, required_fields: set[str], label: str) -> tuple[int, int]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"{label} is empty and has no TSV header") from exc

        if not header:
            raise ValueError(f"{label} has an empty TSV header")
        stripped = [field.strip() for field in header]
        if any(not field for field in stripped):
            raise ValueError(f"{label} contains a blank TSV column name")
        if len(stripped) != len(set(stripped)):
            duplicates = sorted({field for field in stripped if stripped.count(field) > 1})
            raise ValueError(
                f"{label} contains duplicate TSV columns: {', '.join(duplicates)}"
            )
        missing = sorted(required_fields - set(stripped))
        if missing:
            raise ValueError(f"{label} is missing required columns: {', '.join(missing)}")

        row_count = 0
        for physical_line, row in enumerate(reader, start=2):
            if len(row) != len(header):
                raise ValueError(
                    f"{label} line {physical_line} is ragged: expected {len(header)} TSV "
                    f"fields, found {len(row)}"
                )
            row_count += 1
    return len(header), row_count


def execute_strict(
    unaccounted_path: Path,
    data_factory_path: Path,
    content_qa_path: Path,
    ready_path: Path | None = None,
    unresolved_path: Path | None = None,
    report_path: Path | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, str]]:
    shapes = {
        "unaccounted": strict_tsv_shape(
            unaccounted_path, handoff.UNACCOUNTED_REQUIRED, "unaccounted ledger"
        ),
        "data_factory": strict_tsv_shape(
            data_factory_path, handoff.DATA_FACTORY_REQUIRED, "Data Factory batch"
        ),
        "content_qa": strict_tsv_shape(
            content_qa_path, handoff.CONTENT_QA_REQUIRED, "Content QA batch"
        ),
    }

    ready, unresolved, report = handoff.execute(
        unaccounted_path,
        data_factory_path,
        content_qa_path,
        ready_path,
        unresolved_path,
        None,
    )

    evidence = dict(report)
    for key, path in (
        ("unaccounted", unaccounted_path),
        ("data_factory", data_factory_path),
        ("content_qa", content_qa_path),
    ):
        columns, rows = shapes[key]
        evidence[f"{key}_sha256"] = sha256_file(path)
        evidence[f"{key}_bytes"] = str(path.stat().st_size)
        evidence[f"{key}_columns"] = str(columns)
        evidence[f"{key}_physical_data_rows"] = str(rows)

    evidence["provenance_gate"] = "PASS"
    evidence["provenance_contract"] = (
        "strict_tsv+exact_unaccounted+stable_id+run_linkage+complete_content_qa+sha256"
    )

    if report_path is not None:
        handoff.write_report(evidence, report_path)
    return ready, unresolved, evidence


def _write_fixture(root: Path) -> tuple[Path, Path, Path]:
    source = "sample"
    pos = "noun"
    level = "C1"
    entry_id = handoff.lexical_entry_id(source, pos, level)

    unaccounted = root / "unaccounted.tsv"
    data_factory = root / "data.tsv"
    content_qa = root / "qa.tsv"

    handoff.write_tsv(
        [{
            "entry_id": entry_id,
            "source_index": "1",
            "source": source,
            "part_of_speech": pos,
            "level": level,
        }],
        unaccounted,
        ["entry_id", "source_index", "source", "part_of_speech", "level"],
    )
    handoff.write_tsv(
        [{
            "data_factory_run_id": "df-test",
            "entry_id": entry_id,
            "source": source,
            "part_of_speech": pos,
            "level": level,
            "official_source": "official-test-source",
            "source_check": "official row checked",
            "ukrainian_candidate": "приклад",
        }],
        data_factory,
        sorted(handoff.DATA_FACTORY_REQUIRED),
    )
    handoff.write_tsv(
        [{
            "content_qa_run_id": "qa-test",
            "data_factory_run_id": "df-test",
            "entry_id": entry_id,
            "source": source,
            "part_of_speech": pos,
            "level": level,
            "decision": "PASS",
            "ukrainian": "приклад",
            "qa_reason": "source and semantic QA passed",
        }],
        content_qa,
        sorted(handoff.CONTENT_QA_REQUIRED),
    )
    return unaccounted, data_factory, content_qa


def run_self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        unaccounted, data_factory, content_qa = _write_fixture(root)
        report_path = root / "report.tsv"
        ready, unresolved, report = execute_strict(
            unaccounted, data_factory, content_qa, report_path=report_path
        )
        if len(ready) != 1 or unresolved:
            raise AssertionError("Strict provenance self-test expected exactly one ready row")
        if report["provenance_gate"] != "PASS":
            raise AssertionError("Strict provenance self-test did not emit PASS")
        for key in ("unaccounted", "data_factory", "content_qa"):
            digest = report[f"{key}_sha256"]
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise AssertionError(f"Invalid SHA-256 evidence for {key}")

        ragged = root / "ragged.tsv"
        ragged.write_text("entry_id\tsource\tpart_of_speech\tlevel\nonly-three\tword\tnoun\n", encoding="utf-8")
        try:
            strict_tsv_shape(ragged, handoff.UNACCOUNTED_REQUIRED, "ragged test")
        except ValueError as exc:
            if "ragged" not in str(exc).casefold():
                raise
        else:
            raise AssertionError("Strict provenance validator accepted a ragged TSV row")

        duplicate_header = root / "duplicate-header.tsv"
        duplicate_header.write_text(
            "entry_id\tsource\tpart_of_speech\tlevel\tlevel\n"
            "x\tword\tnoun\tC1\tC1\n",
            encoding="utf-8",
        )
        try:
            strict_tsv_shape(
                duplicate_header, handoff.UNACCOUNTED_REQUIRED, "duplicate-header test"
            )
        except ValueError as exc:
            if "duplicate" not in str(exc).casefold():
                raise
        else:
            raise AssertionError("Strict provenance validator accepted duplicate columns")

    print(
        "Oxford 5000 strict handoff provenance self-test passed: malformed TSV is "
        "fail-closed and exact input SHA-256 evidence is deterministic."
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
    args = build_parser().parse_args()
    if args.self_test:
        run_self_test()
        return 0
    if args.unaccounted is None or args.data_factory is None or args.content_qa is None:
        raise SystemExit("--unaccounted, --data-factory and --content-qa are required")
    ready, unresolved, report = execute_strict(
        args.unaccounted,
        args.data_factory,
        args.content_qa,
        args.ready,
        args.unresolved,
        args.report,
    )
    print(
        "Oxford 5000 strict automation provenance validated: "
        f"ready={len(ready)}, fail_closed={len(unresolved)}, "
        f"projected_remaining={report['projected_remaining_after_ready_integration']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
