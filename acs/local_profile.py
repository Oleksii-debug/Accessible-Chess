from __future__ import annotations

"""Crash-safe local profile identity without network or OS-identity derivation."""

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import unicodedata
import uuid
from typing import Any, Mapping


PROFILE_SCHEMA_VERSION = 1
MAX_DISPLAY_NAME_CHARS = 80
_INSTALLATION_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class LocalProfileError(ValueError):
    pass


class FutureProfileSchemaError(LocalProfileError):
    """Raised when newer profile data must be preserved without downgrade."""


@dataclass(frozen=True, slots=True)
class LocalProfile:
    installation_id: str
    display_name: str
    generated_alias: bool
    schema_version: int = PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        installation_id = _installation_id(self.installation_id)
        display_name = _display_name(self.display_name)
        if type(self.generated_alias) is not bool:
            raise LocalProfileError("generated_alias must be boolean")
        if type(self.schema_version) is not int:
            raise LocalProfileError("profile schema version must be an integer")
        if self.schema_version > PROFILE_SCHEMA_VERSION:
            raise FutureProfileSchemaError("profile schema is newer than this application")
        if self.schema_version != PROFILE_SCHEMA_VERSION:
            raise LocalProfileError("unsupported local profile schema")
        object.__setattr__(self, "installation_id", installation_id)
        object.__setattr__(self, "display_name", display_name)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "installation_id": self.installation_id,
            "display_name": self.display_name,
            "generated_alias": self.generated_alias,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LocalProfile":
        if not isinstance(payload, Mapping):
            raise LocalProfileError("profile data must be an object")
        version = payload.get("schema_version")
        if type(version) is not int:
            raise LocalProfileError("profile schema version must be an integer")
        if version > PROFILE_SCHEMA_VERSION:
            raise FutureProfileSchemaError("profile schema is newer than this application")
        expected = {
            "schema_version",
            "installation_id",
            "display_name",
            "generated_alias",
        }
        if set(payload) != expected:
            raise LocalProfileError("profile data has unexpected fields")
        return cls(
            installation_id=payload["installation_id"],
            display_name=payload["display_name"],
            generated_alias=payload["generated_alias"],
            schema_version=version,
        )


