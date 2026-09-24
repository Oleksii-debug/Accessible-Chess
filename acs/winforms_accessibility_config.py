from __future__ import annotations

"""Validate the WinForms accessibility app-config used by packaged Windows builds.

The contract is intentionally provider-neutral and presentation-only. It proves
that the executable opts out of every supported legacy accessibility level
through .NET Framework 4.8.1 without making the release pipeline trust an
arbitrary non-empty XML file.
"""

from pathlib import Path
import xml.etree.ElementTree as ET


MAX_CONFIG_BYTES = 64 * 1024
REQUIRED_ACCESSIBILITY_SWITCHES = (
    "Switch.UseLegacyAccessibilityFeatures",
    "Switch.UseLegacyAccessibilityFeatures.2",
    "Switch.UseLegacyAccessibilityFeatures.3",
    "Switch.UseLegacyAccessibilityFeatures.4",
    "Switch.UseLegacyAccessibilityFeatures.5",
)


class WinFormsAccessibilityConfigError(ValueError):
    """Raised when the packaged WinForms accessibility config is not canonical."""


def _fail(message: str) -> None:
    raise WinFormsAccessibilityConfigError(message)


def validate_winforms_accessibility_config_bytes(data: bytes) -> None:
    if type(data) is not bytes or not data:
        _fail("WinForms accessibility app-config is empty")
    if len(data) > MAX_CONFIG_BYTES:
        _fail("WinForms accessibility app-config exceeds size limit")
    if b"\x00" in data:
        _fail("WinForms accessibility app-config contains NUL bytes")

    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError) as exc:
        raise WinFormsAccessibilityConfigError(
            "WinForms accessibility app-config is invalid XML"
        ) from exc

    if root.tag != "configuration":
        _fail("WinForms accessibility app-config root must be configuration")

    runtimes = [child for child in root if child.tag == "runtime"]
    if len(runtimes) != 1:
        _fail("WinForms accessibility app-config must contain exactly one runtime element")
    runtime = runtimes[0]

    overrides = [child for child in runtime if child.tag == "AppContextSwitchOverrides"]
    if len(overrides) != 1:
        _fail(
            "WinForms accessibility app-config must contain exactly one "
            "AppContextSwitchOverrides element"
        )
    override = overrides[0]

    if set(override.attrib) != {"value"}:
        _fail("WinForms accessibility AppContextSwitchOverrides attributes are invalid")
    if list(override):
        _fail("WinForms accessibility AppContextSwitchOverrides must not contain child elements")

    raw = override.attrib.get("value", "")
    pairs: dict[str, str] = {}
    for token in raw.split(";"):
        token = token.strip()
        if not token:
            _fail("WinForms accessibility switch list contains an empty entry")
        if token.count("=") != 1:
            _fail("WinForms accessibility switch entry is malformed")
        name, value = (part.strip() for part in token.split("=", 1))
        if name in pairs:
            _fail("WinForms accessibility switch list contains a duplicate switch")
        pairs[name] = value

    for name in REQUIRED_ACCESSIBILITY_SWITCHES:
        if name not in pairs:
            _fail("WinForms accessibility app-config must declare all five required switches")
        if pairs[name].casefold() != "false":
            _fail("WinForms accessibility switches must all be false")

    legacy_family = {
        name for name in pairs if name.startswith("Switch.UseLegacyAccessibilityFeatures")
    }
    if legacy_family != set(REQUIRED_ACCESSIBILITY_SWITCHES):
        _fail("WinForms accessibility legacy-switch family must be exactly the supported five")


def validate_winforms_accessibility_config(path: str | Path) -> None:
    config = Path(path)
    try:
        data = config.read_bytes()
    except OSError as exc:
        raise WinFormsAccessibilityConfigError(
            "WinForms accessibility app-config is missing or unreadable"
        ) from exc
    validate_winforms_accessibility_config_bytes(data)


__all__ = [
    "MAX_CONFIG_BYTES",
    "REQUIRED_ACCESSIBILITY_SWITCHES",
    "WinFormsAccessibilityConfigError",
    "validate_winforms_accessibility_config",
    "validate_winforms_accessibility_config_bytes",
]
