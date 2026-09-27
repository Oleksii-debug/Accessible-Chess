from __future__ import annotations

"""Machine-verifiable security support policy for Accessible Chess releases."""

from dataclasses import dataclass
from datetime import date
import json
import os
from pathlib import Path
import re
import stat
from typing import Any
from urllib.parse import urlparse

PRODUCT_NAME = "Accessible Chess"
SCHEMA_VERSION = 1
MINIMUM_SUPPORT_YEARS = 5
CRA_EARLY_WARNING_HOURS = 24
CRA_NOTIFICATION_HOURS = 72
CRA_VULNERABILITY_FINAL_DAYS_AFTER_CORRECTIVE = 14
CRA_INCIDENT_FINAL_MONTHS_AFTER_NOTIFICATION = 1
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,79}$")


class SecuritySupportError(ValueError):
    pass


class _DuplicateKey(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SecuritySupportPolicy:
    version: str
    market_release_date: date
    support_end_date: date
    vulnerability_contact: str
    disclosure_policy_url: str
    security_update_url: str
    security_updates_free: bool = True
    separate_security_updates_when_feasible: bool = True
    end_of_support_notice_required: bool = True

    def __post_init__(self) -> None:
        version = _version(self.version)
        market = _date(self.market_release_date, "market release date")
        end = _date(self.support_end_date, "support end date")
        minimum = _add_years(market, MINIMUM_SUPPORT_YEARS)
        if end < minimum:
            raise SecuritySupportError(
                f"support period must end no earlier than {minimum.isoformat()}"
            )
        contact = _contact_uri(self.vulnerability_contact)
        disclosure = _https_url(self.disclosure_policy_url, "disclosure policy URL")
        update = _https_url(self.security_update_url, "security update URL")
        for value, label in (
            (self.security_updates_free, "security_updates_free"),
            (
                self.separate_security_updates_when_feasible,
                "separate_security_updates_when_feasible",
            ),
            (self.end_of_support_notice_required, "end_of_support_notice_required"),
        ):
            if type(value) is not bool or not value:
                raise SecuritySupportError(f"{label} must be true for release")
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "market_release_date", market)
        object.__setattr__(self, "support_end_date", end)
        object.__setattr__(self, "vulnerability_contact", contact)
        object.__setattr__(self, "disclosure_policy_url", disclosure)
        object.__setattr__(self, "security_update_url", update)

    @property
    def minimum_support_end_date(self) -> date:
        return _add_years(self.market_release_date, MINIMUM_SUPPORT_YEARS)

    def to_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "product": PRODUCT_NAME,
            "version": self.version,
            "market_release_date": self.market_release_date.isoformat(),
            "support_end_date": self.support_end_date.isoformat(),
            "vulnerability_contact": self.vulnerability_contact,
            "disclosure_policy_url": self.disclosure_policy_url,
            "security_update_url": self.security_update_url,
            "security_updates_free": True,
            "separate_security_updates_when_feasible": True,
            "end_of_support_notice_required": True,
            "cra_reporting_contract": {
                "early_warning_hours": CRA_EARLY_WARNING_HOURS,
                "notification_hours": CRA_NOTIFICATION_HOURS,
                "actively_exploited_vulnerability_final_days_after_corrective": (
                    CRA_VULNERABILITY_FINAL_DAYS_AFTER_CORRECTIVE
                ),
                "severe_incident_final_months_after_notification": (
                    CRA_INCIDENT_FINAL_MONTHS_AFTER_NOTIFICATION
                ),
            },
        }


def canonical_security_support_json(policy: SecuritySupportPolicy) -> str:
    if type(policy) is not SecuritySupportPolicy:
        raise SecuritySupportError("policy must be SecuritySupportPolicy")
    manifest = policy.to_manifest()
    validate_security_support_manifest(manifest)
    return json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"


