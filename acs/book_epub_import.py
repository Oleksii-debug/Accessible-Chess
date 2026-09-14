from __future__ import annotations

"""Bounded EPUB container ingestion into the canonical semantic BookDocument.

The EPUB adapter owns only package/container structure. Spine XHTML/HTML is
projected through the existing Book HTML adapter, which in turn delegates PGN and
chess-position semantics to their canonical owners. No filesystem extraction,
network fetch, CSS/script execution, DRM bypass, or duplicate chess parser lives
here.
"""

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from io import BytesIO
import posixpath
import re
import stat
from types import MappingProxyType
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile

from .book_html_import import (
    BookHtmlImportError,
    BookHtmlImportErrorCode,
    import_html_book,
)
from .bookdocument import BookDocument, Heading, block_from_dict


MAX_EPUB_SOURCE_BYTES = 64 * 1024 * 1024
MAX_EPUB_ENTRIES = 20_000
MAX_EPUB_TOTAL_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_EPUB_ENTRY_BYTES = 16 * 1024 * 1024
MAX_EPUB_XML_BYTES = 4 * 1024 * 1024
MAX_EPUB_SPINE_DOCUMENTS = 4_096
MAX_EPUB_WARNINGS = 4_096
_SUPPORTED_SPINE_MEDIA_TYPES = frozenset({"application/xhtml+xml", "text/html"})
_OPF_MEDIA_TYPE = "application/oebps-package+xml"
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class BookEpubImportErrorCode(str, Enum):
    INVALID_ARGUMENT = "invalid_argument"
    UNSUPPORTED_CONTAINER = "unsupported_container"
    UNSAFE_PACKAGE = "unsafe_package"
    RESOURCE_LIMIT = "resource_limit"
    MALFORMED_PACKAGE = "malformed_package"
    UNSUPPORTED_CONTENT = "unsupported_content"
    MALFORMED_CHESS_CONTENT = "malformed_chess_content"
    NO_READABLE_CONTENT = "no_readable_content"


class BookEpubImportError(ValueError):
    """Stable EPUB-ingress failure without local paths or ZIP/XML internals."""

    def __init__(self, message: str, *, code: BookEpubImportErrorCode) -> None:
        super().__init__(message)
        self.code = BookEpubImportErrorCode(code)


@dataclass(frozen=True, slots=True)
class BookEpubImportResult:
    document: BookDocument
    source_sha256: str
    book_key: str
    spine_documents: int
    pgn_games: int
    image_references: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ManifestItem:
    item_id: str
    entry_name: str
    media_type: str
    fallback: str | None


class _Warnings:
    def __init__(self) -> None:
        self.values: list[str] = []
        self._suppressed = False

    def add(self, message: str) -> None:
        text = " ".join(str(message).split())
        if not text:
            return
        if len(self.values) < MAX_EPUB_WARNINGS:
            self.values.append(text)
        elif not self._suppressed:
            self.values.append("additional EPUB import warnings were suppressed")
            self._suppressed = True


def _error(message: str, code: BookEpubImportErrorCode) -> BookEpubImportError:
    return BookEpubImportError(message, code=code)


def _required_text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise _error(
            f"{field} must be non-empty text",
            BookEpubImportErrorCode.INVALID_ARGUMENT,
        )
    return " ".join(value.strip().split())


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field)


def _source_bytes(source: object) -> bytes:
    if type(source) is not bytes:
        raise _error(
            "EPUB source must be bytes supplied by a trusted host",
            BookEpubImportErrorCode.INVALID_ARGUMENT,
        )
    if not source:
        raise _error(
            "EPUB source is empty",
            BookEpubImportErrorCode.UNSUPPORTED_CONTAINER,
        )
    if len(source) > MAX_EPUB_SOURCE_BYTES:
        raise _error(
            "EPUB source exceeds the supported size",
            BookEpubImportErrorCode.RESOURCE_LIMIT,
        )
    return source


