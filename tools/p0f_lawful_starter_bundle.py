from __future__ import annotations

"""Build the P0-F release starter Library from one pinned lawful real corpus.

The runtime never downloads anything. This build/qualification tool fetches (or
accepts a local copy of) one exact Lichess standard-rated archive, verifies the
compressed SHA-256, deterministically curates a representative quality subset,
then materializes the existing four-file starter payload contract:

- starter_uk.pgn: immutable lawful real-game sample (CC0-1.0);
- stress_uk.pgn: deterministic project-authored load/search corpus;
- sample_library.acsdb: canonical ACSDB import of starter_uk.pgn;
- manifest.json: hashes, counts, provenance, licenses and curation evidence.

No downloaded archive is required after build time, and no network path is used
by AccessibleChess.exe.
"""

import argparse
from collections import Counter
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
from acs.pgn_roundtrip import PgnRoundTripError, parse_pgn_text  # noqa: E402
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

CURATION_POLICY_ID = "accessible-chess-p0f-real-sample-v1"
CURATION_MIN_PLIES = 20
CURATION_MIN_OPENING_PREFIXES = 12
CURATION_RESULT_MINIMUMS = {
    "1-0": 20,
    "0-1": 20,
    "1/2-1/2": 8,
}
CURATION_LENGTH_MINIMUMS = {
    "20-59": 20,
    "60-99": 20,
    "100+": 8,
}
CURATION_VALID_RESULTS = frozenset(CURATION_RESULT_MINIMUMS)
CURATION_MAX_SCANNED_GAMES = 5_000


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


def _iter_complete_game_records(source: io.TextIOBase):
    """Yield Event-framed PGN records while preserving source bytes as text."""

    current: list[str] = []
    inside_brace = False
    for line in source:
        if not inside_brace and line.startswith('[Event "') and current:
            record = "".join(current).strip()
            if record:
                yield record
            current = [line]
            inside_brace = _scan_comment_state(line, False)
            continue
        current.append(line)
        inside_brace = _scan_comment_state(line, inside_brace)

    if current:
        record = "".join(current).strip()
        if record:
            yield record


def _write_complete_game_subset(source: io.TextIOBase, destination: Path, limit: int) -> int:
    """Legacy framing helper retained for bounded regression coverage."""

    if type(limit) is not int or limit < MINIMUM_REAL_GAME_COUNT:
        raise ValueError(f"starter real-game limit must be >= {MINIMUM_REAL_GAME_COUNT}")

    written = 0
    with destination.open("w", encoding="utf-8", newline="\n") as output:
        for record in _iter_complete_game_records(source):
            output.write(record)
            output.write("\n\n")
            written += 1
            if written >= limit:
                break
    return written


def _metadata_text(tags: dict[str, str], name: str) -> str:
    value = tags.get(name, "").strip()
    if not value or value in {"?", "-"}:
        return ""
    return value


def _length_band(plies: int) -> str:
    if plies < 60:
        return "20-59"
    if plies < 100:
        return "60-99"
    return "100+"


def _candidate_evidence(record: str, source_index: int) -> tuple[dict[str, object] | None, str | None]:
    """Return strict machine-verifiable quality evidence for one source game."""

    try:
        games = parse_pgn_text(record, strict=True)
    except PgnRoundTripError:
        return None, "strict_parse_failure"
    if len(games) != 1:
        return None, "not_exactly_one_game"

    game = games[0]
    tag_result = game.tags.get("Result", "*").strip()
    line_result = game.line.result or "*"
    if tag_result not in CURATION_VALID_RESULTS or line_result != tag_result:
        return None, "invalid_or_unfinished_result"

    white = _metadata_text(game.tags, "White")
    black = _metadata_text(game.tags, "Black")
    event = _metadata_text(game.tags, "Event")
    if not white or not black or not event:
        return None, "missing_player_or_event_metadata"

    plies = len(game.line.moves)
    if plies < CURATION_MIN_PLIES:
        return None, "too_short"

    opening_moves = tuple(node.san for node in game.line.moves[:4])
    if len(opening_moves) < 4:
        return None, "insufficient_opening_prefix"

    return {
        "source_index": source_index,
        "event": event,
        "white": white,
        "black": black,
        "result": tag_result,
        "plies": plies,
        "length_band": _length_band(plies),
        "opening_prefix": list(opening_moves),
        "record_sha256": _sha256_bytes(record.encode("utf-8")),
    }, None


