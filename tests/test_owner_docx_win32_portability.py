from __future__ import annotations

from pathlib import Path
import unittest
from unittest import mock

import acs.version2_portable_package as portable_package
import scripts.build_owner_portable_candidate as owner_candidate


class OwnerDocxWin32PortabilityTests(unittest.TestCase):
    def test_owner_and_generic_portable_filename_contracts_stay_aligned(self) -> None:
        accepted = (
            "Доступні шахи — інструкція.docx",
            "Guide.DOCX",
            "a" * 250 + ".docx",
        )
        rejected = (
            "CON.docx",
            "nul.DOCX",
            "owner?.docx",
            "owner|guide.docx",
            "owner" + chr(31) + ".docx",
            "owner" + chr(0xD800) + ".docx",
            chr(0x1F642) * 126 + ".docx",
            "C:owner.docx",
            r"C:\owner.docx",
            "nested/owner.docx",
            r"nested\owner.docx",
        )
        for name in accepted:
            with self.subTest(kind="accepted", name=repr(name)):
                self.assertEqual(owner_candidate._owner_docx_filename(name), name)
                self.assertEqual(portable_package._portable_docx_filename(name), name)
        for name in rejected:
            with self.subTest(kind="rejected", name=repr(name)):
                with self.assertRaises(owner_candidate.OwnerPortableCandidateError):
                    owner_candidate._owner_docx_filename(name)
                with self.assertRaises(portable_package.Version2PortablePackageError):
                    portable_package._portable_docx_filename(name)

    def test_ordinary_ukrainian_docx_name_is_accepted(self) -> None:
        name = "Доступні шахи — інструкція.docx"
        self.assertEqual(owner_candidate._owner_docx_name(Path(name)), name)

    def test_raw_filename_authority_rejects_path_and_drive_forms(self) -> None:
        for name in (
            "folder/document.docx",
            r"folder\document.docx",
            "C:document.docx",
            r"C:\document.docx",
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    owner_candidate.OwnerPortableCandidateError,
                    "not Win32-portable",
                ):
                    owner_candidate._owner_docx_filename(name)

    def test_exact_255_utf16_unit_component_is_accepted(self) -> None:
        name = "a" * 250 + ".docx"
        self.assertEqual(len(name.encode("utf-16-le")) // 2, 255)
        self.assertEqual(owner_candidate._owner_docx_name(Path(name)), name)

    def test_utf16_bound_counts_astral_characters_as_two_units(self) -> None:
        astral = chr(0x1F642)
        accepted = astral * 125 + ".docx"
        rejected = astral * 126 + ".docx"
        self.assertEqual(len(accepted.encode("utf-16-le")) // 2, 255)
        self.assertGreater(len(rejected.encode("utf-16-le")) // 2, 255)
        self.assertEqual(owner_candidate._owner_docx_name(Path(accepted)), accepted)
        with self.assertRaisesRegex(
            owner_candidate.OwnerPortableCandidateError,
            "not Win32-portable",
        ):
            owner_candidate._owner_docx_name(Path(rejected))

    def test_win32_forbidden_filename_characters_are_rejected(self) -> None:
        for character in '<>:"|?*':
            with self.subTest(character=character):
                with self.assertRaisesRegex(
                    owner_candidate.OwnerPortableCandidateError,
                    "not Win32-portable",
                ):
                    owner_candidate._owner_docx_name(
                        Path(f"owner{character}document.docx")
                    )

    def test_reserved_dos_device_aliases_are_rejected_with_docx_extension(self) -> None:
        for name in (
            "CON.docx",
            "nul.DOCX",
            "PrN.docx",
            "COM1.docx",
            "LPT9.docx",
            "COM¹.docx",
            "lpt³.docx",
            "CONIN$.docx",
            "conout$.docx",
        ):
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    owner_candidate.OwnerPortableCandidateError,
                    "not Win32-portable",
                ):
                    owner_candidate._owner_docx_name(Path(name))

    def test_trailing_dot_wrong_extension_and_control_character_are_rejected(self) -> None:
        for name in (
            "owner.docx.",
            "owner.txt",
            "owner" + chr(31) + ".docx",
        ):
            with self.subTest(name=repr(name)):
                with self.assertRaisesRegex(
                    owner_candidate.OwnerPortableCandidateError,
                    "not Win32-portable",
                ):
                    owner_candidate._owner_docx_name(Path(name))

    def test_unpaired_surrogate_is_rejected_before_filesystem_materialization(self) -> None:
        malformed = "owner" + chr(0xD800) + ".docx"
        with self.assertRaisesRegex(
            owner_candidate.OwnerPortableCandidateError,
            "not valid Unicode for Win32",
        ):
            owner_candidate._owner_docx_name(Path(malformed))

    def test_owner_assembly_rejects_nonportable_name_before_package_assembly(self) -> None:
        with mock.patch.object(
            owner_candidate,
            "assemble_portable_oneclick_tree",
        ) as assemble:
            with self.assertRaisesRegex(
                owner_candidate.OwnerPortableCandidateError,
                "not Win32-portable",
            ):
                owner_candidate.assemble_owner_portable_candidate(
                    Path("canonical"),
                    Path("launcher.exe"),
                    (Path("CON.docx"), Path("Опис.docx")),
                    Path("candidate"),
                    Path("candidate.zip"),
                    integration_sha="a" * 40,
                    expected_document_sha256=("b" * 64, "c" * 64),
                    expected_sound_archive_sha256="d" * 64,
                )
        assemble.assert_not_called()

    def test_owner_assembly_rejects_case_colliding_root_docx_names_before_copy(self) -> None:
        with mock.patch.object(
            owner_candidate,
            "assemble_portable_oneclick_tree",
        ) as assemble:
            with self.assertRaisesRegex(
                owner_candidate.OwnerPortableCandidateError,
                "distinct Win32 filenames",
            ):
                owner_candidate.assemble_owner_portable_candidate(
                    Path("canonical"),
                    Path("launcher.exe"),
                    (Path("Guide.docx"), Path("guide.DOCX")),
                    Path("candidate"),
                    Path("candidate.zip"),
                    integration_sha="a" * 40,
                    expected_document_sha256=("b" * 64, "c" * 64),
                    expected_sound_archive_sha256="d" * 64,
                )
        assemble.assert_not_called()


if __name__ == "__main__":
    unittest.main()
