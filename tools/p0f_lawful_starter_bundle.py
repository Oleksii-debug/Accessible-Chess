from __future__ import annotations

"""Build the P0-F release starter Library from one pinned lawful real corpus.

The runtime never downloads anything. This build/qualification tool fetches (or
accepts a local copy of) one exact Lichess standard-rated archive, verifies the
compressed SHA-256, deterministically curates a representative quality sample,
then materializes the existing four-file starter payload contract.
"""

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
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

CURATION_POLICY_VERSION = 1
CURATION_MIN_PLIES = 24
CURATION_MIN_RATING = 600
CURATION_MAX_RATING = 3500
CURATION_POOL_MULTIPLIER = 40
CURATION_RESULT_QUOTA_DIVISOR = 20
CURATION_MIN_OPENING_PREFIXES = 16
_VALID_RESULTS = ("1-0", "0-1", "1/2-1/2")
_RESULT_TOKENS = set(_VALID_RESULTS) | {"*"}
_HEADER_RE = re.compile(r'^\[([A-Za-z0-9_]+)\s+"((?:\\.|[^"])*)"\]\s*$')
_MOVE_NUMBER_RE = re.compile(r"^\d+\.(?:\.\.)?")


@dataclass(frozen=True)
class CuratedCandidate:
    source_index: int
    record: str
    record_sha256: str
    result: str
    plies: int
    white: str
    black: str
    white_elo: int
    black_elo: int
    length_band: str
    opening_prefix: str


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
    """Yield Event-delimited complete PGN records in immutable source order."""
    current: list[str] = []
    inside_brace = False
    source_index = 0
    for line in source:
        if not inside_brace and line.startswith('[Event "') and current:
            record = "".join(current).strip()
            if record:
                source_index += 1
                yield source_index, record
            current = [line]
            inside_brace = _scan_comment_state(line, False)
            continue
        current.append(line)
        inside_brace = _scan_comment_state(line, inside_brace)
    if current:
        record = "".join(current).strip()
        if record:
            source_index += 1
            yield source_index, record


def _write_complete_game_subset(source: io.TextIOBase, destination: Path, limit: int) -> int:
    """Legacy framing helper retained for regression coverage; not release curation."""
    if type(limit) is not int or limit < MINIMUM_REAL_GAME_COUNT:
        raise ValueError(f"starter real-game limit must be >= {MINIMUM_REAL_GAME_COUNT}")
    written = 0
    with destination.open("w", encoding="utf-8", newline="\n") as output:
        for _source_index, record in _iter_complete_game_records(source):
            output.write(record)
            written += 1
            if written >= limit:
                output.write("\n")
                return written
            output.write("\n\n")
    return written


