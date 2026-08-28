from __future__ import annotations

"""End-to-end real PGN corpus acceptance over strict and recovery contracts.

This remains QA/evidence code. It reuses the bounded transport/download helpers
from :mod:`scripts.pgn_real_corpus_oracle` and delegates all PGN semantics to
Accessible Chess Product APIs. Strict records must round-trip identically through
``acs.pgn_roundtrip``. Strict-rejected damaged records are accepted only when the
professional ``PgnDocumentSession`` recovery path classifies an already-audited
damage shape, preserves the original source, requires Save As, and produces a
strict-reopenable canonical copy.
"""

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import tempfile

from acs.pgn_document import PgnDocumentError, PgnDocumentErrorCode, PgnDocumentSession
from acs.pgn_roundtrip import (
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    parse_pgn_text,
    serialize_pgn_text,
)
from scripts.pgn_real_corpus_oracle import (
    CORPORA,
    CorpusSpec,
    CorpusStats,
    _MIN_STRICT_PER_CORPUS,
    _adversarial_real_record,
    _download_verified,
    _open_zstd_text,
    _selftest as _transport_selftest,
    _update_strict_stats,
    _verify_batch,
    iter_complete_records,
)

_PRODUCT_BASE = "d706eb93b9a4df3c6e99ab1af584a9cfe6b6f5ea"
_ALLOWED_STRICT_RECOVERY_CODES = {
    PgnRoundTripErrorCode.MALFORMED_PGN,
    PgnRoundTripErrorCode.INVALID_SAN,
}
_MISSING_TERMINATION = "missing movetext game termination marker;"
_INVALID_RESULT = "invalid header Result "
_RECOVERED_RESULT = "recovered malformed result token "


def _normalized_warning(text: str) -> str:
    prefix = "Game 1: "
    return text[len(prefix) :] if text.startswith(prefix) else text


def _classify_document_recovery(
    stats: CorpusStats,
    raw: str,
    strict_error: PgnRoundTripError,
    root: Path,
    ordinal: int,
) -> None:
    if strict_error.code not in _ALLOWED_STRICT_RECOVERY_CODES:
        raise AssertionError(
            f"{stats.name}: real record rejected with unclassified strict code "
            f"{strict_error.code.value}"
        ) from strict_error

    source = root / f"{stats.name}-{ordinal}.pgn"
    destination = root / f"{stats.name}-{ordinal}-recovered.pgn"
    original = raw.encode("utf-8", errors="strict")
    source.write_bytes(original)

    try:
        session = PgnDocumentSession.open(source)
    except Exception as exc:
        raise AssertionError(
            f"{stats.name}: audited damaged record cannot enter document recovery: "
            f"{type(exc).__name__}"
        ) from exc

    view = session.view()
    warnings = tuple(_normalized_warning(item) for item in view.global_warnings)
    if view.source_overwrite_safe or not session.dirty or not warnings:
        raise AssertionError(f"{stats.name}: damaged recovery source was not marked unsafe")
    if source.read_bytes() != original:
        raise AssertionError(f"{stats.name}: opening damaged source changed original bytes")

    has_missing_termination = any(item.startswith(_MISSING_TERMINATION) for item in warnings)
    if not has_missing_termination:
        raise AssertionError(f"{stats.name}: recovery lacks missing-termination provenance")

    if strict_error.code is PgnRoundTripErrorCode.MALFORMED_PGN:
        allowed = all(item.startswith(_MISSING_TERMINATION) for item in warnings)
        if not allowed:
            raise AssertionError(
                f"{stats.name}: unclassified malformed recovery warning: {warnings[:8]}"
            )
    else:
        has_invalid_result = any(item.startswith(_INVALID_RESULT) for item in warnings)
        has_recovered_result = any(item.startswith(_RECOVERED_RESULT) for item in warnings)
        if not (has_invalid_result and has_recovered_result):
            raise AssertionError(
                f"{stats.name}: INVALID_SAN was not the audited malformed-result recovery shape"
            )
        allowed = all(
            item.startswith((_MISSING_TERMINATION, _INVALID_RESULT, _RECOVERED_RESULT))
            for item in warnings
        )
        if not allowed:
            raise AssertionError(
                f"{stats.name}: unclassified invalid-result recovery warning: {warnings[:8]}"
            )

    try:
        session.save()
    except PgnDocumentError as exc:
        if exc.code is not PgnDocumentErrorCode.SOURCE_REQUIRES_SAVE_AS:
            raise AssertionError(
                f"{stats.name}: damaged source failed with wrong save policy {exc.code.value}"
            ) from exc
    else:
        raise AssertionError(f"{stats.name}: damaged source allowed ordinary Save")

    if source.read_bytes() != original:
        raise AssertionError(f"{stats.name}: blocked Save changed original bytes")

    session.save_as(destination)
    if source.read_bytes() != original:
        raise AssertionError(f"{stats.name}: Save As changed original bytes")

    reopened = PgnDocumentSession.open(destination)
    reopened_view = reopened.view()
    if not reopened_view.source_overwrite_safe or reopened_view.global_warnings:
        raise AssertionError(f"{stats.name}: recovered copy is not strict/warning-free")
    strict_reopened = parse_pgn_text(destination.read_text(encoding="utf-8"), strict=True)
    if strict_reopened != reopened.workspace.games():
        raise AssertionError(f"{stats.name}: Save As/reopen changed canonical GameTree")
    canonical_text = serialize_pgn_text(strict_reopened)
    if parse_pgn_text(canonical_text, strict=True) != strict_reopened:
        raise AssertionError(f"{stats.name}: recovered copy is not deterministic")

    counts = Counter(warnings)
    stats.recovery_records += 1
    merged = Counter(stats.recovery_warning_counts)
    merged.update(counts)
    stats.recovery_warning_counts = dict(sorted(merged.items()))

    destination.unlink()
    source.unlink()


