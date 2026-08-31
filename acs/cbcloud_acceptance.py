from __future__ import annotations

"""Fail-closed semantic acceptance harness for future CBCLOUD reader candidates.

CBCLOUD is evidence-qualified only as a four-file local database family.  The
companion suffixes and binary roles are intentionally *not* encoded here.  A
future real acceptance run must bind the exact four lawful source files by
filename and SHA-256, pin an independently licensed reader, and compare its
canonical output with an independent PGN oracle.

This module does not decode CBCLOUD, does not register a runtime importer, does
not contact ChessBase cloud services, and cannot promote Product support.
Synthetic tests exercise only the acceptance machinery.
"""

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
import re
from typing import Callable, Iterable

from .game_identity import identity_for_game
from .gametree import PgnGame, parse_games, serialize_games
from .gametree_legality import validate_game_legality
from .import_contract import SourceFingerprint, fingerprint


CBCLOUD_PRIMARY_SUFFIX = ".cbcloud"
CBCLOUD_FAMILY_FILE_COUNT = 4
CBCLOUD_ACCEPTANCE_PROTOCOL = "accessible-chess-cbcloud-acceptance-v1"
MAX_ACCEPTANCE_GAMES = 100_000
MAX_ORACLE_PGN_BYTES = 64 * 1024 * 1024
_MAX_FILENAME_CHARS = 255
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CbcloudAcceptanceCode(str, Enum):
    WRONG_SOURCE = "wrong_source"
    SOURCE_CHANGED = "source_changed"
    BACKEND_FAILED = "backend_failed"
    RESOURCE_LIMIT = "resource_limit"
    INVALID_DECODED_DATABASE = "invalid_decoded_database"
    ILLEGAL_GAME = "illegal_game"
    INVALID_ORACLE = "invalid_oracle"
    ORACLE_MISMATCH = "oracle_mismatch"
    ROUNDTRIP_MISMATCH = "roundtrip_mismatch"


class CbcloudAcceptanceError(RuntimeError):
    def __init__(self, message: str, *, code: CbcloudAcceptanceCode) -> None:
        super().__init__(message)
        self.code = CbcloudAcceptanceCode(code)


def _bounded_text(value: object, label: str, maximum: int = 2048) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be non-empty bounded text")
    return value


def _https_reference(value: object, label: str) -> str:
    text = _bounded_text(value, label)
    if not text.startswith("https://"):
        raise ValueError(f"{label} must be an https reference")
    return text


def _leaf_filename(value: object) -> str:
    name = _bounded_text(value, "family filename", _MAX_FILENAME_CHARS)
    if name in {".", ".."} or Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("family filename must be a single leaf name")
    return name


