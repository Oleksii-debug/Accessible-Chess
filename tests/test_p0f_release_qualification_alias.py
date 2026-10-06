from __future__ import annotations

import importlib
import unittest


class P0FReleaseQualificationAliasTests(unittest.TestCase):
    def test_release_alias_imports_canonical_packaged_starter_suite(self) -> None:
        alias = importlib.import_module("tests.test_p0f_packaged_starter_application")
        canonical = importlib.import_module("tests.test_v2_packaged_starter_application")

        canonical_cases = {
            name
            for name, value in vars(canonical).items()
            if isinstance(value, type) and issubclass(value, unittest.TestCase)
        }
        alias_cases = {
            name
            for name, value in vars(alias).items()
            if isinstance(value, type) and issubclass(value, unittest.TestCase)
        }
        self.assertTrue(canonical_cases, "canonical packaged starter suite has no TestCase classes")
        self.assertTrue(canonical_cases.issubset(alias_cases))


if __name__ == "__main__":
    unittest.main()
