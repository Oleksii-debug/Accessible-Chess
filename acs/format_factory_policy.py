from __future__ import annotations

"""Section 54 deterministic user policy, with strict scope and consent boundaries.

No source bytes, author names, or private file names reach a model from here.
Natural-language parsing supports only exact unambiguous commands. Unknown intent
must be confirmed in the accessible form, never guessed or executed.
"""

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Literal

MAX_SELECTED_SEGMENTS = 1_000
MAX_SELECTOR_INDEX = 1_000_000
MAX_SELECTOR_WIDTH = 100_000
MAX_SELECTED_ITEMS = 100_000
MAX_OUTPUT_FORMATS = 8
_KNOWN_OUTPUTS = frozenset(("txt", "markdown", "html", "epub3", "docx", "tagged_pdf", "pgn", "acsdb"))
_KNOWN_SCOPES = frozenset(("all", "chapters", "printed_pages", "file_pages", "positions", "games", "diagrams"))
_KNOWN_ERRORS = frozenset(("pause", "review", "stop"))


class FactoryPolicyError(ValueError):
    """Safe policy validation failure, without printing user-provided source."""


def _positive(value: object, label: str, *, bound: int = MAX_SELECTOR_INDEX) -> int:
    if type(value) is not int or not (1 <= value <= bound):
        raise FactoryPolicyError(label + " must be a positive bounded integer")
    return value


def _nonempty_id(value: object, label: str) -> str:
    if type(value) is not str or not 1 <= len(value) <= 128:
        raise FactoryPolicyError(label + " must be non-empty bounded text")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
        raise FactoryPolicyError(label + " has invalid characters")
    return value


def parse_selector_ranges(text: str) -> tuple[tuple[int, int], ...]:
    """Parse 1,3-5,7–9; normalize overlaps and repeats deterministically."""
    if type(text) is not str or not text or len(text) > 20_000:
        raise FactoryPolicyError("Selector must be bounded text")
    parts = text.split(",")
    if len(parts) > MAX_SELECTED_SEGMENTS:
        raise FactoryPolicyError("Too many requested ranges")
    ranges: list[tuple[int, int]] = []
    for part in parts:
        match = re.fullmatch(r"\s*([0-9]{1,7})(?:\s*[-–—]\s*([0-9]{1,7}))?\s*", part)
        if match is None:
            raise FactoryPolicyError("Invalid selector range")
        start = _positive(int(match.group(1)), "Range start")
        end = _positive(int(match.group(2)), "Range end") if match.group(2) else start
        if end < start or end - start + 1 > MAX_SELECTOR_WIDTH:
            raise FactoryPolicyError("Invalid range bounds")
        ranges.append((start, end))
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    total = sum(end - start + 1 for start, end in merged)
    if total > MAX_SELECTED_ITEMS:
        raise FactoryPolicyError("Selected scope exceeds the supported item count")
    return tuple((start, end) for start, end in merged)


@dataclass(frozen=True, slots=True)
class FactorySelection:
    kind: Literal["all", "chapters", "printed_pages", "file_pages", "positions", "games", "diagrams"]
    ranges: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in _KNOWN_SCOPES:
            raise FactoryPolicyError("Unknown selection type")
        if type(self.ranges) is not tuple:
            raise FactoryPolicyError("Selection ranges must be immutable")
        if self.kind == "all":
            if self.ranges:
                raise FactoryPolicyError("Whole-book selection cannot include ranges")
            return
        if not self.ranges or len(self.ranges) > MAX_SELECTED_SEGMENTS:
            raise FactoryPolicyError("Explicit selection needs bounded ranges")
        prior = 0
        total = 0
        for item in self.ranges:
            if type(item) is not tuple or len(item) != 2:
                raise FactoryPolicyError("Invalid range pair")
            start = _positive(item[0], "Range start")
            end = _positive(item[1], "Range end")
            if start <= prior or end < start or end - start + 1 > MAX_SELECTOR_WIDTH:
                raise FactoryPolicyError("Ranges must be sorted, disjoint and bounded")
            total += end - start + 1
            prior = end
        if total > MAX_SELECTED_ITEMS:
            raise FactoryPolicyError("Requested coverage is too large")

    @classmethod
    def from_text(cls, kind: str, ranges: str = "") -> FactorySelection:
        if kind == "all":
            if ranges.strip():
                raise FactoryPolicyError("Unexpected ranges for whole-book scope")
            return cls("all")
        return cls(kind, parse_selector_ranges(ranges))


