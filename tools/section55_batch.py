#!/usr/bin/env python3
"""Section 55 provisional local batch queue: bounded, replay-safe, no network.

This is a local preparation helper, not a certified Braille production line.
The source of truth is each already-published quality-report.json reverified
against original files. The journal is a progress cache, not a print license.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acs.chess_braille_bundle import verify_provisional_bundle
from acs.chess_braille_factory import BrailleFactoryError
from tools.section55_braille_pef import run as prepare_one

MAX_QUEUE_BYTES = 128 * 1024
MAX_JOURNAL_BYTES = 128 * 1024
MAX_QUEUE_JOBS = 32
MAX_JOBS_PER_RUN = 4
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,59}$")
_COMMON = {
    "id", "book_json", "source_file", "book_title", "table_file",
    "table_version", "language", "device_model", "cells_per_line",
    "lines_per_page", "rights_confirmed", "rights_basis", "emit_brf",
}
_REQUIRED = {
    "id", "table_file", "table_version", "language", "device_model",
    "cells_per_line", "lines_per_page", "rights_confirmed", "rights_basis",
    "emit_brf",
}


def _read_bounded(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise BrailleFactoryError("Queue source is missing, nonregular or symlinked")
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise BrailleFactoryError("Queue input exceeds the local byte limit")
    return raw


def _validated_jobs(raw: bytes) -> tuple[str, list[dict]]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrailleFactoryError("Invalid UTF-8 queue specification") from exc
    if type(payload) is not dict or set(payload) != {"schema_version", "jobs"}:
        raise BrailleFactoryError("Unexpected local batch document format")
    if payload["schema_version"] != 1 or type(payload["jobs"]) is not list:
        raise BrailleFactoryError("Unsupported batch queue version")
    jobs = payload["jobs"]
    if not 1 <= len(jobs) <= MAX_QUEUE_JOBS:
        raise BrailleFactoryError("Local batch must contain 1 to 32 entries")
    seen: set[str] = set()
    for job in jobs:
        if type(job) is not dict or not _REQUIRED <= set(job) <= _COMMON:
            raise BrailleFactoryError("Unknown or missing batch job fields")
        key = job["id"]
        if type(key) is not str or not _ID.fullmatch(key) or key in seen:
            raise BrailleFactoryError("Batch IDs must be unique safe identifiers")
        seen.add(key)
        if (job.get("book_json") is None) == (job.get("source_file") is None):
            raise BrailleFactoryError("Each job requires exactly one book source")
        for field in ("table_file", "table_version", "language", "device_model", "rights_basis"):
            if type(job[field]) is not str or not job[field].strip():
                raise BrailleFactoryError("Required batch string field is empty")
        for field in ("book_json", "source_file"):
            if field in job and job[field] is not None:
                if type(job[field]) is not str or not job[field].strip():
                    raise BrailleFactoryError("Local book path must be text")
        if job.get("book_title") is not None and (
            type(job["book_title"]) is not str or not job["book_title"].strip()
        ):
            raise BrailleFactoryError("Batch source title must be meaningful text")
        if job["rights_confirmed"] is not True or type(job["emit_brf"]) is not bool:
            raise BrailleFactoryError("Explicit rights and output-format flags are required")
        if (type(job["cells_per_line"]) is not int or
                type(job["lines_per_page"]) is not int):
            raise BrailleFactoryError("Page dimensions must be integers")
    return sha256(raw).hexdigest(), jobs


def _atomic_journal(path: Path, data: dict) -> None:
    encoded = (json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_JOURNAL_BYTES:
        raise BrailleFactoryError("Local batch journal exceeds budget")
    fd, temp_name = tempfile.mkstemp(prefix=".section55-journal-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _load_journal(path: Path, queue_sha: str) -> dict:
    if not path.exists():
        return {"schema_version": 1, "queue_sha256": queue_sha, "completed": {}}
    raw = _read_bounded(path, MAX_JOURNAL_BYTES)
    try:
        journal = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrailleFactoryError("Malformed persisted batch journal") from exc
    if (type(journal) is not dict or set(journal) != {
            "schema_version", "queue_sha256", "completed"}
            or journal["schema_version"] != 1 or
            journal["queue_sha256"] != queue_sha or
            type(journal["completed"]) is not dict):
        raise BrailleFactoryError("Batch journal refers to another immutable queue revision")
    return journal


def _args_for(job: dict, output: Path) -> argparse.Namespace:
    table = Path(job["table_file"])
    return argparse.Namespace(
        book_json=Path(job["book_json"]) if job.get("book_json") else None,
        source_file=Path(job["source_file"]) if job.get("source_file") else None,
        book_title=job.get("book_title"),
        table_file=table,
        table_id=str(table),
        table_version=job["table_version"],
        language=job["language"],
        device_model=job["device_model"],
        cells_per_line=job["cells_per_line"],
        lines_per_page=job["lines_per_page"],
        rights_confirmed=True,
        rights_basis=job["rights_basis"],
        output_folder=output,
        emit_brf=job["emit_brf"],
        display_table="en-us-brf.dis" if job["emit_brf"] else None,
    )


def process_batch(queue_file: Path, output_root: Path, *, max_per_run: int) -> tuple[int, int]:
    if type(max_per_run) is not int or not 1 <= max_per_run <= MAX_JOBS_PER_RUN:
        raise BrailleFactoryError("Local batch iteration budget must be 1 to 4")
    if output_root.is_symlink() or not output_root.is_dir():
        raise BrailleFactoryError("Output root must be an existing regular directory")
    queue_sha, jobs = _validated_jobs(_read_bounded(queue_file, MAX_QUEUE_BYTES))
    journal_path = output_root / ".section55-batch-journal.json"
    lock_path = output_root / ".section55-batch.lock"
    # Exclusive lock refuses concurrent workers. A stale lock following a
    # crash is deliberately NOT ignored or stolen without operator review.
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise BrailleFactoryError("Another worker or stale batch lock requires review") from exc
    try:
        os.close(fd)
        journal = _load_journal(journal_path, queue_sha)
        expected_ids = {job["id"] for job in jobs}
        existing_ids = set(journal["completed"])
        if not existing_ids <= expected_ids:
            raise BrailleFactoryError("Batch journal contains job IDs outside the pinned queue")
        for entry in journal["completed"].values():
            if (type(entry) is not dict or set(entry) != {
                    "source_sha256", "pef_sha256", "brf_sha256"}
                    or any(type(entry[key]) is not str or
                           not re.fullmatch(r"[0-9a-f]{64}", entry[key])
                           for key in ("source_sha256", "pef_sha256"))
                    or (entry["brf_sha256"] is not None and (
                        type(entry["brf_sha256"]) is not str or
                        not re.fullmatch(r"[0-9a-f]{64}", entry["brf_sha256"])))):
                raise BrailleFactoryError("Batch journal contains malformed completion evidence")
        processed = 0
        for job in jobs:
            key = job["id"]
            args = _args_for(job, output_root / key)
            original = args.book_json if args.book_json is not None else args.source_file
            if args.output_folder.exists():
                # Crash recovery after publication but before journal write.
                # The entire original-source, PEF, BRF and table inventory
                # must still pass. No overwrite of a pre-existing package.
                check = verify_provisional_bundle(
                    args.output_folder, original, table_file=args.table_file,
                )
                current = {
                    "source_sha256": check.source_sha256,
                    "pef_sha256": check.output_pef_sha256,
                    "brf_sha256": check.output_brf_sha256,
                }
                prior = journal["completed"].get(key)
                if prior is not None and prior != current:
                    raise BrailleFactoryError("Completed batch package differs from journal")
                journal["completed"][key] = current
                _atomic_journal(journal_path, journal)
                continue
            if key in journal["completed"]:
                raise BrailleFactoryError("Journal says complete but published batch output vanished")
            if processed >= max_per_run:
                break
            prepare_one(args)
            check = verify_provisional_bundle(
                args.output_folder, original, table_file=args.table_file,
            )
            journal["completed"][key] = {
                "source_sha256": check.source_sha256,
                "pef_sha256": check.output_pef_sha256,
                "brf_sha256": check.output_brf_sha256,
            }
            _atomic_journal(journal_path, journal)
            processed += 1
        pending = len(jobs) - len(journal["completed"])
        return processed, pending
    finally:
        # Do not overwrite an unrelated lock. The queue is local, one process.
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded local unverified Braille batch worker")
    parser.add_argument("--queue-json", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-per-run", type=int, default=1, choices=range(1, 5))
    args = parser.parse_args()
    try:
        completed, pending = process_batch(
            args.queue_json, args.output_root, max_per_run=args.max_per_run,
        )
    except (BrailleFactoryError, ValueError, OSError, TypeError):
        print("SECTION 55 BATCH: FAIL — no further work authorized; inspect local state",
              file=sys.stderr)
        return 2
    print("SECTION 55 BATCH: local provisional jobs newly prepared:", completed)
    print("SECTION 55 BATCH: remaining queued:", pending)
    print("STATUS: UNVERIFIED_REQUIRES_DECISION; no automatic printing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
