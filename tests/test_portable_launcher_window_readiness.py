from pathlib import Path
import unittest


class PortableLauncherWindowReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.source = (root / "packaging" / "portable_launcher.c").read_text(encoding="utf-8")
        cls.workflow = (
            root / ".github" / "workflows" / "p0-user-oneclick-portable-launcher.yml"
        ).read_text(encoding="utf-8")

    def test_success_requires_visible_window_owned_by_exact_child(self):
        for token in (
            "EnumWindows(ac_find_ready_window",
            "GetWindowThreadProcessId(window, &process_id)",
            "process_id != search->process_id",
            "IsWindowVisible(window)",
            "GetWindowTextW(window",
            'L"Accessible Chess"',
            "ac_has_ready_window(g_process.dwProcessId)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.source)

    def test_process_liveness_alone_is_not_success(self):
        self.assertNotIn("CHILD_RUNNING_AFTER_STARTUP_OBSERVATION", self.source)
        self.assertIn("STATUS: STARTUP_WINDOW_READY", self.source)
        self.assertIn("USER_WINDOW_PROVEN: YES", self.source)
        self.assertIn("USER_NVDA_PROVEN: NO", self.source)

    def test_startup_observation_is_bounded_and_fail_closed(self):
        for token in (
            "#define AC_STARTUP_POLL_MS 100",
            "#define AC_STARTUP_WINDOW_TIMEOUT_MS 30000",
            "WaitForSingleObject(g_process.hProcess, AC_STARTUP_POLL_MS)",
            "STATUS: FAILED_STARTUP_TIMEOUT",
            "USER_WINDOW_PROVEN: NO",
            "CHILD_LEFT_RUNNING: YES",
            "ExitProcess(ERROR_TIMEOUT)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.source)

    def test_early_exit_remains_failure_before_window_proof(self):
        window_ready = self.source.index("if (ac_has_ready_window(g_process.dwProcessId))")
        early_exit = self.source.index("STATUS: FAILED_EARLY_EXIT")
        self.assertLess(early_exit, window_ready)
        self.assertIn("CHILD_EXIT_REASON", self.source)
        self.assertIn("USER_WINDOW_PROVEN: NO", self.source[early_exit:window_ready])

    def test_windows_smoke_requires_real_window_and_timeout_regression(self):
        for token in (
            "CreateWindowExW(",
            'L"Accessible Chess"',
            "user32.lib",
            "STATUS: STARTUP_WINDOW_READY",
            "USER_WINDOW_PROVEN: YES",
            "ACS_SMOKE_NO_WINDOW",
            "STATUS: FAILED_STARTUP_TIMEOUT",
            "CHILD_LEFT_RUNNING: YES",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.workflow)


if __name__ == "__main__":
    unittest.main()
