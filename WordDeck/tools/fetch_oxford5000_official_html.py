#!/usr/bin/env python3
"""Fetch and validate the official Oxford 3000/5000 membership-bearing HTML.

Build/CI utility only. Runtime WordDeck stays fully offline. The fetched HTML is a
transient build input and is deliberately not embedded into the application or
uploaded as a release artifact.
"""
from __future__ import annotations

import argparse
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

OFFICIAL_URL = "https://www.oxfordlearnersdictionaries.com/us/wordlists/oxford3000-5000"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WordDeck-Oxford-QA/1.0"


def validate_html(text: str) -> dict[str, int]:
    if "wordlistsContentPanel" not in text:
        raise ValueError("Official Oxford HTML is missing wordlistsContentPanel")
    lexical_rows = len(re.findall(r"<li\b[^>]*\bdata-hw=", text, flags=re.IGNORECASE))
    ox5000_attrs = len(re.findall(r"\bdata-ox5000=", text, flags=re.IGNORECASE))
    ox3000_attrs = len(re.findall(r"\bdata-ox3000=", text, flags=re.IGNORECASE))
    if lexical_rows < 5000:
        raise ValueError(f"Official Oxford HTML looks incomplete: only {lexical_rows} lexical rows")
    if ox5000_attrs < 5000:
        raise ValueError(f"Official Oxford HTML is missing Oxford 5000 membership attributes: {ox5000_attrs}")
    if ox3000_attrs < 3000:
        raise ValueError(f"Official Oxford HTML is missing Oxford 3000 membership attributes: {ox3000_attrs}")
    return {
        "lexical_rows": lexical_rows,
        "ox5000_attributes": ox5000_attrs,
        "ox3000_attributes": ox3000_attrs,
    }


def fetch(url: str = OFFICIAL_URL, attempts: int = 3, timeout: int = 45) -> tuple[str, dict[str, int]]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-GB,en;q=0.9",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise RuntimeError(f"Oxford returned HTTP {status}")
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                text = raw.decode(charset, errors="strict")
                stats = validate_html(text)
                return text, stats
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, UnicodeError, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(attempt * 2)
    raise RuntimeError(
        f"Could not obtain a complete membership-bearing official Oxford word-list HTML after {attempts} attempts: {last_error}"
    ) from last_error


def self_test() -> None:
    rows = []
    for index in range(5000):
        level = "a1" if index < 3000 else "c1"
        ox3000 = level if index < 3000 else ""
        rows.append(
            f'<li data-hw="w{index}" data-ox3000="{ox3000}" data-ox5000="{level}"><a href="/definition/english/w{index}">w{index}</a><span class="pos">noun</span></li>'
        )
    fixture = '<div id="wordlistsContentPanel"><ul>' + ''.join(rows) + '</ul></div>'
    stats = validate_html(fixture)
    assert stats == {"lexical_rows": 5000, "ox5000_attributes": 5000, "ox3000_attributes": 5000}
    try:
        validate_html('<div id="wordlistsContentPanel"><li data-hw="only-one"></li></div>')
    except ValueError:
        pass
    else:
        raise RuntimeError("Official HTML validator accepted a truncated source")
    print("Official Oxford HTML fetcher self-test passed: membership-bearing source validation is fail-closed.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--url", default=OFFICIAL_URL)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if args.output is None:
        parser.error("--output is required unless --self-test is used")

    text, stats = fetch(args.url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8", newline="")
    print(
        "Official Oxford HTML fetched and validated: "
        f"lexical_rows={stats['lexical_rows']}, "
        f"ox5000_attributes={stats['ox5000_attributes']}, "
        f"ox3000_attributes={stats['ox3000_attributes']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