def _parse_headers(record: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in record.splitlines():
        match = _HEADER_RE.match(line.strip())
        if match:
            headers[match.group(1)] = match.group(2).replace(r'\"', '"').replace(r"\\", "\")
    return headers


def _strip_pgn_comments_and_variations(text: str) -> str:
    output: list[str] = []
    brace_depth = 0
    variation_depth = 0
    semicolon = False
    for character in text:
        if semicolon:
            if character in "\r\n":
                semicolon = False
                output.append(" ")
            continue
        if brace_depth:
            if character == "}":
                brace_depth -= 1
            elif character == "{":
                brace_depth += 1
            continue
        if variation_depth:
            if character == "(":
                variation_depth += 1
            elif character == ")":
                variation_depth -= 1
            continue
        if character == ";":
            semicolon = True
        elif character == "{":
            brace_depth = 1
        elif character == "(":
            variation_depth = 1
        else:
            output.append(character)
    return "".join(output)


def _movetext_tokens(record: str) -> tuple[list[str], str | None]:
    body_lines = [line for line in record.splitlines() if not line.lstrip().startswith("[")]
    clean = _strip_pgn_comments_and_variations("\n".join(body_lines))
    moves: list[str] = []
    terminal: str | None = None
    for raw in clean.split():
        if raw.startswith("$"):
            continue
        token = raw
        while True:
            stripped = _MOVE_NUMBER_RE.sub("", token, count=1)
            if stripped == token:
                break
            token = stripped
        if not token or token == "...":
            continue
        if token in _RESULT_TOKENS:
            terminal = token
            continue
        if token.startswith("$"):
            continue
        moves.append(token)
    return moves, terminal


def _length_band(plies: int) -> str:
    if plies < 48:
        return "24-47"
    if plies < 80:
        return "48-79"
    return "80+"


def _candidate_from_record(source_index: int, record: str) -> CuratedCandidate | None:
    headers = _parse_headers(record)
    result = headers.get("Result", "")
    if result not in _VALID_RESULTS:
        return None
    white = headers.get("White", "").strip()
    black = headers.get("Black", "").strip()
    if not white or not black or white == "?" or black == "?" or white == black:
        return None
    try:
        white_elo = int(headers.get("WhiteElo", ""))
        black_elo = int(headers.get("BlackElo", ""))
    except ValueError:
        return None
    if not (
        CURATION_MIN_RATING <= white_elo <= CURATION_MAX_RATING
        and CURATION_MIN_RATING <= black_elo <= CURATION_MAX_RATING
    ):
        return None
    moves, terminal = _movetext_tokens(record)
    if terminal != result or len(moves) < CURATION_MIN_PLIES:
        return None
    opening_prefix = " ".join(moves[:4])
    if len(moves[:4]) < 4 or not opening_prefix:
        return None
    return CuratedCandidate(
        source_index=source_index,
        record=record,
        record_sha256=_sha256_bytes(record.encode("utf-8")),
        result=result,
        plies=len(moves),
        white=white,
        black=black,
        white_elo=white_elo,
        black_elo=black_elo,
        length_band=_length_band(len(moves)),
        opening_prefix=opening_prefix,
    )


def _curation_targets(limit: int) -> tuple[int, int]:
    return max(8, limit // CURATION_RESULT_QUOTA_DIVISOR), min(limit, CURATION_MIN_OPENING_PREFIXES)


def _select_curated_candidates(candidates: list[CuratedCandidate], limit: int) -> list[CuratedCandidate]:
    if type(limit) is not int or limit < MINIMUM_REAL_GAME_COUNT:
        raise ValueError(f"starter real-game limit must be >= {MINIMUM_REAL_GAME_COUNT}")
    if len(candidates) < limit:
        raise RuntimeError(f"curation pool contains only {len(candidates)} qualifying games; need {limit}")
    result_quota, opening_quota = _curation_targets(limit)
    result_counts: Counter[str] = Counter()
    openings: set[str] = set()
    selected: list[CuratedCandidate] = []
    selected_indexes: set[int] = set()
    for candidate in candidates:
        helps_result = result_counts[candidate.result] < result_quota
        helps_opening = len(openings) < opening_quota and candidate.opening_prefix not in openings
        if not (helps_result or helps_opening):
            continue
        selected.append(candidate)
        selected_indexes.add(candidate.source_index)
        result_counts[candidate.result] += 1
        openings.add(candidate.opening_prefix)
    missing_results = {
        result: result_quota - result_counts[result]
        for result in _VALID_RESULTS
        if result_counts[result] < result_quota
    }
    if missing_results or len(openings) < opening_quota:
        raise RuntimeError(
            "pinned source curation pool lacks representative strata: "
            f"results={missing_results}, opening_prefixes={len(openings)}/{opening_quota}"
        )
    for candidate in candidates:
        if len(selected) >= limit:
            break
        if candidate.source_index in selected_indexes:
            continue
        selected.append(candidate)
        selected_indexes.add(candidate.source_index)
    if len(selected) != limit:
        raise RuntimeError(f"curation selected {len(selected)} games; expected {limit}")
    selected.sort(key=lambda item: item.source_index)
    return selected


def _curation_evidence(selected: list[CuratedCandidate], scanned_records: int) -> dict[str, object]:
    result_counts = Counter(item.result for item in selected)
    length_counts = Counter(item.length_band for item in selected)
    opening_prefixes = {item.opening_prefix for item in selected}
    result_quota, opening_quota = _curation_targets(len(selected))
    return {
        "policy_version": CURATION_POLICY_VERSION,
        "selection_policy": "quality-filtered deterministic representative sample from pinned source; source-order stable after stratified quota selection",
        "quality_gate": {
            "allowed_results": list(_VALID_RESULTS),
            "minimum_plies": CURATION_MIN_PLIES,
            "rating_range_inclusive": [CURATION_MIN_RATING, CURATION_MAX_RATING],
            "requires_named_distinct_players": True,
            "requires_terminal_result_match": True,
        },
        "representativeness_gate": {
            "minimum_per_result": result_quota,
            "minimum_distinct_opening_prefixes": opening_quota,
        },
        "scanned_source_records": scanned_records,
        "selected_games": len(selected),
        "result_counts": dict(sorted(result_counts.items())),
        "length_band_counts": dict(sorted(length_counts.items())),
        "distinct_opening_prefixes": len(opening_prefixes),
        "games": [
            {
                "ordinal": ordinal,
                "source_index": item.source_index,
                "record_sha256": item.record_sha256,
                "result": item.result,
                "plies": item.plies,
                "white": item.white,
                "black": item.black,
                "white_elo": item.white_elo,
                "black_elo": item.black_elo,
                "length_band": item.length_band,
                "opening_prefix": item.opening_prefix,
            }
            for ordinal, item in enumerate(selected, start=1)
        ],
    }


def _validate_curation_evidence(starter_pgn: str, evidence: dict[str, object]) -> None:
    records = [record for _index, record in _iter_complete_game_records(io.StringIO(starter_pgn))]
    games = evidence.get("games")
    if not isinstance(games, list) or len(games) != len(records):
        raise ValueError("curation evidence game count does not match starter PGN")
    derived: list[CuratedCandidate] = []
    prior_source_index = 0
    for ordinal, (record, game) in enumerate(zip(records, games, strict=True), start=1):
        if not isinstance(game, dict):
            raise ValueError("curation evidence games must be mappings")
        source_index = game.get("source_index")
        if type(source_index) is not int or source_index <= prior_source_index:
            raise ValueError("curation source indexes must be strictly increasing positive integers")
        prior_source_index = source_index
        candidate = _candidate_from_record(source_index, record)
        if candidate is None:
            raise ValueError(f"starter game {ordinal} does not satisfy curation quality gate")
        expected = {
            "ordinal": ordinal,
            "source_index": source_index,
            "record_sha256": candidate.record_sha256,
            "result": candidate.result,
            "plies": candidate.plies,
            "white": candidate.white,
            "black": candidate.black,
            "white_elo": candidate.white_elo,
            "black_elo": candidate.black_elo,
            "length_band": candidate.length_band,
            "opening_prefix": candidate.opening_prefix,
        }
        if game != expected:
            raise ValueError(f"curation evidence mismatch for starter game {ordinal}")
        derived.append(candidate)
    canonical = _curation_evidence(derived, int(evidence.get("scanned_source_records", len(derived))))
    for key in (
        "policy_version", "selection_policy", "quality_gate", "representativeness_gate",
        "selected_games", "result_counts", "length_band_counts", "distinct_opening_prefixes", "games",
    ):
        if evidence.get(key) != canonical.get(key):
            raise ValueError(f"curation aggregate evidence mismatch: {key}")
    result_quota, opening_quota = _curation_targets(len(derived))
    result_counts = Counter(item.result for item in derived)
    if any(result_counts[result] < result_quota for result in _VALID_RESULTS):
        raise ValueError("curated starter lacks required result representation")
    if len({item.opening_prefix for item in derived}) < opening_quota:
        raise ValueError("curated starter lacks required opening-prefix diversity")


def _write_curated_game_subset(source: io.TextIOBase, destination: Path, limit: int) -> tuple[int, dict[str, object]]:
    if type(limit) is not int or limit < MINIMUM_REAL_GAME_COUNT:
        raise ValueError(f"starter real-game limit must be >= {MINIMUM_REAL_GAME_COUNT}")
    candidates: list[CuratedCandidate] = []
    scanned = 0
    maximum_candidates = limit * CURATION_POOL_MULTIPLIER
    for source_index, record in _iter_complete_game_records(source):
        scanned = source_index
        candidate = _candidate_from_record(source_index, record)
        if candidate is None:
            continue
        candidates.append(candidate)
        if len(candidates) >= maximum_candidates:
            break
    selected = _select_curated_candidates(candidates, limit)
    with destination.open("w", encoding="utf-8", newline="\n") as output:
        for offset, candidate in enumerate(selected):
            if offset:
                output.write("\n\n")
            output.write(candidate.record)
        output.write("\n")
    return len(selected), _curation_evidence(selected, scanned)


def _download_verified(destination: Path) -> int:
    request = Request(CORPUS_URL, headers={"User-Agent": "Accessible-Chess-P0F-Release-Builder/2"})
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


def _extract_subset(compressed: Path, destination: Path, limit: int) -> tuple[int, dict[str, object]]:
    try:
        import zstandard
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("zstandard is required only for build-time Lichess extraction; install zstandard==0.23.0") from exc
    with compressed.open("rb") as source:
        reader = zstandard.ZstdDecompressor().stream_reader(source)
        with reader, io.TextIOWrapper(reader, encoding="utf-8", errors="strict", newline="") as text:
            return _write_curated_game_subset(text, destination, limit)


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
    return {"sha256": _sha256_bytes(payload), "bytes": len(payload), "license_id": license_id}


def _prove_sample_database(path: Path, expected_games: int) -> dict[str, int]:
    with AcsDatabase(path) as database:
        if database.verify_integrity() != ACSDB_SCHEMA_VERSION:
            raise RuntimeError("sample ACSDB integrity/schema verification failed")
        total, distinct, players, events = database.conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT pgn_text), COUNT(DISTINCT white || char(0) || black), COUNT(DISTINCT event) FROM games"
        ).fetchone()
        if total != expected_games or distinct != expected_games:
            raise RuntimeError(f"lawful starter ACSDB count mismatch: total={total}, distinct={distinct}, expected={expected_games}")
        if players < 20:
            raise RuntimeError(f"lawful starter sample lacks player diversity: distinct_player_pairs={players}")
        if events < 1:
            raise RuntimeError("lawful starter sample has no Event metadata")
        return {"games": int(total), "distinct_games": int(distinct), "distinct_player_pairs": int(players), "distinct_events": int(events)}


def build_release_bundle_from_curated_pgn(
    destination: str | Path,
    *,
    starter_pgn: str,
    starter_count: int,
    source_subset_sha256: str,
    source_compressed_bytes: int,
    curation: dict[str, object],
    overwrite: bool = False,
    stress_count: int = STRESS_GAME_COUNT,
) -> dict[str, object]:
    if type(starter_count) is not int or starter_count < MINIMUM_REAL_GAME_COUNT:
        raise ValueError(f"starter_count must be >= {MINIMUM_REAL_GAME_COUNT}")
    records = list(_iter_complete_game_records(io.StringIO(starter_pgn)))
    if len(records) != starter_count:
        raise ValueError("starter PGN complete-record count does not match starter_count")
    if len(source_subset_sha256) != 64 or any(character not in "0123456789abcdefABCDEF" for character in source_subset_sha256):
        raise ValueError("source_subset_sha256 must be a SHA-256 hex digest")
    if type(stress_count) is not int or stress_count <= starter_count:
        raise ValueError("stress_count must be greater than starter_count")
    _validate_curation_evidence(starter_pgn, curation)
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
            "selection": "deterministic quality-and-representativeness curation v1",
            "subset_sha256": source_subset_sha256.lower(),
            "selected_games": starter_count,
        },
        "curation": curation,
        "licenses": {
            CORPUS_LICENSE_ID: {"type": "public-domain-dedication", "url": CORPUS_LICENSE_URL, "source": "Lichess standard database publication"},
            CONTENT_LICENSE_ID: {"type": "project-owned-redistribution-grant", "terms_uk": CONTENT_LICENSE_TERMS_UK},
        },
        "counts": {"starter_games": starter_count, "stress_games": stress_count},
        "sample_library": database_evidence,
        "files": {
            "starter_uk.pgn": _licensed_file(starter_bytes, license_id=CORPUS_LICENSE_ID),
            "stress_uk.pgn": _licensed_file(stress_bytes, license_id=CONTENT_LICENSE_ID),
            "sample_library.acsdb": _licensed_file(library_bytes, license_id=CORPUS_LICENSE_ID),
        },
    }
    _write_text_atomic(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", overwrite=overwrite)
    return manifest


def build_from_pinned_lichess(
    destination: str | Path,
    *,
    overwrite: bool = False,
    starter_count: int = STARTER_REAL_GAME_COUNT,
    stress_count: int = STRESS_GAME_COUNT,
    source_zst: str | Path | None = None,
) -> dict[str, object]:
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
        selected_count, curation = _extract_subset(compressed, subset, starter_count)
        if selected_count != starter_count:
            raise RuntimeError(f"expected {starter_count} curated games, got {selected_count}")
        subset_bytes = subset.read_bytes()
        subset_sha256 = _sha256_bytes(subset_bytes)
        starter_text = subset_bytes.decode("utf-8", errors="strict")
        return build_release_bundle_from_curated_pgn(
            destination,
            starter_pgn=starter_text,
            starter_count=starter_count,
            source_subset_sha256=subset_sha256,
            source_compressed_bytes=compressed_bytes,
            curation=curation,
            overwrite=overwrite,
            stress_count=stress_count,
        )


def _configure_stdout_utf8() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="strict")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the curated lawful CC0 P0-F starter PGN/ACSDB bundle for Accessible Chess.")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--starter-games", type=int, default=STARTER_REAL_GAME_COUNT)
    parser.add_argument("--stress-games", type=int, default=STRESS_GAME_COUNT)
    parser.add_argument("--source-zst", type=Path, default=None, help="Optional local pinned Lichess .pgn.zst; SHA-256 is still verified.")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    manifest = build_from_pinned_lichess(args.destination, overwrite=args.force, starter_count=args.starter_games, stress_count=args.stress_games, source_zst=args.source_zst)
    _configure_stdout_utf8()
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
