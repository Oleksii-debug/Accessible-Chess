"""Curate authentic, above-first-category CC0 tactical work from pinned Lichess data.

This source acquisition/selection utility does NOT create chess rules,
solve studies, infer FIDE ELO, or modify canonical training authority.
The owner sees puzzles rated 2200+ on *Lichess puzzle scale*, not junior
teaching samples. Genuine composed studies are a distinct category.
"""
from __future__ import annotations

import bz2
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

from acs.lawful_corpus_registry import LawfulCorpusError

UPSTREAM_GIT_BLOB = "c72d5988f2aa5caf634d90e130688b26525be33e"
UPSTREAM_LICENSE_BLOB = "0e259d42c996742e9e3cba14c677129b2c1b6311"
FILENAME = "combined_puzzle_db_first_50k.ndjson.bz2"
MAX_SOURCE_BYTES = 96 * 1024 * 1024
MAX_TOTAL_DECOMPRESSED_BYTES = 1536 * 1024 * 1024
MAX_LINE_BYTES = 2 * 1024 * 1024
EXPECTED_ORIGINAL_ROWS = 50_000
PER_BAND_LIMIT = 160
BANDS = ("advanced_2200_2599", "master_2600_2999", "extreme_3000_plus")
PHASES = ("opening", "middlegame", "endgame", "unspecified")
ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "section37-high-level-puzzles-source-receipt.json"
SELECTION = ROOT / "section37-high-level-puzzles-curated.json"
UCIMOVE = re.compile(r"^[a-h][1-8][a-h][1-8][qrbn]?$")
PUZZLE_ID = re.compile(r"^[A-Za-z0-9]{5,8}$")


def rating_band(rating: object) -> str | None:
    if type(rating) is not int or rating < 2200 or rating > 5000:
        return None
    if rating < 2600:
        return BANDS[0]
    if rating < 3000:
        return BANDS[1]
    return BANDS[2]


def parse_puzzle_line(raw: bytes) -> dict | None:
    """Whitelist actual Lichess fields only; no untrusted full-game metadata."""
    if len(raw) > MAX_LINE_BYTES:
        raise LawfulCorpusError("Lichess puzzle line over budget")
    try:
        payload = json.loads(raw)
        p = payload["puzzle"]
        rating = int(p["Rating"])
    except (UnicodeError, KeyError, ValueError, TypeError, OverflowError) as exc:
        raise LawfulCorpusError("Lichess original puzzle metadata invalid") from exc
    band = rating_band(rating)
    if band is None:
        return None  # Never publish beginner or below-first-category puzzles.
    ident = p.get("PuzzleId")
    fen = p.get("FEN")
    uci = p.get("Moves")
    themes = p.get("Themes")
    url = p.get("GameUrl")
    if (
        type(ident) is not str or not PUZZLE_ID.fullmatch(ident)
        or type(fen) is not str or len(fen) > 128 or len(fen.split()) != 6
        or type(uci) is not str or not 2 <= len(uci.split()) <= 128
        or any(UCIMOVE.fullmatch(m) is None for m in uci.split())
        or type(themes) is not str or len(themes) > 512
        or type(url) is not str or len(url) > 128
        or not re.fullmatch(r"https://lichess.org/[A-Za-z0-9]{8}/?(?:black|white)?(?:#[0-9]+)?", url)
    ):
        raise LawfulCorpusError("Lichess advanced puzzle source fields invalid")
    tags = [tag for tag in themes.split() if re.fullmatch(r"[A-Za-z0-9]{2,40}", tag)]
    if not tags:
        raise LawfulCorpusError("Lichess original puzzle has no valid theme")
    phases = tuple(phase for phase in PHASES[:-1] if phase in tags)
    phase = phases[0] if len(phases) == 1 else "unspecified"
    motifs = [
        theme for theme in tags
        if theme in (
            "sacrifice", "quietMove", "zugzwang", "defensiveMove", "fork",
            "pin", "intermezzo", "clearance", "attraction", "skewer",
            "discoveredAttack", "doubleCheck", "promotion",
            "rookEndgame", "pawnEndgame", "bishopEndgame", "knightEndgame",
            "queenEndgame", "master", "veryLong", "long",
        )
    ]
    # On official Lichess source, Moves begins with the *opponent's
    # previous move*. Presentation must apply this move via canonical
    # chess board authority before asking the user to find a solution.
    return {
        "puzzle_id": ident,
        "puzzle_rating": rating,
        "difficulty_band": band,
        "phase": phase,
        "themes": tags,
        "training_motifs": motifs,
        "fen_before_opponent_move": fen,
        "uci_moves_opponent_first": uci,
        "source_game": url,
        "lichess_rating_not_fide": True,
        "composed_study": False,
    }


