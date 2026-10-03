from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SoundSettingsWebViewTests(unittest.TestCase):
    def test_actual_launcher_resource_authority_ships_sound_surface_before_bootstrap(self) -> None:
        source = (ROOT / "acs" / "version2_education_mutation_release.py").read_text(encoding="utf-8")
        sound = '("V2 sound settings surface", root / "full_product_sound_settings.js")'
        bootstrap = '("V2 final-product bootstrap", root / "version2_final_product_bootstrap.js")'
        self.assertIn(sound, source)
        self.assertIn(bootstrap, source)
        self.assertLess(source.index(sound), source.index(bootstrap))

    def test_sound_surface_uses_semantic_native_controls_and_fail_closed_state(self) -> None:
        source = (ROOT / "web" / "full_product_sound_settings.js").read_text(encoding="utf-8")
        for required in (
            'root.id = "sound-profile-settings"',
            'masterEnabled.type = "checkbox"',
            'masterVolume.type = "number"',
            'preview.type = "button"',
            'documentRef.createElement("select")',
            'sound_choices',
            'sound_id: choice.value',
            'sound-event-" + safeId + "-sound"',
            'packHeading.id = "sound-packs-heading"',
            'packStatus.id = "sound-packs-status"',
            'String(item.provenance || "")',
            'item.rights_auditable === true',
            'String(item.rights_source_uri || "")',
            'String(item.license_uri || "")',
            'item.catalog_rights_auditable === true',
            'String(item.catalog_rights_source_uri || "")',
            'String(item.catalog_license_uri || "")',
            'Auditable rights evidence for the catalog candidate is unavailable.',
            'invoke("select_pack", {pack_id: packId}, group.id)',
            'invoke("install_pack", {pack_id: packId, activate: true}, group.id)',
            'invoke("uninstall_pack", {pack_id: packId}, group.id)',
            'invoke("select_pack", {pack_id: "classic"}, packHeading.id)',
            'snapshot.writes_blocked === true',
            'bridge.sound_settings_snapshot',
            'bridge.sound_settings_command',
            'AccessibleChessP0Runtime.exposeAnnouncement',
            'restoreFocus(restoreFocusId, restoreFocusFallbackId)',
            'usableFocusTarget',
            'sound-pack-classic-select',
            'Current state was refreshed',
            'group.id = "sound-pack-" + safeId',
            'const safeId = packId;',
            'group.tabIndex = -1',
            'setAttribute("for"',
            'status.id = "sound-profile-settings-status"',
        ):
            self.assertIn(required, source)
        self.assertNotIn('status.setAttribute("role", "status")', source)
        self.assertNotIn('status.setAttribute("aria-live"', source)
        self.assertNotIn("innerHTML", source)

    def test_executable_sound_surface_contract(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is unavailable")
        completed = subprocess.run(
            [node, str(ROOT / "tests" / "js" / "sound_settings_surface_test.js")],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("SOUND_SETTINGS_WEBVIEW=PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
