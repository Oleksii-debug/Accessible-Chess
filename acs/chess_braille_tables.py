from __future__ import annotations

"""Local conservative SHA-256 inventory for Liblouis translation table includes.

An inventory is NOT a certification of translation semantics or proof of the
actual Liblouis table resolver. Reject ambiguous/escaped include paths.
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

from .chess_braille_factory import BrailleFactoryError

MAX_TABLE_FILES = 128
MAX_TABLE_FILE_BYTES = 2 * 1024 * 1024
MAX_TABLE_CLOSURE_BYTES = 16 * 1024 * 1024
_INCLUDE_OPCODE = re.compile(r"^include\s+(\S+)\s*(?:#.*)?$")


# A local POSIX inventory must not attest a dependency graph that Win32 could
# interpret as a device, an alternate file or an invalid path. These constraints
# apply to every path prefix, including the main table, before filesystem IO.
# Reference: Microsoft Learn, "Naming Files, Paths, and Namespaces".
_WINDOWS_DISALLOWED = frozenset('<>:"\\|?*')
_WINDOWS_DEVICE_STEMS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"{prefix}{digit}" for prefix in ("com", "lpt")
       for digit in "123456789¹²³"}
)


def _reject_nonportable_component(component: str) -> None:
    stem = component.split(".", 1)[0].rstrip(" ").casefold()
    if (
        not component or component in (".", "..")
        or component.endswith((".", " "))
        or stem in _WINDOWS_DEVICE_STEMS
        or any(ord(char) < 32 or char in _WINDOWS_DISALLOWED
               for char in component)
    ):
        raise BrailleFactoryError("Nonportable Windows Liblouis table path component")



@dataclass(frozen=True, slots=True)
class LocalTableClosure:
    files: tuple[tuple[str, str], ...]
    closure_sha256: str
    total_bytes: int
    status: str = "LOCAL_PIN_ONLY_NOT_LANGUAGE_CERTIFICATION"


def scan_local_liblouis_table_closure(path: Path) -> LocalTableClosure:
    """Fingerprint UTF-8 local main table and every unambiguous include file.

    This only permits local relative includes staying inside the main-table
    directory. It refuses symlinks, cycles, duplicate unresolved include
    spellings, UTF-16/binary tables and external path lookups.
    """
    if not isinstance(path, Path):
        raise BrailleFactoryError("Local Liblouis table path must be a Path")
    if path.is_symlink() or not path.is_file():
        raise BrailleFactoryError("Main Liblouis table is not a regular local file")
    root_dir = path.parent.resolve(strict=True)
    try:
        main = path.resolve(strict=True)
    except OSError as exc:
        raise BrailleFactoryError("Main table cannot be resolved safely") from exc
    if main.parent != root_dir or "," in str(main):
        raise BrailleFactoryError("Liblouis main table path is ambiguous")
    visited: dict[str, bytes] = {}
    visiting: set[str] = set()
    # Every file *and directory prefix* has one portable spelling. On common
    # Windows filesystems, differing case can resolve to the same resource,
    # while on Linux they can identify distinct files. Never attest a table
    # closure whose include graph has such cross-platform ambiguity.
    portable_spellings: dict[str, str] = {}
    total = 0

    def visit(file: Path) -> None:
        nonlocal total
        # Checking only the final component misses symlinked directories that
        # resolve to another location *within* the pinned tree.  Such an alias
        # makes the include dependency identity ambiguous across machines.
        try:
            relative_unresolved = file.relative_to(root_dir)
        except ValueError as exc:
            raise BrailleFactoryError("Liblouis include leaves pinned local table root") from exc
        # Use unresolved spelling before Path.resolve() can erase a case alias.
        # Prefix checks also reject A/x.cti alongside a/y.cti, which would
        # otherwise combine different directories on case-insensitive hosts.
        prefixes = tuple("/".join(relative_unresolved.parts[:depth])
                         for depth in range(1, len(relative_unresolved.parts) + 1))
        for spelling in prefixes:
            existing = portable_spellings.get(spelling.casefold())
            if existing is not None and existing != spelling:
                raise BrailleFactoryError("Ambiguous case-insensitive Liblouis include alias")
        cursor = root_dir
        for component in relative_unresolved.parts:
            _reject_nonportable_component(component)
            cursor = cursor / component
            if cursor.is_symlink():
                raise BrailleFactoryError("Symlink in Liblouis include path is forbidden")
        if file.is_symlink() or not file.is_file():
            raise BrailleFactoryError("Included Liblouis table is missing, linked or nonregular")
        try:
            resolved = file.resolve(strict=True)
            relative = resolved.relative_to(root_dir).as_posix()
        except (ValueError, OSError) as exc:
            raise BrailleFactoryError("Liblouis include leaves pinned local table root") from exc
        if relative in visiting:
            raise BrailleFactoryError("Cyclic Liblouis table includes are unsupported")
        if relative in visited:
            return
        # Reserve names prior to recursion so a nested include cannot use a
        # case-variant spelling of a parent that is still being scanned.
        for spelling in prefixes:
            portable_spellings[spelling.casefold()] = spelling
        if len(visited) + len(visiting) >= MAX_TABLE_FILES:
            raise BrailleFactoryError("Liblouis table file count exceeded")
        with resolved.open("rb") as handle:
            raw = handle.read(MAX_TABLE_FILE_BYTES + 1)
        if len(raw) > MAX_TABLE_FILE_BYTES:
            raise BrailleFactoryError("Liblouis table file exceeds provisional input limit")
        total += len(raw)
        if total > MAX_TABLE_CLOSURE_BYTES:
            raise BrailleFactoryError("Liblouis dependency closure exceeds provisional size limit")
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise BrailleFactoryError("Only explicit UTF-8 local tables can be pinned") from exc
        # Python splitlines() also treats VT, FF, NEL and Unicode separators
        # as line breaks.  Liblouis table-line parsing is not certified
        # equivalent, so reject these ambiguous bytes rather than silently
        # inventing new include directives.  LF and CRLF remain supported.
        if ("\r" in content.replace("\r\n", "")
                or any(marker in content for marker in (
                    "\x00", "\v", "\f", "\x1c", "\x1d", "\x1e",
                    "\x85", "\u2028", "\u2029",
                ))):
            raise BrailleFactoryError("Unsafe Liblouis table line separator or control")
        visiting.add(relative)
        try:
            for line in content.splitlines():
                candidate = line.strip()
                # Python's Unicode strip()/\\s accept NBSP, EM SPACE and
                # other non-ASCII whitespace that an external Liblouis table
                # parser has not been proven to interpret as include syntax.
                # Never inventory an include through that lexical ambiguity.
                if candidate.lower().startswith("include") and any(
                    character.isspace() and character not in (" ", "\t")
                    for character in line
                ):
                    raise BrailleFactoryError(
                        "Ambiguous Unicode whitespace in Liblouis include directive"
                    )
                if not candidate or candidate.startswith("#") or candidate.startswith("<"):
                    continue
                if candidate.split(None, 1)[0].lower() != "include":
                    continue
                matched = _INCLUDE_OPCODE.fullmatch(candidate)
                if matched is None:
                    raise BrailleFactoryError("Ambiguous Liblouis include directive")
                operand = matched.group(1)
                # Validate the raw spelling before pathlib normalizes away
                # lexical aliases such as "./" and doubled "/" separators.
                # An inventory must never silently pin a different spelling
                # from the input consumed by an external Liblouis resolver.
                if any(part in ("", ".", "..") for part in operand.split("/")):
                    raise BrailleFactoryError("Unsafe Liblouis include target")
                subpath = Path(operand)
                # A backslash or colon can mean a path separator, drive,
                # or alternate stream on Windows while resolving differently
                # on POSIX.  Use portable, single-identity include paths.
                if (subpath.is_absolute() or "," in operand
                        or "\\" in operand or ":" in operand
                        or any(part in ("", ".", "..") for part in subpath.parts)):
                    raise BrailleFactoryError("Unsafe Liblouis include target")
                visit(resolved.parent / subpath)
        finally:
            visiting.remove(relative)
        visited[relative] = raw

    visit(main)
    digest = sha256(b"section55-liblouis-closure-v1\0")
    for name in sorted(visited):
        encoded_name = name.encode("utf-8")
        raw = visited[name]
        digest.update(len(encoded_name).to_bytes(4, "big"))
        digest.update(encoded_name)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return LocalTableClosure(
        files=tuple((name, sha256(visited[name]).hexdigest())
                    for name in sorted(visited)),
        closure_sha256=digest.hexdigest(),
        total_bytes=total,
    )
