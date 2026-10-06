from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.release_preflight import ReleasePreflightError, _inventory


class ExtendedPythonSourceHygieneTests(unittest.TestCase):
    def test_extended_python_source_suffixes_fail_closed_case_insensitively(self) -> None:
        suffixes = (".pyw", ".pyi", ".pyx", ".pxd", ".pxi")
        for suffix in suffixes:
            for candidate_suffix in (suffix, suffix.upper()):
                with self.subTest(suffix=candidate_suffix), tempfile.TemporaryDirectory() as raw:
                    root = Path(raw)
                    product = root / "AccessibleChess"
                    product.mkdir()
                    leaked = product / f"implementation{candidate_suffix}"
                    leaked.write_text("# readable product source\n", encoding="utf-8")
                    with self.assertRaisesRegex(
                        ReleasePreflightError,
                        "raw product source is forbidden",
                    ):
                        _inventory(root)

    def test_compiled_and_data_artifacts_are_not_misclassified_as_python_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            product = root / "AccessibleChess"
            product.mkdir()
            for name in ("AccessibleChess.exe", "python312.dll", "library.zip", "settings.json"):
                (product / name).write_bytes(b"x")
            inventory = _inventory(root)
            self.assertEqual(
                (
                    "AccessibleChess/AccessibleChess.exe",
                    "AccessibleChess/library.zip",
                    "AccessibleChess/python312.dll",
                    "AccessibleChess/settings.json",
                ),
                inventory,
            )

    def test_legacy_raw_python_and_notebook_rejections_remain_covered(self) -> None:
        for suffix in (".py", ".pyc", ".pyo", ".ipynb"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                product = root / "AccessibleChess"
                product.mkdir()
                (product / f"legacy{suffix}").write_bytes(b"x")
                with self.assertRaises(ReleasePreflightError):
                    _inventory(root)


if __name__ == "__main__":
    unittest.main()
