from __future__ import annotations

"""Evidence-only stress oracle for the current Books semantic core.

This script intentionally mutates no Product code.  It builds a deterministic
100k-block BookDocument by default (20k of each requested semantic family), then
measures BookIndex/BookReader correctness, latency, memory, same-source reopen,
and changed-source fail-closed behavior.
"""

import cProfile
import gc
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import pstats
import sys
import time
import tracemalloc
from typing import Callable, TypeVar

from acs.book_index import BookEntryKind, BookIndex
from acs.bookdocument import BookDocument, Game, Heading, ListBlock, Paragraph, Position
from acs.bookreader import BookReader

T = TypeVar("T")
PER_KIND = int(os.environ.get("BOOK_STRESS_PER_KIND", "20000"))
REPORT_PATH = Path(os.environ.get("BOOK_STRESS_REPORT", "book_large_semantic_stress_report.json"))
FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
PGN = "1. e4 e5 2. Nf3 Nc6 *"


def rss_mib() -> tuple[float | None, float | None]:
    """Return current/peak RSS MiB without third-party dependencies where possible."""
    mib = 1024.0 * 1024.0
    if sys.platform.startswith("linux"):
        values: dict[str, float] = {}
        try:
            for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
                if line.startswith(("VmRSS:", "VmHWM:")):
                    key, value, _unit = line.split()
                    values[key[:-1]] = float(value) * 1024.0 / mib
            return values.get("VmRSS"), values.get("VmHWM")
        except OSError:
            return None, None
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class PMC(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PMC()
            counters.cb = ctypes.sizeof(counters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
            if ok:
                return counters.WorkingSetSize / mib, counters.PeakWorkingSetSize / mib
        except (AttributeError, OSError, ValueError):
            pass
    return None, None


def measure(name: str, func: Callable[[], T], *, profile: bool = False) -> tuple[T, dict[str, object]]:
    gc.collect()
    before_current, _ = tracemalloc.get_traced_memory()
    before_rss, _ = rss_mib()
    tracemalloc.reset_peak()
    profiler = cProfile.Profile() if profile else None
    started = time.perf_counter()
    if profiler is not None:
        profiler.enable()
    try:
        result = func()
    finally:
        if profiler is not None:
            profiler.disable()
    elapsed = time.perf_counter() - started
    after_current, peak = tracemalloc.get_traced_memory()
    after_rss, peak_rss = rss_mib()
    item: dict[str, object] = {
        "seconds": elapsed,
        "traced_current_delta_mib": (after_current - before_current) / (1024.0 * 1024.0),
        "traced_peak_over_baseline_mib": (peak - before_current) / (1024.0 * 1024.0),
        "rss_before_mib": before_rss,
        "rss_after_mib": after_rss,
        "rss_process_peak_mib": peak_rss,
    }
    if profiler is not None:
        stream = io.StringIO()
        pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(12)
        item["profile_top_cumulative"] = stream.getvalue()
    print(f"METRIC {name}: {json.dumps(item, ensure_ascii=False)}", flush=True)
    return result, item


def source_token(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def build_document(seed: str) -> BookDocument:
    sid = source_token(seed)
    blocks = []
    append = blocks.append
    for i in range(PER_KIND):
        suffix = f"{i:05d}"
        rare = " МАТЧ-Ω-ß-Ж" if i % 1000 == 0 else ""
        append(Heading(
            text=f"Розділ Київ Straße Σίσυφος {suffix}{rare}",
            level=(i % 6) + 1,
            block_id=f"{sid}:heading:{suffix}",
            source_anchor=f"{sid}:h:{suffix}",
        ))
        append(Paragraph(
            text=f"Абзац Unicode Україна café CAFÉ {suffix}{rare}",
            block_id=f"{sid}:paragraph:{suffix}",
            source_anchor=f"{sid}:p:{suffix}",
        ))
        append(ListBlock(
            items=[f"Елемент списку Straße Київ {suffix}{rare}"],
            ordered=(i % 2 == 0),
            block_id=f"{sid}:list:{suffix}",
            source_anchor=f"{sid}:l:{suffix}",
        ))
        append(Position(
            fen=FEN,
            caption=f"Позиція Київ {suffix}{rare}",
            block_id=f"{sid}:position:{suffix}",
            source_anchor=f"{sid}:pos:{suffix}",
        ))
        append(Game(
            pgn=PGN,
            title=f"Партія Straße Київ {suffix}{rare}",
            block_id=f"{sid}:game:{suffix}",
            source_anchor=f"{sid}:g:{suffix}",
        ))
    return BookDocument(
        title="Велика семантична книга — stress oracle",
        language="uk",
        author="QA deterministic generator",
        source_name=f"generated:{sid}",
        source_uri=f"urn:accessible-chess:qa:{sid}",
        source_rights="QA-generated semantic fixture",
        blocks=blocks,
    )


def id_digest(document: BookDocument) -> str:
    digest = hashlib.sha256()
    for block in document.blocks:
        digest.update((block.block_id or "").encode("utf-8"))
        digest.update(b"\0")
        digest.update((block.source_anchor or "").encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def main() -> int:
    if PER_KIND < 10000:
        raise SystemExit("BOOK_STRESS_PER_KIND must be >= 10000 for this acceptance oracle")

    tracemalloc.start(1)
    report: dict[str, object] = {
        "python": sys.version,
        "platform": platform.platform(),
        "per_kind": PER_KIND,
        "expected_blocks": PER_KIND * 5,
        "semantic_families": ["Heading", "Paragraph", "List", "Position", "Game"],
        "metrics": {},
        "correctness": {},
    }
    metrics: dict[str, object] = report["metrics"]  # type: ignore[assignment]
    correctness: dict[str, object] = report["correctness"]  # type: ignore[assignment]

    document, metrics["build_document"] = measure("build_document", lambda: build_document("source-A"), profile=True)
    assert len(document.blocks) == PER_KIND * 5
    correctness["block_count"] = len(document.blocks)
    correctness["id_digest_source_a"] = id_digest(document)
    correctness["unique_block_ids"] = len({b.block_id for b in document.blocks}) == len(document.blocks)
    correctness["unique_source_anchors"] = len({b.source_anchor for b in document.blocks}) == len(document.blocks)

    index, metrics["book_index_construct"] = measure("book_index_construct", lambda: BookIndex(document), profile=True)
    assert len(index.entries) == len(document.blocks)
    assert len(index.of_kind(BookEntryKind.HEADING)) == PER_KIND
    assert len(index.of_kind(BookEntryKind.PARAGRAPH)) == PER_KIND
    assert len(index.of_kind(BookEntryKind.LIST)) == PER_KIND
    assert len(index.of_kind(BookEntryKind.POSITION)) == PER_KIND
    assert len(index.of_kind(BookEntryKind.GAME)) == PER_KIND

    rare_matches, metrics["unicode_sparse_search"] = measure(
        "unicode_sparse_search", lambda: index.find("матч-ω-SS-ж"), profile=True
    )
    expected_sparse = (PER_KIND // 1000 + (1 if PER_KIND % 1000 else 0)) * 5
    assert len(rare_matches) == expected_sparse, (len(rare_matches), expected_sparse)
    repeated = index.find("МАТЧ-Ω-ß-Ж")
    assert [e.target.key for e in repeated] == [e.target.key for e in rare_matches]
    correctness["unicode_casefold_deterministic"] = True
    correctness["unicode_sparse_match_count"] = len(rare_matches)

    common_matches, metrics["unicode_dense_search"] = measure(
        "unicode_dense_search", lambda: index.find("КИЇВ"), profile=True
    )
    assert len(common_matches) == PER_KIND * 4
    correctness["unicode_dense_match_count"] = len(common_matches)

    nfc_doc = BookDocument(title="NFC", blocks=[Paragraph(text="café", block_id="nfc")])
    nfc_index = BookIndex(nfc_doc)
    correctness["nfc_query_matches_nfc_label"] = len(nfc_index.find("CAFÉ")) == 1
    correctness["nfd_query_matches_nfc_label"] = len(nfc_index.find("cafe\u0301")) == 1

    reader, metrics["book_reader_construct"] = measure("book_reader_construct", lambda: BookReader(document), profile=True)
    target_match = rare_matches[-2]
    reader.go_to(target_match.target.index)
    reader.save_return_point("stress")
    snapshot, metrics["snapshot_deep_anchor"] = measure("snapshot_deep_anchor", reader.snapshot, profile=True)
    assert snapshot["current_target"] == target_match.target.key

    pos = len(rare_matches) // 2
    previous_match, metrics["previous_match_go_to"] = measure(
        "previous_match_go_to", lambda: reader.go_to(rare_matches[pos - 1].target.index), profile=True
    )
    next_match, metrics["next_match_go_to"] = measure(
        "next_match_go_to", lambda: reader.go_to(rare_matches[pos].target.index), profile=True
    )
    assert previous_match.index < next_match.index
    correctness["next_previous_match_order"] = True

    wire, metrics["serialize_close"] = measure(
        "serialize_close",
        lambda: json.dumps(document.as_dict(), ensure_ascii=False, separators=(",", ":")),
        profile=True,
    )
    report["wire_utf8_bytes"] = len(wire.encode("utf-8"))
    reopened, metrics["reopen_document"] = measure(
        "reopen_document", lambda: BookDocument.from_dict(json.loads(wire)), profile=True
    )
    restored, metrics["restore_after_reopen"] = measure(
        "restore_after_reopen", lambda: BookReader.restore_snapshot(reopened, snapshot), profile=True
    )
    assert restored.index == target_match.target.index
    assert restored.restore_return_point("stress").index == target_match.target.index
    correctness["close_reopen_anchor_exact"] = True
    del wire
    del reopened
    del restored
    gc.collect()

    same_source, metrics["reimport_same_source"] = measure(
        "reimport_same_source", lambda: build_document("source-A"), profile=True
    )
    same_digest = id_digest(same_source)
    assert same_digest == correctness["id_digest_source_a"]
    same_restored, metrics["restore_same_source"] = measure(
        "restore_same_source", lambda: BookReader.restore_snapshot(same_source, snapshot), profile=True
    )
    assert same_restored.index == target_match.target.index
    correctness["same_source_ids_stable"] = True
    correctness["same_source_anchor_restore_exact"] = True
    del same_restored
    del same_source
    gc.collect()

    changed_source, metrics["reimport_changed_source"] = measure(
        "reimport_changed_source", lambda: build_document("source-B-changed"), profile=True
    )
    changed_digest = id_digest(changed_source)
    assert changed_digest != correctness["id_digest_source_a"]
    failed_closed = False
    changed_error = None
    started = time.perf_counter()
    try:
        BookReader.restore_snapshot(changed_source, snapshot)
    except LookupError as exc:
        failed_closed = True
        changed_error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    metrics["restore_changed_source_fail_closed"] = {"seconds": elapsed}
    assert failed_closed
    correctness["changed_source_anchor_fails_closed"] = True
    correctness["changed_source_error"] = changed_error

    report["complexity_observation"] = {
        "book_index_construct": "O(N) entries plus O(N) key map; immutable snapshot",
        "find": "O(N) scan and O(M) materialized tuple; no max-results parameter",
        "reader_location": "heading_path scans blocks through current index",
        "snapshot": "recomputes full document revision digest before publication",
    }

    current_rss, peak_rss = rss_mib()
    current_trace, peak_trace = tracemalloc.get_traced_memory()
    report["final_memory"] = {
        "rss_current_mib": current_rss,
        "rss_peak_mib": peak_rss,
        "traced_current_mib": current_trace / (1024.0 * 1024.0),
        "traced_peak_mib": peak_trace / (1024.0 * 1024.0),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("CORRECTNESS PASS", flush=True)
    print(f"REPORT {REPORT_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