class LocalProfileStore:
    """Atomic local identity store; no network, telemetry or OS username access."""

    def __init__(self, path: str | Path, *, lang: str = "uk") -> None:
        self.path = Path(path)
        self.lang = "en" if lang == "en" else "uk"
        self.warning_code: str | None = None

    @property
    def temporary_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".tmp")

    def load_or_create(self) -> LocalProfile:
        self.warning_code = None
        if not self.path.exists():
            recovered = self._recover_interrupted_save()
            if recovered is not None:
                self.warning_code = "profile_recovered_from_interrupted_save"
                return recovered
            profile = self._new_profile()
            self.save(profile)
            return profile

        try:
            profile = self._read_profile(self.path)
        except FutureProfileSchemaError:
            # A downgrade must never rename/rewrite a profile created by newer code.
            raise
        except (OSError, json.JSONDecodeError, LocalProfileError, TypeError, ValueError):
            self._preserve_broken_file()
            profile = self._new_profile()
            self.save(profile)
            self.warning_code = "profile_recovered_from_invalid_data"
            return profile

        self._discard_stale_temp()
        return profile

    def set_display_name(
        self,
        profile: LocalProfile,
        value: str | None,
    ) -> LocalProfile:
        if type(profile) is not LocalProfile:
            raise LocalProfileError("profile must be LocalProfile")
        if value is None or (type(value) is str and not value.strip()):
            updated = replace(
                profile,
                display_name=self._alias(profile.installation_id),
                generated_alias=True,
            )
        else:
            updated = replace(
                profile,
                display_name=_display_name(value),
                generated_alias=False,
            )
        self.save(updated)
        return updated

    def save(self, profile: LocalProfile) -> None:
        if type(profile) is not LocalProfile:
            raise LocalProfileError("profile must be LocalProfile")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.temporary_path
        try:
            if tmp.exists() or tmp.is_symlink():
                tmp.unlink()
            encoded = (
                json.dumps(
                    profile.as_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
                + "\n"
            )
            with tmp.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.path)
        finally:
            try:
                if tmp.exists() or tmp.is_symlink():
                    tmp.unlink()
            except OSError:
                pass

    def export_json(self, profile: LocalProfile | None = None) -> str:
        item = self.load_or_create() if profile is None else profile
        if type(item) is not LocalProfile:
            raise LocalProfileError("profile must be LocalProfile")
        return json.dumps(
            item.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ) + "\n"

    def delete_local_identity_data(self) -> tuple[Path, ...]:
        """Delete active/temp/recovery profile files owned by this store.

        Other application data is intentionally untouched. Returned paths identify
        files that existed and were removed; callers can report a deterministic
        deletion result without exposing file contents.
        """

        removed: list[Path] = []
        candidates = [self.path, self.temporary_path]
        if self.path.parent.exists():
            prefix = self.path.name + ".broken"
            candidates.extend(
                item
                for item in self.path.parent.iterdir()
                if item.name == prefix or item.name.startswith(prefix + ".")
            )
        seen: set[Path] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            try:
                if candidate.exists() or candidate.is_symlink():
                    candidate.unlink()
                    removed.append(candidate)
            except OSError as exc:
                raise LocalProfileError("local profile deletion failed") from exc
        self.warning_code = None
        return tuple(removed)

    def _read_profile(self, path: Path) -> LocalProfile:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise LocalProfileError("profile file must contain an object")
        return LocalProfile.from_dict(raw)

    def _recover_interrupted_save(self) -> LocalProfile | None:
        tmp = self.temporary_path
        if not tmp.exists():
            return None
        try:
            profile = self._read_profile(tmp)
        except FutureProfileSchemaError:
            # Preserve both a future temp profile and absence of the main profile.
            raise
        except (OSError, json.JSONDecodeError, LocalProfileError, TypeError, ValueError):
            self._discard_stale_temp()
            return None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, self.path)
        return profile

    def _new_profile(self) -> LocalProfile:
        installation_id = uuid.uuid4().hex
        return LocalProfile(
            installation_id=installation_id,
            display_name=self._alias(installation_id),
            generated_alias=True,
        )

    def _alias(self, installation_id: str) -> str:
        installation_id = _installation_id(installation_id)
        serial = int(installation_id[-8:], 16) % 10000
        prefix = "Player" if self.lang == "en" else "Учень"
        return f"{prefix} {serial:04d}"

    def _preserve_broken_file(self) -> None:
        if not self.path.exists() and not self.path.is_symlink():
            return
        backup = self.path.with_suffix(self.path.suffix + ".broken")
        index = 1
        while backup.exists() or backup.is_symlink():
            backup = self.path.with_suffix(self.path.suffix + f".broken.{index}")
            index += 1
        try:
            os.replace(self.path, backup)
        except OSError as exc:
            # Do not overwrite suspect profile data if preservation itself fails.
            raise LocalProfileError("invalid profile could not be preserved") from exc

    def _discard_stale_temp(self) -> None:
        tmp = self.temporary_path
        try:
            if tmp.exists() or tmp.is_symlink():
                tmp.unlink()
        except OSError:
            # A stale temp does not invalidate an already verified main profile.
            pass


def _installation_id(value: object) -> str:
    if type(value) is not str:
        raise LocalProfileError("installation_id must be text")
    normalized = value.strip().lower()
    if _INSTALLATION_ID_RE.fullmatch(normalized) is None:
        raise LocalProfileError("installation_id must be a canonical UUID hex identifier")
    return normalized


def _display_name(value: object) -> str:
    if type(value) is not str:
        raise LocalProfileError("display_name must be text")
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        raise LocalProfileError("display_name must not be empty")
    if len(normalized) > MAX_DISPLAY_NAME_CHARS:
        raise LocalProfileError("display_name exceeds length limit")
    if any(unicodedata.category(ch) in {"Cc", "Cs"} for ch in normalized):
        raise LocalProfileError("display_name contains control characters")
    return normalized


__all__ = [
    "FutureProfileSchemaError",
    "LocalProfile",
    "LocalProfileError",
    "LocalProfileStore",
    "MAX_DISPLAY_NAME_CHARS",
    "PROFILE_SCHEMA_VERSION",
]
