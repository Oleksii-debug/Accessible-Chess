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
import unicodedata
import zlib
from types import MappingProxyType
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
from xml.parsers import expat
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
_EPUB_CONTENT_DOCUMENT_MEDIA_TYPES = frozenset(
    {"application/xhtml+xml", "image/svg+xml"}
)
_MEDIA_OVERLAY_MEDIA_TYPE = "application/smil+xml"
_NCX_MEDIA_TYPE = "application/x-dtbncx+xml"
_CONTAINER_NAMESPACE = "urn:oasis:names:tc:opendocument:xmlns:container"
_CONTAINER_TAG = f"{{{_CONTAINER_NAMESPACE}}}container"
_ROOTFILES_TAG = f"{{{_CONTAINER_NAMESPACE}}}rootfiles"
_ROOTFILE_TAG = f"{{{_CONTAINER_NAMESPACE}}}rootfile"
_LINKS_TAG = f"{{{_CONTAINER_NAMESPACE}}}links"
_LINK_TAG = f"{{{_CONTAINER_NAMESPACE}}}link"
_OPF_MEDIA_TYPE = "application/oebps-package+xml"
_OPF_NAMESPACE = "http://www.idpf.org/2007/opf"
_DUBLIN_CORE_NAMESPACE = "http://purl.org/dc/elements/1.1/"
_PACKAGE_TAG = f"{{{_OPF_NAMESPACE}}}package"
_METADATA_TAG = f"{{{_OPF_NAMESPACE}}}metadata"
_MANIFEST_TAG = f"{{{_OPF_NAMESPACE}}}manifest"
_SPINE_TAG = f"{{{_OPF_NAMESPACE}}}spine"
_GUIDE_TAG = f"{{{_OPF_NAMESPACE}}}guide"
_BINDINGS_TAG = f"{{{_OPF_NAMESPACE}}}bindings"
_COLLECTION_TAG = f"{{{_OPF_NAMESPACE}}}collection"
_TOURS_TAG = f"{{{_OPF_NAMESPACE}}}tours"
_ITEM_TAG = f"{{{_OPF_NAMESPACE}}}item"
_ITEMREF_TAG = f"{{{_OPF_NAMESPACE}}}itemref"
_ID_BEARING_OPF_TAGS = frozenset(
    f"{{{_OPF_NAMESPACE}}}{name}"
    for name in ("collection", "item", "itemref", "link", "manifest", "meta", "package", "spine")
)
_SUPPORTED_PACKAGE_VERSIONS = frozenset({"2.0", "3.0"})
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_INVALID_PERCENT_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
_ENCODED_PATH_SEPARATOR_RE = re.compile(r"%2[fF]")


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
    media_overlay: str | None


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


class _ForbiddenXmlDeclaration(Exception):
    """Internal control-flow sentinel for DTD/entity rejection."""


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