@dataclass(frozen=True, slots=True)
class CbcloudFamilyMemberEvidence:
    """Identity of one exact file in one real CBCLOUD acceptance family.

    No semantic role is carried: current evidence does not qualify companion
    suffix roles.  This object binds only exact bytes and exact filename.
    """

    filename: str
    sha256: str

    def __post_init__(self) -> None:
        _leaf_filename(self.filename)
        if type(self.sha256) is not str or _SHA256_RE.fullmatch(self.sha256) is None:
            raise ValueError("family member sha256 must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class CbcloudAcceptanceManifest:
    """Evidence required before a future CBCLOUD reader may be qualified.

    The four filenames are exact evidence for one acceptance corpus, not a
    normative universal companion map.  Product support remains separately
    gated after a real semantic run passes.
    """

    backend_name: str
    backend_commit: str
    backend_license_spdx: str
    backend_license_reference: str
    family_members: tuple[CbcloudFamilyMemberEvidence, ...]
    family_rights_reference: str
    family_automated_use_permitted: bool
    oracle_pgn_sha256: str
    oracle_provenance_reference: str
    expected_game_count: int
    protocol_id: str = CBCLOUD_ACCEPTANCE_PROTOCOL

    def __post_init__(self) -> None:
        _bounded_text(self.backend_name, "backend_name", 128)
        if type(self.backend_commit) is not str or _SHA40_RE.fullmatch(self.backend_commit) is None:
            raise ValueError("backend_commit must be a lowercase 40-hex commit")
        _bounded_text(self.backend_license_spdx, "backend_license_spdx", 128)
        _https_reference(self.backend_license_reference, "backend_license_reference")
        if type(self.family_members) is not tuple or len(self.family_members) != CBCLOUD_FAMILY_FILE_COUNT:
            raise ValueError("CBCLOUD acceptance requires exactly four manifest-bound files")
        if not all(isinstance(member, CbcloudFamilyMemberEvidence) for member in self.family_members):
            raise TypeError("family_members must contain CbcloudFamilyMemberEvidence values")
        folded = [member.filename.casefold() for member in self.family_members]
        if len(set(folded)) != CBCLOUD_FAMILY_FILE_COUNT:
            raise ValueError("CBCLOUD acceptance family filenames must be case-insensitively unique")
        primaries = [
            member
            for member in self.family_members
            if Path(member.filename).suffix.lower() == CBCLOUD_PRIMARY_SUFFIX
        ]
        if len(primaries) != 1:
            raise ValueError("CBCLOUD acceptance requires exactly one .cbcloud primary member")
        _https_reference(self.family_rights_reference, "family_rights_reference")
        if type(self.family_automated_use_permitted) is not bool or not self.family_automated_use_permitted:
            raise ValueError("family_automated_use_permitted must be explicitly true")
        if type(self.oracle_pgn_sha256) is not str or _SHA256_RE.fullmatch(self.oracle_pgn_sha256) is None:
            raise ValueError("oracle_pgn_sha256 must be a lowercase SHA-256 digest")
        _https_reference(self.oracle_provenance_reference, "oracle_provenance_reference")
        if type(self.expected_game_count) is not int or not 1 <= self.expected_game_count <= MAX_ACCEPTANCE_GAMES:
            raise ValueError("expected_game_count is outside the supported bound")
        if self.protocol_id != CBCLOUD_ACCEPTANCE_PROTOCOL:
            raise ValueError("unsupported CBCLOUD acceptance protocol")


@dataclass(frozen=True, slots=True)
class CbcloudAcceptanceReport:
    """Evidence from one passed CBCLOUD semantic acceptance run.

    Deliberately exposes neither ``safe_to_import`` nor ``supported``.
    """

    family: tuple[SourceFingerprint, ...]
    backend_name: str
    backend_commit: str
    backend_license_spdx: str
    oracle_pgn_sha256: str
    game_count: int
    record_digests: tuple[str, ...]
    roundtrip_record_digests: tuple[str, ...]


CbcloudDecoderCandidate = Callable[[tuple[Path, ...]], Iterable[PgnGame]]


def _same_source(left: SourceFingerprint, right: SourceFingerprint) -> bool:
    return (
        Path(left.path).absolute() == Path(right.path).absolute()
        and left.size == right.size
        and left.sha256 == right.sha256
        and left.suffix.lower() == right.suffix.lower()
    )


def _family_paths(primary: Path, manifest: CbcloudAcceptanceManifest) -> tuple[Path, ...]:
    if primary.suffix.lower() != CBCLOUD_PRIMARY_SUFFIX:
        raise CbcloudAcceptanceError(
            "CBCLOUD semantic acceptance requires an exact .cbcloud primary source",
            code=CbcloudAcceptanceCode.WRONG_SOURCE,
        )
    primary_member = next(
        member
        for member in manifest.family_members
        if Path(member.filename).suffix.lower() == CBCLOUD_PRIMARY_SUFFIX
    )
    if primary.name.casefold() != primary_member.filename.casefold():
        raise CbcloudAcceptanceError(
            "CBCLOUD primary filename does not match the acceptance manifest",
            code=CbcloudAcceptanceCode.WRONG_SOURCE,
        )
    return tuple(primary.parent / member.filename for member in manifest.family_members)


def _fingerprint_manifest_family(
    paths: tuple[Path, ...],
    manifest: CbcloudAcceptanceManifest,
) -> tuple[SourceFingerprint, ...]:
    fingerprints: list[SourceFingerprint] = []
    for path, member in zip(paths, manifest.family_members, strict=True):
        try:
            observed = fingerprint(path)
        except (OSError, ValueError, RuntimeError) as exc:
            raise CbcloudAcceptanceError(
                "CBCLOUD acceptance family could not be fingerprinted safely",
                code=CbcloudAcceptanceCode.WRONG_SOURCE,
            ) from exc
        if observed.sha256 != member.sha256 or Path(observed.path).name.casefold() != member.filename.casefold():
            raise CbcloudAcceptanceError(
                "CBCLOUD family identity does not match the acceptance manifest",
                code=CbcloudAcceptanceCode.WRONG_SOURCE,
            )
        fingerprints.append(observed)
    return tuple(fingerprints)


def _verify_family_unchanged(
    before: tuple[SourceFingerprint, ...],
    paths: tuple[Path, ...],
) -> tuple[SourceFingerprint, ...]:
    after: list[SourceFingerprint] = []
    for previous, path in zip(before, paths, strict=True):
        try:
            current = fingerprint(path)
        except (OSError, ValueError, RuntimeError) as exc:
            raise CbcloudAcceptanceError(
                "CBCLOUD family could not be verified after candidate decoding",
                code=CbcloudAcceptanceCode.SOURCE_CHANGED,
            ) from exc
        if not _same_source(previous, current):
            raise CbcloudAcceptanceError(
                "CBCLOUD family bytes changed during candidate decoding",
                code=CbcloudAcceptanceCode.SOURCE_CHANGED,
            )
        after.append(current)
    return tuple(after)


def _collect_candidate_games(value: object) -> tuple[PgnGame, ...]:
    if isinstance(value, (str, bytes, bytearray, dict)):
        raise CbcloudAcceptanceError(
            "CBCLOUD candidate reader must return an iterable of canonical PgnGame values",
            code=CbcloudAcceptanceCode.INVALID_DECODED_DATABASE,
        )
    try:
        iterator = iter(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise CbcloudAcceptanceError(
            "CBCLOUD candidate reader returned a non-iterable result",
            code=CbcloudAcceptanceCode.INVALID_DECODED_DATABASE,
        ) from exc

    games: list[PgnGame] = []
    for item in iterator:
        if len(games) >= MAX_ACCEPTANCE_GAMES:
            raise CbcloudAcceptanceError(
                "CBCLOUD candidate reader exceeded the acceptance game-count limit",
                code=CbcloudAcceptanceCode.RESOURCE_LIMIT,
            )
        if not isinstance(item, PgnGame):
            raise CbcloudAcceptanceError(
                "CBCLOUD candidate reader returned a non-canonical game value",
                code=CbcloudAcceptanceCode.INVALID_DECODED_DATABASE,
            )
        games.append(item)
    return tuple(games)


def _require_canonical_games(
    games: tuple[PgnGame, ...],
    *,
    label: str,
    code: CbcloudAcceptanceCode,
) -> tuple[str, ...]:
    digests: list[str] = []
    for index, game in enumerate(games):
        if type(game.source_index) is not int or game.source_index != index:
            raise CbcloudAcceptanceError(
                f"{label} game source indexes are not contiguous",
                code=code,
            )
        legality = validate_game_legality(game)
        if not legality.complete:
            raise CbcloudAcceptanceError(
                f"{label} contains a game that canonical legality cannot replay completely",
                code=CbcloudAcceptanceCode.ILLEGAL_GAME if label == "decoded database" else code,
            )
        try:
            digests.append(identity_for_game(game).record_digest)
        except (TypeError, ValueError, RuntimeError) as exc:
            raise CbcloudAcceptanceError(
                f"{label} contains an invalid canonical GameTree",
                code=code,
            ) from exc
    return tuple(digests)


def qualify_cbcloud_candidate(
    primary: str | Path,
    manifest: CbcloudAcceptanceManifest,
    reader: CbcloudDecoderCandidate,
    *,
    oracle_pgn: str,
) -> CbcloudAcceptanceReport:
    """Qualify one future CBCLOUD reader against exact four-file evidence.

    The manifest names exactly four files for *one* acceptance corpus without
    asserting universal companion roles.  All four are fingerprinted before
    reader execution and re-fingerprinted afterward.  Reader output must already
    be canonical ``PgnGame`` values and must match an independently hashed PGN
    oracle by canonical record identity, then survive canonical export/reopen.
    """

    if not isinstance(manifest, CbcloudAcceptanceManifest):
        raise TypeError("manifest must be a CbcloudAcceptanceManifest")
    if not callable(reader):
        raise TypeError("reader must be callable")
    if type(oracle_pgn) is not str:
        raise TypeError("oracle_pgn must be text")

    primary_path = Path(primary)
    family_paths = _family_paths(primary_path, manifest)
    before = _fingerprint_manifest_family(family_paths, manifest)

    oracle_bytes = oracle_pgn.encode("utf-8")
    if len(oracle_bytes) > MAX_ORACLE_PGN_BYTES:
        raise CbcloudAcceptanceError(
            "CBCLOUD independent PGN oracle exceeds the acceptance size limit",
            code=CbcloudAcceptanceCode.RESOURCE_LIMIT,
        )
    if sha256(oracle_bytes).hexdigest() != manifest.oracle_pgn_sha256:
        raise CbcloudAcceptanceError(
            "CBCLOUD independent PGN oracle identity does not match the manifest",
            code=CbcloudAcceptanceCode.INVALID_ORACLE,
        )

    try:
        candidate_value = reader(tuple(Path(item.path) for item in before))
        decoded_games = _collect_candidate_games(candidate_value)
    except CbcloudAcceptanceError:
        _verify_family_unchanged(before, family_paths)
        raise
    except Exception as exc:
        _verify_family_unchanged(before, family_paths)
        raise CbcloudAcceptanceError(
            "CBCLOUD candidate reader failed during semantic acceptance",
            code=CbcloudAcceptanceCode.BACKEND_FAILED,
        ) from exc
    _verify_family_unchanged(before, family_paths)

    if len(decoded_games) != manifest.expected_game_count:
        raise CbcloudAcceptanceError(
            "CBCLOUD candidate decoded game count differs from the acceptance manifest",
            code=CbcloudAcceptanceCode.ORACLE_MISMATCH,
        )
    decoded_digests = _require_canonical_games(
        decoded_games,
        label="decoded database",
        code=CbcloudAcceptanceCode.INVALID_DECODED_DATABASE,
    )

    try:
        oracle_games = tuple(parse_games(oracle_pgn))
    except Exception as exc:
        raise CbcloudAcceptanceError(
            "CBCLOUD independent PGN oracle could not be parsed",
            code=CbcloudAcceptanceCode.INVALID_ORACLE,
        ) from exc
    if len(oracle_games) != manifest.expected_game_count:
        raise CbcloudAcceptanceError(
            "CBCLOUD independent PGN oracle game count differs from the manifest",
            code=CbcloudAcceptanceCode.INVALID_ORACLE,
        )
    oracle_digests = _require_canonical_games(
        oracle_games,
        label="independent oracle",
        code=CbcloudAcceptanceCode.INVALID_ORACLE,
    )
    if decoded_digests != oracle_digests:
        raise CbcloudAcceptanceError(
            "CBCLOUD decoded canonical records differ from the independent PGN oracle",
            code=CbcloudAcceptanceCode.ORACLE_MISMATCH,
        )

    try:
        reopened_games = tuple(parse_games(serialize_games(decoded_games)))
    except Exception as exc:
        raise CbcloudAcceptanceError(
            "CBCLOUD decoded GameTrees failed canonical PGN export/reopen",
            code=CbcloudAcceptanceCode.ROUNDTRIP_MISMATCH,
        ) from exc
    if len(reopened_games) != len(decoded_games):
        raise CbcloudAcceptanceError(
            "CBCLOUD canonical PGN export/reopen changed the game count",
            code=CbcloudAcceptanceCode.ROUNDTRIP_MISMATCH,
        )
    roundtrip_digests = _require_canonical_games(
        reopened_games,
        label="PGN reopen",
        code=CbcloudAcceptanceCode.ROUNDTRIP_MISMATCH,
    )
    if roundtrip_digests != decoded_digests:
        raise CbcloudAcceptanceError(
            "CBCLOUD canonical PGN export/reopen changed semantic record identity",
            code=CbcloudAcceptanceCode.ROUNDTRIP_MISMATCH,
        )

    return CbcloudAcceptanceReport(
        family=before,
        backend_name=manifest.backend_name,
        backend_commit=manifest.backend_commit,
        backend_license_spdx=manifest.backend_license_spdx,
        oracle_pgn_sha256=manifest.oracle_pgn_sha256,
        game_count=len(decoded_games),
        record_digests=decoded_digests,
        roundtrip_record_digests=roundtrip_digests,
    )