def _verify_corpus(
    spec: CorpusSpec,
    path: Path,
    *,
    game_limit: int,
    batch_size: int,
    recovery_root: Path,
) -> CorpusStats:
    stats = CorpusStats(
        name=spec.name,
        license=spec.license,
        published_games=spec.published_games,
    )
    source, reader, text = _open_zstd_text(path)
    first_strict_record: str | None = None
    batch: list[str] = []
    try:
        for ordinal, raw in enumerate(iter_complete_records(text, limit=game_limit), start=1):
            stats.sampled_records += 1
            try:
                games = parse_pgn_text(raw, strict=True)
            except PgnRoundTripError as exc:
                _classify_document_recovery(stats, raw, exc, recovery_root, ordinal)
                continue

            if len(games) != 1:
                raise AssertionError(f"{spec.name}: segmented record parsed as {len(games)} games")
            if first_strict_record is None:
                first_strict_record = raw
            game = games[0]

            serialized = serialize_pgn_text(games)
            reparsed = parse_pgn_text(serialized, strict=True)
            if reparsed != games:
                raise AssertionError(f"{spec.name}: canonical GameTree changed after save/reopen")
            if serialize_pgn_text(reparsed) != serialized:
                raise AssertionError(f"{spec.name}: canonical serialization is nondeterministic")

            _update_strict_stats(stats, raw, game)
            batch.append(raw)
            if len(batch) >= batch_size:
                _verify_batch(spec, batch)
                stats.multi_game_batches += 1
                batch.clear()
    finally:
        text.close()
        try:
            reader.close()
        finally:
            source.close()

    if batch:
        _verify_batch(spec, batch)
        stats.multi_game_batches += 1

    if stats.sampled_records != game_limit:
        raise AssertionError(
            f"{spec.name}: expected {game_limit} sampled records, got {stats.sampled_records}"
        )
    if stats.strict_roundtrip_games < _MIN_STRICT_PER_CORPUS:
        raise AssertionError(
            f"{spec.name}: only {stats.strict_roundtrip_games} strict games; "
            f"minimum is {_MIN_STRICT_PER_CORPUS}"
        )
    if stats.strict_roundtrip_games + stats.recovery_records != stats.sampled_records:
        raise AssertionError(f"{spec.name}: sampled-record accounting is inconsistent")
    if first_strict_record is None:
        raise AssertionError(f"{spec.name}: no strict real game was sampled")

    stats.adversarial_checks += _adversarial_real_record(first_strict_record)
    return stats


def _selftest() -> None:
    _transport_selftest()
    damaged = '''[Event "Damaged broadcast placeholder"]
[Site "?"]
[Result "0-0"]
[Variant "Standard"]

0-0
'''
    with tempfile.TemporaryDirectory(prefix="accessible-chess-pgn-session-selftest-") as directory:
        root = Path(directory)
        stats = CorpusStats(name="selftest", license="none", published_games=1)
        try:
            parse_pgn_text(damaged, strict=True)
        except PgnRoundTripError as exc:
            if exc.code is not PgnRoundTripErrorCode.INVALID_SAN:
                raise
            _classify_document_recovery(stats, damaged, exc, root, 1)
        else:
            raise AssertionError("malformed result placeholder became strict PGN")
        if stats.recovery_records != 1:
            raise AssertionError("document recovery selftest was not counted")
    print("PGN REAL CORPUS SESSION ORACLE SELFTEST PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--games-per-corpus", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=250)
    args = parser.parse_args()

    if args.selftest:
        _selftest()
        return 0
    if args.games_per_corpus < 1000:
        parser.error("--games-per-corpus must remain at least 1000 for the real-corpus gate")
    if args.batch_size < 2 or args.batch_size > args.games_per_corpus:
        parser.error("--batch-size must be between 2 and --games-per-corpus")

    reports: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="accessible-chess-pgn-corpus-") as directory:
        root = Path(directory)
        recovery_root = root / "recovery"
        recovery_root.mkdir()
        for spec in CORPORA:
            destination = root / f"{spec.name}.pgn.zst"
            _download_verified(spec, destination)
            stats = _verify_corpus(
                spec,
                destination,
                game_limit=args.games_per_corpus,
                batch_size=args.batch_size,
                recovery_root=recovery_root,
            )
            reports.append(asdict(stats))

    sampled_total = sum(int(report["sampled_records"]) for report in reports)
    strict_total = sum(int(report["strict_roundtrip_games"]) for report in reports)
    recovery_total = sum(int(report["recovery_records"]) for report in reports)
    if sampled_total != args.games_per_corpus * len(CORPORA):
        raise AssertionError("real-corpus sampled-record total changed")
    if strict_total < 3000:
        raise AssertionError("real-corpus gate did not verify thousands of strict games")
    if strict_total + recovery_total != sampled_total:
        raise AssertionError("real-corpus global accounting is inconsistent")

    payload = {
        "schema": 3,
        "product_base": _PRODUCT_BASE,
        "sampled_records_total": sampled_total,
        "strict_roundtrip_games_total": strict_total,
        "recovery_records_total": recovery_total,
        "corpora": reports,
    }
    print("PGN_REAL_CORPUS_REPORT=" + json.dumps(payload, ensure_ascii=False, sort_keys=True))
    print("PGN REAL CORPUS SESSION ROUND-TRIP PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
