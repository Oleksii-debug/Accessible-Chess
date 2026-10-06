from pathlib import Path
import unittest


class PortableLauncherWindowReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.source = (root / "packaging" / "portable_launcher.c").read_text(encoding="utf-8")
        cls.release_ui = (root / "acs" / "stage1_release_ui.py").read_text(encoding="utf-8")
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

    def test_launcher_title_matches_canonical_release_window(self):
        self.assertIn('L"Accessible Chess"', self.source)
        self.assertIn(
            'window = webview.create_window(\n        "Accessible Chess",',
            self.release_ui,
        )
        self.assertIn("'acs/stage1_release_ui.py'", self.workflow)

    def test_process_liveness_alone_is_not_success(self):
        self.assertNotIn("CHILD_RUNNING_AFTER_STARTUP_OBSERVATION", self.source)
        self.assertIn("STATUS: STARTUP_WINDOW_READY", self.source)
        self.assertIn("USER_WINDOW_PROVEN: YES", self.source)
        self.assertIn("USER_NVDA_PROVEN: NO", self.source)
        self.assertIn("CHILD_PROCESS_ID: ", self.source)
        self.assertIn("g_process.dwProcessId", self.source)

    def test_package_local_state_has_one_live_process_owner(self):
        for token in (
            'L".accessible-chess-instance.lock"',
            "static HANDLE ac_open_instance_lock(void)",
            "GENERIC_READ | GENERIC_WRITE",
            "FILE_ATTRIBUTE_HIDDEN | FILE_FLAG_OPEN_REPARSE_POINT",
            "file_info.nNumberOfLinks != 1",
            "g_instance_lock = ac_open_instance_lock();",
            "ERROR_SHARING_VIOLATION",
            "CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED",
            "DuplicateHandle(",
            "g_process.hProcess",
            "DUPLICATE_SAME_ACCESS",
            "ResumeThread(g_process.hThread)",
            "CloseHandle(g_instance_lock)",
            "PACKAGE_DATA_OWNER: SINGLE_INSTANCE_GUARD_ACTIVE",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.source)

        lock = self.source.index("g_instance_lock = ac_open_instance_lock();")
        report = self.source.index("report = ac_open_report();")
        create = self.source.index("if (!CreateProcessW(")
        transfer = self.source.index("if (!DuplicateHandle(")
        resume = self.source.index("resume_result = ResumeThread(g_process.hThread);")
        release_parent = self.source.index("CloseHandle(g_instance_lock);", resume)
        self.assertLess(lock, report)
        self.assertLess(report, create)
        self.assertLess(create, transfer)
        self.assertLess(transfer, resume)
        self.assertLess(resume, release_parent)

    def test_duplicate_launch_coalesces_without_touching_shared_report(self):
        lock = self.source.index("g_instance_lock = ac_open_instance_lock();")
        duplicate = self.source.index("error == ERROR_SHARING_VIOLATION", lock)
        coalesce = self.source.index("ExitProcess(0);", duplicate)
        report = self.source.index("report = ac_open_report();", lock)
        self.assertLess(lock, duplicate)
        self.assertLess(duplicate, coalesce)
        self.assertLess(coalesce, report)

    def test_instance_lock_is_not_inherited_wholesale(self):
        self.assertIn(
            "            FALSE,\n            CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED,",
            self.source,
        )
        self.assertIn("DuplicateHandle(", self.source)
        self.assertIn("DUPLICATE_SAME_ACCESS", self.source)
        self.assertNotIn("bInheritHandle = TRUE", self.source)

    def test_transient_window_must_remain_stable_before_success(self):
        for token in (
            "ULONGLONG ready_started = 0;",
            "BOOL ready_tracking = FALSE;",
            "ready_started = now;",
            "ready_tracking = TRUE;",
            "now - ready_started >= AC_STARTUP_READY_STABILITY_MS",
            "ready_tracking = FALSE;",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.source)

    def test_visible_window_must_be_responsive_before_success(self):
        for token in (
            "#define AC_WINDOW_RESPONSE_PROBE_MS 100",
            "SendMessageTimeoutW(",
            "WM_NULL",
            "SMTO_ABORTIFHUNG | SMTO_BLOCK",
            "AC_WINDOW_RESPONSE_PROBE_MS",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.source)

    def test_startup_observation_is_bounded_and_fail_closed(self):
        for token in (
            "#define AC_STARTUP_POLL_MS 100",
            "#define AC_STARTUP_READY_STABILITY_MS 500",
            "#define AC_STARTUP_WINDOW_TIMEOUT_MS 30000",
            "#define AC_TIMEOUT_CLEANUP_WAIT_MS 5000",
            "WaitForSingleObject(g_process.hProcess, AC_STARTUP_POLL_MS)",
            "startup_started = GetTickCount64();",
            "now = GetTickCount64();",
            "now - startup_started >= AC_STARTUP_WINDOW_TIMEOUT_MS",
            "STATUS: FAILED_STARTUP_TIMEOUT",
            "USER_WINDOW_PROVEN: NO",
            "TerminateProcess(g_process.hProcess, ERROR_TIMEOUT)",
            "WaitForSingleObject(g_process.hProcess, AC_TIMEOUT_CLEANUP_WAIT_MS)",
            "TIMEOUT_CHILD_CLEANUP: PASS",
            "CHILD_LEFT_RUNNING: NO",
            "ExitProcess(ERROR_TIMEOUT)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.source)

    def test_early_exit_remains_failure_before_window_proof(self):
        window_ready = self.source.index("window_ready = ac_has_ready_window(g_process.dwProcessId);")
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
            "CHILD_PROCESS_ID:",
            "Get-Process -Id $reportedChildPid",
            "$reportedChild.Path -eq $expectedChildPath",
            "ACS_SMOKE_NO_WINDOW",
            "ACS_SMOKE_FLASH_WINDOW",
            "ACS_SMOKE_HUNG_WINDOW",
            "PeekMessageW(",
            "STATUS: FAILED_STARTUP_TIMEOUT",
            "TIMEOUT_CHILD_CLEANUP: PASS",
            "CHILD_LEFT_RUNNING: NO",
            ".accessible-chess-instance.lock",
            "[IO.File]::Open(",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.workflow)

    def test_windows_gate_checks_out_and_proves_exact_candidate(self):
        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha || github.sha }}",
            self.workflow,
        )
        self.assertIn("Prove exact candidate", self.workflow)
        self.assertIn("git rev-parse HEAD", self.workflow)


if __name__ == "__main__":
    unittest.main()
