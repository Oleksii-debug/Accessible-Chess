from __future__ import annotations

"""Hash-pinned acquisition of lawful test assets; NOT a format/chess parser.

Only one explicit trusted, HTTPS, CC0-pinned source may be downloaded automatically.
Unverified books, proprietary ChessBase archives and user-owned files are catalog
entries, not assumed distribution rights or fabricated import PASS results.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
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
    if type(data) is not dict or data.get("schema_version") != 1 or type(data.get("sources")) is not list:
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
                _https_url(value)
        if digest is None and status == "PINNED_NOT_DOWNLOADED_IN_THIS_PASS":
            raise LawfulCorpusError("pinned acquisition requires pinned bytes")
    return tuple(records)


def _https_url(url: object) -> str:
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
        or parsed.hostname not in {"database.lichess.org", "www.gutenberg.org"}
    ):
        raise LawfulCorpusError("source URL must be recognized, credential-free HTTPS")
    return url


def verified_local_source(path: Path, record: dict) -> str:
    digest = record.get("sha256")
    if type(digest) is not str or not _HASH.fullmatch(digest):
        raise LawfulCorpusError("unverified source has no pinned checksum")
    try:
        before = path.lstat()
        attrs = getattr(before, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            or not 0 < before.st_size <= record["max_bytes"]
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
                if total > record["max_bytes"]:
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
        or hasher.hexdigest() != digest
    ):
        raise LawfulCorpusError("source identity or pinned SHA256 mismatch")
    return digest


def acquire_cc0_source(record: dict, cache_dir: Path, *, opener=None) -> Path:
    """Download *only* an explicit CC0 source with known digest; never publish it."""
    if (
        record.get("license") != "CC0" or record.get("redistribution") != "permitted"
        or record.get("acquisition") != "PINNED_NOT_DOWNLOADED_IN_THIS_PASS"
        or record.get("format") != "pgn.zst"
    ):
        raise LawfulCorpusError("source lacks explicit CC0/format/pinned permission")
    url = _https_url(record.get("download_url"))
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
                    if total > record["max_bytes"]:
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
