from __future__ import annotations

"""Bounded structural validation for owner-supplied DOCX release payloads.

This module validates the OOXML/OPC container only. It does not interpret document
content and intentionally stays outside Accessible Chess domain/chess semantics.
"""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import stat
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile, ZipInfo


_MAX_DOCX_BYTES = 64 * 1024 * 1024
_MAX_MEMBER_COUNT = 4096
_MAX_MEMBER_BYTES = 128 * 1024 * 1024
_MAX_TOTAL_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
_MAX_XML_BYTES = 8 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 200
_RATIO_CHECK_MIN_BYTES = 4 * 1024 * 1024
_CHUNK_BYTES = 1024 * 1024

_CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
_REL_NAMESPACES = {
    "http://schemas.openxmlformats.org/package/2006/relationships",
    "http://purl.oclc.org/ooxml/package/relationships",
}
_OFFICE_DOCUMENT_REL_TYPES = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument",
}
_WORD_DOCUMENT_NAMESPACES = {
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
}
_WORD_DOCUMENT_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
_REQUIRED_MEMBERS = {"[content_types].xml", "_rels/.rels", "word/document.xml"}


class PortableDocxIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PortableDocxIntegrityReport:
    path: Path
    member_count: int
    total_uncompressed_bytes: int


def _fail(message: str) -> None:
    raise PortableDocxIntegrityError(message)


