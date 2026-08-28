from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import random
import tempfile
import time
from typing import Iterator
from urllib.request import Request, urlopen

import zstandard

from acs.acsdb import AcsDatabase
from acs.game_identity import same_game_tree
from acs.gametree import PgnGame, parse_games
from acs.library_import_service import LibraryImportService
from acs.pgn_service import open_pgn, save_pgn_atomic
from acs.search_service import GameSearchItem, GameSearchQuery, GameSearchService


@dataclass(frozen=True, slots=True)
class CorpusSpec:
    name: str
    url: str
    sha256: str
    license: str
    published_games: int


STANDARD = CorpusSpec(
    name="lichess-standard-rated-2013-01",
    url="https://database.lichess.org/standard/lichess_db_standard_rated_2013-01.pgn.zst",
    sha256="aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635",
    license="CC0",
    published_games=121_332,
)
UNICODE = CorpusSpec(
    name="lichess-broadcast-2026-02",
    url="https://database.lichess.org/broadcast/lichess_db_broadcast_2026-02.pgn.zst",
    sha256="ea977569917718b33940ba5379db2adad77d58876c29084294d357f15fe6a31b",
    license="CC BY-SA 4.0",
    published_games=19_752,
)
STANDARD_GAMES = 10_000
UNICODE_SCAN_LIMIT = 2_000
PAGE_LIMIT = 200
DOWNLOAD_LIMIT = 32 * 1024 * 1024
DOWNLOAD_CHUNK = 1024 * 1024
SAMPLE_RANDOM = 32
SAMPLE_SEED = 20260828
SEARCHABLE_TAGS = (
    ("White", "player"),
    ("Black", "player"),
    ("Event", "event"),
    ("ECO", "eco"),
    ("Opening", "opening"),
)


def _scan_comment_state(line: str, inside_brace: bool) -> bool:
    for char in line:
        if inside_brace:
            if char == "}":
                inside_brace = False
        elif char == ";":
            break
        elif char == "{":
            inside_brace = True
    return inside_brace


def _records(stream: io.TextIOBase, limit: int) -> Iterator[tuple[int, str]]:
    """Split only on complete Event-tag boundaries; Product owns PGN semantics."""
    current: list[str] = []
    in_brace = False
    ordinal = 0
    for line in stream:
        if current and not in_brace and line.startswith('[Event "'):
            record = "".join(current).strip()
            if record:
                yield ordinal, record + "\n"
                ordinal += 1
                if ordinal >= limit:
                    return
            current = [line]
            in_brace = _scan_comment_state(line, False)
            continue
        current.append(line)
        in_brace = _scan_comment_state(line, in_brace)
    if current and ordinal < limit:
        record = "".join(current).strip()
        if record:
            yield ordinal, record + "\n"


