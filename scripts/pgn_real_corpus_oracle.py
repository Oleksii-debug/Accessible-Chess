from __future__ import annotations

"""Real-world PGN corpus oracle for the canonical D06 GameTree boundary.

This is QA/evidence code, not a second PGN implementation.  Corpus records are
segmented only to keep external test inputs bounded; all PGN semantics, recovery,
serialization and equality checks are delegated to ``acs.pgn_roundtrip`` and the
canonical GameTree model.

The oracle downloads pinned, legally reusable Lichess corpora at CI time.  Game
collections are never committed to this repository.
"""

import argparse
from dataclasses import asdict, dataclass
import hashlib
import io
import json
import multiprocessing
from pathlib import Path
import re
import tempfile
from typing import Iterator, TextIO
from urllib.request import Request, urlopen

from acs.pgn_roundtrip import (
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    canonical_round_trip_text,
    parse_pgn_bytes,
    parse_pgn_text,
    serialize_pgn_text,
)


_MAX_COMPRESSED_BYTES = 32 * 1024 * 1024
_DOWNLOAD_CHUNK = 1024 * 1024
_BOM = b"\xef\xbb\xbf"
_TERMINATION_RE = re.compile(r"(?:1-0|0-1|1/2-1/2|\*)\s*\Z")


@dataclass(frozen=True, slots=True)
class CorpusSpec:
    name: str
    url: str
    sha256: str
    license: str
    published_games: int


CORPORA = (
    CorpusSpec(
        name="lichess-standard-rated-2013-01",
        url="https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst",
        sha256="aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635",
        license="CC0",
        published_games=121_332,
    ),
    CorpusSpec(
        name="lichess-broadcast-2026-02",
        url="https://database.lichess.org/broadcast/lichess_db_broadcast_2026-02.pgn.zst",
        sha256="ea977569917718b33940ba5379db2adad77d58876c29084294d357f15fe6a31b",
        license="CC BY-SA 4.0",
        published_games=19_752,
    ),
)


@dataclass(slots=True)
class CorpusStats:
    name: str
    license: str
    published_games: int
    verified_games: int = 0
    unicode_games: int = 0
    games_with_comments: int = 0
    games_with_nags: int = 0
    games_with_rav: int = 0
    games_with_nested_rav: int = 0
    setup_fen_games: int = 0
    max_mainline_plies: int = 0
    max_variation_depth: int = 0
    multi_game_batches: int = 0
    adversarial_checks: int = 0


def _scan_comment_state(line: str, inside_brace: bool) -> bool:
    """Track only enough lexical state to avoid splitting inside a comment.

    This helper does not interpret moves, tags, results, RAV, SAN, NAG or chess
    state.  Every yielded record is subsequently required to pass the canonical
    D06 parser, so a segmentation mistake cannot create a false green result.
    """

    if not inside_brace and line.startswith("["):
        return False
    index = 0
    while index < len(line):
        character = line[index]
        if inside_brace:
            if character == "}":
                inside_brace = False
        else:
            if character == ";":
                break
            if character == "{":
                inside_brace = True
        index += 1
    return inside_brace


def iter_complete_records(stream: TextIO, *, limit: int) -> Iterator[str]:
    """Yield complete Lichess PGN records, bounded by ``limit``.

    Lichess exports begin each game with an Event tag.  We detect that transport
    boundary only when outside a brace comment.  Canonical strict parsing then
    proves each candidate is exactly one complete PGN game.
    """

    if type(limit) is not int or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive exact integer")

    current: list[str] = []
    inside_brace = False
    yielded = 0

    for line in stream:
        if not inside_brace and line.startswith('[Event "') and current:
            record = "".join(current).strip()
            if record:
                yielded += 1
                yield record + "\n"
                if yielded >= limit:
                    return
            current = [line]
            inside_brace = False
            continue

        current.append(line)
        inside_brace = _scan_comment_state(line, inside_brace)

    if current and yielded < limit:
        record = "".join(current).strip()
        if record:
            yield record + "\n"