def _xml_namespace(tag: str) -> str:
    if not tag.startswith("{") or "}" not in tag:
        return ""
    return tag[1 : tag.index("}")]


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _safe_member_name(info: ZipInfo) -> str:
    name = info.filename
    if not name or "\\" in name or "\x00" in name:
        _fail("DOCX member path is not canonical")
    if name.endswith("/"):
        token = name[:-1]
    else:
        token = name
    pure = PurePosixPath(token)
    if (
        not token
        or pure.is_absolute()
        or pure.as_posix() != token
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        _fail("DOCX member path is not canonical")
    return token


def _validate_member_metadata(info: ZipInfo) -> None:
    if info.flag_bits & 0x1:
        _fail("encrypted DOCX members are forbidden")
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(unix_mode)
    if info.is_dir():
        if file_type not in {0, stat.S_IFDIR}:
            _fail("special DOCX members are forbidden")
    elif file_type not in {0, stat.S_IFREG}:
        _fail("special DOCX members are forbidden")
    if info.file_size < 0 or info.file_size > _MAX_MEMBER_BYTES:
        _fail("DOCX member exceeds the bounded size limit")
    if info.file_size >= _RATIO_CHECK_MIN_BYTES:
        if info.compress_size <= 0:
            _fail("DOCX member has an unsafe compression ratio")
        if info.file_size > info.compress_size * _MAX_COMPRESSION_RATIO:
            _fail("DOCX member has an unsafe compression ratio")


def _read_member(archive: ZipFile, info: ZipInfo, *, maximum: int) -> bytes:
    if info.file_size > maximum:
        _fail("DOCX XML member exceeds the bounded size limit")
    payload = bytearray()
    try:
        with archive.open(info, "r") as source:
            while True:
                chunk = source.read(min(_CHUNK_BYTES, maximum + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > maximum:
                    _fail("DOCX XML member exceeds the bounded size limit")
    except (BadZipFile, RuntimeError, OSError, EOFError) as exc:
        raise PortableDocxIntegrityError("DOCX member bytes are corrupt") from exc
    if len(payload) != info.file_size:
        _fail("DOCX member size does not match ZIP metadata")
    return bytes(payload)


def _parse_xml(payload: bytes, *, label: str) -> ET.Element:
    lowered = payload.lower().replace(b"\x00", b"")
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        _fail(f"{label} contains forbidden XML declarations")
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise PortableDocxIntegrityError(f"{label} is malformed XML") from exc


def _validate_content_types(root: ET.Element) -> None:
    if root.tag != f"{{{_CONTENT_TYPES}}}Types":
        _fail("DOCX content-types root is invalid")
    matches = []
    for child in root:
        if child.tag != f"{{{_CONTENT_TYPES}}}Override":
            continue
        if child.attrib.get("PartName", "").casefold() == "/word/document.xml":
            matches.append(child.attrib.get("ContentType"))
    if matches != [_WORD_DOCUMENT_CONTENT_TYPE]:
        _fail("DOCX main Word document content type is invalid")


def _validate_root_relationships(root: ET.Element) -> None:
    namespace = _xml_namespace(root.tag)
    if namespace not in _REL_NAMESPACES or _xml_local_name(root.tag) != "Relationships":
        _fail("DOCX root relationships document is invalid")
    targets: list[str] = []
    for child in root:
        if _xml_namespace(child.tag) != namespace or _xml_local_name(child.tag) != "Relationship":
            continue
        if child.attrib.get("Type") not in _OFFICE_DOCUMENT_REL_TYPES:
            continue
        target_mode = child.attrib.get("TargetMode")
        if target_mode is not None and target_mode.casefold() != "internal":
            _fail("DOCX main Word document relationship must be internal")
        target = child.attrib.get("Target", "")
        if (
            not target
            or "\\" in target
            or "?" in target
            or "#" in target
            or any(part in {"", ".", ".."} for part in PurePosixPath(target.lstrip("/")).parts)
        ):
            _fail("DOCX main Word document relationship target is invalid")
        targets.append(target.lstrip("/").casefold())
    if targets != ["word/document.xml"]:
        _fail("DOCX must have exactly one internal main Word document relationship")


def _validate_document_root(root: ET.Element) -> None:
    if (
        _xml_namespace(root.tag) not in _WORD_DOCUMENT_NAMESPACES
        or _xml_local_name(root.tag) != "document"
    ):
        _fail("DOCX main Word document XML root is invalid")


def validate_portable_docx(path: str | Path) -> PortableDocxIntegrityReport:
    """Require *path* to be a bounded, structurally valid .docx OOXML package."""

    document = Path(path)
    if document.suffix.casefold() != ".docx":
        _fail("owner Word document must use the .docx extension")
    try:
        details = document.stat()
    except OSError as exc:
        raise PortableDocxIntegrityError("owner Word document cannot be stat'ed") from exc
    if not stat.S_ISREG(details.st_mode) or details.st_size <= 0 or details.st_size > _MAX_DOCX_BYTES:
        _fail("owner Word document file size is invalid")

    try:
        with ZipFile(document, "r") as archive:
            infos = archive.infolist()
            if not infos or len(infos) > _MAX_MEMBER_COUNT:
                _fail("DOCX member count is invalid")
            by_folded: dict[str, ZipInfo] = {}
            total = 0
            for info in infos:
                token = _safe_member_name(info)
                _validate_member_metadata(info)
                folded = token.casefold()
                if folded in by_folded:
                    _fail("DOCX contains duplicate or case-colliding member paths")
                by_folded[folded] = info
                total += int(info.file_size)
                if total > _MAX_TOTAL_UNCOMPRESSED_BYTES:
                    _fail("DOCX uncompressed payload exceeds the bounded size limit")
            if not _REQUIRED_MEMBERS.issubset(by_folded):
                _fail("DOCX is missing required OOXML Word members")

            content_types = _parse_xml(
                _read_member(archive, by_folded["[content_types].xml"], maximum=_MAX_XML_BYTES),
                label="DOCX content types",
            )
            relationships = _parse_xml(
                _read_member(archive, by_folded["_rels/.rels"], maximum=_MAX_XML_BYTES),
                label="DOCX root relationships",
            )
            document_xml = _parse_xml(
                _read_member(archive, by_folded["word/document.xml"], maximum=_MAX_XML_BYTES),
                label="DOCX main document",
            )
            _validate_content_types(content_types)
            _validate_root_relationships(relationships)
            _validate_document_root(document_xml)

            # Force every member through decompression/CRC verification while all
            # size and ratio bounds above are still authoritative.
            for info in infos:
                if info.is_dir():
                    continue
                consumed = 0
                try:
                    with archive.open(info, "r") as source:
                        while True:
                            chunk = source.read(_CHUNK_BYTES)
                            if not chunk:
                                break
                            consumed += len(chunk)
                            if consumed > info.file_size or consumed > _MAX_MEMBER_BYTES:
                                _fail("DOCX member expands beyond declared bounds")
                except (BadZipFile, RuntimeError, OSError, EOFError) as exc:
                    raise PortableDocxIntegrityError("DOCX member bytes are corrupt") from exc
                if consumed != info.file_size:
                    _fail("DOCX member size does not match ZIP metadata")
    except PortableDocxIntegrityError:
        raise
    except (BadZipFile, OSError, RuntimeError, EOFError) as exc:
        raise PortableDocxIntegrityError("owner Word document is not a valid DOCX ZIP") from exc

    return PortableDocxIntegrityReport(
        path=document,
        member_count=len(infos),
        total_uncompressed_bytes=total,
    )
