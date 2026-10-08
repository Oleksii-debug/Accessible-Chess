"""Exact original-source evidence for four real CC0 Lichess 3000–3166 puzzles.

FeXd's GPL puzzle app embeds independently CC0-licensed puzzle *data* from
Lichess. Do not bundle the GPL application, and do not imply a FIDE GM rating,
a composed endgame study, or completed UI/Training integration.

Never mutate chess rules, library authority or release rights here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from acs.lawful_corpus_registry import LawfulCorpusError

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "cddfa24b1a5a9013b99622d6d5e7093a64b1d55a"
SOURCE_GIT_BLOB = "acb74625e5ebd0ae9b454779a371ac87091c8c0e"
LICENSE_GIT_BLOB = "f288702d2fa16d3cdf0035b15a9fcbc552cd88e7"
CSV_PATH = "puzzles/offline/puzzles.csv"
CATALOG = ROOT / "tests/real_corpus/advanced_training/lichess_cc0_extreme_3000_3166_original_puzzles.json"
REPORT = ROOT / "section37-extreme-3000-original-source-readback.json"
MAX_ORIGINAL_BYTES = 8 * 1024 * 1024
PUZZLE_ID = re.compile(r"^[A-Za-z0-9]{5,8}$")
UCI = re.compile(r"^[a-h][1-8][a-h][1-8][nbrq]?$")


def verify_original_extreme_records(catalog: dict, source_lines: list[str]) -> dict:
    """Test exact four Lichess original CSV lines, not recreated chess positions."""
    if catalog.get("original_repo_git_blob") != SOURCE_GIT_BLOB:
        raise LawfulCorpusError("wrong upstream extreme CC0 original identity")
    if catalog.get("puzzle_count") != 4 or len(catalog.get("puzzles", [])) != 4:
        raise LawfulCorpusError("original extreme puzzle selection changed")
    if len(source_lines) != 24595:
        raise LawfulCorpusError("unexpected authentic CC0 mirror puzzle row count")
    seen: set[str] = set()
    for selected in catalog["puzzles"]:
        name = selected.get("puzzle_id")
        rating = selected.get("puzzle_rating")
        offset = selected.get("original_upstream_zero_based_line")
        fen = selected.get("fen_before_opponent_move")
        solution = selected.get("uci_moves_opponent_first")
        if (
            type(name) is not str or not PUZZLE_ID.fullmatch(name) or name in seen
            or type(rating) is not int or rating < 3000 or rating > 5000
            or type(offset) is not int or not 0 <= offset < len(source_lines)
            or type(fen) is not str or len(fen.split()) != 6
            or type(solution) is not str or len(solution.split()) < 2
            or any(UCI.fullmatch(m) is None for m in solution.split())
            or selected.get("composed_study") is not False
            or selected.get("requires_opponent_first_move_before_presenting") is not True
        ):
            raise LawfulCorpusError("invalid source metadata for 3000+ CC0 puzzle")
        seen.add(name)
        exact_row = ",".join((name, fen, solution, str(rating)))
        if source_lines[offset].rstrip("\r\n") != exact_row:
            raise LawfulCorpusError("selected extreme real puzzle differs from original source CSV")
    return {
        "qualified_original_extreme_count": len(seen),
        "min_lichess_puzzle_rating": min(x["puzzle_rating"] for x in catalog["puzzles"]),
        "max_lichess_puzzle_rating": max(x["puzzle_rating"] for x in catalog["puzzles"]),
        "source_rows": len(source_lines),
        "original_rows_exactly_identical": True,
        "fide_rating_or_gm_title_claim": False,
        "licensed_cc0_data_only": True,
    }


def _git_identity(checkout: Path, object_file: str, expected: str) -> None:
    if checkout.is_symlink() or not checkout.is_dir():
        raise LawfulCorpusError("original licensed extreme source directory invalid")
    output = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD:" + object_file],
        capture_output=True, text=True, check=True, timeout=15,
    ).stdout.strip()
    if output != expected:
        raise LawfulCorpusError("upstream CC0 source Git object unexpectedly replaced")


def verify_original_source(checkout: Path) -> dict:
    _git_identity(checkout, CSV_PATH, SOURCE_GIT_BLOB)
    _git_identity(checkout, "LICENSE.md", LICENSE_GIT_BLOB)
    orig = checkout / CSV_PATH
    info = orig.lstat()
    if not stat.S_ISREG(info.st_mode) or orig.is_symlink() or not 0 < info.st_size <= MAX_ORIGINAL_BYTES:
        raise LawfulCorpusError("external original 3000+ puzzle source unsafe")
    original = orig.read_bytes()  # original source <= 8 MB after lstat bound
    if len(original) != info.st_size:
        raise LawfulCorpusError("extreme source changed during bounded read")
    try:
        lines = original.decode("utf-8", errors="strict").splitlines()
    except UnicodeError as exc:
        raise LawfulCorpusError("original extreme CSV encoding invalid") from exc
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    evidence = verify_original_extreme_records(catalog, lines)
    return {
        "original_git_blob": SOURCE_GIT_BLOB,
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "source_original_bytes": len(original),
        "original_commit": SOURCE_COMMIT,
        "original_license_git_blob": LICENSE_GIT_BLOB,
        "catalog_sha256": hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
        "source_evidence": evidence,
        "product_training_ui_qualified": False,
        "section37_done": False,
    }


def main() -> None:
    REPORT.unlink(missing_ok=True)
    expected = os.environ.get("ACCESSIBLE_CHESS_EXPECTED_HEAD")
    product_head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True, timeout=10,
    ).stdout.strip()
    if expected != product_head or not re.fullmatch(r"[a-f0-9]{40}", product_head):
        raise LawfulCorpusError("source-only extreme-puzzle report lacks exact product candidate")
    upstream = os.environ.get("ACS_37_EXTREME_CC0_CHECKOUT")
    if not upstream:
        raise LawfulCorpusError("source-only external original extreme puzzle checkout absent")
    result = verify_original_source(Path(upstream))
    result["source_commit_sha"] = product_head
    REPORT.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "original_source_sha256": result["source_sha256"],
        "exact_original_extreme_count": result["source_evidence"]["qualified_original_extreme_count"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