def validate_security_support_manifest(manifest: dict[str, Any]) -> None:
    if type(manifest) is not dict:
        raise SecuritySupportError("security support manifest must be an object")
    expected = {
        "schema_version",
        "product",
        "version",
        "market_release_date",
        "support_end_date",
        "vulnerability_contact",
        "disclosure_policy_url",
        "security_update_url",
        "security_updates_free",
        "separate_security_updates_when_feasible",
        "end_of_support_notice_required",
        "cra_reporting_contract",
    }
    if set(manifest) != expected:
        raise SecuritySupportError("security support manifest keys are invalid")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise SecuritySupportError("unsupported security support schema")
    if manifest["product"] != PRODUCT_NAME:
        raise SecuritySupportError("security support manifest product mismatch")
    SecuritySupportPolicy(
        version=manifest["version"],
        market_release_date=_parse_iso_date(
            manifest["market_release_date"], "market_release_date"
        ),
        support_end_date=_parse_iso_date(
            manifest["support_end_date"], "support_end_date"
        ),
        vulnerability_contact=manifest["vulnerability_contact"],
        disclosure_policy_url=manifest["disclosure_policy_url"],
        security_update_url=manifest["security_update_url"],
        security_updates_free=manifest["security_updates_free"],
        separate_security_updates_when_feasible=manifest[
            "separate_security_updates_when_feasible"
        ],
        end_of_support_notice_required=manifest[
            "end_of_support_notice_required"
        ],
    )
    reporting = manifest["cra_reporting_contract"]
    if type(reporting) is not dict or reporting != {
        "early_warning_hours": CRA_EARLY_WARNING_HOURS,
        "notification_hours": CRA_NOTIFICATION_HOURS,
        "actively_exploited_vulnerability_final_days_after_corrective": (
            CRA_VULNERABILITY_FINAL_DAYS_AFTER_CORRECTIVE
        ),
        "severe_incident_final_months_after_notification": (
            CRA_INCIDENT_FINAL_MONTHS_AFTER_NOTIFICATION
        ),
    }:
        raise SecuritySupportError("CRA reporting contract values are invalid")


def load_security_support_input(path: str | Path) -> dict[str, Any]:
    raw = _regular_text(Path(path), "security support input")
    if len(raw.encode("utf-8")) > 256 * 1024:
        raise SecuritySupportError("security support input exceeds 256 KiB")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except _DuplicateKey as exc:
        raise SecuritySupportError(f"duplicate JSON key: {exc.args[0]}") from exc
    except json.JSONDecodeError as exc:
        raise SecuritySupportError(
            f"invalid security support JSON: {exc.msg}"
        ) from exc
    if type(value) is not dict:
        raise SecuritySupportError("security support input must be an object")
    return value


def generate_security_support_manifest(
    input_path: str | Path,
    output_path: str | Path,
) -> str:
    manifest = build_security_support_manifest(
        load_security_support_input(input_path)
    )
    validate_security_support_manifest(manifest)
    encoded = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    _atomic_text(Path(output_path), encoded)
    return encoded


def build_security_support_manifest(value: dict[str, Any]) -> dict[str, Any]:
    """Normalize release-author input to the complete fail-closed manifest."""

    if type(value) is not dict:
        raise SecuritySupportError("security support input must be an object")
    expected = {
        "version",
        "market_release_date",
        "support_end_date",
        "vulnerability_contact",
        "disclosure_policy_url",
        "security_update_url",
    }
    if set(value) != expected:
        raise SecuritySupportError("security support input keys are invalid")
    policy = SecuritySupportPolicy(
        version=value["version"],
        market_release_date=_parse_iso_date(
            value["market_release_date"], "market_release_date"
        ),
        support_end_date=_parse_iso_date(
            value["support_end_date"], "support_end_date"
        ),
        vulnerability_contact=value["vulnerability_contact"],
        disclosure_policy_url=value["disclosure_policy_url"],
        security_update_url=value["security_update_url"],
    )
    return policy.to_manifest()


def support_status(policy: SecuritySupportPolicy, *, on_date: date) -> str:
    """Return active/ended without inventing a grace period outside policy."""

    if type(policy) is not SecuritySupportPolicy:
        raise SecuritySupportError("policy must be SecuritySupportPolicy")
    current = _date(on_date, "status date")
    return "active" if current <= policy.support_end_date else "ended"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _regular_text(path: Path, label: str) -> str:
    try:
        meta = path.lstat()
    except OSError as exc:
        raise SecuritySupportError(f"cannot inspect {label}: {exc}") from exc
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISREG(meta.st_mode):
        raise SecuritySupportError(f"{label} must be a regular non-symlink file")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SecuritySupportError(f"cannot read {label} as UTF-8: {exc}") from exc


