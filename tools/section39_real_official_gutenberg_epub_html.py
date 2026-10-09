"""Section 39 genuine official Project Gutenberg EPUB3 + HTML acquisition QA.

This is a TEST-ONLY external original-source observation, deliberately separate
from pin-authenticated corpus acceptance. The officially linked EPUB/HTML
download endpoints are first-party HTTPS only; redirects cannot escape that
host, overlarge/unsafe ZIPs are rejected, and source bytes are never packaged.
"""
from __future__ import annotations

from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import ssl
import stat
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler
import zipfile

from acs.book_epub_import import import_epub_book
from acs.book_html_import import import_html_book
from acs.bookreader import BookReader
from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from tools.revised_sections37_38_offline_manifest import ROOT, _source_head

REPORT = ROOT / "section39-official-original-epub-html-observation.json"
OFFICIAL_HOST = "www.gutenberg.org"
ORIGINALS = (
    (
        "capablanca_chess_fundamentals_epub3", "EPUB",
        "https://www.gutenberg.org/ebooks/33870.epub3.images",
        "Chess Fundamentals", "José Raúl Capablanca", 64 * 1024 * 1024,
    ),
    (
        "gutenberg_chess_strategy_lasker", "HTML",
        "https://www.gutenberg.org/cache/epub/5614/pg5614-h.zip",
        "Chess Strategy", "Edward Lasker", 16 * 1024 * 1024,
    ),
)


def validate_official_url(url: object) -> str:
    if type(url) is not str or len(url) > 250:
        raise LawfulCorpusError("invalid official Gutenberg original URL")
    parts = urlsplit(url)
    if (
        parts.scheme != "https" or parts.hostname != OFFICIAL_HOST
        or parts.username is not None or parts.password is not None
        or parts.port not in (None, 443)
        or parts.query or parts.fragment
        or not (parts.path.startswith("/ebooks/") or parts.path.startswith("/cache/epub/"))
        or ".." in parts.path.split("/")
    ):
        raise LawfulCorpusError("Gutenberg source URL redirects outside approved first-party origin")
    return url


class _FirstPartyOnlyRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_official_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def get_original_bytes(url: str, max_bytes: int) -> tuple[bytes, str]:
    validate_official_url(url)
    if type(max_bytes) is not int or not 0 < max_bytes <= 64 * 1024 * 1024:
        raise LawfulCorpusError("invalid book source byte limit")
    opener = build_opener(
        _FirstPartyOnlyRedirect(),
        HTTPSHandler(context=ssl.create_default_context()),
    )
    request = Request(
        url, headers={
            "User-Agent": "AccessibleChess-Research-Corpus/1.0 (test-only; no redistribution)",
            "Accept": "application/epub+zip,application/zip,application/octet-stream",
        }, method="GET",
    )
    try:
        with opener.open(request, timeout=30) as response:
            destination = validate_official_url(response.geturl())
            if response.status != 200:
                raise LawfulCorpusError("official Gutenberg original server returned non-200")
            advertised = response.headers.get("Content-Length")
            if advertised and (not advertised.isdecimal() or int(advertised) > max_bytes):
                raise LawfulCorpusError("official Gutenberg original exceeds allowed size")
            raw = response.read(max_bytes + 1)
    except (OSError, ValueError) as exc:
        raise LawfulCorpusError("official original Gutenberg EPUB/HTML acquisition unavailable") from exc
    if not 512 <= len(raw) <= max_bytes:
        raise LawfulCorpusError("official original Gutenberg body absent or overlarge")
    return raw, destination


def _html_from_original_zip(raw: bytes) -> tuple[bytes, str]:
    with zipfile.ZipFile(BytesIO(raw), "r") as archive:
        infos = archive.infolist()
        if not 1 <= len(infos) <= 512:
            raise LawfulCorpusError("official Gutenberg HTML ZIP member count invalid")
        total = 0
        candidates = []
        for entry in infos:
            name = entry.filename
            if (
                not name or name.startswith("/") or "\\" in name
                or any(part in ("", ".", "..") for part in name.rstrip("/").split("/"))
                or (entry.is_dir() and not name.endswith("/"))
                or ":" in name or entry.file_size > 8 * 1024 * 1024
                or (entry.external_attr >> 16) & 0o170000 not in (0, stat.S_IFREG, stat.S_IFDIR)
            ):
                raise LawfulCorpusError("official Gutenberg HTML archive unsafe member")
            total += entry.file_size
            if total > 16 * 1024 * 1024:
                raise LawfulCorpusError("official Gutenberg original HTML archive expansion too large")
            if not entry.is_dir() and name.lower().endswith((".htm", ".html")):
                candidates.append(entry)
        if not candidates:
            raise LawfulCorpusError("official original HTML ZIP has no HTML document")
        candidate = max(candidates, key=lambda info: info.file_size)
        html = archive.read(candidate)
        if len(html) != candidate.file_size or len(html) < 200:
            raise LawfulCorpusError("original Gutenberg main HTML content absent")
        return html, candidate.filename


