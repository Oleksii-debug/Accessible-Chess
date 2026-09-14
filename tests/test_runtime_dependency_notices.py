from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from acs.runtime_dependency_notices import (
    RuntimeDependencyNoticeError,
    build_runtime_dependency_notice_bundle,
)


class _Metadata(dict):
    def __init__(self, values=None, *, multi=None):
        super().__init__(values or {})
        self._multi = multi or {}

    def get_all(self, key):
        return list(self._multi.get(key, ()))


class _Distribution:
    def __init__(
        self,
        root: Path,
        *,
        version: str,
        license_files: tuple[str, ...] = ("demo.dist-info/LICENSE.txt",),
        metadata_license_files: tuple[str, ...] | None = None,
        license_expression: str = "MIT",
    ) -> None:
        self.root = root
        self.version = version
        self.files = tuple(license_files)
        declared = license_files if metadata_license_files is None else metadata_license_files
        self.metadata = _Metadata(
            {
                "License-Expression": license_expression,
                "License": "",
                "Home-page": "https://example.test/project",
            },
            multi={
                "License-File": declared,
                "Project-URL": ("Source, https://example.test/source",),
            },
        )

    def locate_file(self, relative):
        return self.root / str(relative)


class RuntimeDependencyNoticeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.python_license = self.root / "PYTHON-LICENSE.txt"
        self.python_license.write_text("Python Software Foundation License\n", encoding="utf-8")

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _distribution(self, name: str, version: str, text: str = "MIT License\n"):
        dist_root = self.root / f"installed-{name}"
        license_path = dist_root / f"{name}.dist-info" / "LICENSE.txt"
        license_path.parent.mkdir(parents=True)
        license_path.write_text(text, encoding="utf-8")
        return _Distribution(
            dist_root,
            version=version,
            license_files=(f"{name}.dist-info/LICENSE.txt",),
        )

    def test_builds_exact_byte_deterministic_manifest_and_python_license(self) -> None:
        pywebview = self._distribution("pywebview", "6.2.1", "BSD 3-Clause fixture\n")
        pythonnet = self._distribution("pythonnet", "3.1.0", "MIT fixture\n")
        installed = {"pywebview": pywebview, "pythonnet": pythonnet}

        bundle = build_runtime_dependency_notice_bundle(
            ("pythonnet", "pywebview"),
            self.root / "notices",
            expected_versions={"pywebview": "6.2.1", "pythonnet": "3.1.0"},
            distribution_loader=installed.__getitem__,
            python_license_path=self.python_license,
            python_version="3.12.10",
        )

        self.assertEqual(bundle.root, self.root / "notices")
        self.assertEqual(bundle.manifest_path.name, "PYTHON_RUNTIME_DEPENDENCIES.json")
        packaged_python = bundle.root / "Python-LICENSE.txt"
        self.assertEqual(packaged_python.read_bytes(), self.python_license.read_bytes())

        manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["python"]["version"], "3.12.10")
        self.assertEqual(manifest["python"]["sha256"], self._digest(packaged_python))
        rows = manifest["distributions"]
        self.assertEqual([row["distribution"] for row in rows], ["pythonnet", "pywebview"])
        self.assertEqual([row["version"] for row in rows], ["3.1.0", "6.2.1"])
        for row in rows:
            self.assertEqual(row["license_expression"], "MIT")
            self.assertEqual(
                row["project_urls"],
                ["https://example.test/source", "https://example.test/project"],
            )
            self.assertEqual(len(row["notice_files"]), 1)
            notice = row["notice_files"][0]
            packaged = bundle.root / notice["packaged_file"]
            self.assertTrue(packaged.is_file())
            self.assertEqual(notice["sha256"], self._digest(packaged))

    def test_pep639_source_relative_metadata_uses_real_installed_wheel_license(self) -> None:
        dist_root = self.root / "installed-pep639"
        installed_path = dist_root / "demo.dist-info" / "licenses" / "LICENSE.txt"
        installed_path.parent.mkdir(parents=True)
        installed_path.write_text("PEP 639 installed license bytes\n", encoding="utf-8")
        dist = _Distribution(
            dist_root,
            version="2.0",
            license_files=("demo.dist-info/licenses/LICENSE.txt",),
            metadata_license_files=("LICENSE.txt",),
        )

        bundle = build_runtime_dependency_notice_bundle(
            ("demo",),
            self.root / "notices",
            expected_versions={"demo": "2.0"},
            distribution_loader=lambda _name: dist,
            python_license_path=self.python_license,
            python_version="3.12.10",
        )
        manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
        notice = manifest["distributions"][0]["notice_files"][0]
        self.assertEqual(notice["source_path"], "demo.dist-info/licenses/LICENSE.txt")
        packaged = bundle.root / notice["packaged_file"]
        self.assertEqual(packaged.read_bytes(), installed_path.read_bytes())
        self.assertEqual(notice["sha256"], self._digest(installed_path))

    def test_non_notice_wheel_inventory_does_not_trigger_notice_path_rejection(self) -> None:
        dist_root = self.root / "installed-inventory"
        license_path = dist_root / "demo.dist-info" / "LICENSE.txt"
        license_path.parent.mkdir(parents=True)
        license_path.write_text("MIT fixture\n", encoding="utf-8")
        dist = _Distribution(
            dist_root,
            version="1.0",
            license_files=(
                "demo/__pycache__/module.cpython-312.pyc",
                "../ordinary-module.py",
                "C:\\temporary\\ordinary-module.py",
                "demo.dist-info/LICENSE.txt",
            ),
            metadata_license_files=(),
        )

        bundle = build_runtime_dependency_notice_bundle(
            ("demo",),
            self.root / "notices",
            expected_versions={"demo": "1.0"},
            distribution_loader=lambda _name: dist,
            python_license_path=self.python_license,
            python_version="3.12.10",
        )
        manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
        rows = manifest["distributions"][0]["notice_files"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_path"], "demo.dist-info/LICENSE.txt")

    def test_version_drift_fails_without_publishing_output(self) -> None:
        dist = self._distribution("pywebview", "6.2.0")
        output = self.root / "notices"
        with self.assertRaisesRegex(RuntimeDependencyNoticeError, "version mismatch"):
            build_runtime_dependency_notice_bundle(
                ("pywebview",),
                output,
                expected_versions={"pywebview": "6.2.1"},
                distribution_loader=lambda _name: dist,
                python_license_path=self.python_license,
            )
        self.assertFalse(output.exists())

    def test_missing_real_license_file_fails_closed(self) -> None:
        dist_root = self.root / "installed-demo"
        dist_root.mkdir()
        dist = _Distribution(
            dist_root,
            version="1.0",
            license_files=(),
        )
        output = self.root / "notices"
        with self.assertRaisesRegex(RuntimeDependencyNoticeError, "no real license"):
            build_runtime_dependency_notice_bundle(
                ("demo",),
                output,
                distribution_loader=lambda _name: dist,
                python_license_path=self.python_license,
            )
        self.assertFalse(output.exists())

    def test_missing_python_license_fails_closed(self) -> None:
        dist = self._distribution("demo", "1.0")
        output = self.root / "payload"
        with self.assertRaisesRegex(RuntimeDependencyNoticeError, "Python license"):
            build_runtime_dependency_notice_bundle(
                ("demo",),
                output,
                distribution_loader=lambda _name: dist,
                python_license_path=self.root / "missing-python-license.txt",
            )
        self.assertFalse(output.exists())

    def test_inventory_and_expected_versions_must_match_exactly(self) -> None:
        with self.assertRaisesRegex(RuntimeDependencyNoticeError, "must match"):
            build_runtime_dependency_notice_bundle(
                ("pywebview",),
                self.root / "notices",
                expected_versions={"pythonnet": "3.1.0"},
                distribution_loader=lambda _name: None,
                python_license_path=self.python_license,
            )

    def test_duplicate_and_unsafe_inventory_is_rejected_before_lookup(self) -> None:
        for inventory, expected in (
            (("pywebview", "PYWEBVIEW"), "duplicates"),
            (("../escape",), "unsafe"),
        ):
            with self.subTest(inventory=inventory):
                with self.assertRaisesRegex(RuntimeDependencyNoticeError, expected):
                    build_runtime_dependency_notice_bundle(
                        inventory,
                        self.root / ("notices-" + expected),
                        distribution_loader=lambda _name: None,
                        python_license_path=self.python_license,
                    )

    def test_unsafe_license_metadata_path_is_rejected(self) -> None:
        dist_root = self.root / "installed-demo"
        dist_root.mkdir()
        dist = _Distribution(
            dist_root,
            version="1.0",
            license_files=("../LICENSE.txt",),
        )
        with self.assertRaisesRegex(RuntimeDependencyNoticeError, "license path is unsafe"):
            build_runtime_dependency_notice_bundle(
                ("demo",),
                self.root / "notices",
                distribution_loader=lambda _name: dist,
                python_license_path=self.python_license,
            )


if __name__ == "__main__":
    unittest.main()
