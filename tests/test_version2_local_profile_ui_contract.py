from __future__ import annotations

from pathlib import Path
import unittest


class Version2LocalProfileUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (
            Path(__file__).resolve().parents[1] / "web" / "version2_release_bootstrap.js"
        ).read_text(encoding="utf-8")

    def test_profile_dialog_is_semantic_keyboard_native_html(self) -> None:
        source = self.source
        self.assertIn('profileDialog = documentRef.createElement("dialog")', source)
        self.assertIn('profileHeading.id = "v2-profile-heading"', source)
        self.assertIn('profileDialog.setAttribute("aria-labelledby", profileHeading.id)', source)
        self.assertIn('profileName.id = "v2-profile-name"', source)
        self.assertIn('profileLabel.htmlFor = profileName.id', source)
        self.assertIn('profileName.setAttribute("aria-describedby", "v2-profile-description v2-profile-status")', source)
        self.assertIn('profileSave.type = "button"', source)
        self.assertIn('profileSkip.type = "button"', source)
        self.assertIn('profileRepair.id = "v2-profile-repair"', source)
        self.assertIn('profileRepair.setAttribute("aria-describedby", "v2-profile-status")', source)

    def test_first_launch_requires_explicit_save_or_skip(self) -> None:
        source = self.source
        self.assertIn('if (!profileState || !profileState.exists) event.preventDefault()', source)
        self.assertIn('bridge.profile_create(profileName.value, false)', source)
        self.assertIn('bridge.profile_create("", true)', source)
        self.assertIn('bridge.profile_rename(profileName.value)', source)
        self.assertIn('if (event.key !== "Enter") return;', source)
        self.assertIn('bridge.profile_repair()', source)
        self.assertIn('const recoveryRequired = exists && profileState.recoveryRequired === true', source)
        self.assertIn('profileRepair.hidden = !recoveryRequired', source)
        self.assertIn('Профіль відкрито з резервної копії.', source)

    def test_ambient_refresh_preserves_unsaved_profile_name(self) -> None:
        source = self.source
        self.assertIn("function renderProfileState(state, preserveDraft)", source)
        self.assertIn("if (!preserveDraft) profileName.value = displayName;", source)
        self.assertIn("renderProfileState(profileState, profileDialog.open)", source)
        self.assertIn("renderProfileState(result);", source)

    def test_browser_never_requests_or_renders_stable_profile_id(self) -> None:
        source = self.source
        self.assertNotIn("profileId", source)
        self.assertNotIn("profile_id", source)


if __name__ == "__main__":
    unittest.main()