def _representative_pool_ready(candidates: list[dict[str, object]], limit: int) -> bool:
    if len(candidates) < limit:
        return False

    result_counts = Counter(str(candidate["result"]) for candidate in candidates)
    if any(result_counts[result] < minimum for result, minimum in CURATION_RESULT_MINIMUMS.items()):
        return False

    length_counts = Counter(str(candidate["length_band"]) for candidate in candidates)
    if any(
        length_counts[band] < minimum
        for band, minimum in CURATION_LENGTH_MINIMUMS.items()
    ):
        return False

    openings = {tuple(candidate["opening_prefix"]) for candidate in candidates}
    return len(openings) >= CURATION_MIN_OPENING_PREFIXES


def _select_representative_candidates(
    candidates: list[dict[str, object]], limit: int
) -> list[dict[str, object]]:
    """Select deterministically while making every representation floor mandatory."""

    if type(limit) is not int or limit < MINIMUM_REAL_GAME_COUNT:
        raise ValueError(f"starter real-game limit must be >= {MINIMUM_REAL_GAME_COUNT}")
    if not _representative_pool_ready(candidates, limit):
        raise RuntimeError("eligible source pool does not satisfy representative curation floors")

    required: set[int] = set()

    for result, minimum in CURATION_RESULT_MINIMUMS.items():
        matches = [
            index for index, candidate in enumerate(candidates)
            if candidate["result"] == result
        ][:minimum]
        required.update(matches)

    for band, minimum in CURATION_LENGTH_MINIMUMS.items():
        matches = [
            index for index, candidate in enumerate(candidates)
            if candidate["length_band"] == band
        ][:minimum]
        required.update(matches)

    seen_openings: set[tuple[str, ...]] = set()
    for index, candidate in enumerate(candidates):
        opening = tuple(str(move) for move in candidate["opening_prefix"])
        if opening in seen_openings:
            continue
        seen_openings.add(opening)
        required.add(index)
        if len(seen_openings) >= CURATION_MIN_OPENING_PREFIXES:
            break

    if len(required) > limit:
        raise RuntimeError("curation floors exceed requested starter sample size")

    selected = set(required)
    for index in range(len(candidates)):
        if len(selected) >= limit:
            break
        selected.add(index)

    chosen = [candidates[index] for index in sorted(selected)]
    if len(chosen) != limit:
        raise RuntimeError(f"expected {limit} curated games, selected {len(chosen)}")
    return chosen


def _selected_aggregate_evidence(selected: list[dict[str, object]]) -> dict[str, object]:
    result_counts = Counter(str(candidate["result"]) for candidate in selected)
    length_counts = Counter(str(candidate["length_band"]) for candidate in selected)
    openings = {tuple(candidate["opening_prefix"]) for candidate in selected}

    for result, minimum in CURATION_RESULT_MINIMUMS.items():
        if result_counts[result] < minimum:
            raise RuntimeError(f"curated sample lacks result stratum {result}")
    for band, minimum in CURATION_LENGTH_MINIMUMS.items():
        if length_counts[band] < minimum:
            raise RuntimeError(f"curated sample lacks length stratum {band}")
    if len(openings) < CURATION_MIN_OPENING_PREFIXES:
        raise RuntimeError("curated sample lacks opening-prefix diversity")

    return {
        "selected_result_counts": dict(sorted(result_counts.items())),
        "selected_length_band_counts": dict(sorted(length_counts.items())),
        "distinct_opening_prefixes": len(openings),
    }