def _download_verified(spec: CorpusSpec, destination: Path) -> None:
    request = Request(spec.url, headers={"User-Agent": "Accessible-Chess-PGN-Corpus-QA/1"})
    digest = hashlib.sha256()
    total = 0
    try:
        response = urlopen(request, timeout=60)
    except Exception as exc:  # network evidence failure, never Product evidence
        raise RuntimeError(f"external corpus download failed for {spec.name}: {type(exc).__name__}") from exc

    with response, destination.open("wb") as output:
        while True:
            chunk = response.read(_DOWNLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_COMPRESSED_BYTES:
                raise RuntimeError(f"compressed corpus exceeds QA bound: {spec.name}")
            digest.update(chunk)
            output.write(chunk)

    actual = digest.hexdigest()
    if actual != spec.sha256:
        raise RuntimeError(
            f"external corpus digest mismatch for {spec.name}: expected {spec.sha256}, got {actual}"
        )


def _open_zstd_text(path: Path):
    try:
        import zstandard  # type: ignore
    except ImportError as exc:
        raise RuntimeError("zstandard is required only for the real-corpus QA oracle") from exc

    source = path.open("rb")
    reader = zstandard.ZstdDecompressor().stream_reader(source)
    text = io.TextIOWrapper(reader, encoding="utf-8", errors="strict", newline=None)
    return source, reader, text


def _line_metrics(line, depth: int = 0) -> tuple[int, int, int, int, int]:
    comments = len(line.leading_comments) + len(line.trailing_comments)
    nags = 0
    rav = 0
    max_depth = depth
    nodes = len(line.moves)
    for node in line.moves:
        comments += len(node.comments_before) + len(node.comments_after)
        nags += len(node.nags)
        for variation in node.variations:
            rav += 1
            child_nodes, child_comments, child_nags, child_rav, child_depth = _line_metrics(
                variation, depth + 1
            )
            nodes += child_nodes
            comments += child_comments
            nags += child_nags
            rav += child_rav
            max_depth = max(max_depth, child_depth)
    return nodes, comments, nags, rav, max_depth


def _update_stats(stats: CorpusStats, raw: str, game) -> None:
    _nodes, comments, nags, rav, max_depth = _line_metrics(game.line)
    stats.verified_games += 1
    stats.unicode_games += int(any(ord(character) > 127 for character in raw))
    stats.games_with_comments += int(comments > 0)
    stats.games_with_nags += int(nags > 0)
    stats.games_with_rav += int(rav > 0)
    stats.games_with_nested_rav += int(max_depth > 1)
    stats.setup_fen_games += int("FEN" in game.tags or game.tags.get("SetUp") == "1")
    stats.max_mainline_plies = max(stats.max_mainline_plies, len(game.line.moves))
    stats.max_variation_depth = max(stats.max_variation_depth, max_depth)


def _strict_probe_child(connection, text: str) -> None:
    try:
        games = parse_pgn_text(text, strict=True)
    except PgnRoundTripError as exc:
        connection.send(("error", exc.code.value))
    except BaseException as exc:  # preserve unexpected failure class without traceback/path noise
        connection.send(("unexpected", type(exc).__name__))
    else:
        connection.send(("ok", str(len(games))))
    finally:
        connection.close()


def _bounded_strict_probe(text: str, *, timeout_seconds: float = 8.0) -> tuple[str, str]:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_strict_probe_child, args=(child, text))
    process.start()
    child.close()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(2)
        parent.close()
        raise AssertionError("canonical PGN parser exceeded malformed-input timeout")
    if not parent.poll():
        code = process.exitcode
        parent.close()
        raise AssertionError(f"canonical PGN parser probe exited without evidence: {code}")
    result = parent.recv()
    parent.close()
    if process.exitcode not in (0, None):
        raise AssertionError(f"canonical PGN parser probe process failed: {process.exitcode}")
    return result


def _expect_error_code(call, expected: PgnRoundTripErrorCode) -> None:
    try:
        call()
    except PgnRoundTripError as exc:
        if exc.code is not expected:
            raise AssertionError(f"expected {expected.value}, got {exc.code.value}") from exc
    else:
        raise AssertionError(f"expected {expected.value}, operation succeeded")


def _adversarial_real_record(raw: str) -> int:
    """Derive damaged inputs from one real record and require fail-closed behavior."""

    baseline = parse_pgn_text(raw, strict=True)
    if len(baseline) != 1:
        raise AssertionError("adversarial seed is not exactly one canonical game")

    encoded = raw.encode("utf-8", errors="strict")
    if parse_pgn_bytes(_BOM + encoded, strict=True) != baseline:
        raise AssertionError("UTF-8 BOM changed canonical GameTree")

    _expect_error_code(
        lambda: parse_pgn_bytes(encoded + b"\xff", strict=True),
        PgnRoundTripErrorCode.INVALID_ENCODING,
    )

    match = _TERMINATION_RE.search(raw)
    if match is None:
        raise AssertionError("real corpus seed has no terminal result marker")

    truncated = raw[: match.start()].rstrip() + "\n"
    recovered = parse_pgn_text(truncated, strict=False)
    if len(recovered) != 1 or not recovered[0].warnings:
        raise AssertionError("truncated real PGN did not expose recovery evidence")
    status, detail = _bounded_strict_probe(truncated)
    if status != "error" or detail != PgnRoundTripErrorCode.MALFORMED_PGN.value:
        raise AssertionError(f"strict truncated PGN classification changed: {status}/{detail}")

    unmatched_close = raw[: match.start()] + "} " + raw[match.start() :]
    status, detail = _bounded_strict_probe(unmatched_close)
    if status != "error":
        raise AssertionError(f"unmatched closing brace was accepted: {status}/{detail}")

    canonical = canonical_round_trip_text(raw)
    canonical_again = canonical_round_trip_text(canonical.text)
    if canonical_again.text != canonical.text or canonical_again.games != canonical.games:
        raise AssertionError("canonical real-game serialization is not deterministic")

    return 5


