from __future__ import annotations

"""Distribution-aware lawful real-PGN semantic identity campaign for D06.

QA/evidence only. Transport framing/sampling is deterministic and bounded; all
PGN semantics are delegated to canonical Accessible Chess D06 APIs.
"""

import argparse
from collections import Counter
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import random
import re
import tempfile

from acs.gametree import CanonicalPgnGameFramer
from acs.pgn_roundtrip import PgnRoundTripError, parse_pgn_text, serialize_pgn_text
from scripts.pgn_real_corpus_oracle import (
    CORPORA,
    CorpusSpec,
    _download_verified,
    _open_zstd_text,
)

AUTHORITY_SHA = "9f1db6655d4568428952bc252667fa3730ba492f"
RESERVOIR_PER_CORPUS = 512
TARGET_PER_CLASS = 8
LONG_MAINLINE_PLIES = 200
STANDARD_RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}
RECOVERY_WARNING_PREFIXES = (
    "missing movetext game termination marker;",
    "invalid header Result ",
    "recovered malformed result token ",
    "nested brace comment delimiters normalized to parentheses",
)
TAG_LINE_RE = re.compile(r'^\s*\[\s*([A-Za-z0-9_]+)\s*"((?:\\.|[^"\\])*)"\s*\]\s*$')
MOVE_NUMBER_RE = re.compile(r"(?<!\S)(\d+)\.(?:\.\.)?(?=\s)")


@dataclass(frozen=True, slots=True)
class SelectedRecord:
    ordinal: int
    raw: str
    raw_sha256: str
    reasons: tuple[str, ...]


@dataclass(slots=True)
class CorpusReport:
    name: str
    license: str
    source_sha256: str
    published_games: int
    scanned_records: int = 0
    selected_records: int = 0
    strict_accepted: int = 0
    recovery_accepted: int = 0
    strict_rejected_unclassified: int = 0
    ordinary_start: int = 0
    setup_fen: int = 0
    black_to_move_start: int = 0
    comments: int = 0
    nags: int = 0
    rav: int = 0
    recursive_rav: int = 0
    unicode_metadata: int = 0
    long_games_ge_200_plies: int = 0
    max_mainline_plies: int = 0
    result_counts: dict[str, int] = field(default_factory=dict)
    recovery_warning_counts: dict[str, int] = field(default_factory=dict)
    semantic_identity_count: int = 0
    semantic_identity_collisions: int = 0
    mismatches: list[dict[str, object]] = field(default_factory=list)
    selected_identity_examples: list[dict[str, object]] = field(default_factory=list)
    coverage_selection_counts: dict[str, int] = field(default_factory=dict)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="strict")).hexdigest()