def _curate_complete_game_subset(
    source: io.TextIOBase,
    destination: Path,
    limit: int,
) -> dict[str, object]:
    """Fail-closed deterministic curation of a representative real-game sample."""

    if type(limit) is not int or limit < MINIMUM_REAL_GAME_COUNT:
        raise ValueError(f"starter real-game limit must be >= {MINIMUM_REAL_GAME_COUNT}")

    candidates: list[dict[str, object]] = []
    records: dict[int, str] = {}
    rejected: Counter[str] = Counter()
    scanned = 0

    for source_index, record in enumerate(_iter_complete_game_records(source), start=1):
        scanned = source_index
        evidence, reason = _candidate_evidence(record, source_index)
        if evidence is None:
            rejected[reason or "unknown"] += 1
        else:
            records[source_index] = record
            candidates.append(evidence)
            if _representative_pool_ready(candidates, limit):
                break
        if scanned >= CURATION_MAX_SCANNED_GAMES:
            break

    if not _representative_pool_ready(candidates, limit):
        raise RuntimeError(
            "pinned source did not satisfy curation floors within "
            f"{CURATION_MAX_SCANNED_GAMES} scanned games"
        )

    selected = _select_representative_candidates(candidates, limit)
    with destination.open("w", encoding="utf-8", newline="\n") as output:
        for candidate in selected:
            output.write(records[int(candidate["source_index"])])
            output.write("\n\n")

    aggregate = _selected_aggregate_evidence(selected)
    return {
        "policy_id": CURATION_POLICY_ID,
        "parser": "acs.pgn_roundtrip.parse_pgn_text(strict=True)",
        "criteria": {
            "minimum_plies": CURATION_MIN_PLIES,
            "valid_results": sorted(CURATION_VALID_RESULTS),
            "required_metadata": ["Event", "White", "Black"],
            "result_minimums": CURATION_RESULT_MINIMUMS,
            "length_band_minimums": CURATION_LENGTH_MINIMUMS,
            "minimum_distinct_opening_prefixes": CURATION_MIN_OPENING_PREFIXES,
            "opening_prefix_plies": 4,
            "maximum_scanned_games": CURATION_MAX_SCANNED_GAMES,
        },
        "scanned_records": scanned,
        "eligible_records": len(candidates),
        "rejected_records": dict(sorted(rejected.items())),
        "selected_games": selected,
        **aggregate,
    }


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


def _extract_curated_subset(
    compressed: Path,
    destination: Path,
    limit: int,
) -> dict[str, object]:
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
            return _curate_complete_game_subset(text, destination, limit)


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
    """Prove the binding W2 sample properties without inventing event-count rules."""

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
        if players < 20:
            raise RuntimeError(
                f"lawful starter sample lacks player diversity: distinct_player_pairs={players}"
            )
        if events < 1:
            raise RuntimeError("lawful starter sample has no Event metadata")
        return {
            "games": int(total),
            "distinct_games": int(distinct),
            "distinct_player_pairs": int(players),
            "distinct_events": int(events),
        }


