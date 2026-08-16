from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping


PROFILE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LocalProfile:
    installation_id: str
    display_name: str
    generated_alias: bool
    schema_version: int = PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        installation_id = str(self.installation_id).strip().lower()
        display_name = str(self.display_name).strip()
        if not installation_id:
            raise ValueError("installation_id must not be empty")
        if not display_name:
            raise ValueError("display_name must not be empty")
        if int(self.schema_version) != PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported local profile schema")
        object.__setattr__(self, "installation_id", installation_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "schema_version", PROFILE_SCHEMA_VERSION)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "installation_id": self.installation_id,
            "display_name": self.display_name,
            "generated_alias": self.generated_alias,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LocalProfile":
        try:
            version = int(payload.get("schema_version", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid local profile schema") from exc
        if version != PROFILE_SCHEMA_VERSION:
            raise ValueError("unsupported local profile schema")
        generated = payload.get("generated_alias")
        if not isinstance(generated, bool):
            raise ValueError("generated_alias must be boolean")
        return cls(
            installation_id=str(payload.get("installation_id", "")),
            display_name=str(payload.get("display_name", "")),
            generated_alias=generated,
            schema_version=version,
        )


class LocalProfileStore:
    """Atomic local identity store; it performs no network upload."""

    def __init__(self, path: str | Path, *, lang: str = "uk") -> None:
        self.path = Path(path)
        self.lang = "en" if lang == "en" else "uk"
        self.warning: str | None = None

    def load_or_create(self) -> LocalProfile:
        self.warning = None
        if not self.path.exists():
            profile = self._new_profile()
            self.save(profile)
            return profile
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping):
                raise ValueError("profile file must contain an object")
            return LocalProfile.from_dict(raw)
        except Exception as exc:
            self.warning = f"local profile recovery: {exc}"
            self._preserve_broken_file()
            profile = self._new_profile()
            self.save(profile)
            return profile

    def set_display_name(self, profile: LocalProfile, value: str | None) -> LocalProfile:
        name = str(value or "").strip()
        if not name:
            updated = replace(profile, display_name=self._alias(profile.installation_id), generated_alias=True)
        else:
            updated = replace(profile, display_name=name, generated_alias=False)
        self.save(updated)
        return updated

    def save(self, profile: LocalProfile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(profile.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def _new_profile(self) -> LocalProfile:
        installation_id = uuid.uuid4().hex
        return LocalProfile(installation_id, self._alias(installation_id), True)

    def _alias(self, installation_id: str) -> str:
        serial = int(str(installation_id)[-8:], 16) % 10000
        prefix = "Player" if self.lang == "en" else "Учень"
        return f"{prefix} {serial:04d}"

    def _preserve_broken_file(self) -> None:
        if not self.path.exists():
            return
        backup = self.path.with_suffix(self.path.suffix + ".broken")
        index = 1
        while backup.exists():
            backup = self.path.with_suffix(self.path.suffix + f".broken.{index}")
            index += 1
        try:
            self.path.replace(backup)
        except OSError:
            pass
