"""Real 3000+ Lichess puzzle-rated CC0 original rows, product-offline copy.

Historical FeXd original dataset rows have explicit provenance; its GPL app code
is NOT imported. Original exact-upstream source checkout comparison still belongs
to the separately configured Section 37 CI and is not self-attested here.
"""
from __future__ import annotations
import hashlib
import json

SOURCE_ID = "lichess_cc0_extreme_4_original_derived_puzzles"
SOURCE_SHA256 = "f6b4ce3953806ebd68462296e7579f88462d5f71f1cdb9badeb2220af542332e"
_SOURCE_JSON = "{\n  \"schema\": \"accessible-chess-section37-original-extreme-training-cc0-v1\",\n  \"original_repository\": \"https://github.com/FeXd/puzzle-chess\",\n  \"original_dataset\": \"puzzles/offline/puzzles.csv\",\n  \"original_repo_git_blob\": \"acb74625e5ebd0ae9b454779a371ac87091c8c0e\",\n  \"original_dataset_sha256\": \"NOT_OBTAINED_IN_THIS_PASS\",\n  \"original_rows_at_source_snapshot\": 24595,\n  \"rights\": \"Original chess puzzles from Lichess CC0, historic mirror source FeXd GPL software; puzzle fact data is CC0\",\n  \"target\": \"above-first-category master-to-GM-aspiration calculation, practical high rated puzzles\",\n  \"publication_scope\": \"CC0 puzzle data only with attribution, not external GPL UI or copyrighted study collection\",\n  \"source_readback_required\": \"CI MUST compare every selected row to exact original pinned Git blob checkout; until then excerpt-mapped real rows, not exact-head CI PASS\",\n  \"puzzle_count\": 4,\n  \"puzzles\": [\n    {\n      \"puzzle_id\": \"2zH3K\",\n      \"puzzle_rating\": 3000,\n      \"fen_before_opponent_move\": \"8/4kB2/p5p1/2P2p1p/1P6/P3P1K1/8/1b6 w - - 1 40\",\n      \"uci_moves_opponent_first\": \"f7g6 f5f4 e3f4 b1g6 a3a4 e7e6 b4b5 a6a5 g3h4 g6c2 f4f5 e6f5 b5b6 c2e4 c5c6 e4c6\",\n      \"original_upstream_zero_based_line\": 24560,\n      \"rating_system\": \"Lichess puzzle, not FIDE Elo\",\n      \"composed_study\": false,\n      \"requires_opponent_first_move_before_presenting\": true\n    },\n    {\n      \"puzzle_id\": \"VvOSE\",\n      \"puzzle_rating\": 3030,\n      \"fen_before_opponent_move\": \"8/8/4p3/p5P1/3k4/2pnN3/P3K2P/8 w - - 1 47\",\n      \"uci_moves_opponent_first\": \"h2h4 d3f4 e2f3 e6e5 g5g6 f4g6 h4h5 g6f4 h5h6 d4d3 h6h7 f4g6 f3f2 g6h8\",\n      \"original_upstream_zero_based_line\": 24579,\n      \"rating_system\": \"Lichess puzzle, not FIDE Elo\",\n      \"composed_study\": false,\n      \"requires_opponent_first_move_before_presenting\": true\n    },\n    {\n      \"puzzle_id\": \"NgGRN\",\n      \"puzzle_rating\": 3164,\n      \"fen_before_opponent_move\": \"7Q/rpk2p1p/p2b4/q1pp4/3P2b1/2P1P3/PP3PPP/R3K2R b KQ - 0 17\",\n      \"uci_moves_opponent_first\": \"c5d4 h8d4 g4h5 g2g4 h5g6 d4a7 d6c5 b2b4 c5b4 e1g1 b4c5 a7a8\",\n      \"original_upstream_zero_based_line\": 24593,\n      \"rating_system\": \"Lichess puzzle, not FIDE Elo\",\n      \"composed_study\": false,\n      \"requires_opponent_first_move_before_presenting\": true\n    },\n    {\n      \"puzzle_id\": \"gWyMk\",\n      \"puzzle_rating\": 3166,\n      \"fen_before_opponent_move\": \"r1b2r1k/1p5P/1n1pp2B/1Pp2p1B/4P2q/P2P2b1/1P2Q2P/R4R1K b - - 1 20\",\n      \"uci_moves_opponent_first\": \"f8f6 h6f4 g3h2 e2h2 h4h2 h1h2\",\n      \"original_upstream_zero_based_line\": 24594,\n      \"rating_system\": \"Lichess puzzle, not FIDE Elo\",\n      \"composed_study\": false,\n      \"requires_opponent_first_move_before_presenting\": true\n    }\n  ]\n}\n"


def original_extreme_source_bytes() -> bytes:
    raw = _SOURCE_JSON.encode("utf-8")
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise RuntimeError("extreme CC0 chess puzzle source checksum invalid")
    return raw


def bundled_extreme_puzzles() -> tuple[dict, ...]:
    data = json.loads(original_extreme_source_bytes())
    if (type(data) is not dict
        or data.get("schema") != "accessible-chess-section37-original-extreme-training-cc0-v1"
        or data.get("puzzle_count") != 4
        or type(data.get("puzzles")) is not list
        or len(data["puzzles"]) != 4):
        raise RuntimeError("extreme 3000+ real puzzle dataset invalid")
    return tuple(data["puzzles"])