def qualify_original_ebooks() -> dict:
    sources = {record["id"]: record for record in load_catalog()}
    evidence = []
    for source_id, fmt, url, title, author, max_bytes in ORIGINALS:
        entry = sources.get(source_id)
        if (
            entry is None
            or entry.get("redistribution") != "NOT_CLEARED"
            or not str(entry.get("source_page", "")).startswith("https://www.gutenberg.org/ebooks/")
            or entry.get("sha256") is not None
        ):
            raise LawfulCorpusError("Gutenberg original needs an authorized test-only, not already pinned catalog entry")
        raw, final_url = get_original_bytes(url, max_bytes)
        original_digest = hashlib.sha256(raw).hexdigest()
        if fmt == "EPUB":
            first = import_epub_book(
                raw, source_name=source_id + ".epub",
                title=title, author=author, language="en",
            )
            second = import_epub_book(
                raw, source_name=source_id + ".epub",
                title=title, author=author, language="en",
            )
            actual_media = raw
            detected_member = None
            book_blocks = len(first.document.blocks)
            if not first.spine_documents:
                raise LawfulCorpusError("actual original EPUB has no canonical reading spine")
        else:
            actual_media, detected_member = _html_from_original_zip(raw)
            first = import_html_book(
                actual_media, source_name=detected_member,
                title=title, author=author, language="en",
            )
            second = import_html_book(
                actual_media, source_name=detected_member,
                title=title, author=author, language="en",
            )
            book_blocks = len(first.document.blocks)
        if (
            first.document.as_dict() != second.document.as_dict()
            or not 5 <= book_blocks <= 100_000
            or first.source_sha256 != hashlib.sha256(actual_media).hexdigest()
        ):
            raise LawfulCorpusError("actual official EPUB/HTML semantic reimport lost book structure")
        reader = BookReader(first.document)
        original_place = reader.location()
        new_place = reader.next_block()
        if new_place.index != original_place.index + 1:
            raise LawfulCorpusError("actual original book does not navigate canonical blocks")
        reader.save_return_point("real_gutenberg_test_checkpoint")
        resumed = BookReader.restore_snapshot(second.document, reader.snapshot())
        if resumed.location() != new_place or resumed.restore_return_point("real_gutenberg_test_checkpoint") != new_place:
            raise LawfulCorpusError("actual original EPUB/HTML reader cannot recover after reimport")
        evidence.append({
            "source_id": source_id,
            "source_format": fmt,
            "original_source_url": url, "actual_final_url": final_url,
            "original_download_sha256": original_digest, "original_download_bytes": len(raw),
            "qualified_html_member": detected_member,
            "qualified_semantic_source_sha256": hashlib.sha256(actual_media).hexdigest(),
            "actual_importer": "acs.book_epub_import.import_epub_book" if fmt == "EPUB" else "acs.book_html_import.import_html_book",
            "semantic_block_count": book_blocks,
            "semantic_bookdocument_equal_reimport": True,
            "reader_resume_reimport": "PASS",
            "source_rights": "US_PD_DECLARATION_ONLY; NOT_CLEARED_FOR_PUBLIC_RELEASE",
            "original_sha256_prepinned_in_catalog": False,
            "real_original_source_read": True,
            "mocked": False,
            "qualification": "PARTIAL_SOURCE_NOT_PREPINNED",
            "public_release": "EXCLUDED",
        })
    return {
        "schema": "accessible-chess-section39-real-external-gutenberg-ebooks-v1",
        "source_count": len(evidence), "sources": evidence,
        "downloaded_original_ebook_bytes_packaged": False,
        "full_original_independent_sha_prequalified": False,
        "section39_terminal_done": False,
    }


def main():
    REPORT.unlink(missing_ok=True)
    head = _source_head()
    report = qualify_original_ebooks()
    report["source_commit_sha"] = head
    stage = REPORT.with_suffix(".tmp")
    try:
        stage.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)+"\n",
                         encoding="utf-8")
        os.replace(stage, REPORT)
    finally:
        stage.unlink(missing_ok=True)
    print(json.dumps({
        "source_commit_sha": head,
        "genuine_original_books": report["source_count"],
        "formats": [e["source_format"] for e in report["sources"]],
        "section39_done": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
