from pathlib import Path
import unittest


class PortableLauncherCoreGuardContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.source = (root / "packaging" / "portable_launcher.c").read_text(encoding="utf-8")
        guard_start = cls.source.index("static HANDLE ac_open_direct_private_file")
        guard_end = cls.source.index("static HANDLE ac_open_instance_lock", guard_start)
        cls.guard = cls.source[guard_start:guard_end]
        main_start = cls.source.index("void WINAPI wWinMainCRTStartup(void)")
        cls.main = cls.source[main_start:]

    def test_core_guard_authenticates_non_reparse_private_regular_file(self):
        for token in (
            "CreateFileW(",
            "FILE_READ_ATTRIBUTES",
            "FILE_SHARE_READ",
            "OPEN_EXISTING",
            "FILE_FLAG_OPEN_REPARSE_POINT",
            "FileAttributeTagInfo",
            "tag_info.FileAttributes & FILE_ATTRIBUTE_DIRECTORY",
            "tag_info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT",
            "GetFileInformationByHandle(handle, &file_info)",
            "file_info.nNumberOfLinks != 1",
            "ERROR_CANT_ACCESS_FILE",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.guard)

        self.assertNotIn("FILE_SHARE_DELETE", self.guard)
        self.assertNotIn("FILE_SHARE_WRITE", self.guard)
        self.assertNotIn("OPEN_ALWAYS", self.guard)

    def test_core_guard_is_held_across_exact_create_process_reopen(self):
        opened = self.main.index("core_guard = ac_open_direct_private_file(g_core);")
        checked = self.main.index("if (core_guard == INVALID_HANDLE_VALUE)", opened)
        created = self.main.index("if (!CreateProcessW(", checked)
        success_close_marker = (
            "    }\n"
            "    CloseHandle(core_guard);\n"
            "    core_guard = INVALID_HANDLE_VALUE;"
        )
        success_close = self.main.index(success_close_marker, created)
        transfer = self.main.index("if (!DuplicateHandle(", success_close)

        self.assertLess(opened, checked)
        self.assertLess(checked, created)
        self.assertLess(created, success_close)
        self.assertLess(success_close, transfer)
        self.assertEqual(self.main.count("CloseHandle(core_guard);"), 2)

    def test_create_process_failure_closes_authenticated_core_handle_before_exit(self):
        created = self.main.index("if (!CreateProcessW(")
        failure_end = self.main.index("    }\n    CloseHandle(core_guard);", created)
        failure_block = self.main[created:failure_end]

        close_guard = failure_block.index("CloseHandle(core_guard);")
        fail = failure_block.index("ac_fail(report, L\"core process creation\", error);")
        self.assertLess(close_guard, fail)

    def test_old_attribute_only_core_validation_is_not_used(self):
        self.assertNotIn("static BOOL ac_direct_file", self.source)
        self.assertNotIn("ac_direct_file(g_core)", self.source)
        self.assertIn("ac_open_direct_private_file(g_core)", self.main)
        self.assertIn("L\"core executable validation\"", self.main)


if __name__ == "__main__":
    unittest.main()
