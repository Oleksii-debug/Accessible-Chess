from __future__ import annotations

"""Fail-closed semantic acceptance harness for future CBONE decoder candidates.

This module deliberately does *not* decode CBONE and does not register a runtime
importer.  It closes the evidence/acceptance seam that a future independently
qualified decoder must pass before Product support can be considered.

The harness binds four independent facts to one exact run:

* lawful automated use of the exact source bytes;
* a pinned backend identity and license;
* an independent PGN oracle for those exact bytes;
* canonical GameTree legality, identity and PGN export/reopen equivalence.

Synthetic tests may exercise this harness, but synthetic data can never promote
CBONE capability status.  Runtime support remains blocked until a real corpus,
reader and oracle satisfy the manifest and the wider Library/Windows gates.
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


CBONE_SUFFIX = ".cbone"
CBONE_ACCEPTANCE_PROTOCOL = "accessible-chess-cbone-acceptance-v1"
MAX_ACCEPTANCE_GAMES = 100_000
MAX_ORACLE_PGN_BYTES = 64 * 1024 * 1024
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CboneAcceptanceCode(str, Enum):
    WRONG_SOURCE = "wrong_source"
    SOURCE_CHANGED = "source_changed"
    BACKEND_FAILED = "backend_failed"
    RESOURCE_LIMIT = "resource_limit"
    INVALID_DECODED_DATABASE = "invalid_decoded_database"
    ILLEGAL_GAME = "illegal_game"
    INVALID_ORACLE = "invalid_oracle"
    ORACLE_MISMATCH = "oracle_mismatch"
    ROUNDTRIP_MISMATCH = "roundtrip_mismatch"


class CboneAcceptanceError(RuntimeError):
    def __init__(self, message: str, *, code: CboneAcceptanceCode) -> None:
        super().__init__(message)
        self.code = CboneAcceptanceCode(code)


def _bounded_text(value: object, label: str, maximum: int = 2048) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be non-empty bounded text")
    return value


def _https_reference(value: object, label: str) -> str:
    text = _bounded_text(value, label)
    if not text.startswith("https://"):
        raise ValueError(f"{label} must be an https reference")
    return text


@dataclass(frozen=True, slots=True)
class CboneAcceptanceManifest:
    """Evidence that must exist before a decoder candidate may be qualified.

    This is not a support flag.  It is an immutable acceptance-run manifest.
    Product support still requires explicit integration/Library/Windows gates
    after a real run passes.
    """

    backend_name: str
    backend_commit: str
    backend_license_spdx: str
    backend_license_reference: str
    source_sha256: str
    source_rights_reference: str
    source_automated_use_permitted: bool
    oracle_pgn_sha256: str
    oracle_provenance_reference: str
    expected_game_count: int
    protocol_id: str = CBONE_ACCEPTANCE_PROTOCOL

    def __post_init__(self) -> None:
        _bounded_text(self.backend_name, "backend_name", 128)
        if type(self.backend_commit) is not str or _SHA40_RE.fullmatch(self.backend_commit) is None:
            raise ValueError("backend_commit must be a lowercase 40-hex commit")
        _bounded_text(self.backend_license_spdx, "backend_license_spdx", 128)
        _https_reference(self.backend_license_reference, "backend_license_reference")
        if type(self.source_sha256) is not str or _SHA256_RE.fullmatch(self.source_sha256) is None:
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        _https_reference(self.source_rights_reference, "source_rights_reference")
        if type(self.source_automated_use_permitted) is not bool or not self.source_automated_use_permitted:
            raise ValueError("source_automated_use_permitted must be explicitly true")
        if type(self.oracle_pgn_sha256) is not str or _SHA256_RE.fullmatch(self.oracle_pgn_sha256) is None:
            raise ValueError("oracle_pgn_sha256 must be a lowercase SHA-256 digest")
        _https_reference(self.oracle_provenance_reference, "oracle_provenance_reference")
        if type(self.expected_game_count) is not int or not 1 <= self.expected_game_count <= MAX_ACCEPTANCE_GAMES:
            raise ValueError("expected_game_count is outside the supported bound")
        if self.protocol_id != CBONE_ACCEPTANCE_PROTOCOL:
            raise ValueError("unsupported CBONE acceptance protocol")


@dataclass(frozen=True, slots=True)
class CboneAcceptanceReport:
    """Machine evidence from one passed semantic acceptance run.

    Deliberately no ``safe_to_import`` or ``supported`` property is exposed.
    Passing this harness is necessary but not sufficient for Product activation.
    """

    source: SourceFingerprint
    backend_name: str
    backend_commit: str
    backend_license_spdx: str
    oracle_pgn_sha256: str
    game_count: int
    record_digests: tuple[str, ...]
    roundtrip_record_digests: tuple[str, ...]


CboneDecoderCandidate = Callable[[Path], Iterable[PgnGame]]


def _same_source(left: SourceFingerprint, right: SourceFingerprint) -> bool:
    return (
        Path(left.path).absolute() == Path(right.path).absolute()
        and left.size == right.size
        and left.sha256 == right.sha256
        and left.suffix.lower() == right.suffix.lower()
    )


def _collect_candidate_games(value: object) -> tuple[PgnGame, ...]:
    if isinstance(value, (str, bytes, bytearray, dict)):
        raise CboneAcceptanceError(
            "CBONE candidate decoder must return an iterable of canonical PgnGame values",
            code=CboneAcceptanceCode.INVALID_DECODED_DATABASE,
        )
    try:
        iterator = iter(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise CboneAcceptanceError(
            "CBONE candidate decoder returned a non-iterable result",
            code=CboneAcceptanceCode.INVALID_DECODED_DATABASE,
        ) from exc

    games: list[PgnGame] = []
    for item in iterator:
        if len(games) >= MAX_ACCEPTANCE_GAMES:
            raise CboneAcceptanceError(
                "CBONE candidate decoder exceeded the acceptance game-count limit",
                code=CboneAcceptanceCode.RESOURCE_LIMIT,
            )
        if not isinstance(item, PgnGame):
            raise CboneAcceptanceError(
                "CBONE candidate decoder returned a non-canonical game value",
                code=CboneAcceptanceCode.INVALID_DECODED_DATABASE,
            )
        games.append(item)
    return tuple(games)


def _require_canonical_games(
    games: tuple[PgnGame, ...],
    *,
    label: str,
    code: CboneAcceptanceCode,
) -> tuple[str, ...]:
    digests: list[str] = []
    for index, game in enumerate(games):
        if type(game.source_index) is not int or game.source_index != index:
            raise CboneAcceptanceError(
                f"{label} game source indexes are not contiguous",
                code=code,
            )
        legality = validate_game_legality(game)
        if not legality.complete:
            raise CboneAcceptanceError(
                f"{label} contains a game that canonical legality cannot replay completely",
                code=CboneAcceptanceCode.ILLEGAL_GAME if label == "decoded database" else code,
            )
        try:
            digests.append(identity_for_game(game).record_digest)
        except (TypeError, ValueError, RuntimeError) as exc:
            raise CboneAcceptanceError(
                f"{label} contains an invalid canonical GameTree",
                code=code,
            ) from exc
    return tuple(digests)


def _fingerprint_after_candidate(before: SourceFingerprint, source_path: Path) -> SourceFingerprint:
    try:
        after = fingerprint(source_path)
    except (OSError, ValueError, RuntimeError) as exc:
        raise CboneAcceptanceError(
            "CBONE source could not be verified after candidate decoding",
            code=CboneAcceptanceCode.SOURCE_CHANGED,
        ) from exc
    if not _same_source(before, after):
        raise CboneAcceptanceError(
            "CBONE source bytes changed during candidate decoding",
            code=CboneAcceptanceCode.SOURCE_CHANGED,
        )
    return after


def qualify_cbone_candidate(
    source: str | Path,
    manifest: CboneAcceptanceManifest,
    decoder: CboneDecoderCandidate,
    *,
    oracle_pgn: str,
) -> CboneAcceptanceReport:
    """Qualify one future CBONE reader against independent semantic evidence.

    The decoder is supplied by the caller so this module never assumes CBONE is
    CBH, 2CBH or any other container.  The source is fingerprinted before and
    after decoder execution; mutation invalidates all output.  Decoded games
    and the independent oracle are then replayed through canonical legality,
    compared by canonical record identity, and the decoded output is required
    to survive canonical PGN export/reopen unchanged.
    """

    if not isinstance(manifest, CboneAcceptanceManifest):
        raise TypeError("manifest must be a CboneAcceptanceManifest")
    if not callable(decoder):
        raise TypeError("decoder must be callable")
    if type(oracle_pgn) is not str:
        raise TypeError("oracle_pgn must be text")

    source_path = Path(source)
    if source_path.suffix.lower() != CBONE_SUFFIX:
        raise CboneAcceptanceError(
            "CBONE semantic acceptance requires an exact .cbone source",
            code=CboneAcceptanceCode.WRONG_SOURCE,
        )

    try:
        before = fingerprint(source_path)
    except (OSError, ValueError, RuntimeError) as exc:
        raise CboneAcceptanceError(
            "CBONE source could not be fingerprinted safely",
            code=CboneAcceptanceCode.WRONG_SOURCE,
        ) from exc
    if before.suffix != CBONE_SUFFIX or before.sha256 != manifest.source_sha256:
        raise CboneAcceptanceError(
            "CBONE source identity does not match the acceptance manifest",
            code=CboneAcceptanceCode.WRONG_SOURCE,
        )

    oracle_bytes = oracle_pgn.encode("utf-8")
    if len(oracle_bytes) > MAX_ORACLE_PGN_BYTES:
        raise CboneAcceptanceError(
            "CBONE independent PGN oracle exceeds the acceptance size limit",
            code=CboneAcceptanceCode.RESOURCE_LIMIT,
        )
    if sha256(oracle_bytes).hexdigest() != manifest.oracle_pgn_sha256:
        raise CboneAcceptanceError(
            "CBONE independent PGN oracle identity does not match the manifest",
            code=CboneAcceptanceCode.INVALID_ORACLE,
        )

    try:
        candidate_value = decoder(Path(before.path))
        decoded_games = _collect_candidate_games(candidate_value)
    except CboneAcceptanceError:
        _fingerprint_after_candidate(before, source_path)
        raise
    except Exception as exc:
        _fingerprint_after_candidate(before, source_path)
        raise CboneAcceptanceError(
            "CBONE candidate decoder failed during semantic acceptance",
            code=CboneAcceptanceCode.BACKEND_FAILED,
        ) from exc
    _fingerprint_after_candidate(before, source_path)

    if len(decoded_games) != manifest.expected_game_count:
        raise CboneAcceptanceError(
            "CBONE candidate decoded game count differs from the acceptance manifest",
            code=CboneAcceptanceCode.ORACLE_MISMATCH,
        )
    decoded_digests = _require_canonical_games(
        decoded_games,
        label="decoded database",
        code=CboneAcceptanceCode.INVALID_DECODED_DATABASE,
    )

    try:
        oracle_games = tuple(parse_games(oracle_pgn))
    except Exception as exc:
        raise CboneAcceptanceError(
            "CBONE independent PGN oracle could not be parsed",
            code=CboneAcceptanceCode.INVALID_ORACLE,
        ) from exc
    if len(oracle_games) != manifest.expected_game_count:
        raise CboneAcceptanceError(
            "CBONE independent PGN oracle game count differs from the manifest",
            code=CboneAcceptanceCode.INVALID_ORACLE,
        )
    oracle_digests = _require_canonical_games(
        oracle_games,
        label="independent oracle",
        code=CboneAcceptanceCode.INVALID_ORACLE,
    )
    if decoded_digests != oracle_digests:
        raise CboneAcceptanceError(
            "CBONE decoded canonical records differ from the independent PGN oracle",
            code=CboneAcceptanceCode.ORACLE_MISMATCH,
        )

    try:
        reopened_games = tuple(parse_games(serialize_games(decoded_games)))
    except Exception as exc:
        raise CboneAcceptanceError(
            "CBONE decoded GameTrees failed canonical PGN export/reopen",
            code=CboneAcceptanceCode.ROUNDTRIP_MISMATCH,
        ) from exc
    if len(reopened_games) != len(decoded_games):
        raise CboneAcceptanceError(
            "CBONE canonical PGN export/reopen changed the game count",
            code=CboneAcceptanceCode.ROUNDTRIP_MISMATCH,
        )
    roundtrip_digests = _require_canonical_games(
        reopened_games,
        label="PGN reopen",
        code=CboneAcceptanceCode.ROUNDTRIP_MISMATCH,
    )
    if roundtrip_digests != decoded_digests:
        raise CboneAcceptanceError(
            "CBONE canonical PGN export/reopen changed semantic record identity",
            code=CboneAcceptanceCode.ROUNDTRIP_MISMATCH,
        )

    return CboneAcceptanceReport(
        source=before,
        backend_name=manifest.backend_name,
        backend_commit=manifest.backend_commit,
        backend_license_spdx=manifest.backend_license_spdx,
        oracle_pgn_sha256=manifest.oracle_pgn_sha256,
        game_count=len(decoded_games),
        record_digests=decoded_digests,
        roundtrip_record_digests=roundtrip_digests,
    )