def _validate_curation_manifest_evidence(
    evidence: dict[str, object],
    starter_count: int,
    starter_pgn: str,
) -> None:
    if not isinstance(evidence, dict):
        raise TypeError("curation_evidence must be a dictionary")
    if evidence.get("policy_id") != CURATION_POLICY_ID:
        raise ValueError("curation evidence has an unexpected policy identity")
    if evidence.get("parser") != "acs.pgn_roundtrip.parse_pgn_text(strict=True)":
        raise ValueError("curation evidence has an unexpected parser identity")
    criteria = evidence.get("criteria")
    if not isinstance(criteria, dict):
        raise ValueError("curation evidence criteria are missing")
    expected_criteria = {
        "minimum_plies": CURATION_MIN_PLIES,
        "valid_results": sorted(CURATION_VALID_RESULTS),
        "required_metadata": ["Event", "White", "Black"],
        "result_minimums": CURATION_RESULT_MINIMUMS,
        "length_band_minimums": CURATION_LENGTH_MINIMUMS,
        "minimum_distinct_opening_prefixes": CURATION_MIN_OPENING_PREFIXES,
        "opening_prefix_plies": 4,
        "maximum_scanned_games": CURATION_MAX_SCANNED_GAMES,
    }
    if criteria != expected_criteria:
        raise ValueError("curation evidence criteria do not match the qualified policy")
    selected = evidence.get("selected_games")
    if not isinstance(selected, list) or len(selected) != starter_count:
        raise ValueError("curation evidence selected_games count does not match starter_count")
    aggregate = _selected_aggregate_evidence(selected)
    for key, value in aggregate.items():
        if evidence.get(key) != value:
            raise ValueError(f"curation aggregate mismatch for {key}")

    records = list(_iter_complete_game_records(io.StringIO(starter_pgn)))
    if len(records) != starter_count:
        raise ValueError("starter PGN record count does not match curation evidence")
    expected_hashes = [
        str(candidate.get("record_sha256", "")).lower()
        for candidate in selected
        if isinstance(candidate, dict)
    ]
    actual_hashes = [_sha256_bytes(record.encode("utf-8")) for record in records]
    if expected_hashes != actual_hashes:
        raise ValueError("curation evidence does not match selected starter PGN records")


def build_release_bundle_from_curated_pgn(
    destination: str | Path,
    *,
    starter_pgn: str,
    starter_count: int,
    source_subset_sha256: str,
    source_compressed_bytes: int,
    curation_evidence: dict[str, object],
    overwrite: bool = False,
    stress_count: int = STRESS_GAME_COUNT,
) -> dict[str, object]:
    """Materialize the release four-file bundle from a verified curated lawful subset."""

    if type(starter_count) is not int or starter_count < MINIMUM_REAL_GAME_COUNT:
        raise ValueError(f"starter_count must be >= {MINIMUM_REAL_GAME_COUNT}")
    if starter_pgn.count('[Event "') != starter_count:
        raise ValueError("starter PGN complete-record count does not match starter_count")
    if len(source_subset_sha256) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in source_subset_sha256
    ):
        raise ValueError("source_subset_sha256 must be a SHA-256 hex digest")
    if type(stress_count) is not int or stress_count <= starter_count:
        raise ValueError("stress_count must be greater than starter_count")
    _validate_curation_manifest_evidence(curation_evidence, starter_count, starter_pgn)

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
            "selection": CURATION_POLICY_ID,
            "subset_sha256": source_subset_sha256.lower(),
            "selected_games": starter_count,
            "curation": curation_evidence,
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
    """Verify the pinned CC0 archive, curate a representative sample, and build assets."""

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

        curation_evidence = _extract_curated_subset(compressed, subset, starter_count)
        selected = curation_evidence["selected_games"]
        if not isinstance(selected, list) or len(selected) != starter_count:
            raise RuntimeError(f"expected {starter_count} curated games")
        subset_bytes = subset.read_bytes()
        subset_sha256 = _sha256_bytes(subset_bytes)
        starter_text = subset_bytes.decode("utf-8", errors="strict")

        return build_release_bundle_from_curated_pgn(
            destination,
            starter_pgn=starter_text,
            starter_count=starter_count,
            source_subset_sha256=subset_sha256,
            source_compressed_bytes=compressed_bytes,
            curation_evidence=curation_evidence,
            overwrite=overwrite,
            stress_count=stress_count,
        )


def _configure_stdout_utf8() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="strict")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the curated lawful CC0 P0-F starter PGN/ACSDB bundle for Accessible Chess."
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
