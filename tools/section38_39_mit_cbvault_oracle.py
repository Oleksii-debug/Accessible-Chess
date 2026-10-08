"""Optional *external*, MIT ChessBase decoder qualification; no product authority fork.

The existing acs.chessbase_decoder / acs.chessbase_library_import service
remains canonical. This compares an MIT clean-room alternative against the
independently Git-SHA-pinned, source-only GPL libcbh fixture oracles, using the
existing canonical PGN/GameTree parser. No GPL source or ChessBase database is
packaged or published. 2CBH/CBONE/CBF are NOT promoted to supported.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from acs.gametree import PgnGame
from acs.pgn_roundtrip import parse_pgn_text
from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from tools.revised_section37_cbh_original_family_inventory import (
    UPSTREAM_COMMIT,
    original_cbh_source_receipts,
    verify_gpl_cbh_family,
)
from tools.revised_sections37_38_offline_manifest import ROOT, _source_head


BACKEND_REPO = "https://github.com/itshak/cbvault"
BACKEND_COMMIT = "3e56040fd2c38fdc2c8a25b4aff4d7ead2c5154b"
BACKEND_LICENSE = "MIT"
BACKEND_VERSION = "0.1.4"
REPORT = ROOT / "section38-39-cbvault-mit-external-cbh-qualification.json"
_MAX_BINARY = 120 * 1024 * 1024
_MAX_PGN = 12 * 1024 * 1024
_SHA = re.compile(r"^[a-f0-9]{40}$")


def _bounded_file_digest(path: Path, *, max_bytes: int) -> tuple[str, int]:
    if path.is_symlink() or not path.is_file():
        raise LawfulCorpusError("external MIT tool is not a direct file")
    stat = path.stat()
    if not 0 < stat.st_size <= max_bytes:
        raise LawfulCorpusError("external MIT tool exceeds qualification budget")
    digester = hashlib.sha256()
    read = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            read += len(chunk)
            if read > max_bytes:
                raise LawfulCorpusError("external binary grew during qualification")
            digester.update(chunk)
    if read != stat.st_size or path.stat().st_size != read:
        raise LawfulCorpusError("external decoder mutated while inspected")
    return digester.hexdigest(), read


def _original_games_signature(games: tuple[PgnGame, ...]) -> tuple:
    """Structural canonical comparison; no new SAN engine or PGN grammar."""
    def line_value(line):
        return (
            tuple(
                (move.san, tuple(move.nags),
                 tuple((" ".join(c.text.split()), c.style.value)
                       for c in move.comments_before),
                 tuple((" ".join(c.text.split()), c.style.value)
                       for c in move.comments_after),
                 tuple(line_value(variation) for variation in move.variations))
                for move in line.moves
            ),
            line.result,
        )
    return tuple((
        g.tags.get("White", ""), g.tags.get("Black", ""),
        g.tags.get("Result", "*"),
        line_value(g.line),
    ) for g in games)


def _run_external_pgn(binary: Path, source: Path) -> bytes:
    """One bounded, immutable source-only CLI invocation; never use a shell."""
    try:
        result = subprocess.run(
            [os.fspath(binary), "pgn", os.fspath(source)],
            cwd=os.fspath(binary.parent), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, timeout=45, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LawfulCorpusError("MIT cbvault external export did not complete") from exc
    if (
        result.returncode != 0 or not result.stdout
        or len(result.stdout) > _MAX_PGN or len(result.stderr) > 1024 * 1024
    ):
        raise LawfulCorpusError("MIT cbvault exported no bounded complete PGN")
    return result.stdout


def qualify_mit_cbvault(
    *, backend_binary: Path, original_libcbh_checkout: Path,
    backend_checkout: Path, expected_product_head: str,
) -> dict:
    if not _SHA.fullmatch(expected_product_head):
        raise LawfulCorpusError("expected candidate source head is not exact SHA")
    if not backend_checkout.is_dir() or backend_checkout.is_symlink():
        raise LawfulCorpusError("MIT source checkout is missing")
    try:
        backend_sha = subprocess.run(
            ["git", "-C", os.fspath(backend_checkout), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise LawfulCorpusError("MIT external source Git identity is unverifiable") from exc
    if backend_sha != BACKEND_COMMIT:
        raise LawfulCorpusError("MIT source commit changed; refuse qualification")

    digest, size = _bounded_file_digest(backend_binary, max_bytes=_MAX_BINARY)
    selected = [x for x in load_catalog()
                if "external_companion_git_blobs" in x]
    before = original_cbh_source_receipts(tuple(selected), original_libcbh_checkout)
    if len(before) != 3:
        raise LawfulCorpusError("no complete legally sourced CBH families")
    result_rows = []
    for row in sorted(selected, key=lambda x: x["id"]):
        fixture = (original_libcbh_checkout / "gtest" /
                   row["external_fixture_directory"])
        cbh = fixture / (row["external_fixture_stem"] + ".cbh")
        oracle = fixture / row["external_oracle_filename"]
        expected_bytes = oracle.read_bytes()
        original_expected = tuple(parse_pgn_text(
            expected_bytes.decode("utf-8-sig", errors="strict"), strict=False))
        exported_bytes = _run_external_pgn(backend_binary, cbh)
        actual_games = tuple(parse_pgn_text(
            exported_bytes.decode("utf-8-sig", errors="strict"), strict=False))
        if not original_expected or not actual_games:
            raise LawfulCorpusError("genuine CBH external import yielded zero games")
        same_games = len(original_expected) == len(actual_games)
        same_structure = (
            same_games
            and _original_games_signature(original_expected)
                == _original_games_signature(actual_games)
        )
        result_rows.append({
            "source_id": row["id"],
            "source_original_upstream_git_sha": UPSTREAM_COMMIT,
            "source_oracle_sha256": hashlib.sha256(expected_bytes).hexdigest(),
            "expected_games": len(original_expected),
            "observed_games": len(actual_games),
            "full_source_game_tree_match": same_structure,
            "actual_pgn_sha256": hashlib.sha256(exported_bytes).hexdigest(),
            "actual_pgn_bytes": len(exported_bytes),
            "format": "cbh",
            "scope": "independent external MIT decoder CLI against GPL source-only originals",
            "qualification": "PASS" if same_structure else "PARTIAL",
            "public_release_redistribution": False,
        })
        # Don't infer structural equivalence from only a matching game count.
    after = original_cbh_source_receipts(tuple(selected), original_libcbh_checkout)
    if before != after:
        raise LawfulCorpusError("source fixture changed during MIT adapter qualification")
    if _bounded_file_digest(backend_binary, max_bytes=_MAX_BINARY) != (digest, size):
        raise LawfulCorpusError("MIT backend binary changed during decoding")
    report = {
        "schema": "accessible-chess-section38-39-mit-cbvault-external-qa-v1",
        "product_candidate_sha": expected_product_head,
        "backend_repository": BACKEND_REPO,
        "backend_commit": BACKEND_COMMIT,
        "backend_crate_version": BACKEND_VERSION,
        "backend_license": BACKEND_LICENSE,
        "backend_sha256": digest,
        "backend_size_bytes": size,
        "upstream_fixture_git_commit": UPSTREAM_COMMIT,
        "families": result_rows,
        "cbh_actual_fixture_count": len(result_rows),
        "cbv_unpacker_available_in_upstream": True,
        "cbv_real_input_qualified_here": False,
        "cbf_supported_here": False,
        "two_cbh_supported_here": False,
        "cbone_supported_here": False,
        "product_decoder_replaced": False,
        "product_integrated_backend": False,
        "external_GPL_binaries_or_test_dbs_packaged": False,
        "section38_terminal_done": False,
        "section39_terminal_done": False,
    }
    return report


def main() -> None:
    REPORT.unlink(missing_ok=True)
    temp = REPORT.with_suffix(".tmp")
    temp.unlink(missing_ok=True)
    candidate_head = _source_head()
    binary = os.environ.get("ACS_CBVAULT_MIT_BINARY")
    upstream = os.environ.get("ACS_CBVAULT_CBH_ORIGINAL_ROOT")
    checkout = os.environ.get("ACS_CBVAULT_MIT_SOURCE_ROOT")
    if not binary or not upstream or not checkout:
        raise LawfulCorpusError("exact external decoder or original-source evidence missing")
    report = qualify_mit_cbvault(
        backend_binary=Path(binary), original_libcbh_checkout=Path(upstream),
        backend_checkout=Path(checkout), expected_product_head=candidate_head,
    )
    try:
        temp.write_text(json.dumps(report, ensure_ascii=False,
                                   indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, REPORT)
    finally:
        temp.unlink(missing_ok=True)
    print(json.dumps({
        "source_commit_sha": candidate_head,
        "qualified_external_families": len(report["families"]),
        "semantically_equivalent": sum(x["qualification"] == "PASS" for x in report["families"]),
        "two_cbh_supported_here": False,
        "section38_done": False,
        "section39_done": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