def _tag_pairs(raw: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for line in raw.splitlines():
        match = TAG_LINE_RE.match(line)
        if match:
            tags[match.group(1)] = match.group(2)
    return tags


def _lexical_hints(raw: str) -> set[str]:
    tags = _tag_pairs(raw)
    hints: set[str] = set()
    fen = tags.get("FEN", "")
    if tags.get("SetUp") == "1" or fen:
        hints.add("setup_fen")
    fen_parts = fen.split()
    if len(fen_parts) >= 2 and fen_parts[1] == "b":
        hints.add("black_to_move_start")
    if "{" in raw or ";" in raw:
        hints.add("comments")
    if "$" in raw or re.search(r"\S(?:!!|\?\?|!\?|\?!|!|\?)(?=\s|[)}]|$)", raw):
        hints.add("nags")
    if "(" in raw and ")" in raw:
        hints.add("rav")
    if any(any(ord(ch) > 127 for ch in value) for value in tags.values()):
        hints.add("unicode_metadata")
    result = tags.get("Result")
    if result == "*" or (result is not None and result not in STANDARD_RESULTS):
        hints.add("unusual_result")
    max_move = 0
    for match in MOVE_NUMBER_RE.finditer(raw):
        max_move = max(max_move, int(match.group(1)))
    if max_move >= 100:
        hints.add("long_game_candidate")
    return hints


def _line_metrics(line, depth: int = 0) -> tuple[int, int, int, int]:
    comments = len(line.leading_comments) + len(line.trailing_comments)
    nags = 0
    rav = 0
    max_depth = depth
    for node in line.moves:
        comments += len(node.comments_before) + len(node.comments_after)
        nags += len(node.nags)
        for variation in node.variations:
            rav += 1
            child_comments, child_nags, child_rav, child_depth = _line_metrics(
                variation, depth + 1
            )
            comments += child_comments
            nags += child_nags
            rav += child_rav
            max_depth = max(max_depth, child_depth)
    return comments, nags, rav, max_depth


def _campaign_classes(game) -> set[str]:
    classes: set[str] = set()
    fen = game.tags.get("FEN", "")
    setup = game.tags.get("SetUp") == "1" or bool(fen)
    if setup:
        classes.add("setup_fen")
    else:
        classes.add("ordinary_start")
    fen_parts = fen.split()
    if len(fen_parts) >= 2 and fen_parts[1] == "b":
        classes.add("black_to_move_start")
    comments, nags, rav, max_depth = _line_metrics(game.line)
    if comments:
        classes.add("comments")
    if nags:
        classes.add("nags")
    if rav:
        classes.add("rav")
    if max_depth >= 2:
        classes.add("recursive_rav")
    if any(any(ord(ch) > 127 for ch in str(value)) for value in game.tags.values()):
        classes.add("unicode_metadata")
    if len(game.line.moves) >= LONG_MAINLINE_PLIES:
        classes.add("long_game")
    result = game.tags.get("Result") or game.line.result or "<missing>"
    if result == "*" or result not in STANDARD_RESULTS:
        classes.add("unusual_result")
    return classes


def _select_records(spec: CorpusSpec, path: Path) -> tuple[list[SelectedRecord], int, dict[str, int]]:
    source, reader, text = _open_zstd_text(path)
    reservoir: list[tuple[int, str, set[str]]] = []
    targeted: dict[str, list[tuple[int, str, set[str]]]] = {
        key: []
        for key in (
            "setup_fen",
            "black_to_move_start",
            "comments",
            "nags",
            "rav",
            "unicode_metadata",
            "unusual_result",
            "long_game_candidate",
        )
    }
    targeted_seen = {key: 0 for key in targeted}
    first: tuple[int, str, set[str]] | None = None
    last: tuple[int, str, set[str]] | None = None
    rng_seed = int(hashlib.sha256((spec.name + spec.sha256).encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(rng_seed)
    scanned = 0
    try:
        framer = CanonicalPgnGameFramer()

        def consume(raw: str) -> None:
            nonlocal first, last, scanned
            scanned += 1
            ordinal = scanned
            hints = _lexical_hints(raw)
            record = (ordinal, raw, hints)
            if first is None:
                first = record
            last = record
            if len(reservoir) < RESERVOIR_PER_CORPUS:
                reservoir.append(record)
            else:
                slot = rng.randrange(ordinal)
                if slot < RESERVOIR_PER_CORPUS:
                    reservoir[slot] = record
            for key in targeted:
                if key not in hints:
                    continue
                targeted_seen[key] += 1
                seen = targeted_seen[key]
                if len(targeted[key]) < TARGET_PER_CLASS:
                    targeted[key].append(record)
                else:
                    slot = rng.randrange(seen)
                    if slot < TARGET_PER_CLASS:
                        targeted[key][slot] = record

        for line in text:
            completed = framer.feed_line(line.rstrip("\n\r"))
            if completed is not None:
                consume(completed.text)
        completed = framer.finish()
        if completed is not None:
            consume(completed.text)
    finally:
        text.close()
        try:
            reader.close()
        finally:
            source.close()

    if scanned != spec.published_games:
        raise AssertionError(
            f"{spec.name}: published count {spec.published_games} but scanned {scanned}"
        )
    combined: dict[int, tuple[str, set[str]]] = {}
    for item in ([first] if first else []) + reservoir + ([last] if last else []):
        if item is not None:
            combined[item[0]] = (item[1], set(item[2]) | {"distribution_sample"})
    for key, items in targeted.items():
        for ordinal, raw, hints in items:
            if ordinal in combined:
                combined[ordinal][1].add(key)
            else:
                combined[ordinal] = (raw, set(hints) | {key})

    counts = {key: len(items) for key, items in targeted.items()}
    selected = [
        SelectedRecord(
            ordinal=ordinal,
            raw=raw,
            raw_sha256=_sha256_text(raw),
            reasons=tuple(sorted(reasons)),
        )
        for ordinal, (raw, reasons) in sorted(combined.items())
    ]
    return selected, scanned, counts


def _append_mismatch(report: CorpusReport, record: SelectedRecord, stage: str, detail: str) -> None:
    report.mismatches.append(
        {
            "source_ordinal": record.ordinal,
            "source_record_sha256": record.raw_sha256,
            "selection_reasons": list(record.reasons),
            "stage": stage,
            "detail": detail[:400],
            "minimal_case": record.raw[:4000],
        }
    )


def _semantic_game_equal(left, right) -> bool:
    """Compare canonical chess/PGN semantics, excluding recovery provenance warnings."""

    return (
        left.tags == right.tags
        and left.line == right.line
        and left.source_index == right.source_index
    )


def _verify_record(report: CorpusReport, record: SelectedRecord, identities: dict[str, str]) -> None:
    strict_error: PgnRoundTripError | None = None
    try:
        parsed = parse_pgn_text(record.raw, strict=True)
    except PgnRoundTripError as exc:
        strict_error = exc
        parsed = ()
    except Exception as exc:
        _append_mismatch(report, record, "strict_parse_exception", type(exc).__name__)
        report.strict_rejected_unclassified += 1
        return

    mode = "strict"
    warnings: list[str] = []
    if strict_error is not None:
        try:
            parsed = parse_pgn_text(record.raw, strict=False)
        except Exception as exc:
            _append_mismatch(
                report,
                record,
                "recovery_parse",
                f"strict={strict_error.code.value}; recovery={type(exc).__name__}",
            )
            report.strict_rejected_unclassified += 1
            return
        if len(parsed) != 1 or not parsed[0].warnings:
            _append_mismatch(
                report,
                record,
                "recovery_contract",
                f"strict={strict_error.code.value}; recovered_games={len(parsed)}; warnings={getattr(parsed[0], 'warnings', None) if parsed else None}",
            )
            report.strict_rejected_unclassified += 1
            return
        warnings = list(parsed[0].warnings)
        unknown = [
            item
            for item in warnings
            if not any(item.startswith(prefix) for prefix in RECOVERY_WARNING_PREFIXES)
        ]
        if unknown:
            _append_mismatch(report, record, "unclassified_recovery_warning", repr(unknown[:8]))
            report.strict_rejected_unclassified += 1
            return
        mode = "recovery"

    if len(parsed) != 1:
        _append_mismatch(report, record, "game_count", f"segmented record parsed as {len(parsed)} games")
        return
    game = parsed[0]
    try:
        serialized = serialize_pgn_text(parsed)
        reopened = parse_pgn_text(serialized, strict=True)
        if len(reopened) != 1 or not _semantic_game_equal(reopened[0], game):
            _append_mismatch(report, record, "semantic_reopen", "canonical GameTree semantics changed")
            return
        if mode == "strict" and reopened[0].warnings != game.warnings:
            _append_mismatch(report, record, "strict_warning_identity", "strict warning state changed")
            return
        if mode == "recovery" and reopened[0].warnings:
            _append_mismatch(report, record, "recovery_warning_canonicalization", "strict canonical reopen still has warnings")
            return
        serialized_again = serialize_pgn_text(reopened)
        if serialized_again != serialized:
            _append_mismatch(report, record, "determinism", "canonical serialization changed")
            return
    except Exception as exc:
        _append_mismatch(report, record, "serialize_or_strict_reopen", type(exc).__name__ + ": " + str(exc))
        return

    identity = _sha256_text(serialized)
    previous = identities.get(identity)
    if previous is not None and previous != serialized:
        report.semantic_identity_collisions += 1
        _append_mismatch(report, record, "semantic_identity_collision", identity)
        return
    identities[identity] = serialized
    report.semantic_identity_count += 1

    if mode == "strict":
        report.strict_accepted += 1
    else:
        report.recovery_accepted += 1
        counts = Counter(report.recovery_warning_counts)
        counts.update(warnings)
        report.recovery_warning_counts = dict(sorted(counts.items()))

    classes = _campaign_classes(game)
    report.ordinary_start += int("ordinary_start" in classes)
    report.setup_fen += int("setup_fen" in classes)
    report.black_to_move_start += int("black_to_move_start" in classes)
    report.comments += int("comments" in classes)
    report.nags += int("nags" in classes)
    report.rav += int("rav" in classes)
    report.recursive_rav += int("recursive_rav" in classes)
    report.unicode_metadata += int("unicode_metadata" in classes)
    report.long_games_ge_200_plies += int("long_game" in classes)
    report.max_mainline_plies = max(report.max_mainline_plies, len(game.line.moves))
    result_key = game.tags.get("Result") or game.line.result or "<missing>"
    results = Counter(report.result_counts)
    results[result_key] += 1
    report.result_counts = dict(sorted(results.items()))

    if len(report.selected_identity_examples) < 12 or set(record.reasons) - {"distribution_sample"}:
        report.selected_identity_examples.append(
            {
                "source_ordinal": record.ordinal,
                "source_record_sha256": record.raw_sha256,
                "semantic_identity_sha256": identity,
                "mode": mode,
                "classes": sorted(classes),
                "selection_reasons": list(record.reasons),
            }
        )


def _verify_corpus(spec: CorpusSpec, path: Path) -> CorpusReport:
    selected, scanned, selection_counts = _select_records(spec, path)
    report = CorpusReport(
        name=spec.name,
        license=spec.license,
        source_sha256=spec.sha256,
        published_games=spec.published_games,
        scanned_records=scanned,
        selected_records=len(selected),
        coverage_selection_counts=selection_counts,
    )
    identities: dict[str, str] = {}
    for record in selected:
        _verify_record(report, record, identities)
    return report


def _coverage_verdict(reports: list[CorpusReport]) -> dict[str, object]:
    sums = Counter()
    for report in reports:
        sums.update(
            {
                "ordinary_start": report.ordinary_start,
                "setup_fen": report.setup_fen,
                "black_to_move_start": report.black_to_move_start,
                "comments": report.comments,
                "nags": report.nags,
                "rav": report.rav,
                "recursive_rav": report.recursive_rav,
                "unicode_metadata": report.unicode_metadata,
                "long_games_ge_200_plies": report.long_games_ge_200_plies,
                "unusual_result": report.result_counts.get("*", 0),
            }
        )
    # Real recursive-RAV and black-to-move SetUp/FEN are independently proven
    # by pgn_real_eval_rav_oracle.py in the same workflow. Do not fabricate them
    # if the database/broadcast corpus sample lacks them.
    required_here = (
        "ordinary_start",
        "comments",
        "nags",
        "unicode_metadata",
        "long_games_ge_200_plies",
        "unusual_result",
    )
    missing = [name for name in required_here if sums[name] <= 0]
    return {"counts": dict(sums), "required_here": list(required_here), "missing": missing}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    reports: list[CorpusReport] = []
    with tempfile.TemporaryDirectory(prefix="accessible-chess-pgn-identity-") as directory:
        root = Path(directory)
        for spec in CORPORA:
            destination = root / f"{spec.name}.pgn.zst"
            _download_verified(spec, destination)
            reports.append(_verify_corpus(spec, destination))

    coverage = _coverage_verdict(reports)
    mismatch_count = sum(len(report.mismatches) for report in reports)
    strict_total = sum(report.strict_accepted for report in reports)
    recovery_total = sum(report.recovery_accepted for report in reports)
    selected_total = sum(report.selected_records for report in reports)
    unclassified_total = sum(report.strict_rejected_unclassified for report in reports)
    payload = {
        "schema": 1,
        "authority_sha": AUTHORITY_SHA,
        "sampling": {
            "strategy": "full-source scan + deterministic reservoir + targeted lexical candidates",
            "reservoir_per_corpus": RESERVOIR_PER_CORPUS,
            "target_per_class": TARGET_PER_CLASS,
            "includes_first_and_last": True,
        },
        "selected_records_total": selected_total,
        "strict_accepted_total": strict_total,
        "recovery_accepted_total": recovery_total,
        "unclassified_rejections_total": unclassified_total,
        "mismatch_count": mismatch_count,
        "coverage": coverage,
        "corpora": [asdict(report) for report in reports],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    if args.report is not None:
        args.report.write_text(encoded + "\n", encoding="utf-8")
    print("PGN_REAL_CORPUS_SEMANTIC_IDENTITY_REPORT=" + json.dumps(payload, ensure_ascii=False, sort_keys=True))

    if coverage["missing"]:
        print("COVERAGE_MISSING=" + ",".join(coverage["missing"]))
        return 3
    if mismatch_count or unclassified_total:
        print("PGN REAL CORPUS SEMANTIC IDENTITY RED")
        return 2
    if strict_total + recovery_total != selected_total:
        print("PGN REAL CORPUS ACCOUNTING RED")
        return 2
    print("PGN REAL CORPUS SEMANTIC IDENTITY PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