@dataclass(frozen=True, slots=True)
class FactoryJobPolicy:
    source_sha256: str
    source_id: str
    selection: FactorySelection
    output_formats: tuple[str, ...]
    output_language: str
    allowed_external_search: bool = False
    allowed_external_ai: bool = False
    provider_id: str | None = None
    model_id: str | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    on_error: Literal["pause", "review", "stop"] = "review"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or type(self.schema_version) is not int:
            raise FactoryPolicyError("Unsupported policy schema version")
        if type(self.source_sha256) is not str or not re.fullmatch(r"[a-f0-9]{64}", self.source_sha256):
            raise FactoryPolicyError("Source SHA-256 identity is required")
        _nonempty_id(self.source_id, "source_id")
        if type(self.selection) is not FactorySelection:
            raise FactoryPolicyError("Validated selection is required")
        if (type(self.output_formats) is not tuple or not self.output_formats or
                len(self.output_formats) > MAX_OUTPUT_FORMATS or
                any(type(x) is not str or x not in _KNOWN_OUTPUTS for x in self.output_formats) or
                len(set(self.output_formats)) != len(self.output_formats)):
            raise FactoryPolicyError("Output formats must be unique supported identifiers")
        if (type(self.output_language) is not str or
                re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z]{2,8})?", self.output_language) is None):
            raise FactoryPolicyError("Output language must be an explicit BCP-47 code")
        if type(self.allowed_external_search) is not bool or type(self.allowed_external_ai) is not bool:
            raise FactoryPolicyError("Consent flags must be explicit booleans")
        if type(self.on_error) is not str or self.on_error not in _KNOWN_ERRORS:
            raise FactoryPolicyError("Unknown error policy")
        if self.allowed_external_ai:
            _nonempty_id(self.provider_id, "provider_id")
            _nonempty_id(self.model_id, "model_id")
            _positive(self.max_input_tokens, "max_input_tokens", bound=2**63 - 1)
            _positive(self.max_output_tokens, "max_output_tokens", bound=2**63 - 1)
        elif any(x is not None for x in (self.provider_id, self.model_id, self.max_input_tokens, self.max_output_tokens)):
            raise FactoryPolicyError("Provider settings require explicit AI permission")

    def snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_sha256": self.source_sha256,
            "source_id": self.source_id,
            "selection": {"kind": self.selection.kind, "ranges": [list(v) for v in self.selection.ranges]},
            "output_formats": list(self.output_formats),
            "output_language": self.output_language,
            "allowed_external_search": self.allowed_external_search,
            "allowed_external_ai": self.allowed_external_ai,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "on_error": self.on_error,
        }

    def digest(self) -> str:
        return sha256(json.dumps(self.snapshot(), ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")).encode("utf-8")).hexdigest()


def parse_factory_scope_command(command: str, *, printed_pages: bool = True) -> FactorySelection:
    """Deterministic narrow command mapping; ambiguity fails closed to a form."""
    if type(command) is not str or not 1 <= len(command) <= 512:
        raise FactoryPolicyError("Command must be bounded text")
    text = " ".join(command.casefold().strip().split())
    if text in ("повністю всю книгу", "всю книгу", "цілу книгу", "whole book"):
        return FactorySelection("all")
    if text in ("всі діаграми", "усі діаграми", "all diagrams"):
        raise FactoryPolicyError("All-diagrams semantic scan requires review")
    matches = (
        (r"(?:лише |тільки )?(?:глава|главу|розділ) (\d+)", "chapters"),
        (r"(?:сторінки|сторінок) (\d+)\s*[-–—]\s*(\d+)", "printed_pages" if printed_pages else "file_pages"),
        (r"до сторінки (\d+)", "printed_pages" if printed_pages else "file_pages"),
        (r"позиції (\d+)\s*[-–—]\s*(\d+)", "positions"),
        (r"перші (\d+) партій", "games"),
    )
    for pattern, kind in matches:
        match = re.fullmatch(pattern, text)
        if not match:
            continue
        if pattern.startswith("до сторінки") or pattern.startswith("перші"):
            return FactorySelection.from_text(kind, "1-" + match.group(1))
        return FactorySelection.from_text(kind, "-".join(match.groups()[-2:]) if len(match.groups()) > 1 else match.group(1))
    raise FactoryPolicyError("Ambiguous instruction: configure exact selection in accessible form")
