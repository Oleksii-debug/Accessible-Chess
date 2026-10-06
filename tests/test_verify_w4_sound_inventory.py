from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.verify_w4_sound_inventory import (
    RUN_METADATA_PATH,
    SOUND_INVENTORY_PATH,
    SOUND_NOTICE_PATH,
    SOUND_ROOT,
    SOUND_WAV_COUNT,
    SoundInventoryVerificationError,
    verify,
)


PRODUCT_SHA = "f" * 40
WORKFLOW_SHA = "a" * 40
SOUND_ZIP_SHA = "b" * 64
DEFAULT_WAV_BYTES = b"RIFF-test-wav"


def _sound_rows(payloads: list[bytes]) -> tuple[list[dict[str, object]], str]:
    rows: list[dict[str, object]] = []
    fingerprint_rows: list[bytes] = []
    for index, payload in enumerate(payloads):
        relative = f"test-{index:03d}.wav"
        digest = hashlib.sha256(payload).hexdigest()
        rows.append(
            {
                "file": f"library/{relative}",
                "sha256": digest,
                "bytes": len(payload),
                "channels": 1,
            }
        )
        fingerprint_rows.append(f"{relative}\0{digest}\n".encode("utf-8"))
    return rows, hashlib.sha256(b"".join(fingerprint_rows)).hexdigest()


def _artifact_bytes(
    *,
    payloads: list[bytes] | None = None,
    inventory_rows: list[dict[str, object]] | None = None,
    authorized_inventory_sha: str | None = None,
    notice_overrides: dict[str, object] | None = None,
    extra_wav: bool = False,
    product_sha: str = PRODUCT_SHA,
    workflow_sha: str = WORKFLOW_SHA,
) -> bytes:
    payloads = list(payloads or [DEFAULT_WAV_BYTES] * SOUND_WAV_COUNT)
    computed_rows, computed_sha = _sound_rows(payloads)
    rows = inventory_rows if inventory_rows is not None else computed_rows
    inventory_sha = authorized_inventory_sha or computed_sha
    inventory: dict[str, object] = {
        "schema_version": 1,
        "source": "urn:test:sound-pack",
        "license_id": "USER_PROVIDED",
        "creator": "test fixture",
        "file_count": SOUND_WAV_COUNT,
        "source_inventory_sha256": inventory_sha,
        "source_archive_sha256": SOUND_ZIP_SHA,
        "source_archive_bytes": 123456,
        "files": rows,
    }
    notice = dict(inventory)
    notice.update(notice_overrides or {})
    metadata = {
        "schema_version": 1,
        "product_sha": product_sha,
        "workflow_sha": workflow_sha,
        "pre_upload_product_freshness": True,
        "pre_upload_workflow_freshness": True,
        "user_sound_pack_zip_sha256": SOUND_ZIP_SHA,
        "user_sound_inventory_sha256": inventory_sha,
        "user_sound_wav_count": SOUND_WAV_COUNT,
        "human_tested": False,
        "nvda_verified": False,
    }

    inner_buffer = io.BytesIO()
    with zipfile.ZipFile(inner_buffer, "w", compression=zipfile.ZIP_STORED) as inner:
        inner.writestr(SOUND_INVENTORY_PATH, json.dumps(inventory, sort_keys=True))
        inner.writestr(SOUND_NOTICE_PATH, json.dumps(notice, sort_keys=True))
        for index, payload in enumerate(payloads):
            inner.writestr(
                f"{SOUND_ROOT}/library/test-{index:03d}.wav",
                payload,
            )
        if extra_wav:
            inner.writestr(f"{SOUND_ROOT}/library/untracked.wav", b"RIFF-extra")

    outer_buffer = io.BytesIO()
    candidate_name = f"Accessible-Chess-V2-{PRODUCT_SHA[:7]}-NVDA-test-candidate.zip"
    with zipfile.ZipFile(outer_buffer, "w", compression=zipfile.ZIP_STORED) as outer:
        outer.writestr(RUN_METADATA_PATH, json.dumps(metadata, sort_keys=True))
        outer.writestr(candidate_name, inner_buffer.getvalue())
    return outer_buffer.getvalue()


def _verify_bytes(payload: bytes) -> None:
    with tempfile.TemporaryDirectory() as directory:
        artifact = Path(directory) / "artifact.zip"
        artifact.write_bytes(payload)
        verify(artifact, PRODUCT_SHA, WORKFLOW_SHA)


class W4SoundInventoryVerificationTests(unittest.TestCase):
    def test_valid_packaged_wavs_are_bound_to_authorized_inventory(self) -> None:
        _verify_bytes(_artifact_bytes())

    def test_tampered_packaged_wav_bytes_fail_against_inventory_row(self) -> None:
        original_payloads = [DEFAULT_WAV_BYTES] * SOUND_WAV_COUNT
        rows, inventory_sha = _sound_rows(original_payloads)
        tampered_payloads = list(original_payloads)
        tampered_payloads[17] = b"RIFF-tampered"
        with self.assertRaisesRegex(
            SoundInventoryVerificationError,
            "packaged sound WAV (byte count|SHA-256) mismatch",
        ):
            _verify_bytes(
                _artifact_bytes(
                    payloads=tampered_payloads,
                    inventory_rows=rows,
                    authorized_inventory_sha=inventory_sha,
                )
            )

    def test_coherent_wav_and_row_rewrite_fails_authorized_inventory_digest(self) -> None:
        original_payloads = [DEFAULT_WAV_BYTES] * SOUND_WAV_COUNT
        _original_rows, authorized_sha = _sound_rows(original_payloads)
        changed_payloads = list(original_payloads)
        changed_payloads[21] = b"RIFF-coherent-rewrite"
        changed_rows, _changed_sha = _sound_rows(changed_payloads)
        with self.assertRaisesRegex(
            SoundInventoryVerificationError,
            "recomputed sound source inventory SHA-256",
        ):
            _verify_bytes(
                _artifact_bytes(
                    payloads=changed_payloads,
                    inventory_rows=changed_rows,
                    authorized_inventory_sha=authorized_sha,
                )
            )

    def test_audit_notice_must_equal_packaged_inventory(self) -> None:
        with self.assertRaisesRegex(
            SoundInventoryVerificationError,
            "audit notice does not equal inventory",
        ):
            _verify_bytes(
                _artifact_bytes(notice_overrides={"creator": "changed notice"})
            )

    def test_untracked_packaged_wav_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            SoundInventoryVerificationError,
            "packaged sound WAV inventory mismatch",
        ):
            _verify_bytes(_artifact_bytes(extra_wav=True))

    def test_run_identity_must_match_requested_product_and_workflow(self) -> None:
        with self.assertRaisesRegex(
            SoundInventoryVerificationError,
            "product_sha mismatch",
        ):
            _verify_bytes(_artifact_bytes(product_sha="e" * 40))
        with self.assertRaisesRegex(
            SoundInventoryVerificationError,
            "workflow_sha mismatch",
        ):
            _verify_bytes(_artifact_bytes(workflow_sha="d" * 40))


if __name__ == "__main__":
    unittest.main()
