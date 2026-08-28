from __future__ import annotations

"""Real legal annotated-game evidence for the V2 Books GameTree envelope.

This module is QA/evidence only.  It does not implement PGN semantics, chess
rules, book import, Library storage, or UI behavior.  Transport records are
segmented only at top-level Lichess Event-tag boundaries.  PGN meaning is always
resolved by the existing bounded D06 ``parse_pgn_text(strict=False)`` boundary,
while the assertion surface under test is PR #303's ``BookDocument.Game`` /
``VariationTree`` application boundary.
"""

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import tempfile
from typing import Iterator, TextIO
from urllib.request import Request, urlopen

from acs.book_game_content import BookGameSource, resolve_book_game, resolve_book_variation
from acs.bookdocument import Game, VariationTree
from acs.gametree import PgnGame, serialize_game
from acs.pgn_roundtrip import PgnRoundTripError, parse_pgn_text


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
_MAX_COMPRESSED_BYTES = 32 * 1024 * 1024
_DOWNLOAD_CHUNK = 1024 * 1024
_DEFAULT_SCAN_LIMIT = 2000
_DEFAULT_ACCEPTED_TARGET = 96


@dataclass(frozen=True, slots=True)
class CorpusSpec:
    name: str
    url: str
    sha256: str
    license: str
    published_games: int


CORPUS = CorpusSpec(
    name="lichess-broadcast-2026-02",
    url="https://database.lichess.org/broadcast/lichess_db_broadcast_2026-02.pgn.zst",
    sha256="ea977569917718b33940ba5379db2adad77d58876c29084294d357f15fe6a31b",
    license="CC BY-SA 4.0",
    published_games=19_752,
)


def _scan_comment_state(line: str, inside_brace: bool) -> bool:
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


def iter_transport_records(stream: TextIO, *, limit: int) -> Iterator[str]:
    """Bound transport records without interpreting any PGN move semantics."""

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
            inside_brace = _scan_comment_state(line, False)
            continue
        current.append(line)
        inside_brace = _scan_comment_state(line, inside_brace)
    if current and yielded < limit:
        record = "".join(current).strip()
        if record:
            yield record + "\n"