def curate_original_lines(lines, *, max_selected: int = PER_BAND_LIMIT) -> dict:
    if type(max_selected) is not int or not 0 < max_selected <= 1000:
        raise LawfulCorpusError("invalid advanced puzzle sample limit")
    per_band: dict[str, list[dict]] = {name: [] for name in BANDS}
    source_rows = 0
    eligible = {name: 0 for name in BANDS}
    ids: set[str] = set()
    for source in lines:
        source_rows += 1
        if source_rows > 50_000:
            raise LawfulCorpusError("unexpected oversized genuine source row count")
        puzzle = parse_puzzle_line(source)
        if puzzle is None:
            continue
        key = puzzle["puzzle_id"]
        if key in ids:
            raise LawfulCorpusError("original Lichess puzzle identity duplicated")
        ids.add(key)
        band = puzzle["difficulty_band"]
        eligible[band] += 1
        if len(per_band[band]) < max_selected:
            per_band[band].append(puzzle)
    return {
        "original_rows_seen": source_rows,
        "eligible_original_count_by_band": eligible,
        "curated_count_by_band": {key: len(rows) for key, rows in per_band.items()},
        "puzzles": [
            item for band in BANDS for item in per_band[band]
        ],
    }


def _source_blob(path: Path) -> tuple[str, int, str]:
    """Pin source to original Git tree blob AND hash full actual compressed file."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or not 0 < info.st_size <= MAX_SOURCE_BYTES:
        raise LawfulCorpusError("original CC0 compressed corpus missing or oversized")
    completed = subprocess.run(
        ["git", "hash-object", "--", str(path.resolve())],
        check=True, capture_output=True, text=True, timeout=90,
    )
    sha1 = completed.stdout.strip()
    if sha1 != UPSTREAM_GIT_BLOB:
        raise LawfulCorpusError("original 50k compressed source Git blob differs from pinned sample")
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while block := stream.read(256 * 1024):
            total += len(block)
            if total > MAX_SOURCE_BYTES:
                raise LawfulCorpusError("original compressed corpus exceeded byte cap")
            digest.update(block)
    after = path.lstat()
    if not os.path.samestat(info, after) or after.st_size != info.st_size:
        raise LawfulCorpusError("original compressed CC0 source changed in-flight")
    return sha1, total, digest.hexdigest()


def read_original_curated_bz2(path: Path) -> tuple[dict, dict]:
    identity, source_bytes, source_sha256 = _source_blob(path)
    decompressed = 0
    def original_lines():
        nonlocal decompressed
        with bz2.open(path, "rb") as source:
            while original := source.readline(MAX_LINE_BYTES + 1):
                decompressed += len(original)
                if len(original) > MAX_LINE_BYTES or decompressed > MAX_TOTAL_DECOMPRESSED_BYTES:
                    raise LawfulCorpusError("original decompress exceeds strict resource budget")
                if not original.endswith(b"\\n") and len(original) >= MAX_LINE_BYTES:
                    raise LawfulCorpusError("truncated oversize puzzle record")
                yield original
    curated = curate_original_lines(original_lines())
    if curated["original_rows_seen"] != EXPECTED_ORIGINAL_ROWS:
        raise LawfulCorpusError("original 50k CC0 puzzle/game source was truncated")
    if any(not curated["curated_count_by_band"][name] for name in BANDS):
        raise LawfulCorpusError("source did not supply all three intended advanced puzzle bands")
    evidence = {
        "original_git_blob": identity,
        "original_sha256": source_sha256,
        "original_compressed_bytes": source_bytes,
        "original_decompressed_bytes": decompressed,
        "original_rows": curated["original_rows_seen"],
        "upstream_license": "CC0-1.0",
        "source_repository": "https://github.com/mcognetta/lichess-combined-puzzle-game-db",
        "source_file": FILENAME,
        "source_first_50k_snapshot_is_2022": True,
        "source_is_latest_lichess_snapshot": False,
        "pure_chess_studies_count": 0,
    }
    return curated, evidence


def main() -> None:
    REPORT.unlink(missing_ok=True)
    SELECTION.unlink(missing_ok=True)
    head = os.environ.get("ACCESSIBLE_CHESS_EXPECTED_HEAD")
    git_head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=ROOT, capture_output=True, text=True, check=True, timeout=10,
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", git_head) or head != git_head:
        raise LawfulCorpusError("not running on exact-source checkout")
    root = os.environ.get("ACS_37_ADVANCED_CC0_SOURCE_ROOT")
    if not root:
        raise LawfulCorpusError("original CC0 combined puzzle source checkout missing")
    checkout = Path(root)
    path = checkout / FILENAME
    try:
        r, e = read_original_curated_bz2(path)
        public = {
            "schema": "accessible-chess-genuine-advanced-lichess-puzzles-v1",
            "source": e,
            "min_rating": 2200,
            "score_type": "lichess_puzzle_rating_not_fide_elo",
            "target_user_level": "first_category_through_classical_candidate_master_to_gm_aspiration",
            "first_uci_is_opponents_last_move": True,
            "solution_hidden_by_default": True,
            "composed_studies_not_claimed": True,
            **r,
        }
        SELECTION.write_text(json.dumps(public, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        REPORT.write_text(json.dumps({
            "source_commit_sha": git_head,
            "status": "SOURCE_ONLY_PASS_NOT_PRODUCT_IMPORT",
            "curated_sha256": hashlib.sha256(SELECTION.read_bytes()).hexdigest(),
            "source_evidence": e,
            "original_rows": r["original_rows_seen"],
            "eligible_by_band": r["eligible_original_count_by_band"],
            "selected_by_band": r["curated_count_by_band"],
            "public_rights": "CC0_1_0",
            "chess_semantics_validated": False,
            "section_37_done": False,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"selected_by_band": r["curated_count_by_band"], "source_commit_sha": git_head}))
    except BaseException:
        REPORT.unlink(missing_ok=True)
        SELECTION.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
