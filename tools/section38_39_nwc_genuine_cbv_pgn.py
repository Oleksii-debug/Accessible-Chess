"""External *original* Northwest Chess annotated CBV/PGN pair qualification.

Source publisher offers a CBV archive and matching independently published PGN
for January 2013. Acquire through first-party HTTPS into an ephemeral CI temp
directory only. The downloaded bytes are NOT pinned before observation, not
redistributed, and not recorded as an original-source PASS unless the full
CBV -> MIT cbvault CLI -> canonical GameTree comparison actually runs.
Standalone observed SHA256 is NOT an independently pinned upstream identity.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import stat
import subprocess
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

from acs.lawful_corpus_registry import LawfulCorpusError
from acs.pgn_roundtrip import parse_pgn_text
from tools.section38_39_mit_cbvault_oracle import (
    _bounded_file_digest, _original_games_signature, _run_external_pgn,
)


PUBLISHER = "https://www.nwchess.com/articles/games/published/published_games.htm"
PUBLISHER_HOST = "www.nwchess.com"
SOURCE_STEM = "NWC%202013-01%20Published%20Games"
CBV_URL = (
    "https://www.nwchess.com/articles/games/published/"
    + SOURCE_STEM + ".cbv"
)
PGN_URL = (
    "https://www.nwchess.com/articles/games/published/"
    + SOURCE_STEM + ".pgn"
)
MAX_SOURCE = 32 * 1024 * 1024
MAX_EXTRACTED_TOTAL = 256 * 1024 * 1024
MAX_GAME_COUNT = 25_000
_NO_SECRET = re.compile(r"^[0-9a-f]{64}$")


class _SamePublisherRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Format bytes are never fetched from an attacker-controlled redirect.
        _qualified_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _qualified_url(url: str) -> str:
    if type(url) is not str or len(url) > 500:
        raise LawfulCorpusError("original CBV/PGN URL is invalid")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise LawfulCorpusError("original CBV/PGN URL has invalid port") from exc
    if (
        parts.scheme != "https" or parts.hostname != PUBLISHER_HOST
        or parts.username is not None or parts.password is not None
        or port not in (None, 443) or parts.fragment or parts.query
        or not parts.path.startswith("/articles/games/published/")
        or any(component in ("..", ".") for component in parts.path.split("/"))
    ):
        raise LawfulCorpusError("original source escapes Northwest Chess publisher")
    return url


def _read_publisher_source(url: str) -> bytes:
    _qualified_url(url)
    opener = build_opener(
        _SamePublisherRedirect, HTTPSHandler(context=ssl.create_default_context())
    )
    try:
        with opener.open(
            Request(url, headers={"User-Agent": "AccessibleChess-FormatQA/1.0"}),
            timeout=35,
        ) as response:
            _qualified_url(response.geturl())
            if response.status != 200:
                raise LawfulCorpusError("original publisher did not serve HTTP 200")
            data = response.read(MAX_SOURCE + 1)
    except LawfulCorpusError:
        raise
    except (OSError, TimeoutError, ValueError) as exc:
        raise LawfulCorpusError("original CBV/PGN publisher read failed") from exc
    if not 0 < len(data) <= MAX_SOURCE:
        raise LawfulCorpusError("original CBV/PGN bytes absent or over quota")
    return data


def _extract_with_mit(binary: Path, archive: Path, outdir: Path) -> None:
    if outdir.exists() or outdir.is_symlink():
        raise LawfulCorpusError("original CBV extraction target is not fresh")
    result = subprocess.run(
        [os.fspath(binary), "archive", "extract", os.fspath(archive), os.fspath(outdir)],
        cwd=os.fspath(binary.parent), stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        shell=False, timeout=120, check=False,
    )
    if result.returncode != 0 or len(result.stderr) > 1024 * 1024:
        raise LawfulCorpusError("MIT CBV decoder refused real publisher original")
    if not outdir.is_dir() or outdir.is_symlink():
        raise LawfulCorpusError("MIT CBV decoder produced no regular destination")
    members = list(outdir.rglob("*"))
    if len(members) > 150:
        raise LawfulCorpusError("decoded CBV output has too many members")
    expanded = 0
    for item in members:
        metadata = item.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise LawfulCorpusError("CBV extraction must not contain symlinks")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise LawfulCorpusError("CBV extraction emitted special file")
        expanded += metadata.st_size
        if expanded > MAX_EXTRACTED_TOTAL:
            raise LawfulCorpusError("original CBV extraction exceeds budget")
    if not any(x.suffix.lower() == ".cbh" for x in members):
        raise LawfulCorpusError("genuine CBV archive lacks classic CBH source")


def qualify_original_publisher_pair(
    *, binary: Path, expected_binary_sha256: str,
) -> dict:
    if type(expected_binary_sha256) is not str or not _NO_SECRET.fullmatch(
        expected_binary_sha256
    ):
        raise LawfulCorpusError("MIT CBV executable requires exact SHA-256")
    before = _bounded_file_digest(binary, max_bytes=120 * 1024 * 1024)
    if before[0] != expected_binary_sha256:
        raise LawfulCorpusError("MIT CBV binary digest mismatch before source I/O")
    expected_raw = _read_publisher_source(PGN_URL)
    cbv_raw = _read_publisher_source(CBV_URL)
    expected_games = tuple(parse_pgn_text(
        expected_raw.decode("utf-8-sig", errors="strict"), strict=False
    ))
    if not 1 <= len(expected_games) <= MAX_GAME_COUNT:
        raise LawfulCorpusError("original Northwest Chess PGN score count invalid")
    with tempfile.TemporaryDirectory(prefix="acs-external-nwc2013-cbv-") as tmp:
        root = Path(tmp)
        archive = root / "published.cbv"
        archive.write_bytes(cbv_raw)
        original_pgn = root / "published.pgn"
        original_pgn.write_bytes(expected_raw)
        target = root / "expanded"
        _extract_with_mit(binary, archive, target)
        candidates = [
            file for file in target.rglob("*")
            if file.is_file() and not file.is_symlink()
            and file.suffix.lower() == ".cbh"
        ]
        if len(candidates) != 1:
            raise LawfulCorpusError("CBV archive did not yield exactly one classic database")
        decoded_raw = _run_external_pgn(binary, candidates[0])
        decoded_games = tuple(parse_pgn_text(
            decoded_raw.decode("utf-8-sig", errors="strict"), strict=False
        ))
    after = _bounded_file_digest(binary, max_bytes=120 * 1024 * 1024)
    if before != after:
        raise LawfulCorpusError("MIT original CBV decoder binary changed during test")
    same_count = len(expected_games) == len(decoded_games)
    same_tree = (
        same_count
        and _original_games_signature(expected_games)
            == _original_games_signature(decoded_games)
    )
    # Intentionally report PARTIAL when annotations, results or original
    # game-identity fields do not match. Never count a game-count-only match.
    return {
        "schema": "acs-section38-39-external-NWC-original-cbv-pgn-oracle-v1",
        "publisher_index": PUBLISHER,
        "publisher": "Northwest Chess",
        "edition": "January 2013 annotated published games",
        "original_pgn_url": PGN_URL,
        "original_cbv_url": CBV_URL,
        "observed_source_pgn_sha256": hashlib.sha256(expected_raw).hexdigest(),
        "observed_source_cbv_sha256": hashlib.sha256(cbv_raw).hexdigest(),
        "source_pgn_bytes": len(expected_raw),
        "source_cbv_bytes": len(cbv_raw),
        "source_original_sha256_previously_pinned": False,
        "pgn_expected_games": len(expected_games),
        "cbv_decoder_actual_games": len(decoded_games),
        "actual_decoder_export_sha256": hashlib.sha256(decoded_raw).hexdigest(),
        "same_game_count": same_count,
        "full_semantic_game_tree_match": same_tree,
        "source_acquisition": "ORIGINAL_EXTERNAL_HTTP200_TEST_ONLY_UNPINNED_OBSERVATION",
        "qualification": "PARTIAL" if same_tree else "FAIL",
        "terminal_cbv_format_pass": False,
        "product_cbv_backend_changed": False,
        "original_files_redistributed": False,
        "owner_release_included": False,
        "section38_terminal_done": False,
        "section39_terminal_done": False,
    }


__all__ = [
    "PUBLISHER", "CBV_URL", "PGN_URL", "_qualified_url",
    "_read_publisher_source", "qualify_original_publisher_pair",
]
