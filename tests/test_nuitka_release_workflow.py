from __future__ import annotations

from pathlib import Path
import unittest


WORKFLOW = Path('.github/workflows/windows-nuitka-standalone.yml')


class NuitkaReleaseWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding='utf-8')

    def test_is_manual_and_uses_standalone_before_any_onefile_path(self) -> None:
        self.assertIn('workflow_dispatch:', self.text)
        self.assertIn("'--mode=standalone'", self.text)
        self.assertNotIn("'--mode=onefile'", self.text)
        self.assertNotIn('PyInstaller', self.text)

    def test_builds_without_console_and_includes_webview_runtime(self) -> None:
        self.assertIn("'--windows-console-mode=disable'", self.text)
        self.assertIn("'--include-data-dir=web=web'", self.text)
        self.assertIn("'--include-package=webview'", self.text)
        self.assertIn("'--include-module=webview.platforms.edgechromium'", self.text)

    def test_runs_diagnostic_and_webview_startup_smoke(self) -> None:
        self.assertIn("--diagnostic", self.text)
        self.assertIn('WebView2 standalone startup smoke', self.text)
        self.assertIn('Start-Process $exe', self.text)
        self.assertIn('if ($p.HasExited)', self.text)

    def test_rejects_raw_python_sources_in_distribution(self) -> None:
        self.assertIn('prohibit_python_source=True', self.text)
        self.assertIn("'.py','.pyc','.pyo'", self.text)
        self.assertIn('Raw Python source/bytecode leaked', self.text)

    def test_generates_manifest_checksums_and_truthful_nvda_status(self) -> None:
        self.assertIn('RELEASE-MANIFEST.json', self.text)
        self.assertIn('Get-FileHash $exe -Algorithm SHA256', self.text)
        self.assertIn('Get-FileHash $manifest -Algorithm SHA256', self.text)
        self.assertIn('NVDA TEST CANDIDATE — WAITING FOR USER TEST', self.text)
        self.assertNotIn('NVDA VERIFIED', self.text)

    def test_does_not_claim_signing_or_stockfish_release_readiness(self) -> None:
        self.assertIn('signing_status=UNSIGNED_INTERNAL_BUILD', self.text)
        self.assertIn('stockfish_bundle_status=NOT_RELEASE_GATED_BY_THIS_WORKFLOW', self.text)


if __name__ == '__main__':
    unittest.main()
