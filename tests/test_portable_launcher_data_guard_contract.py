from pathlib import Path
import unittest


class PortableLauncherDataGuardContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.source = (root / "packaging" / "portable_launcher.c").read_text(
            encoding="utf-8"
        )

    def _block(self, start: str, end: str) -> str:
        begin = self.source.index(start)
        finish = self.source.index(end, begin)
        return self.source[begin:finish]

    def test_data_directory_guard_is_direct_and_blocks_replacement(self) -> None:
        guard = self._block(
            "static HANDLE ac_open_direct_directory_guard(const WCHAR *path)",
            "static HANDLE ac_open_direct_private_file(const WCHAR *path)",
        )
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

    def test_validated_data_guard_precedes_child_start_and_environment_use(self) -> None:
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

    def test_data_guard_is_duplicated_into_suspended_child(self) -> None:
        main = self.source[self.source.index("void WINAPI wWinMainCRTStartup(void)") :]
        self.assertIn("CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED", main)
        for token in (
            "HANDLE data_guard = INVALID_HANDLE_VALUE;",
            "HANDLE child_data_guard = NULL;",
            "DuplicateHandle(\n            GetCurrentProcess(),\n            data_guard,\n            g_process.hProcess,\n            &child_data_guard,",
            "DUPLICATE_SAME_ACCESS",
            'ac_fail(report, L"package-local data directory guard transfer", error)',
            'L"PACKAGE_DATA_GUARD: DIRECT_DIRECTORY_HANDLE_READY"',
            'L"PACKAGE_DATA_GUARD: TRANSFERRED_TO_CHILD"',
        ):
            with self.subTest(token=token):
                self.assertIn(token, main)

    def test_guard_transfer_failure_kills_suspended_child_fail_closed(self) -> None:
        main = self.source[self.source.index("void WINAPI wWinMainCRTStartup(void)") :]
        transfer_start = main.index(
            "if (!DuplicateHandle(\n            GetCurrentProcess(),\n            data_guard,"
        )
        transfer_end = main.index(
            "resume_result = ResumeThread(g_process.hThread)", transfer_start
        )
        transfer = main[transfer_start:transfer_end]
        self.assertIn("TerminateProcess(g_process.hProcess", transfer)
        self.assertIn("CloseHandle(g_process.hThread)", transfer)
        self.assertIn("CloseHandle(g_process.hProcess)", transfer)
        self.assertIn("package-local data directory guard transfer", transfer)


if __name__ == "__main__":
    unittest.main()
