"""Build a genuine-source, offline OWNER-TEST Library seed using canonical ingress.

The Stockfish CC0 PGN archive is verified in its original form, then a small
derived canonical PGN is staged for the existing user_library_seed producer/
consumer contract. The source ZIP is never repackaged; no protected author-
owned book or proprietary ChessBase data is included.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from acs.gametree import CanonicalPgnGameFramer, serialize_game
from acs.lawful_corpus_registry import (
    LawfulCorpusError, load_catalog, read_verified_zip_member, verified_local_source,
)
from acs.pgn_roundtrip import parse_pgn_text
from acs.user_library_seed import (
    BUNDLE_KIND, MANIFEST_NAME, SCHEMA_VERSION, MAX_SOURCE_BYTES,
    load_user_library_seed,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "stockfish_2moves_v2_pgn_zip"
SEED_PGN_NAME = "stockfish_real_opening_games.pgn"
_GAME_COUNT = 32


def _verified_original_pgntree(root: Path) -> tuple[str, dict[str, object]]:
    records = {record["id"]: record for record in
               load_catalog(root / "docs/corpus/revised_sections37_40_sources.json")}
    record = records[SOURCE_ID]
    if (
        record["acquisition"] != "VENDORED_SOURCE_VERIFIED"
        or not record["license"].startswith("CC0")
        or not record["redistribution"].startswith("permitted")
        or record["format"] != "pgn.zip"
    ):
        raise LawfulCorpusError("original Stockfish source rights are not qualified")
    # Source rights evidence is original, independent upstream license bytes.
    # A catalog label alone must never be treated as an authenticated license.
    verified_local_source(
        root / record["license_source"],
        {"sha256": record["license_sha256"], "max_bytes": 1024 * 1024},
    )
    raw = read_verified_zip_member(
        root / record["local_source"], record,
        expected_member=record["zip_member"],
        max_unpacked_bytes=record["max_unpacked_bytes"],
    )
    original = raw.decode("utf-8-sig", errors="strict")
    framer = CanonicalPgnGameFramer(max_frame_bytes=256 * 1024)
    frames = []
    for line in original.splitlines():
        finished = framer.feed_line(line)
        if finished is not None:
            frames.append(finished.text)
            if len(frames) >= _GAME_COUNT:
                break
    if len(frames) != _GAME_COUNT:
        raise LawfulCorpusError("original PGN lacks 32 complete games")
    # Same strict parser used by the canonical owner-seed importer. A source
    # that merely passes the recovery parser must not be shipped as a valid
    # startup Library seed.
    upstream_text = "\n\n".join(frames) + "\n"
    parsed_original = parse_pgn_text(upstream_text, strict=False)
    if len(parsed_original) != _GAME_COUNT or any(not game.line.moves for game in parsed_original):
        raise LawfulCorpusError("verified Stockfish PGN lost original game structures")
    # The historical original opening book is an input, not a product-ready
    # owner seed. Normalize strictly through the EXISTING canonical serializer,
    # never through a new chess formatter, then validate the exact consumed
    # bytes under the owner-seed parser's strict contract.
    derivative_text = "\n\n".join(
        serialize_game(game).rstrip() for game in parsed_original
    ) + "\n"
    parsed = parse_pgn_text(derivative_text, strict=True)
    if len(parsed) != _GAME_COUNT or any(not game.line.moves for game in parsed):
        raise LawfulCorpusError("original Stockfish PGN cannot safely seed Library")
    if len(derivative_text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise LawfulCorpusError("derived real PGN exceeds owner Library budget")
    return derivative_text, record


def prepare_owner_test_stockfish_seed(destination: Path, *, repository_root: Path = ROOT) -> dict:
    """Create a never-overwritten exact user_library_seed package for test use.

    The caller selects a NEW private package-local directory. This does not
    write into the user's live Library, release ZIP, or arbitrary published
    sources. Existing content is never deleted or silently replaced.
    """
    if type(destination) is not Path or type(repository_root) is not Path:
        raise TypeError("corpus seed paths must be Path instances")
    derivative, original = _verified_original_pgntree(repository_root)
    raw = derivative.encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("destination seed already exists")
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise LawfulCorpusError("seed parent must be an existing direct directory")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "bundle_kind": BUNDLE_KIND,
        "runtime_network_required": False,
        "ai_required": False,
        "files": [{
            "file": SEED_PGN_NAME,
            "display_name": "Official Stockfish opening corpus (32 real source games)",
            "bytes": len(raw),
            "sha256": digest,
        }],
    }
    # Stage in one private sibling and only rename a fully verified immutable
    # layout. The canonical seed importer is the validator and publisher.
    with tempfile.TemporaryDirectory(prefix=".acs-real-seed-", dir=destination.parent) as staged:
        staging = Path(staged) / "seed"
        staging.mkdir(mode=0o700)
        (staging / SEED_PGN_NAME).write_bytes(raw)
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verified = load_user_library_seed(staging)
        if len(verified.entries) != 1 or verified.entries[0].sha256 != digest:
            raise LawfulCorpusError("actual-source seed failed canonical preflight")
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("destination changed before seed publication")
        os.rename(staging, destination)

    return {
        "status": "OWNER_TEST_PREPARED_NOT_PUBLIC_RELEASE",
        "source_id": SOURCE_ID,
        "source_sha256": original["sha256"],
        "derived_pgn_sha256": digest,
        "derived_bytes": len(raw),
        "derived_games": _GAME_COUNT,
        "distribution": "OWNER_TEST_ONLY",
        "network_required": False,
    }