def _download(spec: CorpusSpec, destination: Path) -> int:
    request = Request(spec.url, headers={"User-Agent": "Accessible-Chess-Real-Corpus-QA/3"})
    digest = hashlib.sha256()
    total = 0
    try:
        response = urlopen(request, timeout=60)
    except Exception as exc:
        raise RuntimeError(f"download failed for {spec.name}: {type(exc).__name__}") from exc
    with response, destination.open("wb") as output:
        while True:
            chunk = response.read(DOWNLOAD_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > DOWNLOAD_LIMIT:
                raise RuntimeError(f"compressed corpus exceeds QA bound: {spec.name}")
            digest.update(chunk)
            output.write(chunk)
    actual = digest.hexdigest()
    if actual != spec.sha256:
        raise AssertionError(f"corpus digest mismatch for {spec.name}: {actual}")
    return total


def _open_zstd(path: Path):
    raw = path.open("rb")
    reader = zstandard.ZstdDecompressor().stream_reader(raw, closefd=False)
    text = io.TextIOWrapper(reader, encoding="utf-8", errors="strict", newline="")
    return raw, text


def _close_zstd(raw, text) -> None:
    try:
        text.close()
    finally:
        raw.close()


def _write_standard_subset(compressed: Path, subset: Path) -> int:
    raw, text = _open_zstd(compressed)
    count = 0
    try:
        with subset.open("w", encoding="utf-8", newline="\n") as output:
            for _ordinal, record in _records(text, STANDARD_GAMES):
                output.write(record)
                output.write("\n")
                count += 1
    finally:
        _close_zstd(raw, text)
    return count


def _non_ascii(value: str | None) -> bool:
    return bool(value and any(ord(char) > 127 for char in value))


def _unicode_case(games: tuple[PgnGame, ...]) -> tuple[int, str, str] | None:
    for index, game in enumerate(games):
        for tag, field in SEARCHABLE_TAGS:
            value = game.tags.get(tag)
            if _non_ascii(value):
                assert value is not None
                return index, field, value
    return None


def _record_has_searchable_unicode(record: str) -> bool:
    prefixes = tuple(f'[{tag} "' for tag, _field in SEARCHABLE_TAGS)
    return any(
        line.startswith(prefixes) and any(ord(char) > 127 for char in line)
        for line in record.splitlines()
    )


def _find_unicode_record(compressed: Path, candidate: Path):
    raw, text = _open_zstd(compressed)
    scanned = 0
    try:
        for ordinal, record in _records(text, UNICODE_SCAN_LIMIT):
            scanned = ordinal + 1
            if not _record_has_searchable_unicode(record):
                continue
            candidate.write_text(record, encoding="utf-8", newline="\n")
            try:
                opened = open_pgn(candidate)
            except Exception:
                continue
            if opened.total_games != 1 or opened.global_warnings or opened.warning_games:
                continue
            case = _unicode_case(opened.games)
            if case is not None:
                return opened, ordinal, scanned, case
    finally:
        _close_zstd(raw, text)
    raise AssertionError(
        f"no strict searchable Unicode record in first {scanned} records of {UNICODE.name}"
    )


def _literal_case(games: tuple[PgnGame, ...]) -> tuple[int, str, str] | None:
    for index, game in enumerate(games):
        for tag, field in SEARCHABLE_TAGS:
            value = game.tags.get(tag)
            if value and any(marker in value for marker in ("%", "_", "\\")):
                return index, field, value
    return None


def _search(database: AcsDatabase, source_id: int, field: str, value: str):
    query = GameSearchQuery(**{field: value, "source_id": source_id, "limit": PAGE_LIMIT})
    started = time.perf_counter()
    page = GameSearchService(database).search(query)
    return page.items, time.perf_counter() - started


def _enumerate(database: AcsDatabase, source_id: int):
    service = GameSearchService(database)
    cursor: int | None = None
    items: list[GameSearchItem] = []
    pages = 0
    started = time.perf_counter()
    while True:
        page = service.search(
            GameSearchQuery(source_id=source_id, after_game_id=cursor, limit=PAGE_LIMIT)
        )
        pages += 1
        if page.items:
            if items and page.items[0].game_id <= items[-1].game_id:
                raise AssertionError("keyset order did not advance")
            items.extend(page.items)
        if not page.has_more:
            if page.next_after_game_id is not None:
                raise AssertionError("terminal page unexpectedly published a cursor")
            break
        if page.next_after_game_id is None:
            raise AssertionError("non-terminal page omitted a cursor")
        if cursor is not None and page.next_after_game_id <= cursor:
            raise AssertionError("keyset cursor did not advance")
        cursor = page.next_after_game_id
    return tuple(items), pages, time.perf_counter() - started


def _integrity(database: AcsDatabase, expected_games: int) -> dict[str, int | str]:
    quick = str(database.conn.execute("PRAGMA quick_check").fetchone()[0])
    if quick != "ok":
        raise AssertionError(f"quick_check={quick}")
    if database.conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise AssertionError("foreign_key_check failed")
    if database.verify_integrity() != 6:
        raise AssertionError("public ACSDB integrity verification did not return schema 6")
    games = int(database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0])
    folds = int(database.conn.execute("SELECT COUNT(*) FROM game_search_fold").fetchone()[0])
    dirty = int(database.conn.execute("SELECT COUNT(*) FROM game_search_fold_dirty").fetchone()[0])
    if games != expected_games or folds != expected_games or dirty != 0:
        raise AssertionError(f"v6 projection mismatch games={games} folds={folds} dirty={dirty}")
    return {"quick_check": quick, "games": games, "search_fold_rows": folds, "dirty_rows": dirty}


def _sample_indexes(total: int) -> tuple[int, ...]:
    rng = random.Random(SAMPLE_SEED)
    middle = list(range(1, total - 1))
    count = min(SAMPLE_RANDOM, len(middle))
    return tuple(sorted({0, total - 1, *rng.sample(middle, count)}))


def _stored_game(database: AcsDatabase, game_id: int) -> PgnGame:
    row = database.get_game(game_id)
    if row is None:
        raise AssertionError(f"stored game missing: {game_id}")
    games = parse_games(row["pgn_text"])
    if len(games) != 1:
        raise AssertionError(f"stored row did not reopen as one game: {game_id}")
    return games[0]