def _safe_entry_name(raw_name: object) -> str:
    if type(raw_name) is not str or not raw_name or "\x00" in raw_name or "\\" in raw_name:
        raise _error(
            "EPUB contains an unsafe package entry name",
            BookEpubImportErrorCode.UNSAFE_PACKAGE,
        )
    candidate = raw_name[:-1] if raw_name.endswith("/") else raw_name
    if not candidate or candidate.startswith("/") or _DRIVE_RE.match(candidate):
        raise _error(
            "EPUB contains an unsafe package entry name",
            BookEpubImportErrorCode.UNSAFE_PACKAGE,
        )
    parts = candidate.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise _error(
            "EPUB contains an unsafe package entry name",
            BookEpubImportErrorCode.UNSAFE_PACKAGE,
        )
    normalized = posixpath.normpath(candidate)
    if normalized == ".." or normalized.startswith("../") or normalized.startswith("/"):
        raise _error(
            "EPUB package entry escapes the archive root",
            BookEpubImportErrorCode.UNSAFE_PACKAGE,
        )
    return normalized


def _archive_index(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if not infos or len(infos) > MAX_EPUB_ENTRIES:
        raise _error(
            "EPUB contains an unsupported number of package entries",
            BookEpubImportErrorCode.RESOURCE_LIMIT,
        )
    index: dict[str, zipfile.ZipInfo] = {}
    seen: set[str] = set()
    total_uncompressed = 0
    for info in infos:
        name = _safe_entry_name(info.filename)
        if name in seen:
            raise _error(
                "EPUB contains duplicate package entry names",
                BookEpubImportErrorCode.UNSAFE_PACKAGE,
            )
        seen.add(name)
        mode = (info.external_attr >> 16) & 0xFFFF
        if mode and stat.S_ISLNK(mode):
            raise _error(
                "EPUB package links are not supported",
                BookEpubImportErrorCode.UNSAFE_PACKAGE,
            )
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise _error(
                "EPUB uses an unsupported ZIP compression method",
                BookEpubImportErrorCode.UNSUPPORTED_CONTAINER,
            )
        if info.file_size < 0 or info.file_size > MAX_EPUB_ENTRY_BYTES:
            raise _error(
                "EPUB package entry exceeds the supported size",
                BookEpubImportErrorCode.RESOURCE_LIMIT,
            )
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_EPUB_TOTAL_UNCOMPRESSED_BYTES:
            raise _error(
                "EPUB expanded content exceeds the supported size",
                BookEpubImportErrorCode.RESOURCE_LIMIT,
            )
        if not info.is_dir():
            index[name] = info
    return index


def _read_entry(
    archive: zipfile.ZipFile,
    index: dict[str, zipfile.ZipInfo],
    name: str,
    *,
    limit: int = MAX_EPUB_ENTRY_BYTES,
) -> bytes:
    info = index.get(name)
    if info is None:
        raise _error(
            "EPUB references a package entry that is unavailable",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    if info.flag_bits & 0x1:
        raise _error(
            "EPUB encrypted reading content is not supported",
            BookEpubImportErrorCode.UNSUPPORTED_CONTENT,
        )
    if info.file_size > limit:
        raise _error(
            "EPUB package entry exceeds the supported size",
            BookEpubImportErrorCode.RESOURCE_LIMIT,
        )
    try:
        data = archive.read(info)
    except (RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
        raise _error(
            "EPUB package entry could not be read safely",
            BookEpubImportErrorCode.UNSUPPORTED_CONTAINER,
        ) from exc
    if len(data) != info.file_size or len(data) > limit:
        raise _error(
            "EPUB package entry size is inconsistent",
            BookEpubImportErrorCode.UNSAFE_PACKAGE,
        )
    return data


def _xml_root(data: bytes, label: str) -> ET.Element:
    if len(data) > MAX_EPUB_XML_BYTES:
        raise _error(
            f"EPUB {label} exceeds the supported size",
            BookEpubImportErrorCode.RESOURCE_LIMIT,
        )
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise _error(
            f"EPUB {label} contains unsupported XML declarations",
            BookEpubImportErrorCode.UNSAFE_PACKAGE,
        )
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise _error(
            f"EPUB {label} is malformed",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        ) from exc


def _local_name(tag: object) -> str:
    if type(tag) is not str:
        return ""
    return tag.rsplit("}", 1)[-1].split(":", 1)[-1].casefold()


def _direct_child(parent: ET.Element, name: str) -> ET.Element | None:
    wanted = name.casefold()
    for child in parent:
        if _local_name(child.tag) == wanted:
            return child
    return None


def _metadata_values(metadata: ET.Element | None, name: str) -> list[str]:
    if metadata is None:
        return []
    wanted = name.casefold()
    values: list[str] = []
    for element in metadata.iter():
        if _local_name(element.tag) != wanted:
            continue
        text = " ".join("".join(element.itertext()).split())
        if text and text not in values:
            values.append(text)
    return values


def _resolve_package_href(base_dir: str, href: object) -> str:
    if type(href) is not str or not href.strip():
        raise _error(
            "EPUB manifest href is invalid",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    parts = urlsplit(href.strip())
    if parts.scheme or parts.netloc or parts.query:
        raise _error(
            "EPUB manifest contains an external or parameterized reading href",
            BookEpubImportErrorCode.UNSAFE_PACKAGE,
        )
    decoded = unquote(parts.path)
    if not decoded or "\x00" in decoded or "\\" in decoded or decoded.startswith("/") or _DRIVE_RE.match(decoded):
        raise _error(
            "EPUB manifest contains an unsafe reading href",
            BookEpubImportErrorCode.UNSAFE_PACKAGE,
        )
    joined = posixpath.normpath(posixpath.join(base_dir, decoded))
    if joined in {"", ".", ".."} or joined.startswith("../") or joined.startswith("/"):
        raise _error(
            "EPUB manifest reading href escapes the package root",
            BookEpubImportErrorCode.UNSAFE_PACKAGE,
        )
    return joined


def _package_rootfile(container: ET.Element, warnings: _Warnings) -> str:
    candidates: list[ET.Element] = []
    for element in container.iter():
        if _local_name(element.tag) != "rootfile":
            continue
        media_type = (element.attrib.get("media-type") or "").strip().casefold()
        if not media_type or media_type == _OPF_MEDIA_TYPE:
            candidates.append(element)
    if not candidates:
        raise _error(
            "EPUB container has no supported package document",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    if len(candidates) > 1:
        warnings.add("multiple EPUB package documents were present; the first supported rootfile was used")
    full_path = candidates[0].attrib.get("full-path")
    return _resolve_package_href("", full_path)


def _manifest_items(package: ET.Element, opf_dir: str) -> dict[str, _ManifestItem]:
    manifest = _direct_child(package, "manifest")
    if manifest is None:
        raise _error(
            "EPUB package has no manifest",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    output: dict[str, _ManifestItem] = {}
    for element in manifest:
        if _local_name(element.tag) != "item":
            continue
        item_id = (element.attrib.get("id") or "").strip()
        media_type = (element.attrib.get("media-type") or "").strip().casefold()
        href = element.attrib.get("href")
        fallback = (element.attrib.get("fallback") or "").strip() or None
        if not item_id or not media_type:
            raise _error(
                "EPUB manifest item is missing required identity",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        if item_id in output:
            raise _error(
                "EPUB manifest contains duplicate item identifiers",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        output[item_id] = _ManifestItem(
            item_id=item_id,
            entry_name=_resolve_package_href(opf_dir, href),
            media_type=media_type,
            fallback=fallback,
        )
    if not output:
        raise _error(
            "EPUB manifest is empty",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    return output


def _spine_ids(package: ET.Element, warnings: _Warnings) -> list[str]:
    spine = _direct_child(package, "spine")
    if spine is None:
        raise _error(
            "EPUB package has no reading spine",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    ids: list[str] = []
    for element in spine:
        if _local_name(element.tag) != "itemref":
            continue
        item_id = (element.attrib.get("idref") or "").strip()
        if not item_id:
            raise _error(
                "EPUB spine item is missing its manifest reference",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        ids.append(item_id)
        if (element.attrib.get("linear") or "").strip().casefold() == "no":
            warnings.add(f"EPUB non-linear spine item {item_id!r} was preserved in document order")
        if len(ids) > MAX_EPUB_SPINE_DOCUMENTS:
            raise _error(
                "EPUB contains too many spine documents",
                BookEpubImportErrorCode.RESOURCE_LIMIT,
            )
    if not ids:
        raise _error(
            "EPUB reading spine is empty",
            BookEpubImportErrorCode.NO_READABLE_CONTENT,
        )
    return ids


def _supported_manifest_item(
    item_id: str,
    manifest: dict[str, _ManifestItem],
) -> _ManifestItem | None:
    seen: set[str] = set()
    current_id = item_id
    for _depth in range(16):
        if current_id in seen:
            raise _error(
                "EPUB manifest fallback chain contains a cycle",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        seen.add(current_id)
        item = manifest.get(current_id)
        if item is None:
            raise _error(
                "EPUB spine references an unknown manifest item",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        if item.media_type in _SUPPORTED_SPINE_MEDIA_TYPES:
            return item
        if item.fallback is None:
            return None
        current_id = item.fallback
    raise _error(
        "EPUB manifest fallback chain is too deep",
        BookEpubImportErrorCode.RESOURCE_LIMIT,
    )


def _rebase_block(block: object, entry_name: str, chapter_index: int, block_index: int):
    if not hasattr(block, "as_dict"):
        raise _error(
            "EPUB HTML adapter returned an invalid semantic block",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    data = block.as_dict()
    original_id = str(data.get("block_id") or "")
    identity = f"{entry_name}\0{chapter_index}\0{block_index}\0{original_id}"
    data["block_id"] = f"epub-{sha256(identity.encode('utf-8')).hexdigest()[:24]}"
    anchor = data.get("source_anchor")
    data["source_anchor"] = entry_name if not anchor else f"{entry_name}#{anchor}"
    return block_from_dict(data)


def _resolved_asset(entry_name: str, reference: str) -> str | None:
    parts = urlsplit(reference.strip())
    if parts.scheme or parts.netloc or not parts.path:
        return None
    try:
        return _resolve_package_href(posixpath.dirname(entry_name), reference)
    except BookEpubImportError:
        return None


def import_epub_book(
    source: bytes,
    *,
    source_name: str,
    title: str | None = None,
    author: str | None = None,
    language: str | None = None,
) -> BookEpubImportResult:
    """Import a bounded EPUB 2/3 package through existing semantic adapters.

    The caller supplies package bytes; this function never extracts to disk or
    opens external resources. The OPF spine is authoritative for reading order.
    Unsupported spine media is reported explicitly rather than silently invented.
    """

    raw = _source_bytes(source)
    display_source = _required_text(source_name, "source_name")
    override_title = _optional_text(title, "title")
    override_author = _optional_text(author, "author")
    override_language = _optional_text(language, "language")
    warnings = _Warnings()

    try:
        archive = zipfile.ZipFile(BytesIO(raw), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise _error(
            "EPUB source is not a valid ZIP container",
            BookEpubImportErrorCode.UNSUPPORTED_CONTAINER,
        ) from exc

    with archive:
        index = _archive_index(archive)
        infos = archive.infolist()
        if infos[0].filename != "mimetype" or infos[0].compress_type != zipfile.ZIP_STORED:
            raise _error(
                "EPUB mimetype entry must be the first uncompressed package entry",
                BookEpubImportErrorCode.UNSUPPORTED_CONTAINER,
            )
        mimetype = _read_entry(archive, index, "mimetype", limit=128)
        if mimetype != b"application/epub+zip":
            raise _error(
                "EPUB mimetype declaration is invalid",
                BookEpubImportErrorCode.UNSUPPORTED_CONTAINER,
            )

        container = _xml_root(
            _read_entry(archive, index, "META-INF/container.xml", limit=MAX_EPUB_XML_BYTES),
            "container metadata",
        )
        opf_name = _package_rootfile(container, warnings)
        package = _xml_root(
            _read_entry(archive, index, opf_name, limit=MAX_EPUB_XML_BYTES),
            "package metadata",
        )
        opf_dir = posixpath.dirname(opf_name)
        manifest = _manifest_items(package, opf_dir)
        spine = _spine_ids(package, warnings)

        metadata = _direct_child(package, "metadata")
        package_titles = _metadata_values(metadata, "title")
        creators = _metadata_values(metadata, "creator")
        languages = _metadata_values(metadata, "language")
        rights = _metadata_values(metadata, "rights")

        blocks = []
        chapter_titles: list[str] = []
        image_references: list[str] = []
        pgn_games = 0
        imported_spine = 0

        for chapter_index, item_id in enumerate(spine, start=1):
            item = _supported_manifest_item(item_id, manifest)
            if item is None:
                warnings.add(
                    f"EPUB spine item {item_id!r} uses unsupported media and has no readable HTML fallback"
                )
                continue
            chapter = _read_entry(archive, index, item.entry_name)
            try:
                imported = import_html_book(
                    chapter,
                    source_name=f"{display_source}::{item.entry_name}",
                    available_assets=None,
                )
            except BookHtmlImportError as exc:
                if exc.code is BookHtmlImportErrorCode.NO_READABLE_CONTENT:
                    warnings.add(f"EPUB spine document {chapter_index} contained no readable semantic content")
                    continue
                if exc.code is BookHtmlImportErrorCode.MALFORMED_CHESS_CONTENT:
                    raise _error(
                        "EPUB contains invalid explicitly marked chess content",
                        BookEpubImportErrorCode.MALFORMED_CHESS_CONTENT,
                    ) from exc
                if exc.code is BookHtmlImportErrorCode.RESOURCE_LIMIT:
                    raise _error(
                        "EPUB spine document exceeds semantic import limits",
                        BookEpubImportErrorCode.RESOURCE_LIMIT,
                    ) from exc
                if exc.code is BookHtmlImportErrorCode.UNSUPPORTED_ENCODING:
                    raise _error(
                        "EPUB spine document uses an unsupported text encoding",
                        BookEpubImportErrorCode.UNSUPPORTED_CONTENT,
                    ) from exc
                raise _error(
                    "EPUB spine document could not be represented safely",
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                ) from exc

            imported_spine += 1
            chapter_titles.append(imported.document.title)
            pgn_games += imported.pgn_games
            for warning in imported.warnings:
                warnings.add(f"spine {chapter_index}: {warning}")
            for block_index, block in enumerate(imported.document.blocks, start=1):
                blocks.append(_rebase_block(block, item.entry_name, chapter_index, block_index))
            for reference in imported.image_references:
                resolved = _resolved_asset(item.entry_name, reference)
                if resolved is None:
                    warnings.add(f"spine {chapter_index}: an external or unsafe image reference was not resolved")
                    continue
                if resolved not in index:
                    warnings.add(f"spine {chapter_index}: a referenced package image is unavailable")
                    continue
                if resolved not in image_references:
                    image_references.append(resolved)

        if not blocks:
            raise _error(
                "EPUB contains no readable semantic content in its supported spine",
                BookEpubImportErrorCode.NO_READABLE_CONTENT,
            )

        resolved_title = override_title or (package_titles[0] if package_titles else None)
        if not resolved_title:
            first_heading = next((block.text for block in blocks if isinstance(block, Heading)), None)
            resolved_title = first_heading or (chapter_titles[0] if chapter_titles else display_source)
        resolved_author = override_author or ("; ".join(creators) if creators else None)
        resolved_language = override_language or (languages[0] if languages else None)
        resolved_rights = "; ".join(rights) if rights else None

        document = BookDocument(
            title=resolved_title,
            author=resolved_author,
            language=resolved_language,
            source_name=display_source,
            source_rights=resolved_rights,
            blocks=blocks,
            warnings=list(warnings.values),
        )

    digest = sha256(raw).hexdigest()
    return BookEpubImportResult(
        document=document,
        source_sha256=digest,
        book_key=f"epub-sha256:{digest}",
        spine_documents=imported_spine,
        pgn_games=pgn_games,
        image_references=tuple(image_references),
        warnings=tuple(warnings.values),
    )


SUPPORTED_EPUB_BOOK_CAPABILITY = MappingProxyType(
    {
        "format": "EPUB 2/3",
        "container": "bounded ZIP/OPF spine",
        "spine_media": tuple(sorted(_SUPPORTED_SPINE_MEDIA_TYPES)),
        "semantic_projection": "existing HTML/XHTML -> BookDocument adapter",
        "preserves": (
            "package title/creator/language/rights",
            "spine reading order",
            "headings",
            "paragraphs",
            "ordered/unordered lists",
            "accessible image text",
            "explicit data-acs-fen positions/diagrams",
            "canonically accepted embedded PGN",
            "package-relative source anchors",
        ),
        "does_not_claim": (
            "DRM or encrypted spine bypass",
            "filesystem extraction",
            "network resource fetching",
            "CSS/visual-layout fidelity",
            "script execution",
            "SVG-only or image-only chapter recognition",
            "audio/video playback",
            "UTF-16 spine ingestion",
            "PDF/OCR",
        ),
    }
)


__all__ = [
    "BookEpubImportError",
    "BookEpubImportErrorCode",
    "BookEpubImportResult",
    "MAX_EPUB_SOURCE_BYTES",
    "SUPPORTED_EPUB_BOOK_CAPABILITY",
    "import_epub_book",
]
