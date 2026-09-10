from __future__ import annotations

"""Bounded real SetUp/FEN + recursive-RAV acceptance from Lichess CC0 eval data.

The source is the official Lichess evaluation export.  Only a fixed-size prefix
is read; the network response is closed immediately after that bound.  PGN and
chess semantics are *not* implemented here: FEN validation, UCI move parsing,
legal move application and SAN production are delegated to ``acs.chesscore``;
recursive variation legality is delegated to ``acs.gametree_legality``; PGN
round-trip and editing use the canonical D06 Product APIs.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen

import zstandard

from acs.chesscore import Board
from acs.gametree import Comment, MoveNode, PgnGame, VariationLine
from acs.gametree_annotations import MoveAnnotationPatch, move_annotation_target
from acs.gametree_legality import validate_game_legality
from acs.gametree_navigation import GameTreeCursor, VariationStep
from acs.pgn_document import PgnDocumentSession
from acs.pgn_roundtrip import parse_pgn_text, serialize_pgn_text
from acs.pgn_workspace import PgnWorkspace


EVAL_URL = "https://database.lichess.org/lichess_db_eval.jsonl.zst"
LICENSE = "CC0"
SOURCE_UPDATED = "2026-08-02"
MAX_COMPRESSED_PREFIX = 8 * 1024 * 1024
MAX_JSON_LINES = 120_000
MIN_PV_PLIES = 4
# Exact 8 MiB prefix discovered by run 33169545957 on both Ubuntu and Windows.
# Terminal PGN-03 evidence fails closed if the live CC0 export prefix drifts.
EXPECTED_PREFIX_SHA256 = "1ab774b1f4ce4558bac6c21f76eef14776b10ad56e07fe45fc02ec867f0ace87"


def _download_prefix() -> tuple[bytes, dict[str, str | int | None]]:
    request = Request(
        EVAL_URL,
        headers={"User-Agent": "Accessible-Chess-PGN-03-real-corpus/1"},
    )
    with urlopen(request, timeout=45) as response:
        payload = response.read(MAX_COMPRESSED_PREFIX)
        metadata = {
            "status": getattr(response, "status", None),
            "content_type": response.headers.get("Content-Type"),
            "last_modified": response.headers.get("Last-Modified"),
            "etag": response.headers.get("ETag"),
        }
    if not payload:
        raise AssertionError("Lichess evaluation source returned no bytes")
    if len(payload) != MAX_COMPRESSED_PREFIX:
        raise AssertionError(
            f"bounded evaluation prefix was short: {len(payload)} != {MAX_COMPRESSED_PREFIX}"
        )
    digest = hashlib.sha256(payload).hexdigest()
    if EXPECTED_PREFIX_SHA256 is not None and digest != EXPECTED_PREFIX_SHA256:
        raise AssertionError(
            "Lichess evaluation prefix drifted from the pinned PGN-03 evidence source"
        )
    metadata["prefix_bytes"] = len(payload)
    metadata["prefix_sha256"] = digest
    return payload, metadata


def _iter_json_records(prefix: bytes):
    source = io.BytesIO(prefix)
    reader = zstandard.ZstdDecompressor().stream_reader(source)
    text = io.TextIOWrapper(reader, encoding="utf-8", errors="strict", newline="\n")
    try:
        for line_number in range(1, MAX_JSON_LINES + 1):
            try:
                line = text.readline()
            except (EOFError, zstandard.ZstdError):
                return
            if not line:
                return
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # A bounded compressed prefix may end in a partial JSON line.
                return
            if not isinstance(record, dict):
                raise AssertionError("evaluation record is not a JSON object")
            yield line_number, line, record
    finally:
        text.close()


def _canonical_sans(fen: str, tokens: tuple[str, ...]) -> tuple[str, ...]:
    board = Board(fen)
    sans: list[str] = []
    for token in tokens:
        move = board.parse_move(token)
        sans.append(board.push(move))
    return tuple(sans)


def _common_prefix(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    length = 0
    for a, b in zip(left, right):
        if a != b:
            break
        length += 1
    return length


def _legal_sequences(record: dict) -> tuple[str, tuple[tuple[str, ...], ...]]:
    fen = record.get("fen")
    evals = record.get("evals")
    if not isinstance(fen, str) or not isinstance(evals, list):
        return "", ()
    try:
        canonical_fen = Board(fen).fen()
    except Exception:
        return "", ()

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
            if len(tokens) < MIN_PV_PLIES or tokens in seen:
                continue
            try:
                _canonical_sans(canonical_fen, tokens)
            except Exception:
                # The export uses UCI_Chess960.  Skip lines whose castling or
                # variant encoding the standard canonical Board does not own.
                continue
            seen.add(tokens)
            sequences.append(tokens)
    return canonical_fen, tuple(sequences)


def _nested_triple(sequences: tuple[tuple[str, ...], ...]):
    """Find A mainline, B branch from A, and C branch later from B."""

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


def _build_nested_game(
    fen: str,
    triple: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], int, int],
) -> tuple[PgnGame, tuple[str, ...], tuple[str, ...], tuple[str, ...], int, int]:
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
    return game, a_san, b_san, c_san, first_branch, nested_branch


def _end_to_end(
    game: PgnGame,
    *,
    c_san: tuple[str, ...],
    first_branch: int,
    nested_branch: int,
) -> dict[str, object]:
    legality = validate_game_legality(game)
    if not legality.complete or legality.issues:
        raise AssertionError(
            "canonical legality rejected real FEN/RAV tree: "
            + "; ".join(issue.code.value for issue in legality.issues[:8])
        )

    initial_text = serialize_pgn_text((game,))
    parsed = parse_pgn_text(initial_text, strict=True)
    if len(parsed) != 1 or parsed[0] != game:
        raise AssertionError("real FEN/RAV GameTree changed under strict serialization")
    if serialize_pgn_text(parsed) != initial_text:
        raise AssertionError("real FEN/RAV serialization is nondeterministic")

    workspace = PgnWorkspace.from_text(initial_text)
    nested_path = (
        VariationStep(first_branch, 0),
        VariationStep(nested_branch - first_branch, 0),
    )
    workspace.set_cursor(GameTreeCursor(nested_path, 0))
    current = workspace.current_move()
    if current is None or current.san != c_san[nested_branch]:
        raise AssertionError("workspace did not navigate to the real nested RAV move")

    before_revision = workspace.content_revision
    target = move_annotation_target(workspace.current_game(), nested_path, 0)
    workspace.edit_move_annotations(
        target,
        MoveAnnotationPatch(
            comments_after=(Comment("PGN-03 real Lichess evaluation edit"),),
        ),
    )
    if not workspace.dirty or workspace.content_revision != before_revision + 1:
        raise AssertionError("nested real-RAV edit did not update canonical workspace state")

    edited_game = workspace.current_game()
    edited_legality = validate_game_legality(edited_game)
    if not edited_legality.complete or edited_legality.issues:
        raise AssertionError("annotation edit changed real FEN/RAV chess legality")

    with tempfile.TemporaryDirectory(prefix="accessible-chess-real-eval-") as directory:
        destination = Path(directory) / "real-eval-rav.pgn"
        session = PgnDocumentSession.from_text(workspace.to_text())
        saved_before = session.workspace.games()
        session.save_as(destination)
        reopened = PgnDocumentSession.open(destination)
        if reopened.workspace.games() != saved_before:
            raise AssertionError("Save As/reopen changed real FEN/RAV canonical GameTree")
        if reopened.view().global_warnings or not reopened.view().source_overwrite_safe:
            raise AssertionError("strict real FEN/RAV Save As copy reopened with recovery state")
        if reopened.copy_pgn() != session.copy_pgn():
            raise AssertionError("real FEN/RAV reopened serialization changed")

    return {
        "start_fen": legality.start_fen,
        "legal_move_projections": legality.legal_move_count,
        "nested_path_depth": len(nested_path),
        "edited_revision": workspace.content_revision,
    }


def run() -> int:
    prefix, source_metadata = _download_prefix()
    scanned = 0
    legal_multi_pv = 0
    max_sequences = 0
    for line_number, raw_line, record in _iter_json_records(prefix):
        scanned += 1
        fen, sequences = _legal_sequences(record)
        if len(sequences) < 2:
            continue
        legal_multi_pv += 1
        max_sequences = max(max_sequences, len(sequences))
        triple = _nested_triple(sequences)
        if triple is None:
            continue

        game, a_san, b_san, c_san, first_branch, nested_branch = _build_nested_game(
            fen, triple
        )
        e2e = _end_to_end(
            game,
            c_san=c_san,
            first_branch=first_branch,
            nested_branch=nested_branch,
        )
        payload = {
            "schema": 1,
            "source": "Lichess evaluation database",
            "license": LICENSE,
            "source_updated": SOURCE_UPDATED,
            "url": EVAL_URL,
            "source_metadata": source_metadata,
            "scanned_json_records": scanned,
            "legal_multi_pv_records_seen": legal_multi_pv,
            "max_distinct_legal_pvs_seen": max_sequences,
            "candidate_line_number": line_number,
            "candidate_record_sha256": hashlib.sha256(raw_line.encode("utf-8")).hexdigest(),
            "candidate_fen": fen,
            "candidate_fen_sha256": hashlib.sha256(fen.encode("utf-8")).hexdigest(),
            "mainline_plies": len(a_san),
            "branch_plies": len(b_san) - first_branch,
            "nested_branch_plies": len(c_san) - nested_branch,
            "first_branch_index": first_branch,
            "nested_branch_index": nested_branch,
            "e2e": e2e,
            "prefix_pinned": EXPECTED_PREFIX_SHA256 is not None,
        }
        print("PGN_REAL_EVAL_RAV_REPORT=" + json.dumps(payload, sort_keys=True))
        print("PGN REAL EVAL FEN NESTED RAV PASS")
        return 0

    payload = {
        "schema": 1,
        "source": "Lichess evaluation database",
        "license": LICENSE,
        "source_updated": SOURCE_UPDATED,
        "source_metadata": source_metadata,
        "scanned_json_records": scanned,
        "legal_multi_pv_records_seen": legal_multi_pv,
        "max_distinct_legal_pvs_seen": max_sequences,
        "prefix_pinned": EXPECTED_PREFIX_SHA256 is not None,
        "status": "CORPUS_EVIDENCE_NOT_FOUND",
    }
    print("PGN_REAL_EVAL_RAV_REPORT=" + json.dumps(payload, sort_keys=True))
    raise AssertionError(
        "bounded Lichess prefix contained no canonical-legal nested-PV triple; "
        "do not claim real nested-RAV evidence"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
