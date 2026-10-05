from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _blob(path: str) -> str:
    # Respect Git's text filters on Windows while inspecting current worktree
    # bytes; raw hashlib would falsely reject a normal CRLF checkout.
    return subprocess.check_output(
        ["git", "hash-object", "--path=" + path, path], cwd=ROOT, text=True
    ).strip()


def _run_block(source: str, name: str) -> str:
    step = source.split("- name: " + name, 1)[1]
    run = step.split("        run: |\n", 1)[1]
    lines = []
    for line in run.splitlines():
        if line and not line.startswith("          "):
            break
        lines.append(line[10:] if line else "")
    return "\n".join(lines)


class CurrentRemappableSurfaceQualificationTests(unittest.TestCase):
    def test_core_and_dom_gates_use_exact_head_and_execute_new_surfaces(self):
        for filename in ("keybindings-current-apex-core.yml", "keybindings-current-apex-dom-native.yml"):
            with self.subTest(workflow=filename):
                source = (WORKFLOWS / filename).read_text(encoding="utf-8")
                self.assertIn("ref: ${{ github.event.pull_request.head.sha || github.sha }}", source)
                self.assertIn('test "$(git rev-parse HEAD)" = ', source)
                self.assertIn("os: [ubuntu-22.04, windows-2025]", source)
                for path in ("acs/version2_profile.py", "acs/version2_final_product_profile.py",
                             "tests/js/toolbar_keymap_test_support.js"):
                    self.assertIn("- '" + path + "'", source)
                for script in ("books_training_surface_dom_test.js", "version2_local_profile_dom_test.js",
                               "pgn_surface_dom_test.js", "stage1_terminal_keymap_dom_test.js"):
                    self.assertIn("node tests/js/" + script, source)
                for module in ("test_keymap_profile_ingress_current", "test_version2_windows_composition_profile",
                               "test_current_remappable_surfaces_qualification"):
                    self.assertIn("tests." + module, source)
                self.assertNotIn("continue-on-error", source)
                if filename.endswith("core.yml"):
                    self.assertIn("python -m pytest -q", source)
                    for path in ("tests/test_ui_keymap_service.py", "tests/test_version2_final_product_composition.py"):
                        self.assertIn(path, source)

    def test_service_successor_requires_paired_runtime_and_function_test_bytes(self):
        source = (WORKFLOWS / "keybindings-current-apex-dom-native.yml").read_text(encoding="utf-8")
        values = dict(re.findall(r"^          (\w+_BLOB): ([0-9a-f]{40})$", source, re.M))
        self.assertEqual(values["CURRENT_SERVICE_BLOB"], _blob("acs/ui_keymap_service.py"))
        self.assertEqual(values["CURRENT_SERVICE_TEST_BLOB"], _blob("tests/test_ui_keymap_service.py"))
        match = re.search(r'case "\$service_pair" in\n.*?\n          esac', source, re.S)
        self.assertIsNotNone(match)
        valid = values["CURRENT_SERVICE_BLOB"] + ":" + values["CURRENT_SERVICE_TEST_BLOB"]
        for pair, accepted in ((valid, True), (valid.split(":")[0] + ":" + "0" * 40, False)):
            result = subprocess.run(["bash", "-c", "set -eu\n" + match.group(0)],
                                    env={**os.environ, **values, "service_pair": pair},
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode == 0, accepted, result.stderr)

    def test_pgn_exact_successor_cases_accept_current_blobs_and_reject_unknown_bytes(self):
        source = (WORKFLOWS / "d01-pgn-workspace-webview.yml").read_text(encoding="utf-8")
        for variable, path in (
            ("actions_actual", "acs/full_product_actions.py"),
            ("web_index_actual", "web/index.html"),
            ("dom_test_actual", "tests/js/pgn_surface_dom_test.js"),
            ("pgn_surface_actual", "web/full_product_pgn.js"),
        ):
            with self.subTest(path=path):
                match = re.search(r'case "\$' + variable + r'" in\n.*?\n          esac', source, re.S)
                self.assertIsNotNone(match)
                script = "set -eu\n" + match.group(0)
                for sha, success in ((_blob(path), True), ("0" * 40, False)):
                    result = subprocess.run(["bash", "-c", script], env={**os.environ, variable: sha},
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, success, result.stderr)
        self.assertIn(_blob("tests/js/toolbar_keymap_test_support.js"), source)
        self.assertIn(_blob("acs/keybindings.py") + ":" + _blob("acs/ui_native_menu.py"), source)

    def test_recovery_gate_freezes_source_scope_but_runs_on_broader_descendants(self):
        source = (WORKFLOWS / "keymap-recovery-web-accessibility.yml").read_text(encoding="utf-8")
        script = _run_block(source, "Verify exact PR-head ancestry and bounded scope")
        self.assertIn('git diff --name-only "$RECOVERY_BASE_SHA" "$RECOVERY_SOURCE_SHA"', script)
        self.assertNotIn('git diff --name-only "$EVENT_BASE_SHA" HEAD', script)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        env = {
            **os.environ, "EVENT_HEAD_SHA": head, "GITHUB_SHA": head,
            "EVENT_BASE_SHA": "86b963d0868ac9f8dc201921f0aab382aa892d02",
            "RECOVERY_BASE_SHA": "61cffeec4d14e97746148de787e7990ef58639f8",
            "RECOVERY_SOURCE_SHA": "4707e3cbbd2bb33405320162481198ad4ce06293",
        }
        result = subprocess.run(["bash", "-c", script], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        env["EVENT_HEAD_SHA"] = "0" * 40
        result = subprocess.run(["bash", "-c", script], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_classroom_gate_pairs_the_remapped_surface_with_its_actual_regressions(self):
        source = (WORKFLOWS / "d01-teacher-classroom-webview.yml").read_text(encoding="utf-8")
        for path in ("web/full_product_classroom.js", "tests/js/classroom_surface_dom_test.js",
                     "tests/test_dev1_classroom_web_asset.py"):
            self.assertIn(_blob(path), source)
        self.assertIn('test "$classroom_asset_test" = "$(git rev-parse "$d01_owner:', source)
        self.assertIn("node tests/js/classroom_surface_dom_test.js", source)

    def test_persisted_recovery_source_is_retained_without_restricting_descendant_path_count(self):
        source = (WORKFLOWS / "keymap-persisted-read-io-recovery.yml").read_text(encoding="utf-8")
        script = _run_block(source, "Verify exact PR-head ancestry and bounded scope")
        self.assertNotIn('git diff --name-only "$EVENT_BASE_SHA" HEAD', script)
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        env = {
            **os.environ, "EVENT_HEAD_SHA": head, "GITHUB_SHA": head,
            "EVENT_BASE_SHA": "6a59576a082bc5dcc6799f8bc7bc228e7a258160",
            "RECOVERY_BASE_SHA": "59486e2c9eff903e416d59a0e7c349c22ee2111d",
            "RECOVERY_SOURCE_SHA": "c2da619b14445056215f2eed35f531994a805064",
        }
        result = subprocess.run(["bash", "-c", script], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("python -m pytest -q tests/test_ui_keymap_service.py", source)

    def test_package_gates_accept_only_exact_current_source_test_pairs(self):
        gates = (
            ("w6-v2-release-payload-current-assembler.yml", "payload_pair",
             "RESOURCE_PAYLOAD_BLOB", "acs/version2_release_payload.py",
             "RESOURCE_PAYLOAD_TEST_BLOB", "tests/test_version2_release_payload.py"),
            ("w6-v2-package-preflight-current-runtime.yml", "preflight_pair",
             "RESOURCE_PREFLIGHT_BLOB", "acs/version2_package_preflight.py",
             "RESOURCE_PREFLIGHT_TEST_BLOB", "tests/test_version2_package_preflight.py"),
            ("w6-v2-package-assembler.yml", "resource_pair",
             "RESOURCE_PREFLIGHT_BLOB", "acs/version2_package_preflight.py",
             "RESOURCE_ASSEMBLER_TEST_BLOB", "tests/test_version2_package_assembler.py"),
        )
        for filename, variable, runtime_var, runtime_path, test_var, test_path in gates:
            with self.subTest(workflow=filename):
                source = (WORKFLOWS / filename).read_text(encoding="utf-8")
                values = dict(re.findall(r"^  (\w+_BLOB): ([0-9a-f]{40})$", source, re.M))
                self.assertEqual(values[runtime_var], _blob(runtime_path))
                self.assertEqual(values[test_var], _blob(test_path))
                match = re.search(r'case "\$' + variable + r'" in\n.*?\n\s+esac', source, re.S)
                self.assertIsNotNone(match)
                pair = values[runtime_var] + ":" + values[test_var]
                for candidate, accepted in ((pair, True), (values[runtime_var] + ":" + "0" * 40, False)):
                    result = subprocess.run(["bash", "-c", "set -eu\n" + match.group(0)],
                                            env={**os.environ, **values, variable: candidate},
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, accepted, result.stderr)
                self.assertNotIn("continue-on-error", source)


if __name__ == "__main__":
    unittest.main()
