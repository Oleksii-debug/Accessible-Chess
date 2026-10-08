"""Live byte-verified CC0 source acquisition and canonical PGN sample probe.

This is a Section-37 acquisition acceptance gate, not a fabricated all-format
Section-38 closure. Source bytes remain in an ephemeral cache and are never
committed or copied to a public release by this script.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import tempfile

import zstandard

from acs.lawful_corpus_registry import (
    acquire_cc0_source,
    load_catalog,
    verified_local_source,
    iter_bounded_corpus_lines,
)
from acs.import_contract import fingerprint
from tools.v2_library_source_catalog_real_corpus import (
    _parse_complete_game_subset,
    _write_complete_game_subset,
)

SOURCE_IDS = (
    "lichess_standard_rated_2013_02",
    "lichess_standard_rated_2013_03",
    "lichess_standard_rated_2013_04",
    "lichess_standard_rated_2013_08",
)
SAMPLE_GAMES = 128
REPORT_FILE = Path("revised-section37-live-cc0-readback.json")


def main() -> None:
    records = {item["id"]: item for item in load_catalog()}
    results = []
    with tempfile.TemporaryDirectory(prefix="accessible-chess-lawful-source-") as temp:
        cache = Path(temp)
        for source_id in SOURCE_IDS:
            record = records[source_id]
            # The existing shared registry enforces host, rights, limits,
            # no redirects, no owner-file overwrite and whole-source SHA256.
            compressed = acquire_cc0_source(record, cache)
            sha256 = verified_local_source(compressed, record)
            indexed_bytes = record.get("indexed_bytes")
            if indexed_bytes is not None and compressed.stat().st_size != indexed_bytes:
                raise AssertionError(f"{source_id}: source listing byte count mismatch")
            subset = cache / (source_id + "-128.pgn")
            with compressed.open("rb") as raw:
                with zstandard.ZstdDecompressor().stream_reader(raw) as decoded:
                    with io.TextIOWrapper(
                        decoded, encoding="utf-8", errors="strict", newline=""
                    ) as pgn:
                        count = _write_complete_game_subset(
                            iter_bounded_corpus_lines(pgn), subset, SAMPLE_GAMES
                        )
            if count != SAMPLE_GAMES:
                raise AssertionError(
                    f"{source_id}: expected {SAMPLE_GAMES} complete games, got {count}"
                )
            # Reuse the original canonical chess PGN parser and transport
            # framing instead of introducing a parallel format authority.
            parsed = _parse_complete_game_subset(subset)
            if len(parsed) != SAMPLE_GAMES or [
                game.source_index for game in parsed
            ] != list(range(SAMPLE_GAMES)):
                raise AssertionError(
                    f"{source_id}: canonical PGN readback identity mismatch"
                )
            subset_source = fingerprint(subset)
            results.append({
                "source_id": source_id,
                "source_url": record["download_url"],
                "license": record["license"],
                "compressed_sha256": sha256,
                "compressed_bytes": compressed.stat().st_size,
                "subset_sha256": subset_source.sha256,
                "subset_bytes": subset_source.size,
                "canonical_parsed_games": len(parsed),
                "status": "PASS",
            })
    # Never emit a PASS report when any source failed; do not preserve bytes.
    payload = {
        "kind": "revised-section37-live-cc0-source-readback",
        "status": "PASS",
        "real_downloaded_source_count": len(results),
        "sources": results,
        "ephemeral_cache_deleted": True,
        "not_qualified": [
            "third-party Books EPUB/PDF/DOCX",
            "complete ChessBase-family source and companion files",
            "Section 38 all-format application integration",
        ],
    }
    staging = REPORT_FILE.with_suffix(".tmp")
    try:
        staging.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(staging, REPORT_FILE)
    finally:
        staging.unlink(missing_ok=True)
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
