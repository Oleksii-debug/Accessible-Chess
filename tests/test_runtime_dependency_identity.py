from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from acs.runtime_dependency_notices import (
    ExternalArchiveNoticeSource,
    RuntimeDependencyNoticeError,
    build_runtime_dependency_notice_bundle,
)


class RuntimeDependencyIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.python_license = self.root / "PYTHON-LICENSE.txt"
        self.python_license.write_text("Python license fixture\n", encoding="utf-8")

    def _loader_must_not_run(self, _name: str):
        self.fail("distribution lookup must not run after canonical identity rejection")

    def test_inventory_rejects_pep503_alias_duplicates_before_lookup(self) -> None:
        output = self.root / "inventory-output"
        with self.assertRaisesRegex(RuntimeDependencyNoticeError, "inventory contains duplicates"):
            build_runtime_dependency_notice_bundle(
                ("demo-package", "demo_package"),
                output,
                distribution_loader=self._loader_must_not_run,
                python_license_path=self.python_license,
            )
        self.assertFalse(output.exists())

    def test_expected_versions_reject_pep503_alias_duplicates_before_lookup(self) -> None:
        output = self.root / "expected-output"
        with self.assertRaisesRegex(RuntimeDependencyNoticeError, "expected dependency versions contain duplicates"):
            build_runtime_dependency_notice_bundle(
                ("demo-package",),
                output,
                expected_versions={"demo-package": "1.0", "demo.package": "1.0"},
                distribution_loader=self._loader_must_not_run,
                python_license_path=self.python_license,
            )
        self.assertFalse(output.exists())

    def test_external_sources_reject_pep503_alias_duplicates_before_lookup(self) -> None:
        output = self.root / "external-output"
        source = ExternalArchiveNoticeSource(
            archive_path=self.root / "unused.tar.gz",
            source_url="https://example.invalid/demo.tar.gz",
            source_sha256="0" * 64,
            member_path="LICENSE",
        )
        with self.assertRaisesRegex(RuntimeDependencyNoticeError, "external notice source inventory contains duplicates"):
            build_runtime_dependency_notice_bundle(
                ("demo-package",),
                output,
                distribution_loader=self._loader_must_not_run,
                python_license_path=self.python_license,
                external_notice_sources={"demo-package": source, "demo_package": source},
            )
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
