"""Optional *external*, MIT ChessBase decoder qualification; no product authority fork.

The existing acs.chessbase_decoder / acs.chessbase_library_import service
remains canonical. This compares an MIT clean-room alternative against the
independently Git-SHA-pinned, source-only GPL libcbh fixture oracles, using the
existing canonical PGN/GameTree parser. No GPL source or ChessBase database is
packaged or published. 2CBH/CBONE/CBF are NOT promoted to supported.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import stat
import tempfile
import time

from acs.gametree import PgnGame
from acs.pgn_roundtrip import parse_pgn_text
from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from tools.revised_section37_cbh_original_family_inventory import (
    UPSTREAM_COMMIT,
    original_cbh_source_receipts,
    verify_gpl_cbh_family,
)
# This optional Section-38 external oracle uses its own exact-head receipt.
# Do not import a cross-Section offline manifest solely to read the Git SHA.
ROOT = Path(__file__).resolve().parents[1]


def _source_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=ROOT, check=True, capture_output=True, text=True, timeout=10,
    )
    sha = result.stdout.strip()
    expected = os.environ.get("ACCESSIBLE_CHESS_EXPECTED_HEAD")
    if not _SHA.fullmatch(sha) or (expected is not None and expected != sha):
        raise LawfulCorpusError("external oracle checkout is not the expected exact SHA")
    return sha


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
    """Entire canonical semantic tree, not merely SAN and party count.

    Independent CLI output may reorder PGN headers. That is not a chess change;
    dropping *any* actual header value, source comment (including line-level
    prefaces/trailers), NAG, variation, or move numbering is a loss. This QA
    backend must report PARTIAL rather than a fake complete-format PASS.
    """

    def comments(value):
        return tuple((comment.text, comment.style.value) for comment in value)

    def line_value(line):
        return (
            comments(line.leading_comments),
            tuple(
                (
                    move.san,
                    move.move_number,
                    tuple(move.nags),
                    comments(move.comments_before),
                    comments(move.comments_after),
                    tuple(line_value(variation) for variation in move.variations),
                )
                for move in line.moves
            ),
            comments(line.trailing_comments),
            line.result,
        )

    return tuple((
        tuple(sorted(game.tags.items())),
        line_value(game.line),
    ) for game in games)


def _run_external_pgn(binary: Path, source: Path) -> bytes:
    """Run the pinned cbvault CLI with its documented *file* output argument.

    cbvault 0.1.4 uses: cbvault pgn <db> [out]. Without an output path,
    stdout legitimately holds PGN; with a path, stdout is not required for
    qualification. Capture the bounded structured stderr report and monitor
    the actual output file; reject malformed or incomplete results.
    """
    max_stderr = 1024 * 1024
    try:
        with tempfile.TemporaryDirectory(prefix="acs-cbvault-pgn-") as directory:
            output = Path(directory) / "decoded.pgn"

            def output_size() -> int:
                try:
                    metadata = output.lstat()
                except FileNotFoundError:
                    return 0
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or stat.S_ISLNK(metadata.st_mode)
                    or metadata.st_nlink != 1
                    or (
                        getattr(metadata, "st_file_attributes", 0)
                        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                    )
                ):
                    raise LawfulCorpusError("MIT cbvault produced unsafe PGN output")
                return metadata.st_size

            # cbvault 0.1.4's Headers/Annotations readers strip ".cbh",
            # but its Entities::open appends .cbp/.cbt/.cbc/.cbs to the
            # argument literally. Supplying "base.cbh" therefore asks for
            # nonexistent "base.cbh.cbp" and fails before the JSON receipt.
            # Pass the genuine, verified classic database *stem* instead.
            if source.suffix.lower() != ".cbh" or not source.is_file() or source.is_symlink():
                raise LawfulCorpusError("MIT CBH oracle requires a direct .cbh original")
            database_stem = source.with_suffix("")
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                process = subprocess.Popen(
                    [os.fspath(binary), "pgn", os.fspath(database_stem), os.fspath(output), "--json"],
                    cwd=os.fspath(binary.parent), stdin=subprocess.DEVNULL,
                    stdout=stdout, stderr=stderr, shell=False,
                )
                deadline = time.monotonic() + 45
                try:
                    while process.poll() is None:
                        if (
                            output_size() > _MAX_PGN
                            or os.fstat(stdout.fileno()).st_size > max_stderr
                            or os.fstat(stderr.fileno()).st_size > max_stderr
                        ):
                            raise LawfulCorpusError("MIT cbvault output exceeds resource budget")
                        if time.monotonic() >= deadline:
                            raise LawfulCorpusError("MIT cbvault PGN export timed out")
                        time.sleep(0.03)
                    output_bytes = output_size()
                    stdout_bytes = os.fstat(stdout.fileno()).st_size
                    stderr_bytes = os.fstat(stderr.fileno()).st_size
                    if stdout_bytes > max_stderr or stderr_bytes > max_stderr:
                        raise LawfulCorpusError("MIT cbvault output exceeds resource budget")
                    if process.returncode != 0:
                        stderr.seek(0)
                        raw_report = stderr.read(max_stderr + 1)
                        # The upstream CLI's --json report is written only to
                        # stderr. Emit integer counters, never untrusted source
                        # paths, private filenames or arbitrary output strings.
                        counts = None
                        try:
                            lines = raw_report.splitlines()
                            parsed = json.loads(lines[-1])
                            if type(parsed) is dict and all(
                                type(parsed.get(k)) is int
                                and 0 <= parsed[k] <= 1_000_000_000
                                for k in ("records", "games", "failures")
                            ):
                                counts = (parsed["records"], parsed["games"], parsed["failures"])
                        except (UnicodeError, ValueError, IndexError, TypeError):
                            pass
                        # If upstream aborts before its machine JSON receipt,
                        # preserve only a fixed vocabulary of harmless failure
                        # classes. In particular, NEVER forward original file
                        # paths, arbitrary stderr text or copyrighted payload.
                        safe_words = {
                            b"archive", b"bounds", b"corrupt", b"database",
                            b"decode", b"empty", b"end", b"file", b"format",
                            b"header", b"index", b"invalid", b"magic",
                            b"missing", b"mmap", b"moves", b"open",
                            b"range", b"read", b"record", b"size",
                            b"small", b"truncated", b"unexpected",
                            b"unsupported", b"version", b"write",
                        }
                        selected = set()
                        if counts is None:
                            for diagnostic_line in raw_report.splitlines()[-12:]:
                                if diagnostic_line.lstrip().lower().startswith(b"error:"):
                                    selected.update(
                                        re.findall(rb"[a-z]{3,16}", diagnostic_line.lower())
                                    )
                        category = ",".join(sorted(
                            word.decode("ascii") for word in selected & safe_words
                        )) or "opaque"
                        details = (
                            f"; records={counts[0]}, games={counts[1]}, failures={counts[2]}"
                            if counts is not None else f"; safe_error_tokens={category}"
                        )
                        raise LawfulCorpusError(
                            f"MIT cbvault export failed closed (exit={process.returncode}{details})"
                        )
                    if output_bytes > _MAX_PGN:
                        raise LawfulCorpusError("MIT cbvault output exceeds resource budget")
                    if output_bytes == 0:
                        raise LawfulCorpusError("MIT cbvault exported no bounded complete PGN")
                    before = output.lstat()
                    with output.open("rb") as stream:
                        opened = os.fstat(stream.fileno())
                        if not os.path.samestat(before, opened):
                            raise LawfulCorpusError("MIT cbvault PGN output changed on open")
                        data = stream.read(_MAX_PGN + 1)
                        opened_after = os.fstat(stream.fileno())
                    after = output.lstat()
                    if (
                        not 0 < len(data) <= _MAX_PGN
                        or before.st_size != len(data)
                        or not os.path.samestat(before, opened_after)
                        or not os.path.samestat(before, after)
                    ):
                        raise LawfulCorpusError("MIT cbvault PGN readback exceeded budget")
                    return data
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=10)
    except LawfulCorpusError:
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise LawfulCorpusError("MIT cbvault external export did not complete") from exc


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
        # A forgiving parser recovering a damaged ChessBase export is not an
        # exact original-source readback. Count only warning-free games.
        original_recovery_warnings = sum(len(g.warnings) for g in original_expected)
        decoded_recovery_warnings = sum(len(g.warnings) for g in actual_games)
        same_games = len(original_expected) == len(actual_games)
        same_structure = (
            same_games
            and original_recovery_warnings == 0
            and decoded_recovery_warnings == 0
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
            "expected_recovery_warning_count": original_recovery_warnings,
            "decoded_recovery_warning_count": decoded_recovery_warnings,
            "all_original_header_comment_nag_variation_metadata_preserved": same_structure,
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
