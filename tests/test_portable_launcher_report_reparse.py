from pathlib import Path
import unittest


class PortableLauncherReportReparseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.source = (root / "packaging" / "portable_launcher.c").read_text(encoding="utf-8")
        start = cls.source.index("static HANDLE ac_open_report(void)")
        end = cls.source.index("static void ac_prepare_paths(void)", start)
        cls.report_open = cls.source[start:end]

    def test_report_final_component_is_opened_without_following_reparse_points(self):
        for token in (
            "OPEN_ALWAYS",
            "FILE_FLAG_OPEN_REPARSE_POINT",
            "FileAttributeTagInfo",
            "FILE_ATTRIBUTE_REPARSE_POINT",
            "ERROR_CANT_ACCESS_FILE",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.report_open)
        self.assertNotIn("CREATE_ALWAYS", self.report_open)

    def test_reparse_identity_is_checked_before_existing_report_is_truncated(self):
        opened = self.report_open.index("CreateFileW(")
        inspected = self.report_open.index("GetFileInformationByHandleEx(")
        rejected = self.report_open.index("tag_info.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT")
        truncated = self.report_open.index("SetEndOfFile(handle)")
        bom = self.report_open.index("WriteFile(handle, bom")
        self.assertLess(opened, inspected)
        self.assertLess(inspected, rejected)
        self.assertLess(rejected, truncated)
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

    def test_bounded_parallel_launcher_retry_is_preserved(self):
        for token in (
            "AC_REPORT_RETRY_COUNT",
            "ERROR_SHARING_VIOLATION",
            "Sleep(AC_REPORT_RETRY_MS)",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.report_open)


if __name__ == "__main__":
    unittest.main()
