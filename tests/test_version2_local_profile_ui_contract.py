from __future__ import annotations

from pathlib import Path
import unittest


class Version2LocalProfileUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.source = (root / "web" / "version2_release_bootstrap.js").read_text(encoding="utf-8")
        cls.workflow = (
            root / ".github" / "workflows" / "local-profile-first-launch-ui.yml"
        ).read_text(encoding="utf-8")

    def test_workflow_qualifies_exact_head_and_exact_owned_scope(self) -> None:
        workflow = self.workflow
        self.assertIn("ref: ${{ github.event.pull_request.head.sha || github.sha }}", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("Prove live parent ancestry and exact UI scope", workflow)
        self.assertIn("PR_BASE_REF", workflow)
        self.assertIn("PR_BASE_SHA", workflow)
        self.assertIn("PR_HEAD_SHA", workflow)
        self.assertIn("work/local-profile-identity-foundation-20260929", workflow)
        self.assertIn('git merge-base --is-ancestor "$PR_BASE_SHA" "$live_base"', workflow)
        self.assertIn('git merge-base --is-ancestor "$live_base" HEAD', workflow)
        self.assertIn('test "$(git merge-base "$live_base" HEAD)" = "$live_base"', workflow)
        self.assertIn('git diff --check "$live_base" HEAD', workflow)
        self.assertIn('git diff --name-only "$live_base" HEAD', workflow)
        self.assertIn("EXACT_FOURTEEN_PATHS", workflow)
        self.assertNotIn("feature/local-profile-first-launch-ui-20260929", workflow)
        self.assertNotIn("EXACT_MUTATION_SUCCESSOR", workflow)
        self.assertNotIn("local-profile-identity.yml", workflow)
        self.assertNotIn("p0-release-critical-triad-convergence", workflow)
        self.assertNotIn("'acs/local_profile.py'", workflow)
        self.assertNotIn("'tests/test_local_profile.py'", workflow)
        self.assertIn("'acs/version2_local_profile_api.py'", workflow)
        self.assertIn("'tests/test_version2_local_profile_api.py'", workflow)
        self.assertIn("node tests/js/version2_release_bootstrap_dom_test.js", workflow)
        self.assertIn('python-version: "3.12.10"', workflow)

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

    def test_conflict_result_can_refresh_canonical_state_without_closing_dialog(self) -> None:
        source = self.source
        self.assertIn(
            "if (result && result.stateChanged === true) renderProfileState(result);",
            source,
        )

    def test_successful_reconvergence_does_not_close_when_recovery_is_required(self) -> None:
        source = self.source
        self.assertIn(
            "closeOnSuccess && result.recoveryRequired !== true && profileDialog.open",
            source,
        )

    def test_profile_dialog_restores_keyboard_focus_after_close(self) -> None:
        source = self.source
        self.assertIn('let profileReturnFocusId = "";', source)
        self.assertIn('profileReturnFocusId = active && typeof active.id === "string" ? active.id : "";', source)
        self.assertIn('profileDialog.addEventListener("close", function () {', source)
        self.assertIn("if (returnId && focusById(returnId)) return;", source)
        self.assertIn("if (!profileButton.disabled) profileButton.focus({ preventScroll: true });", source)

    def test_first_launch_requires_explicit_save_or_skip(self) -> None:
        source = self.source
        self.assertIn(
            'profileDialog.addEventListener("cancel", function (event) {',
            source,
        )
        self.assertIn(
            "if (profileMutationPending || !profileState || !profileState.exists) {",
            source,
        )
        self.assertIn("event.preventDefault();", source)
        self.assertIn('bridge.profile_create(profileName.value, false)', source)
        self.assertIn('bridge.profile_create("", true)', source)
        self.assertIn('bridge.profile_rename(profileName.value)', source)
        self.assertIn('if (event.key !== "Enter") return;', source)
        self.assertIn('bridge.profile_repair()', source)
        self.assertIn('const recoveryRequired = exists && profileState.recoveryRequired === true', source)
        self.assertIn('profileRepair.hidden = !recoveryRequired', source)
        self.assertIn('openIfMissing && (!result.exists || result.recoveryRequired === true)', source)
        self.assertIn('Профіль відкрито з резервної копії.', source)

    def test_profile_mutations_are_serialized_and_expose_busy_state(self) -> None:
        source = self.source
        self.assertIn("let profileMutationPending = false;", source)
        self.assertIn('profileDialog.setAttribute("aria-busy", profileMutationPending ? "true" : "false")', source)
        self.assertEqual(source.count("if (!beginProfileMutation()) return;"), 3)
        self.assertIn("if (profileMutationPending || !profileState || !profileState.exists)", source)
        self.assertIn("profileSave.disabled = profileMutationPending || recoveryRequired;", source)
        self.assertIn("profileSkip.disabled = profileMutationPending;", source)
        self.assertIn("profileRepair.disabled = profileMutationPending;", source)
        self.assertIn("profileClose.disabled = profileMutationPending;", source)
        self.assertIn("profileName.disabled = profileMutationPending;", source)

    def test_recovery_required_dialog_focuses_repair_action_on_open(self) -> None:
        source = self.source
        self.assertIn(
            "profileState.recoveryRequired === true &&",
            source,
        )
        self.assertIn("!profileRepair.hidden", source)
        self.assertIn("!profileRepair.disabled", source)
        self.assertIn(
            "profileRepair.focus({ preventScroll: true });",
            source,
        )
        self.assertIn(
            "profileName.focus();\n      profileName.select();",
            source,
        )

    def test_recovery_failure_reuses_primary_focus_policy(self) -> None:
        source = self.source
        self.assertIn("function focusProfilePrimaryAction()", source)
        self.assertIn("global.setTimeout(focusProfilePrimaryAction, 0);", source)
        repair = source.split('profileRepair.addEventListener("click"', 1)[1]
        repair = repair.split('profileClose.addEventListener("click"', 1)[0]
        self.assertGreaterEqual(repair.count("focusProfilePrimaryAction();"), 3)
        self.assertNotIn("profileName.focus();", repair)

    def test_recovery_required_state_routes_rename_to_repair(self) -> None:
        source = self.source
        self.assertIn(
            "profileSave.disabled = profileMutationPending || recoveryRequired;",
            source,
        )
        self.assertIn("if (profileState && profileState.recoveryRequired === true)", source)
        self.assertIn(
            'profileRepair.focus({ preventScroll: true });',
            source,
        )
        self.assertIn(
            "Відновіть локальний профіль перед зміною імені.",
            source,
        )
        self.assertIn("profileName.disabled = profileMutationPending;", source)

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
