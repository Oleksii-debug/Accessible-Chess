from __future__ import annotations

"""Hash-pinned acquisition of lawful test assets; NOT a format/chess parser.

Only one explicit trusted, HTTPS, CC0-pinned source may be downloaded automatically.
Unverified books, proprietary ChessBase archives and user-owned files are catalog
entries, not assumed distribution rights or fabricated import PASS results.
"""

import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import zipfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

CATALOG_FILE = Path(__file__).resolve().parents[1] / "docs" / "corpus" / "revised_sections37_40_sources.json"
_ID = re.compile(r"^[a-z0-9][a-z0-9_]{2,79}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")
_CHUNK = 256 * 1024


class LawfulCorpusError(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    """Never follow a third-party redirect before authenticating its destination."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_no_redirect(request: Request, timeout: int):
    return build_opener(_NoRedirect()).open(request, timeout=timeout)


def load_catalog(path: Path = CATALOG_FILE) -> tuple[dict, ...]:
    # Refuse oversized untrusted metadata before reading it all into memory.
    try:
        with path.open("rb") as stream:
            raw = stream.read(256 * 1024 + 1)
    except OSError as exc:
        raise LawfulCorpusError("corpus catalog cannot be read") from exc
    if len(raw) > 256 * 1024:
        raise LawfulCorpusError("corpus catalog exceeds maximum size")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise LawfulCorpusError("corpus catalog JSON is invalid") from exc
    if (
        type(data) is not dict
        or type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or type(data.get("sources")) is not list
    ):
        raise LawfulCorpusError("corpus catalog schema invalid")
    records = data["sources"]
    if not records or len(records) > 256:
        raise LawfulCorpusError("corpus catalog size invalid")
    seen: set[str] = set()
    for entry in records:
        if type(entry) is not dict:
            raise LawfulCorpusError("corpus entry invalid")
        identifier = entry.get("id")
        if type(identifier) is not str or not _ID.fullmatch(identifier) or identifier in seen:
            raise LawfulCorpusError("corpus source id invalid or duplicate")
        seen.add(identifier)
        status = entry.get("acquisition")
        if type(status) is not str or status not in {
            "PINNED_NOT_DOWNLOADED_IN_THIS_PASS", "DISCOVERED_NOT_HASH_VERIFIED",
            "SOURCE_PAGE_ONLY", "BLOCKED_NO_LAWFUL_COMPLETE_SAMPLE",
            "VENDORED_SOURCE_VERIFIED",
        }:
            raise LawfulCorpusError("corpus acquisition truth invalid")
        digest = entry.get("sha256")
        if digest is not None and (type(digest) is not str or not _HASH.fullmatch(digest)):
            raise LawfulCorpusError("corpus digest invalid")
        size = entry.get("max_bytes")
        if type(size) is not int or not 0 <= size <= 128 * 1024 * 1024:
            raise LawfulCorpusError("corpus byte limit invalid")
        for key in ("source_page", "download_url"):
            value = entry.get(key)
            if value is not None:
                _https_url(value, source_page=key == "source_page")
        if digest is None and status == "PINNED_NOT_DOWNLOADED_IN_THIS_PASS":
            raise LawfulCorpusError("pinned acquisition requires pinned bytes")
    return tuple(records)


def _https_url(url: object, *, source_page: bool = False) -> str:
    if type(url) is not str or len(url) > 2048:
        raise LawfulCorpusError("source URL invalid")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise LawfulCorpusError("source URL malformed") from exc
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or port not in (None, 443)
        or parsed.fragment or parsed.query
        or parsed.hostname not in (
            {"database.lichess.org", "www.gutenberg.org", "github.com", "shop.chessbase.com", "help.chessbase.com", "ibca-info.org", "s2.chess-results.com", "s1.chess-results.com", "chess-results.com", "www.olimpbase.org", "braillechess.org.uk", "studies.chessbase.com"}
            if source_page else {"database.lichess.org", "www.gutenberg.org", "de.chessbase.com"}
        )
    ):
        raise LawfulCorpusError("source URL must be recognized, credential-free HTTPS")
    return url


def _bounded_source_size(record: dict) -> int:
    """Validate a caller-provided acquisition budget before any file or network I/O.

    Catalog validation is not a substitute: source records may also be provided
    directly by a QA caller. A bool, float('inf') or absent budget must never
    accidentally disable source-size enforcement.
    """
    limit = record.get("max_bytes")
    if type(limit) is not int or not 0 < limit <= 128 * 1024 * 1024:
        raise LawfulCorpusError("source byte limit invalid")
    return limit


def verified_local_source(path: Path, record: dict) -> str:
    max_bytes = _bounded_source_size(record)
    digest = record.get("sha256")
    if type(digest) is not str or not _HASH.fullmatch(digest):
        raise LawfulCorpusError("unverified source has no pinned checksum")
    indexed = record.get("indexed_bytes")
    if indexed is not None and (
        type(indexed) is not int or not 0 < indexed <= max_bytes
    ):
        raise LawfulCorpusError("invalid source byte count in provenance index")
    try:
        before = path.lstat()
        attrs = getattr(before, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            or not 0 < before.st_size <= max_bytes
        ):
            raise LawfulCorpusError("source is not a bounded direct regular file")
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not os.path.samestat(before, opened):
                raise LawfulCorpusError("source was replaced while opening")
            total = 0
            while block := stream.read(_CHUNK):
                total += len(block)
                if total > max_bytes:
                    raise LawfulCorpusError("source grew beyond declared byte bound")
                hasher.update(block)
            opened_after = os.fstat(stream.fileno())
        after = path.lstat()
    except (OSError, ValueError) as exc:
        if isinstance(exc, LawfulCorpusError):
            raise
        raise LawfulCorpusError("source cannot be verified") from exc
    if (
        not os.path.samestat(before, after)
        or not os.path.samestat(before, opened_after)
        or opened_after.st_size != before.st_size
        or (indexed is not None and total != indexed)
        or hasher.hexdigest() != digest
    ):
        raise LawfulCorpusError("source identity or pinned SHA256 mismatch")
    return digest




def read_verified_source_snapshot(path: Path, record: dict) -> bytes:
    """Read exactly the pinned source bytes without a verify/open race.

    Import and format QA must consume this immutable bounded buffer, rather
    than hashing a filename and later doing an unbounded Path.read_bytes().
    The API is not an authorization to redistribute or publish source bytes.
    """
    limit = _bounded_source_size(record)
    digest = record.get("sha256")
    if type(digest) is not str or not _HASH.fullmatch(digest):
        raise LawfulCorpusError("unverified source has no pinned checksum")
    indexed = record.get("indexed_bytes")
    if indexed is not None and (
        type(indexed) is not int or not 0 < indexed <= limit
    ):
        raise LawfulCorpusError("invalid source byte count in provenance index")
    try:
        before = path.lstat()
        attrs = getattr(before, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            or not 0 < before.st_size <= limit
        ):
            raise LawfulCorpusError("source is not a bounded direct regular file")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not os.path.samestat(before, opened):
                raise LawfulCorpusError("source was replaced while opening")
            raw = stream.read(limit + 1)
            opened_after = os.fstat(stream.fileno())
        after = path.lstat()
    except (OSError, ValueError) as exc:
        if isinstance(exc, LawfulCorpusError):
            raise
        raise LawfulCorpusError("source snapshot cannot be verified") from exc
    if (
        not os.path.samestat(before, after)
        or not os.path.samestat(before, opened_after)
        or opened_after.st_size != before.st_size
        or len(raw) != before.st_size
        or (indexed is not None and len(raw) != indexed)
        or hashlib.sha256(raw).hexdigest() != digest
    ):
        raise LawfulCorpusError("consumed source identity or pinned SHA256 mismatch")
    return raw


def iter_bounded_corpus_lines(
    source, *, max_line_chars: int = 128 * 1024,
    max_decoded_chars: int = 64 * 1024 * 1024,
):
    """Limit decompressed PGN framing input before buffering complete games.

    This guards the existing transport record framer (not PGN semantics) from
    malicious or unexpectedly huge decoded lines and records. It is deliberately
    independent of the compression library and reuses the canonical PGN parser.
    """
    if (
        type(max_line_chars) is not int or max_line_chars <= 0
        or type(max_decoded_chars) is not int or max_decoded_chars <= 0
    ):
        raise LawfulCorpusError("decoded corpus limits must be positive integers")
    total = 0
    while True:
        line = source.readline(max_line_chars + 1)
        if not line:
            return
        if type(line) is not str:
            raise LawfulCorpusError("decoded corpus reader must yield text")
        # readline(size) can return an incomplete long physical line.
        # Reject instead of accidentally framing its remainder as a new line.
        if len(line) > max_line_chars or (
            len(line) == max_line_chars
            and not line.endswith(("\n", "\r"))
            and bool(source.read(1))
        ):
            raise LawfulCorpusError("decoded corpus line exceeds resource limit")
        total += len(line)
        if total > max_decoded_chars:
            raise LawfulCorpusError("decoded corpus exceeds resource limit")
        yield line


def acquire_cc0_source(record: dict, cache_dir: Path, *, opener=None) -> Path:
    """Download *only* an explicit CC0 source with known digest; never publish it."""
    max_bytes = _bounded_source_size(record)
    if (
        record.get("license") != "CC0" or record.get("redistribution") != "permitted"
        or record.get("acquisition") != "PINNED_NOT_DOWNLOADED_IN_THIS_PASS"
        or record.get("format") != "pgn.zst"
    ):
        raise LawfulCorpusError("source lacks explicit CC0/format/pinned permission")
    url = _https_url(record.get("download_url"))
    # Discovery catalog may link to copyrighted CBV examples; automatic CC0
    # transfer remains restricted to the authoritative Lichess archive host.
    if urlsplit(url).hostname != "database.lichess.org":
        raise LawfulCorpusError("automatic CC0 acquisition host not authorized")
    digest = record.get("sha256")
    if type(digest) is not str or not _HASH.fullmatch(digest):
        raise LawfulCorpusError("source lacks pinned SHA256")
    identifier = record.get("id")
    if type(identifier) is not str or not _ID.fullmatch(identifier):
        raise LawfulCorpusError("unsafe catalog source identifier")
    if not cache_dir.is_dir() or cache_dir.is_symlink():
        raise LawfulCorpusError("cache must be an existing direct directory")
    destination = cache_dir / (identifier + ".pgn.zst")
    if destination.exists() or destination.is_symlink():
        verified_local_source(destination, record)
        return destination
    temp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".corpus-", suffix=".tmp", dir=cache_dir, delete=False) as output:
            temp = Path(output.name)
            transport = _open_no_redirect if opener is None else opener
            response = transport(Request(url, headers={"User-Agent": "AccessibleChessCorpusQA/1"}), timeout=60)
            with response:
                # Default transport prevents redirects before a second network request.
                # Also reject injected transports that report a changed final endpoint.
                if not hasattr(response, "geturl") or response.geturl() != url:
                    raise LawfulCorpusError("source redirected away from pinned endpoint")
                total = 0
                digest_actual = hashlib.sha256()
                while chunk := response.read(_CHUNK):
                    total += len(chunk)
                    if total > max_bytes:
                        raise LawfulCorpusError("source exceeds declared byte bound")
                    digest_actual.update(chunk)
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if total == 0 or digest_actual.hexdigest() != digest:
            raise LawfulCorpusError("downloaded corpus SHA256 mismatch")
        verified_local_source(temp, record)
        # Exclusive atomic name creation, no overwrite of existing owner data.
        os.link(temp, destination)
        verified_local_source(destination, record)
        return destination
    except (OSError, ValueError) as exc:
        if isinstance(exc, LawfulCorpusError):
            raise
        raise LawfulCorpusError("verified corpus acquisition failed closed") from exc
    finally:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass



def read_verified_zip_member(
    archive_path: Path, record: dict, *, expected_member: str,
    max_unpacked_bytes: int = 16 * 1024 * 1024,
) -> bytes:
    """Bounded, checksum-pinned single-member ZIP reader, never path-extracting.

    This only obtains real test-source bytes. EPD/PGN semantics are delegated
    to the existing canonical format services by later qualification stages.
    """
    if (
        type(expected_member) is not str or not expected_member
        or len(expected_member) > 128
        or expected_member in {".", ".."}
        or "/" in expected_member or "\\" in expected_member
        or any(ord(char) < 0x20 for char in expected_member)
    ):
        raise LawfulCorpusError("ZIP member name must be a safe direct filename")
    if (
        type(max_unpacked_bytes) is not int
        or not 0 < max_unpacked_bytes <= 64 * 1024 * 1024
    ):
        raise LawfulCorpusError("ZIP expansion budget invalid")
    # Verify the exact immutable bytes that the ZIP reader consumes. Merely
    # verifying the path and reopening it permits a file swap after the hash
    # check (a classic check/use race), including a valid but different ZIP.
    verified_local_source(archive_path, record)
    limit = _bounded_source_size(record)
    try:
        with archive_path.open("rb") as stream:
            before = archive_path.lstat()
            opened = os.fstat(stream.fileno())
            attrs = getattr(before, "st_file_attributes", 0)
            if (
                not stat.S_ISREG(before.st_mode)
                or stat.S_ISLNK(before.st_mode)
                or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                or not os.path.samestat(before, opened)
            ):
                raise LawfulCorpusError("ZIP source changed while opening")
            snapshot = stream.read(limit + 1)
            after = archive_path.lstat()
            if (
                not os.path.samestat(before, after)
                or len(snapshot) == 0 or len(snapshot) > limit
                or hashlib.sha256(snapshot).hexdigest() != record["sha256"]
            ):
                raise LawfulCorpusError("ZIP source changed after verification")
    except OSError as exc:
        raise LawfulCorpusError("ZIP source snapshot cannot be read") from exc
    try:
        with zipfile.ZipFile(io.BytesIO(snapshot)) as source:
            members = source.infolist()
            if len(members) != 1:
                raise LawfulCorpusError("ZIP must contain exactly one file")
            member = members[0]
            unix_mode = (member.external_attr >> 16) & 0xFFFF
            if (
                member.filename != expected_member or member.is_dir()
                or (member.flag_bits & 1)
                or stat.S_IFMT(unix_mode) not in (0, stat.S_IFREG)
                or member.file_size <= 0
                or member.file_size > max_unpacked_bytes
            ):
                raise LawfulCorpusError("unsafe or oversized ZIP member")
            with source.open(member, "r") as stream:
                content = stream.read(max_unpacked_bytes + 1)
                if len(content) != member.file_size:
                    raise LawfulCorpusError("ZIP member length mismatch")
                if stream.read(1):
                    raise LawfulCorpusError("ZIP decompression exceeded bound")
            return content
    except LawfulCorpusError:
        raise
    except (OSError, RuntimeError, EOFError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise LawfulCorpusError("verified ZIP cannot be read safely") from exc


def qualify_offline_collection(
    records: tuple[dict, ...], cache_dir: Path, *, distribution: str,
) -> tuple[dict[str, str], ...]:
    """Inventory only; no implicit extraction, UI publication or chess import.

    PUBLIC_RELEASE is strict CC0 verified material only. Owner TEST_BUILD may use
    separately authorized sources outside this routine, never by silently
    changing this third-party rights policy.
    """
    if distribution not in {"TEST_BUILD", "PUBLIC_RELEASE"}:
        raise LawfulCorpusError("offline distribution class invalid")
    output: list[dict[str, str]] = []
    for record in records:
        if (
            record.get("license") != "CC0"
            or record.get("redistribution") != "permitted"
            or record.get("acquisition") != "PINNED_NOT_DOWNLOADED_IN_THIS_PASS"
            or record.get("format") != "pgn.zst"
        ):
            continue
        identifier = record["id"]
        if type(identifier) is not str or not _ID.fullmatch(identifier):
            raise LawfulCorpusError("unsafe offline corpus id")
        candidate = cache_dir / (identifier + ".pgn.zst")
        if not candidate.exists() and not candidate.is_symlink():
            continue
        digest = verified_local_source(candidate, record)
        output.append({
            "source_id": identifier,
            "filename": candidate.name,
            "sha256": digest,
            "distribution": distribution,
            "semantic_state": "VERIFIED_BYTES_NOT_IMPORTED",
        })
    return tuple(sorted(output, key=lambda item: item["source_id"]))


def _vendored_asset_path(repository_root: Path, relative: object) -> Path:
    """Locate only direct, non-reparse fixtures in tests/real_corpus.

    Catalog text never grants permission to traverse outside the fixture root,
    including through a symlinked intermediate directory on Unix or a Windows
    reparse point. This helper does not copy or publish owner-owned material.
    """
    from pathlib import PurePosixPath

    if type(relative) is not str or not relative or "\\" in relative or ":" in relative:
        raise LawfulCorpusError("vendored corpus path invalid")
    segments = relative.split("/")
    if (
        len(segments) < 3
        or segments[:2] != ["tests", "real_corpus"]
        or any(part in ("", ".", "..") for part in segments)
        or PurePosixPath(relative).is_absolute()
    ):
        raise LawfulCorpusError("vendored corpus path escapes fixture root")
    path = repository_root
    for part in segments:
        path = path / part
        try:
            info = path.lstat()
        except OSError as exc:
            raise LawfulCorpusError("vendored corpus path cannot be inspected") from exc
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise LawfulCorpusError("vendored corpus path is indirect")
    if not stat.S_ISREG(info.st_mode):
        raise LawfulCorpusError("vendored corpus asset must be regular")
    return path


def inventory_vendored_corpus(
    records: tuple[dict, ...], repository_root: Path, *, distribution: str,
) -> tuple[dict[str, str | int], ...]:
    """Verify genuine local CC0 source and license bytes for a *non-copying* index.

    The result is evidence of bytes only, not semantic chess import or a
    redistributable release package. A PUBLIC_RELEASE inventory conservatively
    permits only exact CC0/permitted records; qualified TEST_BUILD inventories
    may include other explicitly declared upstream CC0 variants. A
    NOT_CLEARED book/CBV is never automatically repackaged.
    """
    if distribution not in {"TEST_BUILD", "PUBLIC_RELEASE"}:
        raise LawfulCorpusError("offline distribution class invalid")
    if not repository_root.is_dir() or repository_root.is_symlink():
        raise LawfulCorpusError("corpus root must be direct")
    output: list[dict[str, str | int]] = []
    seen: set[str] = set()
    for entry in records:
        if type(entry) is not dict or entry.get("acquisition") != "VENDORED_SOURCE_VERIFIED":
            continue
        license_name = entry.get("license")
        rights = entry.get("redistribution")
        if (
            type(license_name) is not str or not license_name.startswith("CC0")
            or type(rights) is not str or not rights.startswith("permitted")
        ):
            continue
        if distribution == "PUBLIC_RELEASE" and (license_name != "CC0" or rights != "permitted"):
            continue
        source_id = entry.get("id")
        if type(source_id) is not str or not _ID.fullmatch(source_id) or source_id in seen:
            raise LawfulCorpusError("vendored corpus ID invalid or duplicate")
        seen.add(source_id)
        if (
            type(entry.get("indexed_bytes")) is not int
            or not 0 < entry["indexed_bytes"] <= _bounded_source_size(entry)
        ):
            raise LawfulCorpusError("vendored source provenance size invalid")
        expected_license = entry.get("license_sha256")
        if type(expected_license) is not str or not _HASH.fullmatch(expected_license):
            raise LawfulCorpusError("vendored corpus license is not hash-pinned")
        source_path = _vendored_asset_path(repository_root, entry.get("local_source"))
        license_path = _vendored_asset_path(repository_root, entry.get("license_source"))
        source_digest = verified_local_source(source_path, entry)
        verified_local_source(
            license_path,
            {"sha256": expected_license, "max_bytes": 1024 * 1024},
        )
        output.append({
            "source_id": source_id,
            "relative_path": entry["local_source"],
            "format": str(entry.get("format", "")),
            "sha256": source_digest,
            "bytes": entry["indexed_bytes"],
            "license_sha256": expected_license,
            "distribution": distribution,
            "semantic_state": "VERIFIED_BYTES_NOT_IMPORTED",
        })
    return tuple(sorted(output, key=lambda item: item["source_id"]))
