from pathlib import Path
import unittest


class PortableLauncherSourceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).resolve().parents[1] / "packaging" / "portable_launcher.c").read_text(
            encoding="utf-8"
        )

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
