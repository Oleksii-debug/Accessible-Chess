from __future__ import annotations

import unittest

from acs.webview2_accessibility import (
    WINDOWS_FORMS_ACCESSIBILITY_SWITCHES,
    enable_windows_forms_modern_accessibility,
)


class _RecordingAppContext:
    calls: list[tuple[str, bool]] = []

    @classmethod
    def SetSwitch(cls, name: str, enabled: bool) -> None:
        cls.calls.append((name, enabled))


class _FailingAppContext:
    @staticmethod
    def SetSwitch(name: str, enabled: bool) -> None:
        raise RuntimeError("synthetic AppContext failure")


class _MissingSetterAppContext:
    pass


class ModernWinFormsAccessibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        _RecordingAppContext.calls = []

    def test_exact_modern_provider_switches_are_disabled_in_order(self) -> None:
        self.assertTrue(enable_windows_forms_modern_accessibility(_RecordingAppContext))
        self.assertEqual(
            [(name, False) for name in WINDOWS_FORMS_ACCESSIBILITY_SWITCHES],
            _RecordingAppContext.calls,
        )
        self.assertEqual(
            (
                "Switch.UseLegacyAccessibilityFeatures",
                "Switch.UseLegacyAccessibilityFeatures.2",
                "Switch.UseLegacyAccessibilityFeatures.3",
                "Switch.UseLegacyAccessibilityFeatures.4",
                "Switch.UseLegacyAccessibilityFeatures.5",
            ),
            WINDOWS_FORMS_ACCESSIBILITY_SWITCHES,
        )

    def test_provider_configuration_fails_closed_when_switch_assignment_fails(self) -> None:
        self.assertFalse(enable_windows_forms_modern_accessibility(_FailingAppContext))

    def test_provider_configuration_fails_closed_without_setswitch(self) -> None:
        self.assertFalse(enable_windows_forms_modern_accessibility(_MissingSetterAppContext))


if __name__ == "__main__":
    unittest.main()
