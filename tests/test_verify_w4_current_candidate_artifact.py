from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from acs.version2_package_preflight import Version2PackagePreflightError
from scripts.verify_w4_candidate_artifact import CandidateArtifactError
from scripts.verify_w4_current_candidate_artifact import (
    CURRENT_RUN_METADATA_KEYS,
    RUN_METADATA_PATH,
    SOUND_INVENTORY_PATH,
    SOUND_REQUIRED_METADATA,
    SOUND_ROOT,
    SOUND_WAV_COUNT,
    _read_current_run_metadata,
    _translated_legacy_metadata,
    _verify_current_sound_binding,
    _verify_exact_product_package_preflight,
    validate_current_run_metadata,
    verify_current,
)


PRODUCT_SHA = "f" * 40
WORKFLOW_SHA = "a" * 40
SOUND_ZIP_SHA = "b" * 64
SOUND_INVENTORY_SHA = "c" * 64
CONFIG_SHA = "d" * 64


def _metadata(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": 1,
        "product_sha": PRODUCT_SHA,
        "workflow_sha": WORKFLOW_SHA,
        "pre_upload_product_freshness": True,
        "pre_upload_workflow_freshness": True,
        "user_sound_pack_zip_sha256": SOUND_ZIP_SHA,
        "user_sound_inventory_sha256": SOUND_INVENTORY_SHA,
        "user_sound_wav_count": SOUND_WAV_COUNT,
        "human_tested": False,
        "nvda_verified": False,
    }
    value.update(overrides)
    return value


def _current_outer_bytes(
    metadata: dict[str, object],
    *,
    inventory_overrides: dict[str, object] | None = None,
    wav_count: int = SOUND_WAV_COUNT,
) -> bytes:
    inner_buffer = io.BytesIO()
    inventory: dict[str, object] = {
        "file_count": SOUND_WAV_COUNT,
        "source_inventory_sha256": SOUND_INVENTORY_SHA,
        "source_archive_sha256": SOUND_ZIP_SHA,
        "source_archive_bytes": 123456,
    }
    inventory.update(inventory_overrides or {})
    with zipfile.ZipFile(inner_buffer, "w", compression=zipfile.ZIP_STORED) as inner:
        inner.writestr(SOUND_INVENTORY_PATH, json.dumps(inventory))
        for name in sorted(SOUND_REQUIRED_METADATA - {SOUND_INVENTORY_PATH}):
            inner.writestr(name, "{}")
        for index in range(wav_count):
            inner.writestr(f"{SOUND_ROOT}/library/test-{index:03d}.wav", b"RIFF")

    outer_buffer = io.BytesIO()
    candidate_name = f"Accessible-Chess-V2-{PRODUCT_SHA[:7]}-NVDA-test-candidate.zip"
    with zipfile.ZipFile(outer_buffer, "w", compression=zipfile.ZIP_STORED) as outer:
        outer.writestr(
            RUN_METADATA_PATH,
            json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n",
        )
        outer.writestr(candidate_name, inner_buffer.getvalue())
    return outer_buffer.getvalue()


