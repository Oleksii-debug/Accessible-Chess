from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.winforms_accessibility_config import (
    REQUIRED_ACCESSIBILITY_SWITCHES,
    WinFormsAccessibilityConfigError,
    validate_winforms_accessibility_config,
    validate_winforms_accessibility_config_bytes,
)


def _config(*, switches=None) -> bytes:
    if switches is None:
        switches = [(name, "false") for name in REQUIRED_ACCESSIBILITY_SWITCHES]
    value = ";".join(f"{name}={setting}" for name, setting in switches)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<configuration>\n'
        '  <startup><supportedRuntime version="v4.0" '
        'sku=".NETFramework,Version=v4.8" /></startup>\n'
        '  <runtime>\n'
        f'    <AppContextSwitchOverrides value="{value}" />\n'
        '  </runtime>\n'
        '</configuration>\n'
    ).encode("utf-8")


class WinFormsAccessibilityConfigTests(unittest.TestCase):
    def test_canonical_five_switch_config_passes(self) -> None:
        validate_winforms_accessibility_config_bytes(_config())

    def test_file_boundary_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "AccessibleChess.exe.config"
            path.write_bytes(_config())
            validate_winforms_accessibility_config(path)

    def test_empty_invalid_xml_wrong_root_and_nul_fail(self) -> None:
        cases = (
            (b"", "empty"),
            (b"<configuration>", "invalid XML"),
            (b"<settings />", "root"),
            (b"<configuration>\x00</configuration>", "NUL"),
        )
        for data, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(WinFormsAccessibilityConfigError, expected):
                    validate_winforms_accessibility_config_bytes(data)

    def test_size_limit_fails(self) -> None:
        with self.assertRaisesRegex(WinFormsAccessibilityConfigError, "size limit"):
            validate_winforms_accessibility_config_bytes(b" " * (64 * 1024 + 1))

    def test_runtime_and_override_cardinality_fail(self) -> None:
        cases = (
            (b"<configuration />", "exactly one runtime"),
            (
                b"<configuration><runtime/><runtime/></configuration>",
                "exactly one runtime",
            ),
            (
                b"<configuration><runtime/></configuration>",
                "exactly one AppContext",
            ),
            (
                b"<configuration><runtime>"
                b"<AppContextSwitchOverrides value='x=false'/>"
                b"<AppContextSwitchOverrides value='x=false'/>"
                b"</runtime></configuration>",
                "exactly one AppContext",
            ),
        )
        for data, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(WinFormsAccessibilityConfigError, expected):
                    validate_winforms_accessibility_config_bytes(data)

    def test_missing_future_duplicate_true_and_malformed_switches_fail(self) -> None:
        valid = [(name, "false") for name in REQUIRED_ACCESSIBILITY_SWITCHES]
        cases = (
            (valid[:-1], "all five required"),
            (
                valid + [("Switch.UseLegacyAccessibilityFeatures.6", "false")],
                "exactly the supported five",
            ),
            (valid + [(valid[0][0], "false")], "duplicate"),
            (
                [
                    (name, "true" if index == 2 else "false")
                    for index, (name, _) in enumerate(valid)
                ],
                "all be false",
            ),
        )
        for switches, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(WinFormsAccessibilityConfigError, expected):
                    validate_winforms_accessibility_config_bytes(_config(switches=switches))

        malformed = _config().replace(b".5=false", b".5=false=oops")
        with self.assertRaisesRegex(WinFormsAccessibilityConfigError, "malformed"):
            validate_winforms_accessibility_config_bytes(malformed)

    def test_order_is_not_semantically_significant(self) -> None:
        valid = [(name, "false") for name in REQUIRED_ACCESSIBILITY_SWITCHES]
        valid[0], valid[1] = valid[1], valid[0]
        validate_winforms_accessibility_config_bytes(_config(switches=valid))

    def test_unrelated_appcontext_switch_is_allowed(self) -> None:
        valid = [(name, "false") for name in REQUIRED_ACCESSIBILITY_SWITCHES]
        valid.append(("Switch.System.Windows.Forms.UseLegacyToolTipDisplay", "false"))
        validate_winforms_accessibility_config_bytes(_config(switches=valid))

    def test_override_attributes_and_children_fail(self) -> None:
        with_extra_attribute = _config().replace(
            b"AppContextSwitchOverrides value=",
            b'AppContextSwitchOverrides extra="1" value=',
        )
        with self.assertRaisesRegex(WinFormsAccessibilityConfigError, "attributes"):
            validate_winforms_accessibility_config_bytes(with_extra_attribute)

        with_child = _config().replace(
            b'false" />\n  </runtime>',
            b'false"><x /></AppContextSwitchOverrides>\n  </runtime>',
        )
        with self.assertRaisesRegex(WinFormsAccessibilityConfigError, "child elements"):
            validate_winforms_accessibility_config_bytes(with_child)


if __name__ == "__main__":
    unittest.main()