def _canonical_casefold_name(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    return unicodedata.normalize("NFC", normalized.casefold())


def _archive_index(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if not infos or len(infos) > MAX_EPUB_ENTRIES:
        raise _error(
            "EPUB contains an unsupported number of package entries",
            BookEpubImportErrorCode.RESOURCE_LIMIT,
        )
    index: dict[str, zipfile.ZipInfo] = {}
    seen: set[str] = set()
    canonical_children: dict[tuple[int, str], tuple[int, str]] = {}
    canonical_directory_nodes: set[int] = set()
    canonical_file_nodes: set[int] = set()
    next_canonical_node = 1
    total_uncompressed = 0
    for info in infos:
        name = _safe_entry_name(info.filename)
        if name in seen:
            raise _error(
                "EPUB contains duplicate package entry names",
                BookEpubImportErrorCode.UNSAFE_PACKAGE,
            )
        seen.add(name)

        parts = name.split("/")
        parent_node = 0
        for part_index, raw_part in enumerate(parts):
            if parent_node in canonical_file_nodes:
                raise _error(
                    "EPUB package entry path traverses an existing regular file",
                    BookEpubImportErrorCode.UNSAFE_PACKAGE,
                )
            canonical_part = _canonical_casefold_name(raw_part)
            edge = (parent_node, canonical_part)
            previous = canonical_children.get(edge)
            if previous is None:
                child_node = next_canonical_node
                next_canonical_node += 1
                canonical_children[edge] = (child_node, raw_part)
            else:
                child_node, previous_raw_part = previous
                if previous_raw_part != raw_part:
                    raise _error(
                        "EPUB package entry names collide after Unicode canonical case folding",
                        BookEpubImportErrorCode.UNSAFE_PACKAGE,
                    )
            if part_index < len(parts) - 1:
                if child_node in canonical_file_nodes:
                    raise _error(
                        "EPUB package entry path traverses an existing regular file",
                        BookEpubImportErrorCode.UNSAFE_PACKAGE,
                    )
                canonical_directory_nodes.add(child_node)
            parent_node = child_node

        is_directory = info.is_dir()
        if is_directory:
            if parent_node in canonical_file_nodes:
                raise _error(
                    "EPUB package path is both a regular file and a directory",
                    BookEpubImportErrorCode.UNSAFE_PACKAGE,
                )
            canonical_directory_nodes.add(parent_node)
        else:
            if parent_node in canonical_directory_nodes:
                raise _error(
                    "EPUB package path is both a regular file and a directory",
                    BookEpubImportErrorCode.UNSAFE_PACKAGE,
                )
            canonical_file_nodes.add(parent_node)

        mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        if file_type and file_type not in {stat.S_IFREG, stat.S_IFDIR}:
            raise _error(
                "EPUB package contains an unsupported special entry type",
                BookEpubImportErrorCode.UNSAFE_PACKAGE,
            )
        if file_type == stat.S_IFDIR and not is_directory:
            raise _error(
                "EPUB package directory metadata contradicts its entry name",
                BookEpubImportErrorCode.UNSAFE_PACKAGE,
            )
        if file_type == stat.S_IFREG and is_directory:
            raise _error(
                "EPUB package file metadata contradicts its entry name",
                BookEpubImportErrorCode.UNSAFE_PACKAGE,
            )
        if info.flag_bits & 0x1:
            raise _error(
                "EPUB uses ZIP encryption, which OCF does not permit",
                BookEpubImportErrorCode.UNSUPPORTED_CONTAINER,
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
        if not is_directory:
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
    except (RuntimeError, NotImplementedError, zipfile.BadZipFile, zlib.error) as exc:
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

    parser = expat.ParserCreate()

    def reject_declaration(*_args: object) -> None:
        raise _ForbiddenXmlDeclaration()

    parser.StartDoctypeDeclHandler = reject_declaration
    parser.EntityDeclHandler = reject_declaration
    parser.UnparsedEntityDeclHandler = reject_declaration
    parser.ExternalEntityRefHandler = reject_declaration
    try:
        parser.Parse(data, True)
    except _ForbiddenXmlDeclaration as exc:
        raise _error(
            f"EPUB {label} contains unsupported XML declarations",
            BookEpubImportErrorCode.UNSAFE_PACKAGE,
        ) from exc
    except expat.ExpatError as exc:
        raise _error(
            f"EPUB {label} is malformed",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        ) from exc

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


def _is_exact_identifier(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and not any(character.isspace() for character in value)
    )


def _direct_child(parent: ET.Element, name: str) -> ET.Element | None:
    wanted = f"{{{_OPF_NAMESPACE}}}{name}"
    for child in parent:
        if child.tag == wanted:
            return child
    return None


def _required_unique_direct_child(
    parent: ET.Element,
    name: str,
) -> ET.Element:
    """Return the only direct OPF section with this local name."""
    wanted = f"{{{_OPF_NAMESPACE}}}{name}"
    matches = [child for child in parent if child.tag == wanted]
    if len(matches) != 1:
        raise _error(
            f"EPUB package must contain exactly one {name} section",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    return matches[0]


def _metadata_values(metadata: ET.Element | None, name: str) -> list[str]:
    if metadata is None:
        return []
    wanted = f"{{{_DUBLIN_CORE_NAMESPACE}}}{name}"
    values: list[str] = []
    for element in metadata:
        if element.tag != wanted:
            continue
        if len(element):
            raise _error(
                "EPUB Dublin Core metadata must contain text only",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        text = " ".join((element.text or "").split())
        if text and text not in values:
            values.append(text)
    return values


def _is_container_namespace_tag(tag: object) -> bool:
    return type(tag) is str and tag.startswith(f"{{{_CONTAINER_NAMESPACE}}}")


def _is_opf_namespace_tag(tag: object) -> bool:
    return type(tag) is str and tag.startswith(f"{{{_OPF_NAMESPACE}}}")


def _validate_package_ids_unique(package: ET.Element, metadata: ET.Element) -> None:
    """Reject duplicate EPUB-defined IDs before resolving IDREF semantics."""

    seen: set[str] = set()

    def record(element: ET.Element) -> None:
        raw_id = element.attrib.get("id")
        if raw_id is None:
            return
        if not _is_exact_identifier(raw_id):
            raise _error(
                "EPUB package contains a malformed document identifier",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        if raw_id in seen:
            raise _error(
                "EPUB package contains duplicate document identifiers",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        seen.add(raw_id)

    # EPUB's id attribute is document-scoped. Count every recognized OPF
    # id-bearing element plus Dublin Core elements anywhere the package grammar
    # permits metadata (including metadata nested inside an outdated-but-
    # conforming collection). Foreign extension elements do not acquire EPUB ID
    # semantics merely by spelling an attribute "id".
    dc_prefix = f"{{{_DUBLIN_CORE_NAMESPACE}}}"
    for element in package.iter():
        if element.tag in _ID_BEARING_OPF_TAGS or (
            type(element.tag) is str and element.tag.startswith(dc_prefix)
        ):
            record(element)


def _validate_package_document(package: ET.Element) -> None:
    if package.tag != _PACKAGE_TAG:
        raise _error(
            "EPUB package metadata has an invalid OPF root element or namespace",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    version = package.attrib.get("version")
    if version not in _SUPPORTED_PACKAGE_VERSIONS:
        raise _error(
            "EPUB package metadata has an invalid package version",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    if (package.text or "").strip() or any(
        (child.tail or "").strip() for child in package
    ):
        raise _error(
            "EPUB package contains invalid mixed text",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    unique_identifier = package.attrib.get("unique-identifier")
    if not _is_exact_identifier(unique_identifier):
        raise _error(
            "EPUB package metadata has a missing or malformed unique identifier",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    structural_children = [
        child.tag for child in package if _is_opf_namespace_tag(child.tag)
    ]
    required = (_METADATA_TAG, _MANIFEST_TAG, _SPINE_TAG)
    if (
        tuple(structural_children[:3]) != required
        or any(structural_children.count(tag) != 1 for tag in required)
    ):
        raise _error(
            "EPUB package required sections must be the first three OPF children in canonical order",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    trailing = structural_children[3:]
    if version == "3.0":
        index = 0
        if index < len(trailing) and trailing[index] == _GUIDE_TAG:
            index += 1
        if index < len(trailing) and trailing[index] == _BINDINGS_TAG:
            index += 1
        while index < len(trailing) and trailing[index] == _COLLECTION_TAG:
            index += 1
        valid_trailing_structure = index == len(trailing)
    else:
        index = 0
        if index < len(trailing) and trailing[index] == _TOURS_TAG:
            index += 1
        if index < len(trailing) and trailing[index] == _GUIDE_TAG:
            index += 1
        valid_trailing_structure = index == len(trailing)
    if not valid_trailing_structure:
        raise _error(
            "EPUB package contains an invalid OPF top-level element or ordering",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    metadata = _required_unique_direct_child(package, "metadata")
    if (metadata.text or "").strip() or any(
        (child.tail or "").strip() for child in metadata
    ):
        raise _error(
            "EPUB metadata contains invalid mixed text",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    for child in metadata:
        if _is_opf_namespace_tag(child.tag) and child.tag not in {
            f"{{{_OPF_NAMESPACE}}}meta",
            f"{{{_OPF_NAMESPACE}}}link",
        }:
            raise _error(
                "EPUB metadata contains an invalid OPF element",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
    _validate_package_ids_unique(package, metadata)
    dc_prefix = f"{{{_DUBLIN_CORE_NAMESPACE}}}"
    for element in metadata:
        if type(element.tag) is not str or not element.tag.startswith(dc_prefix):
            continue
        if len(element):
            raise _error(
                "EPUB Dublin Core metadata must contain text only",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        if not " ".join((element.text or "").split()):
            raise _error(
                "EPUB Dublin Core metadata values must not be empty",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )

    if not _metadata_values(metadata, "title"):
        raise _error(
            "EPUB package metadata is missing a non-empty dc:title",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    if not _metadata_values(metadata, "language"):
        raise _error(
            "EPUB package metadata is missing a non-empty dc:language",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    identifier_tag = f"{{{_DUBLIN_CORE_NAMESPACE}}}identifier"
    matching_identifiers: list[str] = []
    for element in metadata:
        if element.tag != identifier_tag or element.attrib.get("id") != unique_identifier:
            continue
        if len(element):
            raise _error(
                "EPUB unique identifier metadata must contain text only",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        value = " ".join((element.text or "").split())
        if not value:
            raise _error(
                "EPUB unique identifier metadata is empty",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        matching_identifiers.append(value)
    if len(matching_identifiers) != 1:
        raise _error(
            "EPUB package unique identifier must resolve to exactly one direct dc:identifier",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )


def _resolve_package_href(
    base_dir: str,
    href: object,
    *,
    allow_fragment: bool = False,
    allow_surrounding_whitespace: bool = False,
) -> str:
    if type(href) is not str or not href.strip():
        raise _error(
            "EPUB manifest href is invalid",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    raw_href = href.strip()
    if not allow_surrounding_whitespace and raw_href != href:
        raise _error(
            "EPUB package href contains surrounding whitespace",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in raw_href):
        raise _error(
            "EPUB package href contains an ASCII control character",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    try:
        parts = urlsplit(raw_href)
    except ValueError as exc:
        raise _error(
            "EPUB package href is malformed",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        ) from exc
    if "#" in raw_href and not allow_fragment:
        raise _error(
            "EPUB package href must not contain a fragment identifier",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    if parts.scheme or parts.netloc or parts.query:
        raise _error(
            "EPUB manifest contains an external or parameterized reading href",
            BookEpubImportErrorCode.UNSAFE_PACKAGE,
        )
    if _INVALID_PERCENT_ESCAPE_RE.search(parts.path):
        raise _error(
            "EPUB package href contains malformed percent encoding",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    if _ENCODED_PATH_SEPARATOR_RE.search(parts.path):
        raise _error(
            "EPUB package href percent-encodes a path separator",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    try:
        decoded = unquote(parts.path, errors="strict")
    except UnicodeDecodeError as exc:
        raise _error(
            "EPUB package href contains invalid UTF-8 percent encoding",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        ) from exc
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in decoded):
        raise _error(
            "EPUB package href decodes to an ASCII control character",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
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


def _package_rootfile(
    container: ET.Element,
    warnings: _Warnings,
    archive_index: dict[str, zipfile.ZipInfo],
) -> str:
    if (
        container.tag != _CONTAINER_TAG
        or container.attrib.get("version") != "1.0"
    ):
        raise _error(
            "EPUB container metadata has an invalid root element or version",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    if (container.text or "").strip() or any(
        (child.tail or "").strip() for child in container
    ):
        raise _error(
            "EPUB container contains invalid mixed text",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    # OCF validates container.xml after removing foreign-namespace elements and
    # their contents. Enforce the remaining canonical child order exactly:
    # rootfiles first, followed by at most one optional links section.
    structural_children = [
        child for child in container if _is_container_namespace_tag(child.tag)
    ]
    if (
        not structural_children
        or structural_children[0].tag != _ROOTFILES_TAG
        or len(structural_children) > 2
        or (
            len(structural_children) == 2
            and structural_children[1].tag != _LINKS_TAG
        )
    ):
        raise _error(
            "EPUB container has invalid canonical child structure",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    rootfiles = structural_children[0]
    if (rootfiles.text or "").strip() or any(
        (child.tail or "").strip() for child in rootfiles
    ):
        raise _error(
            "EPUB rootfiles section contains invalid text content",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    candidates: list[str] = []
    seen_paths: set[str] = set()
    for element in rootfiles:
        if not _is_container_namespace_tag(element.tag):
            # Foreign extension element and all its contents are ignored by OCF.
            continue
        if element.tag != _ROOTFILE_TAG:
            raise _error(
                "EPUB rootfiles section contains an invalid container element",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        if (element.text or "").strip():
            raise _error(
                "EPUB rootfile element must be empty",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        for child in element:
            if _is_container_namespace_tag(child.tag) or (child.tail or "").strip():
                raise _error(
                    "EPUB rootfile element must be empty",
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )
        media_type = element.attrib.get("media-type")
        if media_type != _OPF_MEDIA_TYPE:
            raise _error(
                "EPUB rootfile has a missing or invalid package media type",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        full_path = _resolve_package_href("", element.attrib.get("full-path"))
        if full_path in seen_paths:
            raise _error(
                "EPUB container resolves multiple rootfiles to the same package document",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        if full_path not in archive_index:
            raise _error(
                "EPUB container references a package document that is unavailable",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        seen_paths.add(full_path)
        candidates.append(full_path)
        if (element.tail or "").strip():
            raise _error(
                "EPUB rootfiles section contains invalid text content",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )

    if not candidates:
        raise _error(
            "EPUB container has no supported package document",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )

    if len(structural_children) == 2:
        links = structural_children[1]
        if (links.text or "").strip() or any(
            (child.tail or "").strip() for child in links
        ):
            raise _error(
                "EPUB container links section contains invalid text content",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        link_count = 0
        for element in links:
            if not _is_container_namespace_tag(element.tag):
                continue
            if element.tag != _LINK_TAG:
                raise _error(
                    "EPUB container links section contains an invalid element",
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )
            link_count += 1
            if (element.text or "").strip():
                raise _error(
                    "EPUB container link element must be empty",
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )
            for child in element:
                if _is_container_namespace_tag(child.tag) or (child.tail or "").strip():
                    raise _error(
                        "EPUB container link element must be empty",
                        BookEpubImportErrorCode.MALFORMED_PACKAGE,
                    )
            raw_href = element.attrib.get("href")
            raw_rel = element.attrib.get("rel")
            if type(raw_href) is not str or not raw_href or raw_href != raw_href.strip():
                raise _error(
                    "EPUB container link href is missing or malformed",
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )
            try:
                href_parts = urlsplit(raw_href)
            except ValueError as exc:
                raise _error(
                    "EPUB container link href is malformed",
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                ) from exc
            if href_parts.scheme or href_parts.netloc or not href_parts.path:
                raise _error(
                    "EPUB container link href is not path-relative",
                    BookEpubImportErrorCode.UNSAFE_PACKAGE,
                )
            _resolve_package_href("", href_parts.path)
            if (
                type(raw_rel) is not str
                or not raw_rel
                or raw_rel != raw_rel.strip()
                or any(
                    not token or any(character.isspace() for character in token)
                    for token in raw_rel.split(" ")
                )
            ):
                raise _error(
                    "EPUB container link rel is missing or malformed",
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )
        if not link_count:
            raise _error(
                "EPUB container links section is empty",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )

    if len(candidates) > 1:
        warnings.add("multiple EPUB package documents were present; the first supported rootfile was used")
    return candidates[0]


def _manifest_items(package: ET.Element, opf_dir: str) -> dict[str, _ManifestItem]:
    manifest = _required_unique_direct_child(package, "manifest")
    if (manifest.text or "").strip():
        raise _error(
            "EPUB manifest contains invalid text content",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    output: dict[str, _ManifestItem] = {}
    resource_owners: dict[str, str] = {}
    for element in manifest:
        if element.tag != _ITEM_TAG:
            if _local_name(element.tag) == "item" or _is_opf_namespace_tag(element.tag):
                raise _error(
                    "EPUB manifest contains an invalid item element",
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )
            if (element.tail or "").strip():
                raise _error(
                    "EPUB manifest contains invalid text content",
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )
            continue
        if (element.text or "").strip() or len(element):
            raise _error(
                "EPUB manifest item must be empty",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        if (element.tail or "").strip():
            raise _error(
                "EPUB manifest contains invalid text content",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        raw_item_id = element.attrib.get("id")
        raw_media_type = element.attrib.get("media-type")
        href = element.attrib.get("href")
        raw_fallback = element.attrib.get("fallback")
        raw_media_overlay = element.attrib.get("media-overlay")
        if (
            not _is_exact_identifier(raw_item_id)
            or type(raw_media_type) is not str
            or not raw_media_type
            or raw_media_type != raw_media_type.strip()
            or any(character.isspace() for character in raw_media_type)
        ):
            raise _error(
                "EPUB manifest item is missing or has malformed required identity",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        item_id = raw_item_id
        media_type = raw_media_type.casefold()
        if raw_fallback is None:
            fallback = None
        elif not _is_exact_identifier(raw_fallback):
            raise _error(
                "EPUB manifest fallback identifier is malformed",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        else:
            fallback = raw_fallback
        if raw_media_overlay is None:
            media_overlay = None
        elif not _is_exact_identifier(raw_media_overlay):
            raise _error(
                "EPUB manifest media-overlay identifier is malformed",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        else:
            media_overlay = raw_media_overlay
        if item_id in output:
            raise _error(
                "EPUB manifest contains duplicate item identifiers",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        entry_name = _resolve_package_href(opf_dir, href)
        previous_item_id = resource_owners.get(entry_name)
        if previous_item_id is not None:
            raise _error(
                "EPUB manifest resolves multiple item identifiers to the same package resource",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        resource_owners[entry_name] = item_id
        output[item_id] = _ManifestItem(
            item_id=item_id,
            entry_name=entry_name,
            media_type=media_type,
            fallback=fallback,
            media_overlay=media_overlay,
        )
    if not output:
        raise _error(
            "EPUB manifest is empty",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    _validate_manifest_fallback_graph(output)
    _validate_manifest_media_overlays(output)
    return output


def _validate_manifest_media_overlays(
    manifest: dict[str, _ManifestItem],
) -> None:
    for item in manifest.values():
        overlay_id = item.media_overlay
        if overlay_id is None:
            continue
        if item.media_type not in _EPUB_CONTENT_DOCUMENT_MEDIA_TYPES:
            raise _error(
                "EPUB media-overlay is only valid on EPUB content documents",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        overlay = manifest.get(overlay_id)
        if overlay is None:
            raise _error(
                "EPUB media-overlay references an unknown manifest item",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        if overlay.media_type != _MEDIA_OVERLAY_MEDIA_TYPE:
            raise _error(
                "EPUB media-overlay target has an invalid media type",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )


def _validate_manifest_fallback_graph(
    manifest: dict[str, _ManifestItem],
) -> None:
    for item in manifest.values():
        if item.fallback is not None and item.fallback not in manifest:
            raise _error(
                "EPUB manifest fallback references an unknown item",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )

    for start_id in manifest:
        seen: set[str] = set()
        current_id = start_id
        while True:
            if current_id in seen:
                raise _error(
                    "EPUB manifest fallback chain contains a cycle",
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )
            seen.add(current_id)
            fallback = manifest[current_id].fallback
            if fallback is None:
                break
            if fallback in seen:
                raise _error(
                    "EPUB manifest fallback chain contains a cycle",
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )
            if len(seen) >= 16:
                raise _error(
                    "EPUB manifest fallback chain is too deep",
                    BookEpubImportErrorCode.RESOURCE_LIMIT,
                )
            current_id = fallback


def _validate_manifest_resources(
    manifest: dict[str, _ManifestItem],
    *,
    package_entry_name: str,
    archive_index: dict[str, zipfile.ZipInfo],
) -> None:
    for item in manifest.values():
        entry_name = item.entry_name
        if (
            entry_name == package_entry_name
            or entry_name == "mimetype"
            or entry_name == "META-INF"
            or entry_name.startswith("META-INF/")
        ):
            raise _error(
                "EPUB manifest references a restricted package resource",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        if entry_name not in archive_index:
            raise _error(
                "EPUB manifest references a package resource that is unavailable",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )


def _spine_ids(
    package: ET.Element,
    warnings: _Warnings,
    manifest: dict[str, _ManifestItem],
) -> list[str]:
    spine = _required_unique_direct_child(package, "spine")
    if (spine.text or "").strip():
        raise _error(
            "EPUB spine contains invalid text content",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    raw_toc = spine.attrib.get("toc")
    if raw_toc is not None:
        if not _is_exact_identifier(raw_toc):
            raise _error(
                "EPUB spine toc identifier is malformed",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        toc_item = manifest.get(raw_toc)
        if toc_item is None:
            raise _error(
                "EPUB spine toc references an unknown manifest item",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        if toc_item.media_type != _NCX_MEDIA_TYPE:
            raise _error(
                "EPUB spine toc target is not an NCX resource",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )

    page_progression = spine.attrib.get("page-progression-direction")
    if page_progression is not None and page_progression not in {
        "ltr",
        "rtl",
        "default",
    }:
        raise _error(
            "EPUB spine has an invalid page progression direction",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
        )
    ids: list[str] = []
    seen_ids: set[str] = set()
    has_linear_item = False
    for element in spine:
        if element.tag != _ITEMREF_TAG:
            if _local_name(element.tag) == "itemref" or _is_opf_namespace_tag(element.tag):
                raise _error(
                    "EPUB spine contains an invalid itemref element",
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )
            if (element.tail or "").strip():
                raise _error(
                    "EPUB spine contains invalid text content",
                    BookEpubImportErrorCode.MALFORMED_PACKAGE,
                )
            continue
        if (element.text or "").strip() or len(element):
            raise _error(
                "EPUB spine itemref must be empty",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        if (element.tail or "").strip():
            raise _error(
                "EPUB spine contains invalid text content",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        raw_item_id = element.attrib.get("idref")
        if not _is_exact_identifier(raw_item_id):
            raise _error(
                "EPUB spine item has a missing or malformed manifest reference",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        item_id = raw_item_id
        if item_id in seen_ids:
            raise _error(
                "EPUB spine references the same manifest item more than once",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        seen_ids.add(item_id)
        raw_linear = element.attrib.get("linear")
        if raw_linear is None:
            linear = "yes"
        elif (
            raw_linear not in {"yes", "no"}
            or raw_linear != raw_linear.strip()
        ):
            raise _error(
                "EPUB spine item has an invalid linear attribute",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
        else:
            linear = raw_linear
        ids.append(item_id)
        if linear == "no":
            warnings.add(f"EPUB non-linear spine item {item_id!r} was preserved in document order")
        else:
            has_linear_item = True
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
    if not has_linear_item:
        raise _error(
            "EPUB reading spine has no linear item",
            BookEpubImportErrorCode.MALFORMED_PACKAGE,
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
        if item.media_type in _EPUB_CONTENT_DOCUMENT_MEDIA_TYPES:
            if item.fallback is None:
                return None
            current_id = item.fallback
            continue
        if item.fallback is None:
            raise _error(
                "EPUB foreign spine content has no EPUB content fallback",
                BookEpubImportErrorCode.MALFORMED_PACKAGE,
            )
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
        return _resolve_package_href(
            posixpath.dirname(entry_name),
            reference,
            allow_fragment=True,
            allow_surrounding_whitespace=True,
        )
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
        if infos[0].extra:
            raise _error(
                "EPUB mimetype entry must not contain a ZIP extra field",
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
        opf_name = _package_rootfile(container, warnings, index)
        package = _xml_root(
            _read_entry(archive, index, opf_name, limit=MAX_EPUB_XML_BYTES),
            "package metadata",
        )
        _validate_package_document(package)
        opf_dir = posixpath.dirname(opf_name)
        manifest = _manifest_items(package, opf_dir)
        _validate_manifest_resources(
            manifest,
            package_entry_name=opf_name,
            archive_index=index,
        )
        spine = _spine_ids(package, warnings, manifest)
        manifest_by_resource = {
            item.entry_name: item
            for item in manifest.values()
        }

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
                manifest_item = manifest_by_resource.get(resolved)
                if manifest_item is None:
                    warnings.add(
                        f"spine {chapter_index}: a referenced package image is not declared in the manifest"
                    )
                    continue
                if not manifest_item.media_type.startswith("image/"):
                    warnings.add(
                        f"spine {chapter_index}: a referenced package resource is not declared as an image"
                    )
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
            "Media Overlay playback/synchronization",
            "NCX navigation rendering",
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