def _verify_corpus(spec: CorpusSpec, path: Path, *, game_limit: int, batch_size: int) -> CorpusStats:
    stats = CorpusStats(
        name=spec.name,
        license=spec.license,
        published_games=spec.published_games,
    )
    source, reader, text = _open_zstd_text(path)
    first_record: str | None = None
    batch: list[str] = []
    try:
        for raw in iter_complete_records(text, limit=game_limit):
            if first_record is None:
                first_record = raw

            games = parse_pgn_text(raw, strict=True)
            if len(games) != 1:
                raise AssertionError(f"{spec.name}: segmented record parsed as {len(games)} games")
            game = games[0]

            serialized = serialize_pgn_text(games)
            reparsed = parse_pgn_text(serialized, strict=True)
            if reparsed != games:
                raise AssertionError(f"{spec.name}: canonical GameTree changed after save/reopen")
            if serialize_pgn_text(reparsed) != serialized:
                raise AssertionError(f"{spec.name}: canonical serialization is nondeterministic")

            _update_stats(stats, raw, game)
            batch.append(raw)
            if len(batch) >= batch_size:
                joined = "\n".join(batch)
                result = canonical_round_trip_text(joined)
                if len(result.games) != len(batch):
                    raise AssertionError(f"{spec.name}: multi-game batch cardinality changed")
                if canonical_round_trip_text(result.text).text != result.text:
                    raise AssertionError(f"{spec.name}: multi-game serialization is nondeterministic")
                stats.multi_game_batches += 1
                batch.clear()
    finally:
        text.close()
        try:
            reader.close()
        finally:
            source.close()

    if batch:
        joined = "\n".join(batch)
        result = canonical_round_trip_text(joined)
        if len(result.games) != len(batch):
            raise AssertionError(f"{spec.name}: final multi-game batch cardinality changed")
        if canonical_round_trip_text(result.text).text != result.text:
            raise AssertionError(f"{spec.name}: final multi-game serialization is nondeterministic")
        stats.multi_game_batches += 1

    if stats.verified_games != game_limit:
        raise AssertionError(
            f"{spec.name}: expected {game_limit} complete games, verified {stats.verified_games}"
        )
    if first_record is None:
        raise AssertionError(f"{spec.name}: no complete real game was sampled")
    stats.adversarial_checks += _adversarial_real_record(first_record)
    return stats


def _selftest() -> None:
    corpus = """[Event \"One\"]
[Site \"A\"]
[Result \"1-0\"]

1. e4 {multiline
[Event \"not a boundary\"]
comment} e5 2. Nf3 1-0

[Event \"Two\"]
[Site \"B\"]
[Result \"0-1\"]

1. d4 d5 0-1
"""
    records = list(iter_complete_records(io.StringIO(corpus), limit=10))
    if len(records) != 2:
        raise AssertionError(f"record segmenter produced {len(records)} records")
    if "not a boundary" not in records[0] or '[Event "Two"]' not in records[1]:
        raise AssertionError("record segmenter lost or misassigned content")

    first = parse_pgn_text(records[0], strict=True)
    second = parse_pgn_text(records[1], strict=True)
    if len(first) != 1 or len(second) != 1:
        raise AssertionError("selftest records do not parse canonically")
    if parse_pgn_bytes(_BOM + records[0].encode("utf-8"), strict=True) != first:
        raise AssertionError("selftest BOM contract failed")
    print("PGN REAL CORPUS ORACLE SELFTEST PASS")


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
        for spec in CORPORA:
            destination = root / f"{spec.name}.pgn.zst"
            _download_verified(spec, destination)
            stats = _verify_corpus(
                spec,
                destination,
                game_limit=args.games_per_corpus,
                batch_size=args.batch_size,
            )
            reports.append(asdict(stats))

    total = sum(int(report["verified_games"]) for report in reports)
    if total < 2000:
        raise AssertionError("real-corpus gate did not verify thousands of games")

    payload = {
        "schema": 1,
        "product_base": "6567f3d35ffefaa85ae7e8b87d9fcc0d188e7cac",
        "verified_games_total": total,
        "corpora": reports,
    }
    print("PGN_REAL_CORPUS_REPORT=" + json.dumps(payload, ensure_ascii=False, sort_keys=True))
    print("PGN REAL CORPUS ROUND-TRIP PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
