import contextlib
import io
from pathlib import Path
import re
import runpy
import sys
import types
import unittest
from unittest import mock


class PortableLauncherSourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.root = root
        cls.source = (root / "packaging" / "portable_launcher.c").read_text(encoding="utf-8")
        cls.runtime = (root / "run_accessible_chess.py").read_text(encoding="utf-8")
        cls.workflow = (
            root / ".github" / "workflows" / "p0-user-oneclick-portable-launcher.yml"
        ).read_text(encoding="utf-8")

    def test_uses_native_child_process_and_package_local_appdata(self):
        for token in (
            "CreateProcessW(",
            "SetEnvironmentVariableW(L\"LOCALAPPDATA\"",
            "L\"App\"",
            "L\"data\"",
            "L\"launch-report.txt\"",
            "CREATE_UNICODE_ENVIRONMENT",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.source)

    def test_user_failure_is_native_accessible_popup_and_utf8_report(self):
        self.assertIn("MessageBoxW(", self.source)
        self.assertIn("CP_UTF8", self.source)
        self.assertIn("STATUS: FAILED_EARLY_EXIT", self.source)
        self.assertIn("CHILD_EXIT_CODE", self.source)
        self.assertIn("CHILD_EXIT_REASON", self.source)
        self.assertIn("USER_NVDA_PROVEN: NO", self.source)

    def test_packaged_bootstrap_exit_reasons_are_stable_and_synchronized(self):
        contracts = (
            (
                "ACCESSIBILITY_HOST_INIT_EXIT_CODE",
                71,
                "ACCESSIBILITY_HOST_INIT_FAILED",
            ),
            (
                "SAFE_LOCAL_SERVER_INIT_EXIT_CODE",
                72,
                "SAFE_LOCAL_SERVER_INIT_FAILED",
            ),
            (
                "RELEASE_UI_STARTUP_EXIT_CODE",
                73,
                "RELEASE_UI_STARTUP_FAILED",
            ),
        )
        for name, code, reason in contracts:
            with self.subTest(name=name):
                self.assertRegex(
                    self.runtime,
                    re.compile(rf"^{name}\s*=\s*{code}\s*$", re.MULTILINE),
                )
                self.assertRegex(
                    self.source,
                    re.compile(rf"^#define\s+{name}\s+{code}\s*$", re.MULTILINE),
                )
                self.assertIn(reason, self.source)
                self.assertIn(name, self.runtime)
        self.assertIn("raise SystemExit(exit_code)", self.runtime)
        self.assertIn("UNKNOWN_EARLY_EXIT", self.source)

    def _run_packaged_bootstrap(
        self,
        *,
        host_ok: bool,
        server_ok: bool,
        renderer_raises: bool = False,
        host_raises: bool = False,
        server_raises: bool = False,
        release_ui_raises: bool = False,
    ) -> tuple[object, str]:
        accessibility = types.ModuleType("acs.webview2_accessibility")

        def enable_renderer_accessibility() -> None:
            if renderer_raises:
                raise RuntimeError("synthetic renderer accessibility bootstrap failure")

        def install_host_patch() -> bool:
            if host_raises:
                raise RuntimeError("synthetic accessibility host bootstrap failure")
            return host_ok

        accessibility.enable_webview2_renderer_accessibility = enable_renderer_accessibility
        accessibility.install_pywebview_accessibility_host_patch = install_host_patch
        safe_server = types.ModuleType("acs.webview_safe_server")

        def install_safe_server() -> bool:
            if server_raises:
                raise RuntimeError("synthetic safe local server bootstrap failure")
            return server_ok

        safe_server.install_pywebview_safe_local_server_port = install_safe_server
        release_ui = types.ModuleType("acs.stage1_release_ui")

        def release_main() -> None:
            if release_ui_raises:
                raise RuntimeError("synthetic release UI startup failure")

        release_ui.main = release_main
        stderr = io.StringIO()

        with (
            mock.patch.dict(
                sys.modules,
                {
                    "acs.webview2_accessibility": accessibility,
                    "acs.webview_safe_server": safe_server,
                    "acs.stage1_release_ui": release_ui,
                },
            ),
            mock.patch.object(sys, "argv", [str(self.root / "run_accessible_chess.py")]),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            runpy.run_path(str(self.root / "run_accessible_chess.py"), run_name="__main__")
        return raised.exception.code, stderr.getvalue()

    def test_real_entrypoint_reports_renderer_accessibility_exception_code(self):
        code, stderr = self._run_packaged_bootstrap(
            host_ok=True,
            server_ok=True,
            renderer_raises=True,
        )
        self.assertEqual(code, 71)
        self.assertIn(
            "Accessible WebView2 renderer accessibility could not be initialized.",
            stderr,
        )
        self.assertIn("synthetic renderer accessibility bootstrap failure", stderr)

    def test_real_entrypoint_reports_accessibility_host_bootstrap_code(self):
        code, stderr = self._run_packaged_bootstrap(host_ok=False, server_ok=True)
        self.assertEqual(code, 71)
        self.assertIn("Accessible WebView2 host could not be initialized.", stderr)

    def test_real_entrypoint_reports_accessibility_host_exception_code(self):
        code, stderr = self._run_packaged_bootstrap(
            host_ok=True,
            server_ok=True,
            host_raises=True,
        )
        self.assertEqual(code, 71)
        self.assertIn("Accessible WebView2 host could not be initialized.", stderr)
        self.assertIn("synthetic accessibility host bootstrap failure", stderr)

    def test_real_entrypoint_reports_safe_local_server_bootstrap_code(self):
        code, stderr = self._run_packaged_bootstrap(host_ok=True, server_ok=False)
        self.assertEqual(code, 72)
        self.assertIn("Accessible WebView2 local server could not be initialized.", stderr)

    def test_real_entrypoint_reports_safe_local_server_exception_code(self):
        code, stderr = self._run_packaged_bootstrap(
            host_ok=True,
            server_ok=True,
            server_raises=True,
        )
        self.assertEqual(code, 72)
        self.assertIn("Accessible WebView2 local server could not be initialized.", stderr)
        self.assertIn("synthetic safe local server bootstrap failure", stderr)

    def test_real_entrypoint_reports_release_ui_startup_code_and_traceback(self):
        code, stderr = self._run_packaged_bootstrap(
            host_ok=True,
            server_ok=True,
            release_ui_raises=True,
        )
        self.assertEqual(code, 73)
        self.assertIn("Accessible Chess release UI could not be started.", stderr)
        self.assertIn("synthetic release UI startup failure", stderr)

    def test_report_handle_is_launcher_local_and_root_is_validated_first(self):
        self.assertNotIn("STARTF_USESTDHANDLES", self.source)
        self.assertNotIn("bInheritHandle = TRUE", self.source)
        self.assertIn(
            "            FALSE,\n            CREATE_UNICODE_ENVIRONMENT,",
            self.source,
        )
        root_check = self.source.index("if (!ac_direct_directory(g_root))")
        report_open = self.source.index("report = ac_open_report();")
        self.assertLess(root_check, report_open)

    def test_report_open_retries_only_bounded_sharing_violation(self):
        for token in (
            "#define AC_REPORT_RETRY_MS 100",
            "#define AC_REPORT_RETRY_COUNT 40",
            "ERROR_SHARING_VIOLATION",
            "Sleep(AC_REPORT_RETRY_MS)",
            "SetLastError(error)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.source)
        self.assertIn("attempt <= AC_REPORT_RETRY_COUNT", self.source)

    def test_windows_workflow_exercises_overlapping_root_launchers(self):
        for token in (
            "$first = Start-Process -FilePath $launcher",
            "Start-Sleep -Milliseconds 100",
            "$second = Start-Process -FilePath $launcher",
            "$first.WaitForExit(10000)",
            "$second.WaitForExit(10000)",
            "Overlapping second portable launcher smoke failed",
            "Launch report missing after overlapping launchers",
            "Start-Sleep -Seconds 5",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.workflow)
        first_launch = self.workflow.index("$first = Start-Process -FilePath $launcher")
        second_launch = self.workflow.index("$second = Start-Process -FilePath $launcher")
        first_wait = self.workflow.index("$first.WaitForExit(10000)")
        self.assertLess(first_launch, second_launch)
        self.assertLess(second_launch, first_wait)

    def test_no_shell_execution_path_is_introduced(self):
        for forbidden in (
            "ShellExecuteW(",
            "ShellExecuteExW(",
            "WinExec(",
            "system(",
            "_wsystem(",
            "CreateProcessA(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.source)

    def test_runtime_reparse_boundaries_fail_closed(self):
        self.assertIn("FILE_ATTRIBUTE_REPARSE_POINT", self.source)
        self.assertIn("ac_direct_directory(g_root)", self.source)
        self.assertIn("ac_direct_directory(g_app_dir)", self.source)
        self.assertIn("ac_direct_directory(g_data)", self.source)
        self.assertIn("ac_direct_file(g_core)", self.source)


if __name__ == "__main__":
    unittest.main()
