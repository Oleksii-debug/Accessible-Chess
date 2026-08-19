#!/usr/bin/env python3
"""Validate the authoritative Oxford 5000 additional-word snapshot.

Oxford describes this resource as 2,000 additional B2/C1 words beyond the Oxford
3000. In the membership-bearing interactive HTML those lexical items collapse to
1,997 unique orthographic surface strings because some surface forms represent
more than one lexical item/POS. WordDeck therefore records the publisher's 2,000
word-list-item statement separately from the machine-observed unique-surface count
and the row-preserving POS/CEFR lexical-identity count used for reconciliation.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

import extract_oxford5000_official as official

PUBLISHER_ADDITIONAL_WORDS = 2000
EXPECTED_UNIQUE_SURFACES = 1997
ALLOWED_LEVELS = {"B2", "C1"}


def validate(path: Path, expected_surfaces: int = EXPECTED_UNIQUE_SURFACES) -> tuple[list[dict[str, str]], dict[str, int]]:
    rows = official.extract(path.read_text(encoding="utf-8"))
    surfaces = {row["source"].strip().casefold() for row in rows}
    if len(surfaces) != expected_surfaces:
        raise ValueError(
            "Official Oxford additional inventory surface signature changed or is incomplete: "
            f"unique_surfaces={len(surfaces)} != expected={expected_surfaces}; "
            f"lexical_rows={len(rows)}"
        )

    levels = Counter(row["level"].strip().upper() for row in rows)
    unexpected = sorted(set(levels) - ALLOWED_LEVELS)
    if unexpected:
        raise ValueError(f"Official Oxford extra inventory contains unsupported CEFR levels: {unexpected}")

    identities = {
        (
            row["source"].strip().casefold(),
            row["part_of_speech"].strip().casefold(),
            row["level"].strip().upper(),
        )
        for row in rows
    }
    if len(identities) != len(rows):
        raise ValueError("Official Oxford extractor returned duplicate lexical identities")

    stats = {
        "publisher_additional_words": PUBLISHER_ADDITIONAL_WORDS,
        "official_unique_surfaces": len(surfaces),
        "official_exclusive_lexical_rows": len(rows),
        "official_b2_lexical_rows": levels["B2"],
        "official_c1_lexical_rows": levels["C1"],
    }
    return rows, stats


def write_report(stats: dict[str, int], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(("metric", "value"))
        for key in (
            "publisher_additional_words",
            "official_unique_surfaces",
            "official_exclusive_lexical_rows",
            "official_b2_lexical_rows",
            "official_c1_lexical_rows",
        ):
            writer.writerow((key, stats[key]))


def self_test() -> None:
    import tempfile

    fixture = """
<div id="wordlistsContentPanel"><ul>
<li data-hw="alpha" data-ox3000="" data-ox5000="b2"><a href="/definition/english/alpha_1">alpha</a><span class="pos">noun</span></li>
<li data-hw="alpha" data-ox3000="" data-ox5000="b2"><a href="/definition/english/alpha_2">alpha</a><span class="pos">adjective</span></li>
<li data-hw="beta" data-ox3000="" data-ox5000="c1"><a href="/definition/english/beta">beta</a><span class="pos">noun</span></li>
</ul></div>
"""
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "official.html"
        path.write_text(fixture, encoding="utf-8")
        rows, stats = validate(path, expected_surfaces=2)
        assert len(rows) == 3
        assert stats == {
            "publisher_additional_words": 2000,
            "official_unique_surfaces": 2,
            "official_exclusive_lexical_rows": 3,
            "official_b2_lexical_rows": 2,
            "official_c1_lexical_rows": 1,
        }
        try:
            validate(path, expected_surfaces=1997)
        except ValueError as exc:
            assert "unique_surfaces=2" in str(exc)
            assert "lexical_rows=3" in str(exc)
        else:
            raise RuntimeError("Official inventory validator accepted a truncated surface inventory")
    print("Official Oxford 5000 inventory validator self-test passed: publisher word count, unique surfaces and POS-split lexical rows remain distinct and fail-closed.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official-html", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--expected-surfaces", type=int, default=EXPECTED_UNIQUE_SURFACES)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if args.official_html is None:
        parser.error("--official-html is required unless --self-test is used")

    rows, stats = validate(args.official_html, expected_surfaces=args.expected_surfaces)
    if args.report is not None:
        write_report(stats, args.report)
    print(
        "Official Oxford 5000 additional inventory verified: "
        f"publisher_words={stats['publisher_additional_words']}, "
        f"unique_surfaces={stats['official_unique_surfaces']}, "
        f"lexical_rows={stats['official_exclusive_lexical_rows']}, "
        f"B2_rows={stats['official_b2_lexical_rows']}, "
        f"C1_rows={stats['official_c1_lexical_rows']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