def _peak_rss_kib() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="accessible-chess-real-v6-") as raw_root:
        root = Path(raw_root)
        standard_zst = root / "standard.pgn.zst"
        standard_pgn = root / "standard-10000.pgn"
        unicode_zst = root / "broadcast.pgn.zst"
        unicode_pgn = root / "broadcast-unicode.pgn"
        exported_pgn = root / "sample-export.pgn"
        db_path = root / "library.acsdb"

        standard_compressed_bytes = _download(STANDARD, standard_zst)
        if _write_standard_subset(standard_zst, standard_pgn) != STANDARD_GAMES:
            raise AssertionError("failed to segment exactly 10,000 complete standard games")

        parse_started = time.perf_counter()
        standard_opened = open_pgn(standard_pgn)
        parse_seconds = time.perf_counter() - parse_started
        standard_games = standard_opened.games
        if len(standard_games) != STANDARD_GAMES:
            raise AssertionError(f"canonical parser returned {len(standard_games)} standard games")
        if standard_opened.global_warnings or standard_opened.warning_games:
            raise AssertionError("standard 10k source was not warning-free")

        unicode_compressed_bytes = _download(UNICODE, unicode_zst)
        unicode_opened, unicode_ordinal, unicode_scanned, unicode_case = _find_unicode_record(
            unicode_zst, unicode_pgn
        )
        unicode_games = unicode_opened.games
        unicode_index, unicode_field, unicode_value = unicode_case
        literal = _literal_case(standard_games)

        database = AcsDatabase(db_path)
        try:
            if database.schema_version != 6:
                raise AssertionError(f"expected schema 6, got {database.schema_version}")

            import_started = time.perf_counter()
            standard_result = LibraryImportService(database).import_games(
                standard_games,
                source_name=f"{STANDARD.name}-first-{STANDARD_GAMES}.pgn",
                source_format="pgn",
                source_sha256=standard_opened.source.sha256,
                source_warning_count=0,
            )
            standard_import_seconds = time.perf_counter() - import_started
            if standard_result.game_count != STANDARD_GAMES:
                raise AssertionError("standard Library import count mismatch")

            unicode_import_started = time.perf_counter()
            unicode_result = LibraryImportService(database).import_games(
                unicode_games,
                source_name=f"{UNICODE.name}-unicode-record-{unicode_ordinal}.pgn",
                source_format="pgn",
                source_sha256=unicode_opened.source.sha256,
                source_warning_count=0,
            )
            unicode_import_seconds = time.perf_counter() - unicode_import_started

            expected_total = STANDARD_GAMES + len(unicode_games)
            integrity_before = _integrity(database, expected_total)

            items, pages, enumerate_seconds = _enumerate(database, standard_result.source_id)
            if len(items) != STANDARD_GAMES:
                raise AssertionError("public Search did not enumerate all 10,000 standard games")
            indexes = [item.source_index for item in items]
            if indexes != list(range(STANDARD_GAMES)):
                raise AssertionError("source_index sequence is not contiguous 0..9999")
            by_index = {item.source_index: item for item in items}

            unicode_query = unicode_value.swapcase()
            unicode_items, unicode_search_seconds = _search(
                database, unicode_result.source_id, unicode_field, unicode_query
            )
            if unicode_index not in {item.source_index for item in unicode_items}:
                raise AssertionError("real Unicode query did not find the imported record")

            literal_evidence: dict[str, object]
            if literal is None:
                literal_evidence = {"observed": False}
            else:
                literal_index, literal_field, literal_value = literal
                literal_items, literal_seconds = _search(
                    database, standard_result.source_id, literal_field, literal_value
                )
                if literal_index not in {item.source_index for item in literal_items}:
                    raise AssertionError("natural literal-metachar query did not find its source game")
                literal_evidence = {
                    "observed": True,
                    "source_index": literal_index,
                    "field": literal_field,
                    "value": literal_value,
                    "elapsed_seconds": literal_seconds,
                }

            sample_indexes = _sample_indexes(STANDARD_GAMES)
            sample_games: list[PgnGame] = []
            sample_rows: list[dict[str, object]] = []
            for source_index in sample_indexes:
                item = by_index[source_index]
                stored = _stored_game(database, item.game_id)
                reference = standard_games[source_index]
                if stored.tags != reference.tags or not same_game_tree(stored, reference):
                    raise AssertionError(f"stored game mismatch at source index {source_index}")
                sample_games.append(stored)
                sample_rows.append({"source_index": source_index, "game_id": item.game_id})

            unicode_item = next(item for item in unicode_items if item.source_index == unicode_index)
            unicode_stored = _stored_game(database, unicode_item.game_id)
            if unicode_stored.tags != unicode_games[unicode_index].tags:
                raise AssertionError("stored Unicode tags changed")
            if not same_game_tree(unicode_stored, unicode_games[unicode_index]):
                raise AssertionError("stored Unicode GameTree changed")

            export_started = time.perf_counter()
            save_pgn_atomic(exported_pgn, sample_games)
            exported_opened = open_pgn(exported_pgn)
            export_reopen_seconds = time.perf_counter() - export_started
            if len(exported_opened.games) != len(sample_games):
                raise AssertionError("sample export/reopen count mismatch")
            for index, (expected, actual) in enumerate(zip(sample_games, exported_opened.games)):
                if expected.tags != actual.tags or not same_game_tree(expected, actual):
                    raise AssertionError(f"sample export/reopen mismatch at sample {index}")
        finally:
            database.close()

        database_bytes = db_path.stat().st_size
        reopened = AcsDatabase(db_path)
        try:
            integrity_after = _integrity(reopened, STANDARD_GAMES + len(unicode_games))
            reopened_items, reopened_pages, reopened_seconds = _enumerate(
                reopened, standard_result.source_id
            )
            if len(reopened_items) != STANDARD_GAMES:
                raise AssertionError("reopened Search enumeration count mismatch")
            replay_unicode, _ = _search(
                reopened, unicode_result.source_id, unicode_field, unicode_query
            )
            if unicode_index not in {item.source_index for item in replay_unicode}:
                raise AssertionError("reopened Unicode Search mismatch")
        finally:
            reopened.close()

        summary = {
            "status": "PASS",
            "product_candidate": "c1bd4f0c7610365458689a786ebb56d1c7d073df",
            "schema": 6,
            "standard_corpus": {
                "name": STANDARD.name,
                "license": STANDARD.license,
                "published_games": STANDARD.published_games,
                "compressed_sha256": STANDARD.sha256,
                "compressed_bytes": standard_compressed_bytes,
                "subset_games": STANDARD_GAMES,
                "subset_sha256": standard_opened.source.sha256,
                "subset_bytes": standard_opened.source.size,
                "warning_games": standard_opened.warning_games,
            },
            "unicode_corpus": {
                "name": UNICODE.name,
                "license": UNICODE.license,
                "published_games": UNICODE.published_games,
                "compressed_sha256": UNICODE.sha256,
                "compressed_bytes": unicode_compressed_bytes,
                "scan_limit": UNICODE_SCAN_LIMIT,
                "records_scanned": unicode_scanned,
                "selected_ordinal": unicode_ordinal,
                "selected_sha256": unicode_opened.source.sha256,
                "selected_bytes": unicode_opened.source.size,
                "field": unicode_field,
                "value": unicode_value,
                "query": unicode_query,
                "search_seconds": unicode_search_seconds,
            },
            "library": {
                "standard_games": standard_result.game_count,
                "unicode_games": unicode_result.game_count,
                "parse_seconds": parse_seconds,
                "standard_import_seconds": standard_import_seconds,
                "unicode_import_seconds": unicode_import_seconds,
                "keyset_pages": pages,
                "enumerate_seconds": enumerate_seconds,
                "reopened_keyset_pages": reopened_pages,
                "reopened_enumerate_seconds": reopened_seconds,
                "database_bytes": database_bytes,
                "peak_rss_kib": _peak_rss_kib(),
            },
            "integrity_before_close": integrity_before,
            "integrity_after_reopen": integrity_after,
            "literal_metachar_search": literal_evidence,
            "sample_seed": SAMPLE_SEED,
            "sampled_games": sample_rows,
            "sampled_game_count": len(sample_rows),
            "stored_tags_and_gametrees": "PASS",
            "sample_export_reopen": {
                "games": len(sample_games),
                "sha256": exported_opened.source.sha256,
                "bytes": exported_opened.source.size,
                "elapsed_seconds": export_reopen_seconds,
                "status": "PASS",
            },
            "public_search_full_enumeration": "PASS",
            "reopen": "PASS",
            "nonclaims": [
                "not a million-game readiness benchmark",
                "not an independent re-claim of PGN parser semantics",
                "not a corruption oracle; Audit-B owns adversarial projection-damage evidence",
                "not Windows/NVDA release acceptance",
            ],
        }
        Path("real-lichess-acsdb-v6-summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print("V2_REAL_LICHESS_ACSDB_V6=" + json.dumps(summary, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