def _atomic_text(path: Path, content: str) -> None:
    parent = path.parent
    try:
        meta = parent.lstat()
    except OSError as exc:
        raise SecuritySupportError(f"cannot inspect output directory: {exc}") from exc
    if stat.S_ISLNK(meta.st_mode) or not stat.S_ISDIR(meta.st_mode):
        raise SecuritySupportError("output parent must be a real directory")
    if path.exists() or path.is_symlink():
        current = path.lstat()
        if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
            raise SecuritySupportError(
                "existing output must be a regular non-symlink file"
            )
    temp = parent / f".{path.name}.tmp-{os.getpid()}"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                fd = -1
                stream.write(content.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if fd != -1:
                os.close(fd)
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
    except OSError as exc:
        raise SecuritySupportError(
            f"cannot publish security support manifest atomically: {exc}"
        ) from exc


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def _date(value: Any, label: str) -> date:
    if type(value) is not date:
        raise SecuritySupportError(f"{label} must be a date")
    return value


def _parse_iso_date(value: Any, label: str) -> date:
    if type(value) is not str:
        raise SecuritySupportError(f"{label} must be YYYY-MM-DD text")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise SecuritySupportError(f"{label} must be canonical YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise SecuritySupportError(f"{label} must be canonical YYYY-MM-DD")
    return parsed


def _version(value: Any) -> str:
    if type(value) is not str or not _VERSION_RE.fullmatch(value):
        raise SecuritySupportError("version is invalid")
    return value


def _https_url(value: Any, label: str) -> str:
    if type(value) is not str or value != value.strip() or len(value) > 2048:
        raise SecuritySupportError(f"{label} is invalid")
    if "\\" in value or _has_encoded_ascii_control(value):
        raise SecuritySupportError(f"{label} must be a clean HTTPS URL")
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise SecuritySupportError(f"{label} must be a clean HTTPS URL") from exc
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise SecuritySupportError(f"{label} must be a clean HTTPS URL")
    return value


def _has_encoded_ascii_control(value: str) -> bool:
    lowered = value.lower()
    for code in range(0x20):
        if f"%{code:02x}" in lowered:
            return True
    return "%7f" in lowered


def _contact_uri(value: Any) -> str:
    if type(value) is not str or value != value.strip() or len(value) > 2048:
        raise SecuritySupportError("vulnerability contact is invalid")
    if "\\" in value or _has_encoded_ascii_control(value):
        raise SecuritySupportError("vulnerability contact is invalid")
    parsed = urlparse(value)
    if parsed.scheme == "https":
        try:
            port = parsed.port
        except ValueError as exc:
            raise SecuritySupportError("HTTPS vulnerability contact is invalid") from exc
        if (
            not parsed.netloc
            or parsed.hostname is None
            or parsed.username
            or parsed.password
            or parsed.fragment
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise SecuritySupportError("HTTPS vulnerability contact is invalid")
        return value
    if parsed.scheme == "mailto":
        address = parsed.path
        if (
            not address
            or "@" not in address
            or parsed.query
            or parsed.fragment
            or any(ch.isspace() for ch in address)
        ):
            raise SecuritySupportError("mailto vulnerability contact is invalid")
        return value
    raise SecuritySupportError("vulnerability contact must be HTTPS or mailto")


__all__ = [
    "CRA_EARLY_WARNING_HOURS",
    "CRA_INCIDENT_FINAL_MONTHS_AFTER_NOTIFICATION",
    "CRA_NOTIFICATION_HOURS",
    "CRA_VULNERABILITY_FINAL_DAYS_AFTER_CORRECTIVE",
    "MINIMUM_SUPPORT_YEARS",
    "SecuritySupportError",
    "SecuritySupportPolicy",
    "build_security_support_manifest",
    "canonical_security_support_json",
    "generate_security_support_manifest",
    "load_security_support_input",
    "support_status",
    "validate_security_support_manifest",
]
