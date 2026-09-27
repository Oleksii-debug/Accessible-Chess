from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.version2_packaged_starter_application import _load_manifest
from scripts import stage_p0f_release_content as staging
from tests.test_v2_packaged_starter_application import _write_bundle


class P0FReleaseContentStagingTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        source = root / "qualified-w2"
        _write_bundle(source)
        product = root / "package" / "AccessibleChess"
        product.mkdir(parents=True)
        (product / "AccessibleChess.exe").write_bytes(b"MZ-test-package-executable")
        return source, product

    def test_direct_directory_preserves_lexical_spelling_when_resolver_normalizes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p0f-stage-path-spelling-") as raw:
            direct = Path(raw).absolute()
            normalized = direct.parent / (direct.name + "-normalized-spelling")
            with mock.patch.object(Path, "resolve", return_value=normalized):
                self.assertEqual(
                    direct,
                    staging._require_direct_directory(direct, label="direct fixture"),
                )

    def test_stages_exact_validated_bundle_at_runtime_discovery_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p0f-stage-success-") as raw:
            source, product = self._fixture(Path(raw))
            target = staging.stage_bundle(source, product)

            self.assertEqual(product / "release-content" / "w2-starter", target)
            self.assertEqual(
                {"starter_uk.pgn", "stress_uk.pgn", "sample_library.acsdb", "manifest.json"},
                {item.name for item in target.iterdir()},
            )
            _load_manifest(target)
            for name in ("starter_uk.pgn", "stress_uk.pgn", "sample_library.acsdb", "manifest.json"):
                self.assertEqual((source / name).read_bytes(), (target / name).read_bytes())

    def test_existing_target_fails_closed_without_replacement(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p0f-stage-existing-") as raw:
            source, product = self._fixture(Path(raw))
            target = product / "release-content" / "w2-starter"
            target.mkdir(parents=True)
            marker = target / "owner.txt"
            marker.write_text("foreign", encoding="utf-8")

            with self.assertRaisesRegex(staging.StageError, "target already exists"):
                staging.stage_bundle(source, product)

            self.assertEqual("foreign", marker.read_text(encoding="utf-8"))
            self.assertEqual({"owner.txt"}, {item.name for item in target.iterdir()})

    def test_unexpected_source_payload_is_rejected_before_publication(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p0f-stage-extra-") as raw:
            source, product = self._fixture(Path(raw))
            (source / "unexpected.bin").write_bytes(b"not release content")

            with self.assertRaisesRegex(staging.StageError, "file inventory is invalid"):
                staging.stage_bundle(source, product)

            self.assertFalse((product / "release-content" / "w2-starter").exists())

    def test_manifest_change_during_validation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p0f-stage-race-") as raw:
            source, product = self._fixture(Path(raw))
            original_load = staging._load_manifest

            def validate_then_mutate(path: Path):
                result = original_load(path)
                if Path(path) == source:
                    manifest_path = source / "manifest.json"
                    document = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest_path.write_text(
                        json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                return result

            with mock.patch.object(staging, "_load_manifest", side_effect=validate_then_mutate):
                with self.assertRaisesRegex(staging.StageError, "manifest changed during validation"):
                    staging.stage_bundle(source, product)

            self.assertFalse((product / "release-content" / "w2-starter").exists())

    def test_failed_copy_rolls_back_release_root_created_by_transaction(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p0f-stage-rollback-") as raw:
            source, product = self._fixture(Path(raw))
            release_root = product / "release-content"

            with mock.patch.object(
                staging,
                "_fsync_copy",
                side_effect=staging.StageError("synthetic copy failure"),
            ):
                with self.assertRaisesRegex(staging.StageError, "synthetic copy failure"):
                    staging.stage_bundle(source, product)

            self.assertFalse(release_root.exists())

    def test_failed_copy_preserves_preexisting_release_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p0f-stage-preserve-root-") as raw:
            source, product = self._fixture(Path(raw))
            release_root = product / "release-content"
            release_root.mkdir()
            marker = release_root / "owner.txt"
            marker.write_text("keep", encoding="utf-8")

            with mock.patch.object(
                staging,
                "_fsync_copy",
                side_effect=staging.StageError("synthetic copy failure"),
            ):
                with self.assertRaisesRegex(staging.StageError, "synthetic copy failure"):
                    staging.stage_bundle(source, product)

            self.assertEqual("keep", marker.read_text(encoding="utf-8"))
            self.assertEqual({"owner.txt"}, {item.name for item in release_root.iterdir()})

    def test_missing_executable_rejects_staging(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p0f-stage-no-exe-") as raw:
            source, product = self._fixture(Path(raw))
            (product / "AccessibleChess.exe").unlink()

            with self.assertRaisesRegex(staging.StageError, "AccessibleChess.exe is missing"):
                staging.stage_bundle(source, product)

            self.assertFalse((product / "release-content" / "w2-starter").exists())

    def test_directory_at_executable_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="p0f-stage-exe-dir-") as raw:
            source, product = self._fixture(Path(raw))
            exe = product / "AccessibleChess.exe"
            exe.unlink()
            exe.mkdir()

            with self.assertRaisesRegex(staging.StageError, "direct regular file"):
                staging.stage_bundle(source, product)

            self.assertFalse((product / "release-content" / "w2-starter").exists())


if __name__ == "__main__":
    unittest.main()
