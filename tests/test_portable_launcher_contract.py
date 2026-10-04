from pathlib import Path
import unittest


class PortableLauncherSourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.source = (root / "packaging" / "portable_launcher.c").read_text(encoding="utf-8")
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
        self.assertIn("USER_NVDA_PROVEN: NO", self.source)

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
