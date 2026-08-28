from __future__ import annotations

"""Locate the first real PGN-05 strict-vs-file-ingress divergence.

This is diagnostic evidence only. It reuses the pinned PGN-05 transport source
and compares canonical strict D06 parsing with the exact structural parser path
currently used by the file service. No PGN or chess semantics are implemented
here and Product is not modified.
"""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from acs.gametree import parse_games
from acs.pgn_document import PgnDocumentSession
from acs.pgn_roundtrip import (
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    parse_pgn_text,
    serialize_pgn_text,
)
from scripts import pgn_large_resource_perf_oracle as corpus


def _nodes(line, path: tuple[tuple[int, int], ...] = ()):
    for move_index, node in enumerate(line.moves):
        yield path, move_index, node
        for variation_index, variation in enumerate(node.variations):
            child_path = path + ((move_index, variation_index),)
            yield from _nodes(variation, child_path)


def _first_semantic_difference(strict_game, direct_game) -> dict[str, object] | None:
    strict_nodes = list(_nodes(strict_game.line))
    direct_nodes = list(_nodes(direct_game.line))
    if len(strict_nodes) != len(direct_nodes):
        return {
            "kind": "node_count",
            "strict_nodes": len(strict_nodes),
            "direct_nodes": len(direct_nodes),
        }
    for strict_item, direct_item in zip(strict_nodes, direct_nodes):
        strict_path, strict_index, strict_node = strict_item
        direct_path, direct_index, direct_node = direct_item
        if strict_path != direct_path or strict_index != direct_index:
            return {
                "kind": "address",
                "strict_path": repr(strict_path),
                "direct_path": repr(direct_path),
                "strict_move_index": strict_index,
                "direct_move_index": direct_index,
            }
        if strict_node.san != direct_node.san or strict_node.nags != direct_node.nags:
            return {
                "kind": "san_or_nag",
                "path": repr(strict_path),
                "move_index": strict_index,
                "strict_san": strict_node.san,
                "direct_san": direct_node.san,
                "strict_nags": list(strict_node.nags),
                "direct_nags": list(direct_node.nags),
            }
    return None


def _single_record_document_result(raw: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="accessible-chess-pgn05-diagnostic-") as directory:
        path = Path(directory) / "record.pgn"
        path.write_text(raw, encoding="utf-8", newline="\n")
        try:
            session = PgnDocumentSession.open(path)
        except Exception as exc:
            return {
                "status": "rejected",
                "exception": type(exc).__name__,
                "message": str(exc),
            }
        return {
            "status": "accepted",
            "game_count": session.view().game_count,
            "warnings": list(session.view().global_warnings),
        }


def run(limit: int) -> int:
    with tempfile.TemporaryDirectory(prefix="accessible-chess-pgn05-diagnostic-corpus-") as directory:
        compressed = Path(directory) / "lichess-standard-2013-01.pgn.zst"
        source = corpus._download_verified(compressed)
        with corpus._open_zstd_text(compressed) as stream:
            records = list(corpus.iter_complete_records(stream, limit=limit))

    if len(records) != limit:
        raise AssertionError(f"diagnostic received {len(records)} records, expected {limit}")

    for record_index, raw in enumerate(records, start=1):
        strict_games = parse_pgn_text(raw, strict=True)
        if len(strict_games) != 1:
            raise AssertionError(f"strict record {record_index} changed cardinality")
        direct_games = tuple(parse_games(raw))
        if len(direct_games) != 1:
            raise AssertionError(f"direct structural record {record_index} changed cardinality")

        direct_error: PgnRoundTripError | None = None
        try:
            serialize_pgn_text(direct_games)
        except PgnRoundTripError as exc:
            direct_error = exc

        difference = _first_semantic_difference(strict_games[0], direct_games[0])
        if direct_error is None and difference is None:
            continue

        strict_game = strict_games[0]
        payload = {
            "schema": 1,
            "source": "Lichess standard rated 2013-01",
            "source_license": corpus.CORPUS_LICENSE,
            "source_sha256": corpus.CORPUS_SHA256,
            "record_index": record_index,
            "record_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "event": strict_game.tags.get("Event", ""),
            "white": strict_game.tags.get("White", ""),
            "black": strict_game.tags.get("Black", ""),
            "strict_ingress": "ACCEPTED",
            "direct_structural_serialize": (
                "ACCEPTED" if direct_error is None else "REJECTED"
            ),
            "direct_error_code": (
                None if direct_error is None else direct_error.code.value
            ),
            "difference": difference,
            "single_record_document": _single_record_document_result(raw),
            "diagnosis": (
                "FILE_DOCUMENT_INGRESS_BYPASSES_CANONICAL_STRICT_NORMALIZATION"
                if direct_error is not None
                and direct_error.code is PgnRoundTripErrorCode.INVALID_SAN
                and difference is not None
                and difference.get("kind") == "san_or_nag"
                else "UNCLASSIFIED_INGRESS_DIVERGENCE"
            ),
            "product_mutation": "NONE",
            "download": source,
        }
        print("PGN05_DOCUMENT_INGRESS_DEFECT=" + json.dumps(payload, sort_keys=True))
        print("PGN-05 DOCUMENT INGRESS DIVERGENCE FOUND")
        return 0

    payload = {
        "schema": 1,
        "records_checked": limit,
        "source_sha256": corpus.CORPUS_SHA256,
        "status": "NO_DIVERGENCE_FOUND",
    }
    print("PGN05_DOCUMENT_INGRESS_DEFECT=" + json.dumps(payload, sort_keys=True))
    print("PGN-05 DOCUMENT INGRESS DIVERGENCE NOT REPRODUCED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit must be positive")
    return run(args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
