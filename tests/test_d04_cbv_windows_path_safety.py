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
    _validate_output_inventory_names,
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

    @staticmethod
    def _unsafe_windows_names() -> tuple[str, ...]:
        reserved = (
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "CLOCK$",
            *(f"COM{index}" for index in range(1, 10)),
            *(f"LPT{index}" for index in range(1, 10)),
            "COM¹",
            "COM²",
            "COM³",
            "LPT¹",
            "LPT²",
            "LPT³",
        )
        reserved_paths = tuple(
            path
            for name in reserved
            for path in (f"nested/{name}", f"nested/{name.lower()}.cbh")
        )
        forbidden = tuple(
            f"nested/bad{character}name.cbh"
            for character in '<>:"|?*'
        )
        controls = tuple(
            f"nested/bad{chr(codepoint)}name.cbh"
            for codepoint in range(32)
            if codepoint != 10  # LF is the backend record separator, never an entry character.
        )
        return (
            *reserved_paths,
            "nested/database.cbh:secret",
            *forbidden,
            *controls,
            "nested/trailing-dot.cbh.",
            "nested/trailing-space.cbh ",
            "/absolute/database.cbh",
            r"\rooted\database.cbh",
            "C:/private/database.cbh",
            r"C:\private\database.cbh",
            r"C:relative\database.cbh",
            r"\\server\share\database.cbh",
            "../escape.cbh",
            "nested/../escape.cbh",
            "nested/deeper/../../escape.cbh",
        )

    def _assert_list_rejected_before_extract(self, entry: str) -> None:
        payload = (entry + "\n").encode("utf-8")
        with mock.patch("acs.cbv_extractor._run_uncbv", return_value=payload) as runner:
            with self.assertRaises(CbvExtractError) as caught:
                extract_cbv_external(self.source, self.output, self.config)
        self.assertEqual(caught.exception.code, CbvExtractCode.INVALID_ENTRY)
        self.assertEqual(
            [call.args[1][0] for call in runner.call_args_list],
            ["list"],
            "unsafe archive entry must stop after exactly one list call",
        )

    def test_exhaustive_windows_unsafe_names_fail_before_extraction(self) -> None:
        for entry in self._unsafe_windows_names():
            with self.subTest(entry=repr(entry)):
                self._assert_list_rejected_before_extract(entry)

    def test_case_collisions_fail_before_extraction(self) -> None:
        unsafe_lists = (
            b"same.cbh\nSAME.CBH\n",
            b"Folder/A.cbh\nfolder/B.cbg\n",
            b"Folder/A.cbh\nFOLDER/A.CBH\n",
        )
        for payload in unsafe_lists:
            with self.subTest(payload=payload):
                with mock.patch("acs.cbv_extractor._run_uncbv", return_value=payload) as runner:
                    with self.assertRaises(CbvExtractError) as caught:
                        extract_cbv_external(self.source, self.output, self.config)
                self.assertEqual(caught.exception.code, CbvExtractCode.INVALID_ENTRY)
                self.assertEqual(
                    [call.args[1][0] for call in runner.call_args_list],
                    ["list"],
                )

    def test_non_lf_inventory_separators_fail_before_extraction(self) -> None:
        unsafe_payloads = (
            ("VT", b"safe.cbh\x0bevil.cbg\n"),
            ("FF", b"safe.cbh\x0cevil.cbg\n"),
            ("FS", b"safe.cbh\x1cevil.cbg\n"),
            ("GS", b"safe.cbh\x1devil.cbg\n"),
            ("RS", b"safe.cbh\x1eevil.cbg\n"),
            ("NEL", "safe.cbh\u0085evil.cbg\n".encode("utf-8")),
            ("U+2028", "safe.cbh\u2028evil.cbg\n".encode("utf-8")),
            ("U+2029", "safe.cbh\u2029evil.cbg\n".encode("utf-8")),
            ("stray CR", b"safe.cbh\revil.cbg\n"),
        )
        for label, payload in unsafe_payloads:
            with self.subTest(separator=label):
                with mock.patch("acs.cbv_extractor._run_uncbv", return_value=payload) as runner:
                    with self.assertRaises(CbvExtractError) as caught:
                        extract_cbv_external(self.source, self.output, self.config)
                self.assertEqual(caught.exception.code, CbvExtractCode.INVALID_ENTRY)
                self.assertEqual(
                    [call.args[1][0] for call in runner.call_args_list],
                    ["list"],
                    "unsafe inventory must perform exactly one list call and zero extract calls",
                )

    def test_actual_output_inventory_reuses_complete_windows_name_policy(self) -> None:
        for entry in self._unsafe_windows_names():
            with self.subTest(entry=repr(entry)):
                with self.assertRaises(CbvExtractError) as caught:
                    _validate_output_inventory_names(set(), {entry})
                self.assertEqual(caught.exception.code, CbvExtractCode.OUTPUT_INVALID)

    def test_actual_output_inventory_rejects_case_collisions(self) -> None:
        inventories = (
            (set(), {"same.cbh", "SAME.CBH"}),
            ({"Folder", "folder"}, {"Folder/A.cbh"}),
            ({"Folder"}, {"Folder/A.cbh", "FOLDER/A.CBG"}),
        )
        for directories, files in inventories:
            with self.subTest(directories=directories, files=files):
                with self.assertRaises(CbvExtractError) as caught:
                    _validate_output_inventory_names(directories, files)
                self.assertEqual(caught.exception.code, CbvExtractCode.OUTPUT_INVALID)

    def test_unlisted_empty_output_directory_is_rejected(self) -> None:
        def runner(_executable, arguments, _config, **_kwargs):
            if arguments[0] == "list":
                return b"Archive.cbh\n"
            (self.output / "Archive.cbh").write_bytes(b"header")
            (self.output / "unexpected-empty-directory").mkdir()
            return b""

        with mock.patch("acs.cbv_extractor._run_uncbv", side_effect=runner):
            with self.assertRaises(CbvExtractError) as caught:
                extract_cbv_external(self.source, self.output, self.config)
        self.assertEqual(caught.exception.code, CbvExtractCode.OUTPUT_INVALID)

    def test_crlf_inventory_remains_valid(self) -> None:
        commands: list[str] = []

        def runner(_executable, arguments, _config, *, cwd, monitor_directory=None):
            commands.append(arguments[0])
            if arguments[0] == "list":
                return b"Training Set/Database.v1.cbh\r\nTraining Set/Database.v1.cbg\r\nTraining Set/Database.v1.cba\r\n"
            self.assertEqual(arguments[0], "extract")
            nested = self.output / "Training Set"
            nested.mkdir()
            (nested / "Database.v1.cbh").write_bytes(b"header")
            (nested / "Database.v1.cbg").write_bytes(b"moves")
            (nested / "Database.v1.cba").write_bytes(b"annotations")
            return b""

        with mock.patch("acs.cbv_extractor._run_uncbv", side_effect=runner):
            result = extract_cbv_external(self.source, self.output, self.config)

        self.assertEqual(result.entry_count, 3)
        self.assertEqual(commands, ["list", "extract"])

    def test_legitimate_nested_unicode_and_device_like_names_remain_valid(self) -> None:
        entries = (
            "Training Set/Україна 2026/Database.v1.cbh",
            "Training Set/Україна 2026/COM10.cbg",
            "Training Set/Україна 2026/LPT10.cba",
            "Training Set/Україна 2026/clock.cbt",
            "Training Set/Україна 2026/auxiliary name.cbj",
        )

        def runner(_executable, arguments, _config, *, cwd, monitor_directory=None):
            if arguments[0] == "list":
                return ("\n".join(entries) + "\n").encode("utf-8")
            self.assertEqual(arguments[0], "extract")
            self.assertEqual(Path(cwd), self.output)
            self.assertEqual(Path(monitor_directory), self.output)
            for entry in entries:
                target = self.output.joinpath(*entry.split("/"))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(entry.encode("utf-8"))
            return b""

        with mock.patch("acs.cbv_extractor._run_uncbv", side_effect=runner):
            result = extract_cbv_external(self.source, self.output, self.config)

        self.assertEqual(
            result.primary_path,
            self.output / "Training Set" / "Україна 2026" / "Database.v1.cbh",
        )
        self.assertEqual(result.entry_count, len(entries))
        _validate_output_inventory_names(
            {"Training Set", "Training Set/Україна 2026"},
            set(entries),
        )


if __name__ == "__main__":
    unittest.main()