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
        report_start = cls.source.index("static HANDLE ac_open_report(void)")
        report_end = cls.source.index("static void ac_prepare_paths(void)", report_start)
        cls.report_open = cls.source[report_start:report_end]

    def test_uses_native_child_process_and_package_local_appdata(self):
        for token in (
            "CreateProcessW(",
            "SetEnvironmentVariableW(L\"LOCALAPPDATA\"",
            "L\"App\"",
            "L\"data\"",
            "L\"launch-report.txt\"",
            "CHILD_PROCESS_ID: ",
            "g_process.dwProcessId",
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

    def test_startup_timeout_retires_child_before_fallible_report_writes(self):
        start = self.source.index("static void ac_fail_startup_timeout(HANDLE report)")
        end = self.source.index("void WINAPI wWinMainCRTStartup(void)", start)
        timeout = self.source[start:end]

        self.assertIn("#define AC_TIMEOUT_CLEANUP_WAIT_MS 5000", self.source)
        self.assertIn(
            "TerminateProcess(g_process.hProcess, ERROR_TIMEOUT)",
            timeout,
        )
        self.assertIn(
            "WaitForSingleObject(g_process.hProcess, AC_TIMEOUT_CLEANUP_WAIT_MS)",
            timeout,
        )
        self.assertIn('L"TIMEOUT_CHILD_CLEANUP: PASS"', timeout)
        self.assertIn('L"TIMEOUT_CHILD_CLEANUP: FAILED"', timeout)
        self.assertIn('L"CHILD_LEFT_RUNNING: NO"', timeout)
        self.assertIn('L"CHILD_LEFT_RUNNING: YES"', timeout)
        self.assertLess(
            timeout.index("TerminateProcess(g_process.hProcess, ERROR_TIMEOUT)"),
            timeout.index('ac_write_line(report, L"STATUS: FAILED_STARTUP_TIMEOUT")'),
        )

        self.assertIn("'TIMEOUT_CHILD_CLEANUP: PASS'", self.workflow)
        self.assertIn("'CHILD_LEFT_RUNNING: NO'", self.workflow)
        self.assertIn(".accessible-chess-instance.lock", self.workflow)
        self.assertIn("[IO.File]::Open(", self.workflow)

    def test_report_write_failure_retires_owned_child_before_popup_and_exit(self):
        retire_start = self.source.index(
            "static BOOL ac_retire_owned_child(DWORD code)"
        )
        retire_end = self.source.index(
            "static void ac_report_write_fail(HANDLE report, DWORD code)",
            retire_start,
        )
        retire = self.source[retire_start:retire_end]
        for token in (
            "WaitForSingleObject(g_process.hProcess, 0)",
            "TerminateProcess(g_process.hProcess, stable_code)",
            "AC_TIMEOUT_CLEANUP_WAIT_MS",
            "WAIT_OBJECT_0",
        ):
            with self.subTest(token=token):
                self.assertIn(token, retire)

        fail_start = retire_end
        fail_end = self.source.index(
            "static void ac_write_utf8(HANDLE handle",
            fail_start,
        )
        failure = self.source[fail_start:fail_end]
        self.assertIn(
            "BOOL child_stopped = ac_retire_owned_child(stable_code);",
            failure,
        )
        self.assertIn("ac_close_child_process_handle();", failure)
        self.assertIn("The main Accessible Chess process may still be running.", failure)
        self.assertLess(
            failure.index("ac_retire_owned_child(stable_code)"),
            failure.index("MessageBoxW("),
        )
        self.assertLess(
            failure.index("ac_close_child_process_handle();"),
            failure.index("MessageBoxW("),
        )
        self.assertLess(failure.index("MessageBoxW("), failure.index("ExitProcess(stable_code)"))

        fail_generic_start = self.source.index(
            "static void ac_fail(HANDLE report, const WCHAR *stage, DWORD code)"
        )
        fail_generic_end = self.source.index(
            "static BOOL ac_direct_directory",
            fail_generic_start,
        )
        generic_failure = self.source[fail_generic_start:fail_generic_end]
        self.assertIn(
            "BOOL child_stopped = ac_retire_owned_child(code == 0 ? ERROR_GEN_FAILURE : code);",
            generic_failure,
        )
        self.assertLess(
            generic_failure.index("ac_retire_owned_child("),
            generic_failure.index("ac_write_line(report"),
        )
        self.assertIn("ac_close_child_process_handle();", generic_failure)
        self.assertLess(
            generic_failure.index("ac_write_line(report"),
            generic_failure.index("ac_close_child_process_handle();"),
        )
        self.assertLess(
            generic_failure.index("ac_close_child_process_handle();"),
            generic_failure.index("MessageBoxW("),
        )

        main = self.source[self.source.index("void WINAPI wWinMainCRTStartup(void)") :]
        self.assertNotIn("CloseHandle(g_process.hProcess);", main)
        for stage in (
            'L"package-local data ownership transfer"',
            'L"package-local data directory guard transfer"',
            'L"core process resume"',
            'L"child process identity report"',
            'L"early child exit-code read"',
            'L"startup window observation"',
        ):
            with self.subTest(stage=stage):
                stage_at = main.index(stage)
                prefix = main[max(0, stage_at - 240):stage_at]
                self.assertNotIn("ac_close_child_process_handle();", prefix)
                self.assertNotIn("TerminateProcess(g_process.hProcess", prefix)

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
        release_ui_raises: bool = False,
        renderer_raises: bool = False,
        host_install_raises: bool = False,
        server_install_raises: bool = False,
        safe_port_raises: bool = False,
        accessibility_module_missing: bool = False,
        safe_server_module_missing: bool = False,
    ) -> tuple[object, str]:
        accessibility = types.ModuleType("acs.webview2_accessibility")

        def enable_renderer_accessibility() -> None:
            if renderer_raises:
                raise ImportError("synthetic renderer accessibility initialization failure")

        accessibility.enable_webview2_renderer_accessibility = enable_renderer_accessibility

        def host_install():
            if host_install_raises:
                raise ImportError("synthetic accessibility host import failure")
            return host_ok

        accessibility.install_pywebview_accessibility_host_patch = host_install
        safe_server = types.ModuleType("acs.webview_safe_server")

        class SafeLocalServerPortError(RuntimeError):
            pass

        safe_server.SafeLocalServerPortError = SafeLocalServerPortError

        def server_install():
            if server_install_raises:
                raise ImportError("synthetic webview import failure")
            return server_ok

        safe_server.install_pywebview_safe_local_server_port = server_install
        release_ui = types.ModuleType("acs.stage1_release_ui")

        def release_main() -> None:
            if safe_port_raises:
                raise SafeLocalServerPortError("synthetic safe-port exhaustion")
            if release_ui_raises:
                raise RuntimeError("synthetic release UI startup failure")

        release_ui.main = release_main
        stderr = io.StringIO()

        with (
            mock.patch.dict(
                sys.modules,
                {
                    "acs.webview2_accessibility": (
                        None if accessibility_module_missing else accessibility
                    ),
                    "acs.webview_safe_server": (
                        None if safe_server_module_missing else safe_server
                    ),
                    "acs.stage1_release_ui": release_ui,
                },
            ),
            mock.patch.object(sys, "argv", [str(self.root / "run_accessible_chess.py")]),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            runpy.run_path(str(self.root / "run_accessible_chess.py"), run_name="__main__")
        return raised.exception.code, stderr.getvalue()

    def test_real_entrypoint_classifies_missing_accessibility_support_module(self):
        code, stderr = self._run_packaged_bootstrap(
            host_ok=True,
            server_ok=True,
            accessibility_module_missing=True,
        )
        self.assertEqual(code, 71)
        self.assertIn(
            "Accessible WebView2 renderer accessibility support could not be loaded.",
            stderr,
        )

    def test_real_entrypoint_classifies_missing_safe_server_support_module(self):
        code, stderr = self._run_packaged_bootstrap(
            host_ok=True,
            server_ok=True,
            safe_server_module_missing=True,
        )
        self.assertEqual(code, 72)
        self.assertIn(
            "Accessible WebView2 local server support could not be loaded.",
            stderr,
        )

    def test_real_entrypoint_reports_renderer_accessibility_bootstrap_code(self):
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

    def test_real_entrypoint_reports_accessibility_host_bootstrap_code(self):
        code, stderr = self._run_packaged_bootstrap(host_ok=False, server_ok=True)
        self.assertEqual(code, 71)
        self.assertIn("Accessible WebView2 host could not be initialized.", stderr)

    def test_real_entrypoint_reports_safe_local_server_bootstrap_code(self):
        code, stderr = self._run_packaged_bootstrap(host_ok=True, server_ok=False)
        self.assertEqual(code, 72)
        self.assertIn("Accessible WebView2 local server could not be initialized.", stderr)

    def test_real_entrypoint_maps_bootstrap_installer_exceptions_to_specific_codes(self):
        host_code, _stderr = self._run_packaged_bootstrap(
            host_ok=True,
            server_ok=True,
            host_install_raises=True,
        )
        self.assertEqual(host_code, 71)

        server_code, _stderr = self._run_packaged_bootstrap(
            host_ok=True,
            server_ok=True,
            server_install_raises=True,
        )
        self.assertEqual(server_code, 72)

    def test_real_entrypoint_keeps_deferred_safe_port_failure_on_code_72(self):
        code, stderr = self._run_packaged_bootstrap(
            host_ok=True,
            server_ok=True,
            safe_port_raises=True,
        )
        self.assertEqual(code, 72)
        self.assertIn("could not obtain a safe loopback port", stderr)

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
            "            FALSE,\n            CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED,",
            self.source,
        )
        self.assertIn("DuplicateHandle(", self.source)
        self.assertIn("DUPLICATE_SAME_ACCESS", self.source)
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

    def test_report_open_rejects_aliases_before_truncating_existing_bytes(self):
        for token in (
            "OPEN_ALWAYS",
            "FILE_FLAG_OPEN_REPARSE_POINT",
            "FileAttributeTagInfo",
            "tag_info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT",
            "BY_HANDLE_FILE_INFORMATION file_info",
            "GetFileInformationByHandle(handle, &file_info)",
            "file_info.nNumberOfLinks != 1",
            "ERROR_CANT_ACCESS_FILE",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.report_open)
        self.assertNotIn("CREATE_ALWAYS", self.report_open)

        opened = self.report_open.index("CreateFileW(")
        reparse_inspected = self.report_open.index("GetFileInformationByHandleEx(")
        reparse_rejected = self.report_open.index(
            "tag_info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT"
        )
        link_inspected = self.report_open.index("GetFileInformationByHandle(handle, &file_info)")
        link_rejected = self.report_open.index("file_info.nNumberOfLinks != 1")
        truncated = self.report_open.index("SetEndOfFile(handle)")
        bom = self.report_open.index("WriteFile(handle, bom")
        self.assertLess(opened, reparse_inspected)
        self.assertLess(reparse_inspected, reparse_rejected)
        self.assertLess(reparse_rejected, link_inspected)
        self.assertLess(link_inspected, link_rejected)
        self.assertLess(link_rejected, truncated)
        self.assertLess(truncated, bom)

    def test_report_reset_and_bom_write_fail_closed(self):
        for token in (
            "SetFilePointerEx(handle, zero, NULL, FILE_BEGIN)",
            "SetEndOfFile(handle)",
            "written != 3",
            "ERROR_WRITE_FAULT",
            "SetLastError(error)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.report_open)

    def test_report_body_writes_and_flushes_fail_closed(self):
        write_start = self.source.index("static void ac_write_utf8(HANDLE handle")
        write_end = self.source.index("static void ac_write_line(HANDLE handle", write_start)
        write_body = self.source[write_start:write_end]
        for token in (
            "if (!WriteFile(",
            "written != (DWORD)(bytes - 1)",
            "ac_report_write_fail(handle, ERROR_WRITE_FAULT)",
            "ERROR_NO_UNICODE_TRANSLATION",
        ):
            with self.subTest(token=token):
                self.assertIn(token, write_body)
        self.assertIn("static void ac_flush_report(HANDLE report)", self.source)
        self.assertIn("if (!FlushFileBuffers(report))", self.source)
        self.assertEqual(self.source.count("FlushFileBuffers(report)"), 1)
        self.assertGreaterEqual(self.source.count("ac_flush_report(report);"), 5)
        self.assertIn(
            "incomplete report must not be treated as valid evidence",
            self.source,
        )

    def test_windows_workflow_exercises_overlapping_root_launchers(self):
        for token in (
            "$first = Start-Process -FilePath $launcher",
            "Start-Sleep -Milliseconds 100",
            "$second = Start-Process -FilePath $launcher",
            "$first.WaitForExit(10000)",
            "$second.WaitForExit(10000)",
            "Overlapping second portable launcher smoke failed",
            "Launch report missing after overlapping launchers",
            "PACKAGE_DATA_OWNER: SINGLE_INSTANCE_GUARD_ACTIVE",
            "$ownedChildren.Count -ne 1",
            "Expected exactly one package-local child after overlapping launchers",
            "Single package-local child PID mismatch",
            "AccessibleChessDirectoryDeleteProbe",
            "DeleteAccess = 0x00010000",
            "ShareDelete = 0x00000004",
            "BackupSemantics = 0x02000000",
            "OpenReparsePoint = 0x00200000",
            "foreach ($guardedDirectory in @($root, $app, $data))",
            "$probeError -ne 32",
            "Transferred directory guard missing",
            "Start-Sleep -Seconds 7",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.workflow)
        first_launch = self.workflow.index("$first = Start-Process -FilePath $launcher")
        second_launch = self.workflow.index("$second = Start-Process -FilePath $launcher")
        first_wait = self.workflow.index("$first.WaitForExit(10000)")
        self.assertLess(first_launch, second_launch)
        self.assertLess(second_launch, first_wait)

    def test_windows_workflow_executes_native_early_exit_reason_mapping(self):
        for token in (
            "ACS_SMOKE_EXIT_CODE",
            "ACCESSIBILITY_HOST_INIT_FAILED",
            "SAFE_LOCAL_SERVER_INIT_FAILED",
            "RELEASE_UI_STARTUP_FAILED",
            "UNKNOWN_EARLY_EXIT",
            "CHILD_EXIT_REASON:",
            "EarlyExitChild.exe",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.workflow)

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
        self.assertIn("ac_open_direct_private_file(g_core)", self.source)

    def test_data_directory_guard_is_direct_and_blocks_replacement(self):
        start = self.source.index(
            "static HANDLE ac_open_direct_directory_guard(const WCHAR *path)"
        )
        end = self.source.index("static HANDLE ac_open_direct_private_file", start)
        guard = self.source[start:end]
        for token in (
            "CreateFileW(",
            "FILE_READ_ATTRIBUTES",
            "FILE_SHARE_READ | FILE_SHARE_WRITE",
            "OPEN_EXISTING",
            "FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT",
            "GetFileInformationByHandleEx(",
            "FileAttributeTagInfo",
            "tag_info.FileAttributes & FILE_ATTRIBUTE_DIRECTORY",
            "tag_info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT",
            "ERROR_CANT_ACCESS_FILE",
        ):
            with self.subTest(token=token):
                self.assertIn(token, guard)
        self.assertNotIn("FILE_SHARE_DELETE", guard)

    def test_data_directory_guard_precedes_environment_and_child_start(self):
        main = self.source[self.source.index("void WINAPI wWinMainCRTStartup(void)") :]
        directory_check = main.index("if (!ac_direct_directory(g_data))")
        guard_open = main.index("data_guard = ac_open_direct_directory_guard(g_data)")
        environment = main.index('SetEnvironmentVariableW(L"LOCALAPPDATA", g_data)')
        create_process = main.index("if (!CreateProcessW(")
        transfer = main.index("            data_guard,", create_process)
        resume = main.index("resume_result = ResumeThread(g_process.hThread)")
        local_close = main.index("CloseHandle(data_guard)", resume)

        self.assertLess(directory_check, guard_open)
        self.assertLess(guard_open, environment)
        self.assertLess(environment, create_process)
        self.assertLess(create_process, transfer)
        self.assertLess(transfer, resume)
        self.assertLess(resume, local_close)

    def test_package_root_and_app_directory_guards_are_transferred_to_child(self):
        main = self.source[self.source.index("void WINAPI wWinMainCRTStartup(void)") :]
        for token in (
            "HANDLE root_guard = INVALID_HANDLE_VALUE;",
            "HANDLE app_guard = INVALID_HANDLE_VALUE;",
            "HANDLE child_root_guard = NULL;",
            "HANDLE child_app_guard = NULL;",
            "root_guard = ac_open_direct_directory_guard(g_root);",
            "app_guard = ac_open_direct_directory_guard(g_app_dir);",
            "DuplicateHandle(\n            GetCurrentProcess(),\n            root_guard,\n            g_process.hProcess,\n            &child_root_guard,",
            "DuplicateHandle(\n            GetCurrentProcess(),\n            app_guard,\n            g_process.hProcess,\n            &child_app_guard,",
            'ac_fail(\n            INVALID_HANDLE_VALUE,\n            L"package-root directory guard",',
            'ac_fail(\n            report,\n            L"App runtime directory guard",',
            'ac_fail(report, L"package-root directory guard transfer", error)',
            'ac_fail(report, L"App runtime directory guard transfer", error)',
            'L"PACKAGE_ROOT_GUARD: DIRECT_DIRECTORY_HANDLE_READY"',
            'L"APP_RUNTIME_GUARD: DIRECT_DIRECTORY_HANDLE_READY"',
            'L"PACKAGE_ROOT_GUARD: TRANSFERRED_TO_CHILD"',
            'L"APP_RUNTIME_GUARD: TRANSFERRED_TO_CHILD"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, main)

        root_check = main.index("if (!ac_direct_directory(g_root))")
        root_open = main.index("root_guard = ac_open_direct_directory_guard(g_root)")
        instance_lock = main.index("g_instance_lock = ac_open_instance_lock()")
        app_check = main.index("if (!ac_direct_directory(g_app_dir))")
        app_open = main.index("app_guard = ac_open_direct_directory_guard(g_app_dir)")
        core_open = main.index("core_guard = ac_open_direct_private_file(g_core)")
        create_process = main.index("if (!CreateProcessW(")
        root_transfer = main.index("            root_guard,", create_process)
        app_transfer = main.index("            app_guard,", root_transfer)
        data_transfer = main.index("            data_guard,", app_transfer)
        resume = main.index("resume_result = ResumeThread(g_process.hThread)")
        root_close = main.index("CloseHandle(root_guard)", resume)
        app_close = main.index("CloseHandle(app_guard)", root_close)

        self.assertLess(root_check, root_open)
        self.assertLess(root_open, instance_lock)
        self.assertLess(app_check, app_open)
        self.assertLess(app_open, core_open)
        self.assertLess(core_open, create_process)
        self.assertLess(create_process, root_transfer)
        self.assertLess(root_transfer, app_transfer)
        self.assertLess(app_transfer, data_transfer)
        self.assertLess(data_transfer, resume)
        self.assertLess(resume, root_close)
        self.assertLess(root_close, app_close)

    def test_data_directory_guard_is_retained_by_suspended_child(self):
        main = self.source[self.source.index("void WINAPI wWinMainCRTStartup(void)") :]
        for token in (
            "CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED",
            "HANDLE data_guard = INVALID_HANDLE_VALUE;",
            "HANDLE child_data_guard = NULL;",
            "DuplicateHandle(\n            GetCurrentProcess(),\n            data_guard,\n            g_process.hProcess,\n            &child_data_guard,",
            'ac_fail(report, L"package-local data directory guard transfer", error)',
            'L"PACKAGE_DATA_GUARD: DIRECT_DIRECTORY_HANDLE_READY"',
            'L"PACKAGE_DATA_GUARD: TRANSFERRED_TO_CHILD"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, main)

        transfer_start = main.index(
            "if (!DuplicateHandle(\n            GetCurrentProcess(),\n            data_guard,"
        )
        transfer_end = main.index(
            "resume_result = ResumeThread(g_process.hThread)", transfer_start
        )
        transfer = main[transfer_start:transfer_end]
        self.assertNotIn("TerminateProcess(g_process.hProcess", transfer)
        self.assertIn("CloseHandle(g_process.hThread)", transfer)
        self.assertNotIn("ac_close_child_process_handle()", transfer)
        self.assertIn(
            'ac_fail(report, L"package-local data directory guard transfer", error)',
            transfer,
        )


if __name__ == "__main__":
    unittest.main()
