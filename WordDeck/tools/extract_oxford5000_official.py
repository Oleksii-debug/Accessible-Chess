#!/usr/bin/env python3
"""Extract canonical Oxford 5000-exclusive lexical rows from saved official HTML.

Development/build-time utility only. It does not ship with WordDeck and does not
perform network access by default. The authoritative input is a saved copy of
Oxford Learner's Dictionaries' Oxford 3000/5000 word-list page.

The extractor is deliberately row-preserving: distinct part-of-speech / CEFR
list rows remain distinct records. Existing Oxford 3000 rows are excluded.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

OFFICIAL_URL = "https://www.oxfordlearnersdictionaries.com/us/wordlists/oxford3000-5000"
ALLOWED_LEVELS = {"b2", "c1"}


class OxfordWordListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._panel_depth = 0
        self._li_depth = 0
        self._current: dict[str, str] | None = None
        self._capture_word = False
        self._capture_pos = False
        self.rows: list[dict[str, str]] = []

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {key: (value or "") for key, value in attrs}

    @staticmethod
    def _has_class(attrs: dict[str, str], wanted: str) -> bool:
        return wanted in attrs.get("class", "").split()

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = self._attrs(attrs_list)
        if tag == "div":
            if attrs.get("id") == "wordlistsContentPanel":
                self._panel_depth = 1
            elif self._panel_depth:
                self._panel_depth += 1

        if not self._panel_depth:
            return

        if tag == "li" and "data-hw" in attrs:
            if self._current is not None:
                raise RuntimeError("Nested Oxford lexical <li> records are not supported")
            self._li_depth = 1
            self._current = {
                "data_hw": attrs.get("data-hw", "").strip(),
                "ox3000": attrs.get("data-ox3000", "").strip().lower(),
                "ox5000": attrs.get("data-ox5000", "").strip().lower(),
                "source": "",
                "part_of_speech": "",
                "definition_path": "",
            }
            return

        if self._current is None:
            return

        if tag == "li":
            self._li_depth += 1
        elif tag == "a" and not self._current["definition_path"]:
            self._capture_word = True
            self._current["definition_path"] = attrs.get("href", "").strip()
        elif tag == "span" and self._has_class(attrs, "pos"):
            self._capture_pos = True

    def handle_endtag(self, tag: str) -> None:
        if self._current is not None:
            if tag == "a":
                self._capture_word = False
            elif tag == "span":
                self._capture_pos = False
            elif tag == "li":
                self._li_depth -= 1
                if self._li_depth == 0:
                    self.rows.append(self._current)
                    self._current = None
                    self._capture_word = False
                    self._capture_pos = False

        if tag == "div" and self._panel_depth:
            self._panel_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._capture_word:
            self._current["source"] = (self._current["source"] + " " + text).strip()
        elif self._capture_pos:
            self._current["part_of_speech"] = (self._current["part_of_speech"] + " " + text).strip()


def canonical_entry_id(source: str, pos: str, level: str, definition_path: str) -> str:
    """Order-independent row ID derived from Oxford row identity fields."""
    identity = "\x1f".join(
        part.strip().casefold() for part in (source, pos, level, definition_path)
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"ox5000-{digest}"


def extract(text: str) -> list[dict[str, str]]:
    parser = OxfordWordListParser()
    parser.feed(text)
    parser.close()
    if not parser.rows:
        raise RuntimeError("No Oxford lexical rows were found in wordlistsContentPanel")

    output: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    seen_identity: set[tuple[str, str, str, str]] = set()

    for source_index, raw in enumerate(parser.rows):
        ox3000 = raw["ox3000"]
        ox5000 = raw["ox5000"]

        # Oxford 5000 contains the Oxford 3000 plus 2,000 additions. We only
        # export additions: valid B2/C1 Oxford-5000 membership and no Oxford-3000 membership.
        if not ox5000 or ox3000:
            continue
        if ox5000 not in ALLOWED_LEVELS:
            raise RuntimeError(
                f"Unexpected Oxford 5000-exclusive CEFR level {ox5000!r} for {raw['data_hw']!r}; "
                "WordDeck must not invent a C2 Oxford workspace."
            )

        source = html.unescape(raw["source"] or raw["data_hw"]).strip()
        pos = html.unescape(raw["part_of_speech"]).strip()
        path = raw["definition_path"].strip()
        if not source or not pos or not path:
            raise RuntimeError(f"Incomplete Oxford row at source index {source_index}: {raw}")

        identity = (source.casefold(), pos.casefold(), ox5000, path)
        if identity in seen_identity:
            raise RuntimeError(f"Duplicate exact Oxford lexical row: {identity}")
        seen_identity.add(identity)

        entry_id = canonical_entry_id(source, pos, ox5000, path)
        if entry_id in seen_ids:
            raise RuntimeError(f"Stable-ID hash collision for Oxford row {identity}")
        seen_ids.add(entry_id)

        output.append(
            {
                "entry_id": entry_id,
                "source_index": str(source_index),
                "source": source,
                "part_of_speech": pos,
                "level": ox5000.upper(),
                "definition_path": path,
                "source_url": urljoin(OFFICIAL_URL, path),
                "status": "pending_translation_qa",
            }
        )

    if not output:
        raise RuntimeError("No Oxford 5000-exclusive B2/C1 rows were extracted")
    return output


def write_tsv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "entry_id",
        "source_index",
        "source",
        "part_of_speech",
        "level",
        "definition_path",
        "source_url",
        "status",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def self_test() -> None:
    fixture = f"""
    <html><body>
      <div id="wordlistsContentPanel"><ul>
        <li data-hw="ability" data-ox3000="a2" data-ox5000="a2">
          <a href="/definition/english/ability">ability</a><span class="pos">noun</span>
        </li>
        <li data-hw="abuse" data-ox3000="" data-ox5000="c1">
          <a href="/definition/english/abuse_1">abuse</a><span class="pos">noun</span>
        </li>
        <li data-hw="abuse" data-ox5000="c1">
          <a href="/definition/english/abuse_2">abuse</a><span class="pos">verb</span>
        </li>
        <li data-hw="acid" data-ox5000="c1">
          <a href="/definition/english/acid_1">acid</a><span class="pos">adjective</span>
        </li>
        <li data-hw="acid" data-ox5000="b2">
          <a href="/definition/english/acid_2">acid</a><span class="pos">noun</span>
        </li>
      </ul></div>
    </body></html>
    """
    rows = extract(fixture)
    if [(r["source"], r["part_of_speech"], r["level"]) for r in rows] != [
        ("abuse", "noun", "C1"),
        ("abuse", "verb", "C1"),
        ("acid", "adjective", "C1"),
        ("acid", "noun", "B2"),
    ]:
        raise RuntimeError(f"Row-preserving extraction self-test failed: {rows}")
    if len({r["entry_id"] for r in rows}) != 4:
        raise RuntimeError("Distinct Oxford rows did not receive distinct stable IDs")
    if canonical_entry_id("abuse", "noun", "c1", "/definition/english/abuse_1") != rows[0]["entry_id"]:
        raise RuntimeError("Canonical Oxford stable ID is not deterministic")

    c2_fixture = """
      <div id="wordlistsContentPanel"><ul>
        <li data-hw="invented" data-ox5000="c2">
          <a href="/definition/english/invented">invented</a><span class="pos">adjective</span>
        </li>
      </ul></div>
    """
    try:
        extract(c2_fixture)
    except RuntimeError as exc:
        if "C2" not in str(exc).upper():
            raise
    else:
        raise RuntimeError("Extractor accepted an invented Oxford C2 addition")

    print("Oxford 5000 official-row extractor self-test passed: POS rows preserved, Oxford 3000 excluded, C2 rejected.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", type=Path, help="Saved official Oxford 3000/5000 HTML page")
    parser.add_argument("--output", type=Path, help="Output canonical additions TSV")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if args.html is None or args.output is None:
        parser.error("--html and --output are required unless --self-test is used")

    rows = extract(args.html.read_text(encoding="utf-8"))
    write_tsv(rows, args.output)
    print(f"Extracted {len(rows)} canonical Oxford 5000-exclusive rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
