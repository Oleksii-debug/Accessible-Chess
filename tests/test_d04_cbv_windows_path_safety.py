from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.cbv_extractor import (
    CbvExtractCode,
    CbvExtractError,
    ExternalCbvExtractorConfig,
    extract_cbv_external,
)


class CbvWindowsPathSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "Archive.cbv"
        self.source.write_bytes(b"immutable CBV archive")
        self.backend = self.root / "uncbv"
        self.backend.write_bytes(b"pinned external backend")
        self.output = self.root / "output"
        self.output.mkdir()
        self.config = ExternalCbvExtractorConfig(
            self.backend,
            expected_backend_sha256=sha256(self.backend.read_bytes()).hexdigest(),
            timeout_seconds=3,
        )

    def test_windows_special_or_ambiguous_names_fail_before_extraction(self) -> None:
        unsafe_entries = (
            "CON.cbh",
            "nested/prn.cbg",
            "nested/AUX.txt",
            "nested/NUL",
            "nested/COM1.cba",
            "nested/com9.anything",
            "nested/LPT1.cbt",
            "nested/lpt9.txt",
            "nested/CLOCK$.cbh",
            "nested/COM¹.cbh",
            "nested/LPT³.cbg",
            "nested/database.cbh:secret",
            "nested/bad?.cbh",
            "nested/bad*.cbh",
            "nested/bad\".cbh",
            "nested/bad<.cbh",
            "nested/bad>.cbh",
            "nested/bad|.cbh",
            "nested/trailing-dot.cbh.",
            "nested/trailing-space.cbh ",
            "nested/control\tname.cbh",
        )
        for entry in unsafe_entries:
            with self.subTest(entry=entry):
                payload = (entry + "\n").encode("utf-8")
                with mock.patch("acs.cbv_extractor._run_uncbv", return_value=payload) as runner:
                    with self.assertRaises(CbvExtractError) as caught:
                        extract_cbv_external(self.source, self.output, self.config)
                self.assertEqual(caught.exception.code, CbvExtractCode.INVALID_ENTRY)
                self.assertEqual(
                    runner.call_count,
                    1,
                    "unsafe archive entry reached the extraction invocation",
                )

    def test_normal_nested_chessbase_names_remain_valid(self) -> None:
        def runner(_executable, arguments, _config, *, cwd, monitor_directory=None):
            if arguments[0] == "list":
                return (
                    "Training Set/Database.v1.cbh\n"
                    "Training Set/Database.v1.cbg\n"
                    "Training Set/Database.v1.cba\n"
                ).encode("utf-8")
            self.assertEqual(arguments[0], "extract")
            self.assertEqual(Path(cwd), self.output)
            self.assertEqual(Path(monitor_directory), self.output)
            nested = self.output / "Training Set"
            nested.mkdir()
            (nested / "Database.v1.cbh").write_bytes(b"header")
            (nested / "Database.v1.cbg").write_bytes(b"moves")
            (nested / "Database.v1.cba").write_bytes(b"annotations")
            return b""

        with mock.patch("acs.cbv_extractor._run_uncbv", side_effect=runner):
            result = extract_cbv_external(self.source, self.output, self.config)

        self.assertEqual(result.primary_path, self.output / "Training Set" / "Database.v1.cbh")
        self.assertEqual(result.entry_count, 3)


if __name__ == "__main__":
    unittest.main()
