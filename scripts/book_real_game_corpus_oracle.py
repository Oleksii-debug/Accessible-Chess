from __future__ import annotations

"""Real legal annotated-material evidence for the V2 Books GameTree envelope.

This module is QA/evidence only. It does not implement PGN semantics, chess
rules, book import, Library storage, or UI behavior. Real broadcast PGN exercises
Book ``Game`` and reference content through the bounded D06 ingress. A separately
pinned Lichess CC0 evaluation record, already independently qualified by PGN-03,
provides a real nested-variation source for Book ``VariationTree``. All chess
legality, SAN production, GameTree serialization, and PGN parsing delegate to
canonical Accessible Chess APIs.
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
from acs.chesscore import Board
from acs.gametree import MoveNode, PgnGame, VariationLine, serialize_game
from acs.gametree_legality import validate_game_legality
from acs.pgn_roundtrip import PgnRoundTripError, parse_pgn_text, serialize_pgn_text


_MAX_COMPRESSED_BYTES = 32 * 1024 * 1024
_DOWNLOAD_CHUNK = 1024 * 1024
_DEFAULT_SCAN_LIMIT = 2000
_DEFAULT_ACCEPTED_TARGET = 96

EVAL_URL = "https://database.lichess.org/lichess_db_eval.jsonl.zst"
EVAL_LICENSE = "CC0"
EVAL_SOURCE_UPDATED = "2026-08-02"
EVAL_PREFIX_BYTES = 8 * 1024 * 1024
EVAL_PREFIX_SHA256 = "1ab774b1f4ce4558bac6c21f76eef14776b10ad56e07fe45fc02ec867f0ace87"
EVAL_CANDIDATE_LINE = 2
EVAL_CANDIDATE_RECORD_SHA256 = "af61c8a9631f1156f12d3a17bbdeb822b8073c6e1bbcfcb0b21e04afdd90502a"
EVAL_CANDIDATE_FEN = "8/4r3/2R2pk1/6pp/3P4/6P1/5K1P/8 b - - 0 1"
_MIN_PV_PLIES = 4


@dataclass(frozen=True, slots=True)
class CorpusSpec:
    name: str
    url: str
    sha256: str
    license: str
    published_games: int


BROADCAST_CORPUS = CorpusSpec(
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


def _download_broadcast_verified(destination: Path) -> None:
    request = Request(
        BROADCAST_CORPUS.url,
        headers={"User-Agent": "Accessible-Chess-Book-Corpus-QA/1"},
    )
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
    if actual != BROADCAST_CORPUS.sha256:
        raise RuntimeError(
            "external broadcast digest mismatch: "
            f"expected {BROADCAST_CORPUS.sha256}, got {actual}"
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


def _download_eval_prefix() -> bytes:
    request = Request(
        EVAL_URL,
        headers={"User-Agent": "Accessible-Chess-Book-Corpus-QA/1"},
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = response.read(EVAL_PREFIX_BYTES)
    except Exception as exc:
        raise RuntimeError(f"evaluation corpus download failed: {type(exc).__name__}") from exc
    if len(payload) != EVAL_PREFIX_BYTES:
        raise AssertionError(
            f"bounded evaluation prefix was short: {len(payload)} != {EVAL_PREFIX_BYTES}"
        )
    actual = hashlib.sha256(payload).hexdigest()
    if actual != EVAL_PREFIX_SHA256:
        raise AssertionError(
            f"evaluation corpus prefix digest drifted: expected {EVAL_PREFIX_SHA256}, got {actual}"
        )
    return payload


def _eval_candidate(prefix: bytes) -> tuple[str, dict[str, object]]:
    try:
        import zstandard  # type: ignore
    except ImportError as exc:
        raise RuntimeError("zstandard is required only for real-corpus QA") from exc

    source = io.BytesIO(prefix)
    reader = zstandard.ZstdDecompressor().stream_reader(source)
    text = io.TextIOWrapper(reader, encoding="utf-8", errors="strict", newline="\n")
    candidate = ""
    try:
        for line_number in range(1, EVAL_CANDIDATE_LINE + 1):
            line = text.readline()
            if not line:
                raise AssertionError(
                    f"evaluation corpus ended before pinned line {EVAL_CANDIDATE_LINE}"
                )
            if line_number == EVAL_CANDIDATE_LINE:
                candidate = line.strip()
    finally:
        text.close()

    if not candidate:
        raise AssertionError("pinned evaluation candidate is empty")
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    if digest != EVAL_CANDIDATE_RECORD_SHA256:
        raise AssertionError(
            "pinned evaluation candidate record drifted from independently qualified PGN-03 evidence"
        )
    try:
        record = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AssertionError("pinned evaluation candidate is not valid JSON") from exc
    if not isinstance(record, dict):
        raise AssertionError("pinned evaluation candidate is not an object")
    return candidate, record


def _canonical_sans(fen: str, tokens: tuple[str, ...]) -> tuple[str, ...]:
    board = Board(fen)
    sans: list[str] = []
    for token in tokens:
        move = board.parse_move(token)
        sans.append(board.push(move))
    return tuple(sans)


def _legal_sequences(record: dict[str, object]) -> tuple[str, tuple[tuple[str, ...], ...]]:
    fen = record.get("fen")
    evals = record.get("evals")
    if not isinstance(fen, str) or not isinstance(evals, list):
        raise AssertionError("pinned evaluation record lacks FEN/evals")
    canonical_fen = Board(fen).fen()
    if canonical_fen != EVAL_CANDIDATE_FEN:
        raise AssertionError("pinned evaluation candidate FEN drifted")

    seen: set[tuple[str, ...]] = set()
    sequences: list[tuple[str, ...]] = []
    for evaluation in evals:
        if not isinstance(evaluation, dict):
            continue
        pvs = evaluation.get("pvs")
        if not isinstance(pvs, list):
            continue
        for pv in pvs:
            if not isinstance(pv, dict):
                continue
            line = pv.get("line")
            if not isinstance(line, str):
                continue
            tokens = tuple(line.split())
            if len(tokens) < _MIN_PV_PLIES or tokens in seen:
                continue
            try:
                _canonical_sans(canonical_fen, tokens)
            except Exception:
                continue
            seen.add(tokens)
            sequences.append(tokens)
    return canonical_fen, tuple(sequences)


def _common_prefix(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    length = 0
    for left_token, right_token in zip(left, right):
        if left_token != right_token:
            break
        length += 1
    return length


def _nested_triple(sequences: tuple[tuple[str, ...], ...]):
    for a_index, a in enumerate(sequences):
        for b_index, b in enumerate(sequences):
            if b_index == a_index:
                continue
            first_branch = _common_prefix(a, b)
            if first_branch >= min(len(a), len(b)):
                continue
            for c_index, c in enumerate(sequences):
                if c_index in {a_index, b_index}:
                    continue
                if _common_prefix(a, c) != first_branch:
                    continue
                nested_branch = _common_prefix(b, c)
                if nested_branch <= first_branch:
                    continue
                if nested_branch >= min(len(b), len(c)):
                    continue
                return a, b, c, first_branch, nested_branch
    return None


def _nodes(sans: tuple[str, ...]) -> list[MoveNode]:
    return [MoveNode(san) for san in sans]


def _build_real_eval_game(
    fen: str,
    triple: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], int, int],
) -> tuple[PgnGame, int, int]:
    a, b, c, first_branch, nested_branch = triple
    a_san = _canonical_sans(fen, a)
    b_san = _canonical_sans(fen, b)
    c_san = _canonical_sans(fen, c)

    root = VariationLine(moves=_nodes(a_san), result="*")
    b_line = VariationLine(moves=_nodes(b_san[first_branch:]))
    c_line = VariationLine(moves=_nodes(c_san[nested_branch:]))
    root.moves[first_branch].variations.append(b_line)
    b_line.moves[nested_branch - first_branch].variations.append(c_line)
    game = PgnGame(
        tags={
            "Event": "Lichess CC0 real evaluation",
            "Site": "database.lichess.org",
            "SetUp": "1",
            "FEN": fen,
            "Result": "*",
        },
        line=root,
    )
    return game, first_branch, nested_branch


def _real_eval_variation_evidence() -> dict[str, object]:
    prefix = _download_eval_prefix()
    raw_record, record = _eval_candidate(prefix)
    fen, sequences = _legal_sequences(record)
    if len(sequences) < 7:
        raise AssertionError(
            f"pinned evaluation candidate lost real legal PVs: {len(sequences)} < 7"
        )
    triple = _nested_triple(sequences)
    if triple is None:
        raise AssertionError("pinned evaluation candidate lost its real nested-PV topology")

    game, first_branch, nested_branch = _build_real_eval_game(fen, triple)
    legality = validate_game_legality(game)
    if not legality.complete or legality.issues:
        raise AssertionError("canonical legality rejected pinned real evaluation variation tree")

    canonical_text = serialize_pgn_text((game,))
    resolved = resolve_book_variation(
        VariationTree(
            root_fen=fen,
            pgn=canonical_text,
            title="Pinned real Lichess evaluation variation tree",
            block_id="real-eval-variation",
            source_anchor=f"lichess-eval:{EVAL_CANDIDATE_RECORD_SHA256}",
        )
    )
    if resolved.root_fen != fen:
        raise AssertionError("Book VariationTree changed the pinned real evaluation FEN")
    if serialize_pgn_text((resolved.game,)) != canonical_text:
        raise AssertionError("Book VariationTree changed pinned real evaluation GameTree serialization")
    resolved_legality = validate_game_legality(resolved.game)
    if not resolved_legality.complete or resolved_legality.issues:
        raise AssertionError("Book VariationTree changed real evaluation chess legality")

    comments, nags, rav, depth = _line_metrics(resolved.game.line)
    if rav < 2 or depth < 2:
        raise AssertionError(
            f"Book VariationTree did not preserve real nested RAV topology: rav={rav}, depth={depth}"
        )

    return {
        "source": "Lichess evaluation database",
        "license": EVAL_LICENSE,
        "source_updated": EVAL_SOURCE_UPDATED,
        "url": EVAL_URL,
        "prefix_bytes": EVAL_PREFIX_BYTES,
        "prefix_sha256": EVAL_PREFIX_SHA256,
        "candidate_line": EVAL_CANDIDATE_LINE,
        "candidate_record_sha256": hashlib.sha256(raw_record.encode("utf-8")).hexdigest(),
        "candidate_fen": fen,
        "distinct_canonical_legal_pvs": len(sequences),
        "first_branch_index": first_branch,
        "nested_branch_index": nested_branch,
        "book_rav_branches": rav,
        "book_nested_depth": depth,
        "canonical_legal_move_projections": resolved_legality.legal_move_count,
        "canonical_text_sha256": hashlib.sha256(canonical_text.encode("utf-8")).hexdigest(),
        "comments_in_generated_semantic_tree": comments,
        "nags_in_generated_semantic_tree": nags,
    }


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
    broadcast_rav_games = 0
    unicode_games = 0
    max_broadcast_variation_depth = 0
    sample_record_sha256: list[str] = []
    reference_source: PgnGame | None = None
    reference_source_serialized: str | None = None

    with tempfile.TemporaryDirectory(prefix="accessible-chess-book-corpus-") as temp_dir:
        archive = Path(temp_dir) / "broadcast.pgn.zst"
        _download_broadcast_verified(archive)
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
                    source_anchor=f"{BROADCAST_CORPUS.name}:{record_index}",
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
                broadcast_rav_games += int(rav > 0)
                unicode_games += int(any(ord(character) > 127 for character in raw))
                max_broadcast_variation_depth = max(max_broadcast_variation_depth, depth)

                record_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                if len(sample_record_sha256) < 16:
                    sample_record_sha256.append(record_hash)

                if reference_source is None and comments > 0 and nags > 0:
                    reference_source = direct
                    reference_source_serialized = direct_serialized

                quotas_met = (
                    accepted >= accepted_target
                    and comment_games >= 24
                    and nag_games >= 12
                    and unicode_games >= 1
                    and reference_source is not None
                )
                if quotas_met:
                    break
        finally:
            text.close()
            reader.close()
            source.close()

    partial = {
        "accepted_book_games": accepted,
        "comment_games": comment_games,
        "nag_games": nag_games,
        "unicode_games": unicode_games,
        "broadcast_rav_games_observed": broadcast_rav_games,
        "parser_rejected_records": parser_rejected,
        "parser_warning_records": parser_warning_records,
    }
    print("BOOK_REAL_BROADCAST_PARTIAL=" + json.dumps(partial, sort_keys=True))

    if accepted < accepted_target:
        raise AssertionError(f"only {accepted} clean real Book games accepted")
    if comment_games < 24:
        raise AssertionError(f"real Book corpus has insufficient comment coverage: {comment_games}")
    if nag_games < 12:
        raise AssertionError(f"real Book corpus has insufficient NAG coverage: {nag_games}")
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

    variation_evidence = _real_eval_variation_evidence()

    report: dict[str, object] = {
        "source_name": BROADCAST_CORPUS.name,
        "source_url": BROADCAST_CORPUS.url,
        "source_sha256": BROADCAST_CORPUS.sha256,
        "source_license": BROADCAST_CORPUS.license,
        "source_published_games": BROADCAST_CORPUS.published_games,
        "canonical_ingress": "acs.pgn_roundtrip.parse_pgn_text(strict=False)",
        "scan_limit": scan_limit,
        "accepted_book_games": accepted,
        "parser_rejected_records": parser_rejected,
        "parser_warning_records": parser_warning_records,
        "comment_games": comment_games,
        "nag_games": nag_games,
        "unicode_games": unicode_games,
        "broadcast_rav_games_observed": broadcast_rav_games,
        "max_broadcast_variation_depth": max_broadcast_variation_depth,
        "reference_mode_real_game": True,
        "sample_record_sha256": sample_record_sha256,
        "real_variation_tree": variation_evidence,
        "product_mutation": False,
        "pgn_parser_support_claimed_here": False,
        "raw_eval_decoder_support_claimed_here": False,
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
