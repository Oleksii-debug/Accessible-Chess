from __future__ import annotations

"""Bounded public-source probe for a real 2CBV + independent PGN oracle lead.

This script intentionally never writes downloaded chess payload bytes to disk and
never uploads them. It emits only provenance, URL, size and SHA-256 evidence.
Public download availability is not interpreted as redistribution permission or
semantic format support.
"""

from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
import argparse
import json
import re
from typing import BinaryIO, Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

MATTNETZ_PAGE = "https://www.sv-mattnetz-berlin.de/?cat=19"
BSV_PAGE = "https://www.berlinerschachverband.de/berliner-einzelmeisterschaft-m-klasse.html"
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
USER_AGENT = "AccessibleChess-V2-format-evidence/1.0 (+https://github.com/Oleksii-debug/Accessible-Chess)"


class ProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Anchor:
    text: str
    href: str


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[Anchor] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        values = dict(attrs)
        href = values.get("href")
        if href:
            self._href = href
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._href is None:
            return
        text = " ".join("".join(self._parts).split())
        self.anchors.append(Anchor(text=text, href=self._href))
        self._href = None
        self._parts = []


def parse_anchors(html: str) -> tuple[Anchor, ...]:
    parser = _AnchorParser()
    parser.feed(html)
    return tuple(parser.anchors)


def _open(url: str):
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ProbeError("Evidence URL must use HTTPS")
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
        },
    )
    return urlopen(request, timeout=45)


def read_bounded(stream: BinaryIO, limit: int) -> bytes:
    data = bytearray()
    while True:
        chunk = stream.read(min(1024 * 1024, limit + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > limit:
            raise ProbeError("Evidence response exceeded configured byte bound")
    return bytes(data)


def fetch_bytes(url: str, *, limit: int) -> tuple[bytes, str, dict[str, str]]:
    with _open(url) as response:
        body = read_bounded(response, limit)
        headers = {key.casefold(): value for key, value in response.headers.items()}
        final_url = response.geturl()
    if urlparse(final_url).scheme != "https":
        raise ProbeError("Evidence redirect left HTTPS")
    return body, final_url, headers


def _find_anchor(anchors: Iterable[Anchor], exact_text: str) -> Anchor | None:
    wanted = " ".join(exact_text.split()).casefold()
    for anchor in anchors:
        if " ".join(anchor.text.split()).casefold() == wanted:
            return anchor
    return None


def _content_disposition_filename(headers: dict[str, str]) -> str:
    value = headers.get("content-disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", value, re.I)
    return match.group(1).strip().strip('"') if match else ""


def _expected_suffix_confident(final_url: str, headers: dict[str, str], suffix: str) -> bool:
    path = urlparse(final_url).path.casefold()
    filename = _content_disposition_filename(headers).casefold()
    return path.endswith(suffix.casefold()) or filename.endswith(suffix.casefold())


def _public_download_evidence(url: str, expected_suffix: str) -> dict[str, object]:
    try:
        body, final_url, headers = fetch_bytes(url, limit=MAX_DOWNLOAD_BYTES)
    except Exception as exc:  # evidence probe must report blockers, not fabricate success
        return {
            "url": url,
            "reachable": False,
            "error_class": type(exc).__name__,
            "payload_identity_confident": False,
        }

    return {
        "url": url,
        "final_url": final_url,
        "reachable": True,
        "size_bytes": len(body),
        "sha256": sha256(body).hexdigest(),
        "content_type": headers.get("content-type", ""),
        "content_disposition_filename": _content_disposition_filename(headers),
        "payload_identity_confident": _expected_suffix_confident(
            final_url, headers, expected_suffix
        ),
    }


def _fetch_html(url: str) -> str:
    body, _final_url, _headers = fetch_bytes(url, limit=MAX_HTML_BYTES)
    return body.decode("utf-8", errors="replace")


def _bsv_round_pgn_anchors(html: str) -> tuple[Anchor, ...]:
    anchors = parse_anchors(html)
    selected: list[Anchor] = []
    seen: set[str] = set()
    pattern = re.compile(r"2024-BSV-BEM24-M-Klasse-R([1-9])\.pgn", re.I)
    for anchor in anchors:
        target = anchor.href
        match = pattern.search(target) or pattern.search(anchor.text)
        if not match:
            continue
        round_no = match.group(1)
        if round_no in seen:
            continue
        seen.add(round_no)
        selected.append(anchor)
    return tuple(sorted(selected, key=lambda item: int(pattern.search(item.href + " " + item.text).group(1))))


def run_probe() -> dict[str, object]:
    report: dict[str, object] = {
        "schema_version": 1,
        "format": "2CBV",
        "status": "BLOCKED",
        "support_promotion_allowed": False,
        "payload_bytes_persisted": False,
        "payload_bytes_uploaded_as_artifact": False,
        "repository_ci_redistribution_rights_qualified": False,
        "decoder_qualified": False,
        "semantic_acceptance_executed": False,
    }

    mattnetz_html = _fetch_html(MATTNETZ_PAGE)
    mattnetz_anchors = parse_anchors(mattnetz_html)
    pgn_anchor = _find_anchor(mattnetz_anchors, "PGN Datei alle Runden")
    cbv2_anchor = _find_anchor(mattnetz_anchors, "2CBV Datei alle Runden")
    report["mattnetz_page"] = {
        "url": MATTNETZ_PAGE,
        "same_event_pgn_anchor_found": pgn_anchor is not None,
        "same_event_2cbv_anchor_found": cbv2_anchor is not None,
    }

    if pgn_anchor is not None:
        pgn_url = urljoin(MATTNETZ_PAGE, pgn_anchor.href)
        report["mattnetz_same_event_pgn"] = _public_download_evidence(pgn_url, ".pgn")
    if cbv2_anchor is not None:
        cbv2_url = urljoin(MATTNETZ_PAGE, cbv2_anchor.href)
        report["mattnetz_same_event_2cbv"] = _public_download_evidence(cbv2_url, ".2cbv")

    bsv_html = _fetch_html(BSV_PAGE)
    bsv_anchors = _bsv_round_pgn_anchors(bsv_html)
    bsv_downloads: list[dict[str, object]] = []
    for anchor in bsv_anchors:
        url = urljoin(BSV_PAGE, anchor.href)
        bsv_downloads.append(_public_download_evidence(url, ".pgn"))
    report["independent_bsv_mklasse_pgn"] = {
        "url": BSV_PAGE,
        "round_anchor_count": len(bsv_anchors),
        "rounds": bsv_downloads,
    }

    two_cbv = report.get("mattnetz_same_event_2cbv", {})
    independent_rounds = report["independent_bsv_mklasse_pgn"]["rounds"]
    report["paired_corpus_lead_qualified"] = bool(
        report["mattnetz_page"]["same_event_2cbv_anchor_found"]
        and report["mattnetz_page"]["same_event_pgn_anchor_found"]
        and len(independent_rounds) == 9
        and all(item.get("reachable") for item in independent_rounds)
        and isinstance(two_cbv, dict)
        and two_cbv.get("reachable")
    )
    report["acceptance_ready"] = False
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run_probe()
    with open(args.output, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
