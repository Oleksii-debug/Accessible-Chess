from __future__ import annotations

"""Independent real multilingual TXT acceptance for the #421 text-book importer.

The corpus is downloaded transiently by CI from immutable Polish Wikibooks
revision IDs and is never vendored. This oracle is evidence-only: it does not
change or promote the Product TXT/Markdown support matrix owned by PR #421.
"""

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import tempfile

from acs.book_progress_store import BookProgressStore
from acs.book_text_import import BookTextFormat, import_text_book
from acs.bookdocument import Diagram, Game, Paragraph, Position
from acs.bookreader import BookReader


SUMMARY_PATH = Path("book-real-polish-text-summary.json")


@dataclass(frozen=True, slots=True)
class CorpusCase:
    key: str
    path: Path
    expected_sha256: str
    revision: int
    page: str
    title: str
    needles: tuple[str, ...]


POLISH_DIACRITICS = frozenset("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


def _actual_sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _case_summary(case: CorpusCase, *, provenance_pending: bool) -> tuple[dict[str, object], object, object]:
    raw = case.path.read_bytes()
    actual_sha = _actual_sha(raw)
    if len(raw) > 8 * 1024 * 1024:
        raise AssertionError(f"{case.key}: source exceeds #421 TXT source bound")
    try:
        raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AssertionError(f"{case.key}: pinned Wikibooks revision is not UTF-8") from exc

    if not provenance_pending and actual_sha != case.expected_sha256:
        raise AssertionError(
            f"{case.key}: pinned source digest changed: expected {case.expected_sha256}, got {actual_sha}"
        )

    result = import_text_book(
        raw,
        source_name=f"Polish Wikibooks {case.page} oldid={case.revision}",
        source_format=BookTextFormat.TXT,
        title=case.title,
        author="Wikibooks contributors",
        language="pl",
    )
    paragraphs = tuple(block for block in result.document.blocks if isinstance(block, Paragraph))
    games = tuple(block for block in result.document.blocks if isinstance(block, Game))
    positions = tuple(block for block in result.document.blocks if isinstance(block, Position))
    diagrams = tuple(block for block in result.document.blocks if isinstance(block, Diagram))

    if result.source_sha256 != actual_sha:
        raise AssertionError(f"{case.key}: TXT adapter digest differs from exact source bytes")
    if result.book_key != f"txt-sha256:{actual_sha}":
        raise AssertionError(f"{case.key}: stable book key is not bound to exact bytes")
    if result.source_format is not BookTextFormat.TXT:
        raise AssertionError(f"{case.key}: source was not classified as TXT")
    if len(paragraphs) < 2:
        raise AssertionError(f"{case.key}: too few readable paragraphs: {len(paragraphs)}")

    combined = "\n".join(block.text for block in paragraphs)
    for needle in case.needles:
        if needle not in combined:
            raise AssertionError(f"{case.key}: required Polish reading text missing: {needle}")
    if not any(character in POLISH_DIACRITICS for character in combined):
        raise AssertionError(f"{case.key}: Polish diacritics disappeared from semantic text")
    if games or positions or diagrams or result.pgn_games or result.positions:
        raise AssertionError(f"{case.key}: plain TXT import fabricated chess semantics")

    reader = BookReader(result.document)
    target_index = min(max(1, len(result.document.blocks) // 2), len(result.document.blocks) - 1)
    origin = reader.go_to(target_index)
    return_name = f"polish-{case.key}-origin"
    reader.save_return_point(return_name)
    if len(result.document.blocks) > 1:
        reader.next_block()
    if reader.restore_return_point(return_name) != origin:
        raise AssertionError(f"{case.key}: exact BookReader return point changed")

    summary = {
        "key": case.key,
        "page": case.page,
        "revision": case.revision,
        "bytes": len(raw),
        "sha256": actual_sha,
        "expected_sha256": case.expected_sha256,
        "paragraphs": len(paragraphs),
        "semantic_blocks": len(result.document.blocks),
        "polish_diacritic_characters": sum(character in POLISH_DIACRITICS for character in combined),
        "fabricated_games": len(games),
        "fabricated_positions": len(positions),
        "fabricated_diagrams": len(diagrams),
        "exact_return": "PASS",
        "book_key": result.book_key,
        "block_ids": [block.block_id for block in result.document.blocks],
    }
    return summary, result, origin


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", required=True)
    parser.add_argument("--history-sha256", required=True)
    parser.add_argument("--rules", required=True)
    parser.add_argument("--rules-sha256", required=True)
    parser.add_argument("--endgame", required=True)
    parser.add_argument("--endgame-sha256", required=True)
    args = parser.parse_args()

    cases = (
        CorpusCase(
            key="history",
            path=Path(args.history),
            expected_sha256=args.history_sha256,
            revision=192022,
            page="Szachy/Historia",
            title="Szachy — Historia",
            needles=("Prawdopodobnie", "średnio"),
        ),
        CorpusCase(
            key="rules",
            path=Path(args.rules),
            expected_sha256=args.rules_sha256,
            revision=125460,
            page="Szachy/Ogólne zasady gry",
            title="Szachy — Ogólne zasady gry",
            needles=("szachownicą", "białymi"),
        ),
        CorpusCase(
            key="endgame",
            path=Path(args.endgame),
            expected_sha256=args.endgame_sha256,
            revision=486248,
            page="Szachy/Koniec gry",
            title="Szachy — Koniec gry",
            needles=("wiecznym szachem", "remis"),
        ),
    )

    provenance_pending = any(case.expected_sha256 == "UNPINNED" for case in cases)
    if any(case.expected_sha256 != "UNPINNED" and len(case.expected_sha256) != 64 for case in cases):
        raise AssertionError("expected SHA-256 must be UNPINNED or an exact 64-character digest")

    summaries: list[dict[str, object]] = []
    imported: dict[str, object] = {}
    origins: dict[str, object] = {}
    distinct_diacritics: set[str] = set()

    for case in cases:
        case_summary, result, origin = _case_summary(case, provenance_pending=provenance_pending)
        summaries.append(case_summary)
        imported[case.key] = result
        origins[case.key] = origin
        raw_text = case.path.read_text(encoding="utf-8-sig")
        distinct_diacritics.update(character for character in raw_text if character in POLISH_DIACRITICS)

    if len(distinct_diacritics) < 6:
        raise AssertionError(
            "multilingual corpus did not retain a meaningful Polish diacritic set: "
            + "".join(sorted(distinct_diacritics))
        )

    with tempfile.TemporaryDirectory(prefix="acs-real-polish-txt-") as directory:
        progress_path = Path(directory) / "book-progress.json"
        store = BookProgressStore(progress_path)
        for case in cases:
            result = imported[case.key]
            reader = BookReader(result.document)
            reader.go_to(origins[case.key].index)
            reader.save_return_point(f"polish-{case.key}-origin")
            store.save(result.book_key, reader)

        reopened_store = BookProgressStore(progress_path)
        for case in cases:
            raw = case.path.read_bytes()
            fresh = import_text_book(
                raw,
                source_name=f"Polish Wikibooks {case.page} oldid={case.revision}",
                source_format=BookTextFormat.TXT,
                title=case.title,
                author="Wikibooks contributors",
                language="pl",
            )
            original = imported[case.key]
            if [block.block_id for block in fresh.document.blocks] != [
                block.block_id for block in original.document.blocks
            ]:
                raise AssertionError(f"{case.key}: deterministic semantic block identities changed on reimport")
            reopened = reopened_store.restore(fresh.book_key, fresh.document)
            if reopened.location() != origins[case.key]:
                raise AssertionError(f"{case.key}: progress close/reopen changed exact reading location")
            if reopened.restore_return_point(f"polish-{case.key}-origin") != origins[case.key]:
                raise AssertionError(f"{case.key}: named return point did not survive progress reopen")

    summary = {
        "status": "PROVENANCE_PENDING" if provenance_pending else "PASS",
        "claim": "independent multilingual UTF-8 TXT chess-text acceptance on exact PR421 owner Product",
        "product_owner": {
            "pr": 421,
            "sha": "4e88c0a0bb9b125ee57ab4bc2d667876c00ffc92",
            "mutation": "NONE",
        },
        "license": {
            "project": "Polish Wikibooks",
            "text_framework": "CC BY-SA 3.0 / compatible Wikibooks text licensing; exact revisions retained for attribution",
            "redistribution": "CI downloads transiently; source text is not vendored or uploaded as an artifact",
        },
        "corpus": summaries,
        "distinct_polish_diacritics": "".join(sorted(distinct_diacritics)),
        "checks": {
            "utf8_decode": "PASS",
            "diacritic_preservation": "PASS",
            "no_fabricated_chess_semantics": "PASS",
            "stable_book_key": "PASS",
            "deterministic_block_ids": "PASS",
            "exact_reader_return": "PASS",
            "multi_book_progress_reopen": "PASS",
        },
        "support_boundary": {
            "TXT": "NO_NEW_SUPPORT_PROMOTION; OWNER_421_REMAINS_AUTHORITY",
            "Markdown": "NOT_TESTED",
            "HTML_XHTML": "NOT_TESTED",
            "Windows_NVDA": "NOT_CLAIMED",
        },
    }
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print("REAL_POLISH_TEXT_BOOK=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))

    if provenance_pending:
        print("REAL POLISH TXT SEMANTICS PASS; PROVENANCE HASH PINNING REQUIRED")
        for case_summary in summaries:
            print(f"PIN_{str(case_summary['key']).upper()}_SHA256={case_summary['sha256']}")
        raise SystemExit(42)

    print("REAL POLISH TXT BOOK QA PASS")


if __name__ == "__main__":
    main()
