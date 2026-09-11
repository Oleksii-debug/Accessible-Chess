from __future__ import annotations

"""Build the P0-F release starter Library from one pinned lawful real corpus.

The runtime never downloads anything. This build/qualification tool fetches (or
accepts a local copy of) one exact Lichess standard-rated archive, verifies the
compressed SHA-256, extracts the first N complete PGN records, then materializes
the existing four-file starter payload contract:

- starter_uk.pgn: immutable lawful real-game sample (CC0-1.0);
- stress_uk.pgn: deterministic project-authored load/search corpus;
- sample_library.acsdb: canonical ACSDB import of starter_uk.pgn;
- manifest.json: hashes, counts, provenance, licenses and selection policy.

No downloaded archive is required after build time, and no network path is used
by AccessibleChess.exe.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from acs.acsdb import ACSDB_SCHEMA_VERSION, AcsDatabase  # noqa: E402
from acs.starter_content import (  # noqa: E402
    CONTENT_LICENSE_ID,
    CONTENT_LICENSE_TERMS_UK,
    STRESS_GAME_COUNT,
    build_sample_library,
    build_stress_pgn,
)


CORPUS_NAME = "lichess-standard-rated-2013-01"
CORPUS_URL = "https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst"
CORPUS_SHA256 = "aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635"
CORPUS_LICENSE_ID = "CC0-1.0"
CORPUS_LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
CORPUS_PUBLISHED_GAMES = 121_332
STARTER_REAL_GAME_COUNT = 240
MINIMUM_REAL_GAME_COUNT = 200
DOWNLOAD_LIMIT_BYTES = 32 * 1024 * 1024
DOWNLOAD_CHUNK = 1024 * 1024


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(DOWNLOAD_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scan_comment_state(line: str, inside_brace: bool) -> bool:
    for character in line:
        if inside_brace:
            if character == "}":
                inside_brace = False
            continue
        if character == ";":
            break
        if character == "{":
            inside_brace = True
    return inside_brace


def _write_complete_game_subset(source: io.TextIOBase, destination: Path, limit: int) -> int:
    """Frame complete Event-delimited PGN records without changing PGN semantics."""

    if type(limit) is not int or limit < MINIMUM_REAL_GAME_COUNT:
        raise ValueError(f"starter real-game limit must be >= {MINIMUM_REAL_GAME_COUNT}")

    current: list[str] = []
    inside_brace = False
    written = 0
    with destination.open("w", encoding="utf-8", newline="\n") as output:
        for line in source:
            if not inside_brace and line.startswith('[Event "') and current:
                record = "".join(current).strip()
                if record:
                    output.write(record)
                    output.write("\n\n")
                    written += 1
                    if written >= limit:
                        return written
                current = [line]
                inside_brace = _scan_comment_state(line, False)
                continue
            current.append(line)
            inside_brace = _scan_comment_state(line, inside_brace)

        if current and written < limit:
            record = "".join(current).strip()
            if record:
                output.write(record)
                output.write("\n")
                written += 1
    return written


def _download_verified(destination: Path) -> int:
    request = Request(CORPUS_URL, headers={"User-Agent": "Accessible-Chess-P0F-Release-Builder/1"})
    digest = hashlib.sha256()
    total = 0
    response = urlopen(request, timeout=60)
    with response, destination.open("wb") as output:
        while True:
            chunk = response.read(DOWNLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > DOWNLOAD_LIMIT_BYTES:
                raise RuntimeError("compressed Lichess corpus exceeds qualified download bound")
            digest.update(chunk)
            output.write(chunk)
    actual = digest.hexdigest()
    if actual != CORPUS_SHA256:
        raise AssertionError(f"Lichess corpus digest mismatch: {actual}")
    return total


def _verify_local_source(path: Path) -> int:
    if not path.is_file():
        raise FileNotFoundError(path)
    size = path.stat().st_size
    if size > DOWNLOAD_LIMIT_BYTES:
        raise RuntimeError("compressed Lichess corpus exceeds qualified download bound")
    actual = _sha256_file(path)
    if actual != CORPUS_SHA256:
        raise AssertionError(f"Lichess corpus digest mismatch: {actual}")
    return size


def _extract_subset(compressed: Path, destination: Path, limit: int) -> int:
    try:
        import zstandard
    except ImportError as exc:  # pragma: no cover - dependency is exercised in Actions.
        raise RuntimeError(
            "zstandard is required only for build-time Lichess extraction; "
            "install the pinned qualification dependency zstandard==0.23.0"
        ) from exc

    with compressed.open("rb") as source:
        reader = zstandard.ZstdDecompressor().stream_reader(source)
        with reader, io.TextIOWrapper(reader, encoding="utf-8", errors="strict", newline="") as text:
            return _write_complete_game_subset(text, destination, limit)


def _write_text_atomic(path: Path, text: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _licensed_file(payload: bytes, *, license_id: str) -> dict[str, object]:
    return {
        "sha256": _sha256_bytes(payload),
        "bytes": len(payload),
        "license_id": license_id,
    }


def _prove_sample_database(path: Path, expected_games: int) -> dict[str, int]:
    with AcsDatabase(path) as database:
        if database.verify_integrity() != ACSDB_SCHEMA_VERSION:
            raise RuntimeError("sample ACSDB integrity/schema verification failed")
        total, distinct, players, events = database.conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT pgn_text), "
            "COUNT(DISTINCT white || char(0) || black), COUNT(DISTINCT event) FROM games"
        ).fetchone()
        if total != expected_games or distinct != expected_games:
            raise RuntimeError(
                f"lawful starter ACSDB count mismatch: total={total}, distinct={distinct}, "
                f"expected={expected_games}"
            )
        if players < 20 or events < 5:
            raise RuntimeError(
                f"lawful starter sample lacks useful metadata diversity: players={players}, events={events}"
            )
        return {
            "games": int(total),
            "distinct_games": int(distinct),
            "distinct_player_pairs": int(players),
            "distinct_events": int(events),
        }


def build_release_bundle_from_curated_pgn(
    destination: str | Path,
    *,
    starter_pgn: str,
    starter_count: int,
    source_subset_sha256: str,
    source_compressed_bytes: int,
    overwrite: bool = False,
    stress_count: int = STRESS_GAME_COUNT,
) -> dict[str, object]:
    """Materialize the release four-file bundle from a verified lawful PGN subset."""

    if type(starter_count) is not int or starter_count < MINIMUM_REAL_GAME_COUNT:
        raise ValueError(f"starter_count must be >= {MINIMUM_REAL_GAME_COUNT}")
    if starter_pgn.count('[Event "') != starter_count:
        raise ValueError("starter PGN complete-record count does not match starter_count")
    if len(source_subset_sha256) != 64:
        raise ValueError("source_subset_sha256 must be a SHA-256 hex digest")
    if type(stress_count) is not int or stress_count <= starter_count:
        raise ValueError("stress_count must be greater than starter_count")

    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    starter_path = output / "starter_uk.pgn"
    stress_path = output / "stress_uk.pgn"
    library_path = output / "sample_library.acsdb"
    manifest_path = output / "manifest.json"

    if not overwrite:
        for path in (starter_path, stress_path, library_path, manifest_path):
            if path.exists():
                raise FileExistsError(path)

    stress_pgn = build_stress_pgn(stress_count)
    _write_text_atomic(starter_path, starter_pgn, overwrite=overwrite)
    _write_text_atomic(stress_path, stress_pgn, overwrite=overwrite)
    build_sample_library(library_path, starter_pgn=starter_pgn, overwrite=overwrite)
    database_evidence = _prove_sample_database(library_path, starter_count)

    starter_bytes = starter_path.read_bytes()
    stress_bytes = stress_path.read_bytes()
    library_bytes = library_path.read_bytes()
    manifest: dict[str, object] = {
        "schema_version": 3,
        "bundle_kind": "lawful-curated-real-game-starter",
        "runtime_network_required": False,
        "starter_source": {
            "name": CORPUS_NAME,
            "url": CORPUS_URL,
            "license_id": CORPUS_LICENSE_ID,
            "published_games": CORPUS_PUBLISHED_GAMES,
            "compressed_sha256": CORPUS_SHA256,
            "compressed_bytes": source_compressed_bytes,
            "selection": f"first {starter_count} complete Event-framed standard-rated games",
            "subset_sha256": source_subset_sha256,
            "selected_games": starter_count,
        },
        "licenses": {
            CORPUS_LICENSE_ID: {
                "type": "public-domain-dedication",
                "url": CORPUS_LICENSE_URL,
                "source": "Lichess standard database publication",
            },
            CONTENT_LICENSE_ID: {
                "type": "project-owned-redistribution-grant",
                "terms_uk": CONTENT_LICENSE_TERMS_UK,
            },
        },
        "counts": {
            "starter_games": starter_count,
            "stress_games": stress_count,
        },
        "sample_library": database_evidence,
        "files": {
            "starter_uk.pgn": _licensed_file(starter_bytes, license_id=CORPUS_LICENSE_ID),
            "stress_uk.pgn": _licensed_file(stress_bytes, license_id=CONTENT_LICENSE_ID),
            "sample_library.acsdb": _licensed_file(library_bytes, license_id=CORPUS_LICENSE_ID),
        },
    }
    _write_text_atomic(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        overwrite=overwrite,
    )
    return manifest


def build_from_pinned_lichess(
    destination: str | Path,
    *,
    overwrite: bool = False,
    starter_count: int = STARTER_REAL_GAME_COUNT,
    stress_count: int = STRESS_GAME_COUNT,
    source_zst: str | Path | None = None,
) -> dict[str, object]:
    """Verify the pinned CC0 archive, extract a bounded sample, and build release assets."""

    with tempfile.TemporaryDirectory(prefix="accessible-chess-p0f-lawful-") as temporary:
        root = Path(temporary)
        compressed = root / "lichess.pgn.zst"
        subset = root / "starter_uk.pgn"

        if source_zst is None:
            compressed_bytes = _download_verified(compressed)
        else:
            source = Path(source_zst)
            compressed_bytes = _verify_local_source(source)
            shutil.copyfile(source, compressed)

        segmented = _extract_subset(compressed, subset, starter_count)
        if segmented != starter_count:
            raise RuntimeError(f"expected {starter_count} complete games, got {segmented}")
        subset_bytes = subset.read_bytes()
        subset_sha256 = _sha256_bytes(subset_bytes)
        starter_text = subset_bytes.decode("utf-8", errors="strict")

        return build_release_bundle_from_curated_pgn(
            destination,
            starter_pgn=starter_text,
            starter_count=starter_count,
            source_subset_sha256=subset_sha256,
            source_compressed_bytes=compressed_bytes,
            overwrite=overwrite,
            stress_count=stress_count,
        )


def _configure_stdout_utf8() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="strict")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the lawful CC0 P0-F starter PGN/ACSDB bundle for Accessible Chess."
    )
    parser.add_argument("destination", type=Path)
    parser.add_argument("--starter-games", type=int, default=STARTER_REAL_GAME_COUNT)
    parser.add_argument("--stress-games", type=int, default=STRESS_GAME_COUNT)
    parser.add_argument(
        "--source-zst",
        type=Path,
        default=None,
        help="Optional local pinned Lichess .pgn.zst; SHA-256 is still verified.",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    manifest = build_from_pinned_lichess(
        args.destination,
        overwrite=args.force,
        starter_count=args.starter_games,
        stress_count=args.stress_games,
        source_zst=args.source_zst,
    )
    _configure_stdout_utf8()
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