class W4CurrentCandidateArtifactTests(unittest.TestCase):
    def test_current_schema_is_exact_and_preserves_sound_identity(self) -> None:
        value = validate_current_run_metadata(_metadata(), PRODUCT_SHA, WORKFLOW_SHA)
        self.assertEqual(set(value), CURRENT_RUN_METADATA_KEYS)
        self.assertEqual(value["user_sound_pack_zip_sha256"], SOUND_ZIP_SHA)
        self.assertEqual(value["user_sound_inventory_sha256"], SOUND_INVENTORY_SHA)
        self.assertEqual(value["user_sound_wav_count"], 330)

    def test_current_schema_rejects_legacy_config_field_instead_of_silently_accepting_it(self) -> None:
        with self.assertRaisesRegex(CandidateArtifactError, "unexpected=.*winforms"):
            validate_current_run_metadata(
                _metadata(winforms_accessibility_config_sha256=CONFIG_SHA),
                PRODUCT_SHA,
                WORKFLOW_SHA,
            )

    def test_current_schema_rejects_sound_count_or_acceptance_overclaim(self) -> None:
        with self.assertRaisesRegex(CandidateArtifactError, "user_sound_wav_count must equal 330"):
            validate_current_run_metadata(
                _metadata(user_sound_wav_count=329), PRODUCT_SHA, WORKFLOW_SHA
            )
        with self.assertRaisesRegex(CandidateArtifactError, "nvda_verified must be False"):
            validate_current_run_metadata(
                _metadata(nvda_verified=True), PRODUCT_SHA, WORKFLOW_SHA
            )

    def test_outer_current_metadata_round_trip_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outer.zip"
            path.write_bytes(_current_outer_bytes(_metadata()))
            value = _read_current_run_metadata(path, PRODUCT_SHA, WORKFLOW_SHA)
        self.assertEqual(value, _metadata())

    def test_sound_identity_is_bound_to_inner_candidate_inventory_and_wavs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outer.zip"
            path.write_bytes(_current_outer_bytes(_metadata()))
            _verify_current_sound_binding(path, PRODUCT_SHA, _metadata())

    def test_sound_identity_fails_closed_on_inventory_digest_or_wav_count_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outer.zip"
            path.write_bytes(
                _current_outer_bytes(
                    _metadata(),
                    inventory_overrides={"source_inventory_sha256": "e" * 64},
                )
            )
            with self.assertRaisesRegex(CandidateArtifactError, "inventory SHA-256"):
                _verify_current_sound_binding(path, PRODUCT_SHA, _metadata())

            path.write_bytes(_current_outer_bytes(_metadata(), wav_count=329))
            with self.assertRaisesRegex(CandidateArtifactError, "library WAV inventory mismatch"):
                _verify_current_sound_binding(path, PRODUCT_SHA, _metadata())

    def test_exact_product_package_preflight_rechecks_materialized_inner_candidate(self) -> None:
        observed: dict[str, object] = {}

        def validate(candidate_path: Path, *, expected_integration_sha: str) -> object:
            observed["expected_sha"] = expected_integration_sha
            with zipfile.ZipFile(candidate_path, "r") as candidate:
                observed["members"] = set(candidate.namelist())
            return object()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outer.zip"
            path.write_bytes(_current_outer_bytes(_metadata()))
            with patch(
                "scripts.verify_w4_current_candidate_artifact.validate_version2_package_zip",
                side_effect=validate,
            ) as validator:
                _verify_exact_product_package_preflight(path, PRODUCT_SHA)

        validator.assert_called_once()
        self.assertEqual(observed["expected_sha"], PRODUCT_SHA)
        self.assertIn(SOUND_INVENTORY_PATH, observed["members"])

    def test_exact_product_package_preflight_failure_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outer.zip"
            path.write_bytes(_current_outer_bytes(_metadata()))
            with patch(
                "scripts.verify_w4_current_candidate_artifact.validate_version2_package_zip",
                side_effect=Version2PackagePreflightError("catalog drift"),
            ):
                with self.assertRaisesRegex(
                    CandidateArtifactError,
                    "exact Product package preflight failed: catalog drift",
                ):
                    _verify_exact_product_package_preflight(path, PRODUCT_SHA)

    def test_verify_current_invokes_exact_product_preflight_before_legacy_contract(self) -> None:
        calls: list[str] = []

        def record_preflight(path: Path, expected_sha: str) -> None:
            self.assertTrue(path.is_file())
            self.assertEqual(expected_sha, PRODUCT_SHA)
            calls.append("preflight")

        def record_legacy(*args: object, **kwargs: object) -> None:
            calls.append("legacy")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outer.zip"
            path.write_bytes(_current_outer_bytes(_metadata()))
            with (
                patch(
                    "scripts.verify_w4_current_candidate_artifact._verify_exact_product_package_preflight",
                    side_effect=record_preflight,
                ),
                patch(
                    "scripts.verify_w4_current_candidate_artifact.verify_legacy_contract",
                    side_effect=record_legacy,
                ),
            ):
                verify_current(
                    path,
                    PRODUCT_SHA,
                    WORKFLOW_SHA,
                    CONFIG_SHA,
                )

        self.assertEqual(calls, ["preflight", "legacy"])

    def test_translation_retains_legacy_config_binding_without_sound_key_leak(self) -> None:
        translated = _translated_legacy_metadata(_metadata(), CONFIG_SHA)
        self.assertEqual(translated["winforms_accessibility_config_sha256"], CONFIG_SHA)
        self.assertNotIn("user_sound_pack_zip_sha256", translated)
        self.assertNotIn("user_sound_inventory_sha256", translated)
        self.assertNotIn("user_sound_wav_count", translated)
        self.assertFalse(translated["human_tested"])
        self.assertFalse(translated["nvda_verified"])


if __name__ == "__main__":
    unittest.main()