def _download_verified(destination: Path) -> None:
    request = Request(CORPUS.url, headers={"User-Agent": "Accessible-Chess-Book-Corpus-QA/1"})
    digest = hashlib.sha256()
    total = 0
    try:
        response = urlopen(request, timeout=60)
    except Exception as exc:
        raise RuntimeError(f"external corpus download failed: {type(exc).__name__}") from exc
    with response, destination.open("wb") as output:
        while True:
            chunk = response.read(_DOWNLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_COMPRESSED_BYTES:
                raise RuntimeError("compressed Book QA corpus exceeds the evidence bound")
            digest.update(chunk)
            output.write(chunk)
    actual = digest.hexdigest()
    if actual != CORPUS.sha256:
        raise RuntimeError(
            f"external corpus digest mismatch: expected {CORPUS.sha256}, got {actual}"
        )


def _open_zstd_text(path: Path):
    try:
        import zstandard  # type: ignore
    except ImportError as exc:
        raise RuntimeError("zstandard is required only for real-corpus QA") from exc
    source = path.open("rb")
    reader = zstandard.ZstdDecompressor().stream_reader(source)
    text = io.TextIOWrapper(reader, encoding="utf-8", errors="strict", newline=None)
    return source, reader, text


def _line_metrics(line, depth: int = 0) -> tuple[int, int, int, int]:
    comments = len(line.leading_comments) + len(line.trailing_comments)
    nags = 0
    rav = 0
    max_depth = depth
    for move in line.moves:
        comments += len(move.comments_before) + len(move.comments_after)
        nags += len(move.nags)
        for variation in move.variations:
            rav += 1
            child_comments, child_nags, child_rav, child_depth = _line_metrics(
                variation, depth + 1
            )
            comments += child_comments
            nags += child_nags
            rav += child_rav
            max_depth = max(max_depth, child_depth)
    return comments, nags, rav, max_depth


class _RealCanonicalLookup:
    def __init__(self, game: PgnGame) -> None:
        self.game = game
        self.calls: list[int] = []

    def load_book_game(self, game_id: int) -> PgnGame:
        self.calls.append(game_id)
        if game_id != 73:
            raise LookupError(game_id)
        return self.game


def run_oracle(*, scan_limit: int, accepted_target: int) -> dict[str, object]:
    if type(scan_limit) is not int or isinstance(scan_limit, bool) or scan_limit < 1:
        raise ValueError("scan_limit must be a positive exact integer")
    if type(accepted_target) is not int or isinstance(accepted_target, bool) or accepted_target < 32:
        raise ValueError("accepted_target must be an exact integer of at least 32")
    if accepted_target > scan_limit:
        raise ValueError("accepted_target cannot exceed scan_limit")

    accepted = 0
    parser_rejected = 0
    parser_warning_records = 0
    comment_games = 0
    nag_games = 0
    rav_games = 0
    nested_rav_games = 0
    unicode_games = 0
    max_variation_depth = 0
    sample_record_sha256: list[str] = []
    reference_source: PgnGame | None = None
    reference_source_serialized: str | None = None
    variation_record_hash: str | None = None

    with tempfile.TemporaryDirectory(prefix="accessible-chess-book-corpus-") as temp_dir:
        archive = Path(temp_dir) / "broadcast.pgn.zst"
        _download_verified(archive)
        source, reader, text = _open_zstd_text(archive)
        try:
            for record_index, raw in enumerate(
                iter_transport_records(text, limit=scan_limit), start=1
            ):
                try:
                    direct_games = parse_pgn_text(raw, strict=False)
                except (PgnRoundTripError, RecursionError):
                    parser_rejected += 1
                    continue
                if len(direct_games) != 1:
                    parser_rejected += 1
                    continue
                direct = direct_games[0]
                if direct.warnings:
                    parser_warning_records += 1
                    continue

                direct_serialized = serialize_game(direct)
                block = Game(
                    pgn=raw,
                    title=f"Pinned real broadcast game {record_index}",
                    block_id=f"real-game-{record_index}",
                    source_anchor=f"{CORPUS.name}:{record_index}",
                )
                resolved = resolve_book_game(block)
                if resolved.source is not BookGameSource.EMBEDDED:
                    raise AssertionError("real Book Game did not resolve as embedded content")
                if resolved.block_id != block.block_id or resolved.source_anchor != block.source_anchor:
                    raise AssertionError("Book semantic identity changed at the GameTree boundary")
                if resolved.warnings:
                    raise AssertionError("warning-free canonical D06 game gained warnings through Books")
                if serialize_game(resolved.game) != direct_serialized:
                    raise AssertionError("Book Game boundary changed canonical D06 GameTree serialization")

                comments, nags, rav, depth = _line_metrics(resolved.game.line)
                accepted += 1
                comment_games += int(comments > 0)
                nag_games += int(nags > 0)
                rav_games += int(rav > 0)
                nested_rav_games += int(depth > 1)
                unicode_games += int(any(ord(character) > 127 for character in raw))
                max_variation_depth = max(max_variation_depth, depth)

                record_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                if len(sample_record_sha256) < 16:
                    sample_record_sha256.append(record_hash)

                if reference_source is None and comments > 0 and nags > 0:
                    reference_source = direct
                    reference_source_serialized = direct_serialized

                if (
                    variation_record_hash is None
                    and rav > 0
                    and direct.tags.get("SetUp") != "1"
                    and "FEN" not in direct.tags
                ):
                    variation = resolve_book_variation(
                        VariationTree(
                            root_fen=START_FEN,
                            pgn=raw,
                            title="Pinned real annotated variation tree",
                            block_id=f"real-variation-{record_index}",
                            source_anchor=f"{CORPUS.name}:{record_index}",
                        )
                    )
                    if variation.root_fen != START_FEN:
                        raise AssertionError("Book VariationTree root changed")
                    if serialize_game(variation.game) != direct_serialized:
                        raise AssertionError(
                            "Book VariationTree boundary changed canonical D06 GameTree serialization"
                        )
                    variation_record_hash = record_hash

                quotas_met = (
                    accepted >= accepted_target
                    and comment_games >= 24
                    and nag_games >= 12
                    and rav_games >= 1
                    and unicode_games >= 1
                    and reference_source is not None
                    and variation_record_hash is not None
                )
                if quotas_met:
                    break
        finally:
            text.close()
            reader.close()
            source.close()

    if accepted < accepted_target:
        raise AssertionError(f"only {accepted} clean real Book games accepted")
    if comment_games < 24:
        raise AssertionError(f"real Book corpus has insufficient comment coverage: {comment_games}")
    if nag_games < 12:
        raise AssertionError(f"real Book corpus has insufficient NAG coverage: {nag_games}")
    if rav_games < 1 or variation_record_hash is None:
        raise AssertionError("real Book corpus did not exercise a canonical RAV VariationTree")
    if unicode_games < 1:
        raise AssertionError("real Book corpus did not exercise Unicode source material")
    if reference_source is None or reference_source_serialized is None:
        raise AssertionError("real Book corpus did not provide a canonical reference-mode candidate")

    lookup = _RealCanonicalLookup(reference_source)
    referenced = resolve_book_game(Game(game_id=73, title="Real canonical reference"), lookup=lookup)
    if lookup.calls != [73]:
        raise AssertionError("Book reference lookup call identity changed")
    if referenced.source is not BookGameSource.REFERENCE:
        raise AssertionError("real Book reference did not resolve through reference mode")
    if referenced.game is reference_source:
        raise AssertionError("Book reference mode returned caller-owned mutable GameTree")
    if serialize_game(referenced.game) != reference_source_serialized:
        raise AssertionError("Book reference mode changed the real canonical GameTree")

    report: dict[str, object] = {
        "source_name": CORPUS.name,
        "source_url": CORPUS.url,
        "source_sha256": CORPUS.sha256,
        "source_license": CORPUS.license,
        "source_published_games": CORPUS.published_games,
        "canonical_ingress": "acs.pgn_roundtrip.parse_pgn_text(strict=False)",
        "scan_limit": scan_limit,
        "accepted_book_games": accepted,
        "parser_rejected_records": parser_rejected,
        "parser_warning_records": parser_warning_records,
        "comment_games": comment_games,
        "nag_games": nag_games,
        "rav_games": rav_games,
        "nested_rav_games": nested_rav_games,
        "unicode_games": unicode_games,
        "max_variation_depth": max_variation_depth,
        "variation_tree_real_record_sha256": variation_record_hash,
        "reference_mode_real_game": True,
        "sample_record_sha256": sample_record_sha256,
        "product_mutation": False,
        "pgn_parser_support_claimed_here": False,
        "library_integration_claimed_here": False,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-limit", type=int, default=_DEFAULT_SCAN_LIMIT)
    parser.add_argument("--accepted-target", type=int, default=_DEFAULT_ACCEPTED_TARGET)
    arguments = parser.parse_args()
    report = run_oracle(
        scan_limit=arguments.scan_limit,
        accepted_target=arguments.accepted_target,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    print("BOOK REAL GAME CORPUS QA PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
