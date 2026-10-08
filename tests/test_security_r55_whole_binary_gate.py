"""R55 Accessible Chess first-party whole-binary integration, not vendor qualification."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json

import pytest

from continuum_runtime.commercial_protector import ProtectorProfile
from continuum_runtime.whole_binary import (
    BinaryTarget, WholeBinaryPlan, _pe_image, prepare_whole_binary,
)
from scripts.security_r55_whole_binary_gate import (
    ProductEvidenceError, assess_product_whole_binary,
)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def pe() -> bytes:
    """Structurally valid synthetic x64 PE fixture, NOT a compiled Chess release."""
    data = bytearray(1024)
    data[:2] = b"MZ"
    data[0x3c:0x40] = (0x80).to_bytes(4, "little")
    data[0x80:0x84] = b"PE\x00\x00"
    data[0x84:0x86] = (0x8664).to_bytes(2, "little")
    data[0x86:0x88] = (1).to_bytes(2, "little")
    data[0x94:0x96] = (0xF0).to_bytes(2, "little")
    data[0x98:0x9a] = (0x20b).to_bytes(2, "little")
    return bytes(data)


@pytest.fixture()
def trial(tmp_path):
    source_root = tmp_path / "native"
    protected_root = tmp_path / "protected"
    source_root.mkdir()
    protected_root.mkdir()
    original = pe()
    assert _pe_image(original) is True
    (source_root / "AccessibleChess.exe").write_bytes(original)
    plan = WholeBinaryPlan(
        schema_version=1, build_id="chess-r55-synthetic-1",
        targets=(BinaryTarget("AccessibleChess.exe", sha(original)),),
    )
    profiles = {
        "AccessibleChess.exe": ProtectorProfile(
            schema_version=1, vendor="pace-ilok", profile_id="unit-test",
            build_id=plan.build_id, input_sha256=sha(original),
            tool_sha256="1" * 64, recipe_sha256="2" * 64,
        )
    }
    key = b"R55-NO-REAL-COMMERCIAL-KEY-TEST-ONLY"
    product = "a" * 64
    receipt, protected = prepare_whole_binary(
        plan=plan,
        sources={"AccessibleChess.exe": original},
        profiles=profiles,
        product_sha256=product,
        secret_key=key,
        protector=lambda _name, raw, variant: raw + b"-synthetic-" + variant,
        inspector=lambda _name, raw: _pe_image(raw),
    )
    (protected_root / "AccessibleChess.exe").write_bytes(
        protected["AccessibleChess.exe"]
    )
    plan_file = tmp_path / "plan.json"
    profiles_file = tmp_path / "profiles.json"
    receipt_file = tmp_path / "receipt.json"
    plan_file.write_text(json.dumps(asdict(plan)))
    profiles_file.write_text(json.dumps({
        name: asdict(profile) for name, profile in profiles.items()
    }))
    receipt_file.write_text(json.dumps(asdict(receipt)))
    return {
        "source_root": source_root,
        "protected_root": protected_root,
        "plan_file": plan_file,
        "profiles_file": profiles_file,
        "receipt_file": receipt_file,
        "expected_build_id": plan.build_id,
        "expected_product_sha256": product,
        "secret_key": key,
    }


def test_r55_synthetic_pe_passes_structural_readback_but_never_release(trial):
    result = assess_product_whole_binary(**trial)
    assert result["status"] == "STRUCTURAL_PE_INTEGRITY_ONLY"
    assert result["targets"] == ["AccessibleChess.exe"]
    assert result["release_approved"] is False
    assert result["native_protector_inspection"] == "NOT_PERFORMED"


def test_r55_forged_protected_image_is_denied(trial):
    (trial["protected_root"] / "AccessibleChess.exe").write_bytes(pe() + b"bad")
    with pytest.raises(ProductEvidenceError):
        assess_product_whole_binary(**trial)


def test_r55_original_copy_cannot_qualify_as_protected(trial):
    (trial["protected_root"] / "AccessibleChess.exe").write_bytes(pe())
    with pytest.raises(ProductEvidenceError, match="R55_UNPROTECTED_COPY"):
        assess_product_whole_binary(**trial)


@pytest.mark.parametrize("field", ["expected_product_sha256", "expected_build_id", "secret_key"])
def test_r55_cross_build_product_or_secret_reuse_denied(trial, field):
    forged = {**trial, field: (
        "b" * 64 if field == "expected_product_sha256" else
        "wrong-release" if field == "expected_build_id" else b"wrong" * 8
    )}
    with pytest.raises(ProductEvidenceError):
        assess_product_whole_binary(**forged)


def test_r55_third_party_stockfish_cannot_be_silently_protected(trial):
    plan = json.loads(trial["plan_file"].read_text())
    plan["targets"].append({
        "name": "stockfish.exe", "source_sha256": "0" * 64
    })
    trial["plan_file"].write_text(json.dumps(plan))
    with pytest.raises(ProductEvidenceError, match="R55_TARGET_SCHEMA_INVALID"):
        assess_product_whole_binary(**trial)


def test_r55_forged_receipt_is_rejected(trial):
    receipt = json.loads(trial["receipt_file"].read_text())
    receipt["protected_manifest_sha256"] = "0" * 64
    trial["receipt_file"].write_text(json.dumps(receipt))
    with pytest.raises(ProductEvidenceError):
        assess_product_whole_binary(**trial)


def test_r55_missing_protected_image_denied(trial):
    (trial["protected_root"] / "AccessibleChess.exe").unlink()
    with pytest.raises(ProductEvidenceError):
        assess_product_whole_binary(**trial)


def test_r55_symlink_protected_image_denied(trial):
    file = trial["protected_root"] / "AccessibleChess.exe"
    file.unlink()
    try:
        file.symlink_to(trial["source_root"] / "AccessibleChess.exe")
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable")
    with pytest.raises(ProductEvidenceError):
        assess_product_whole_binary(**trial)


def test_r55_invalid_receipt_boolean_schema_denied(trial):
    data = json.loads(trial["receipt_file"].read_text())
    data["schema_version"] = True
    trial["receipt_file"].write_text(json.dumps(data))
    with pytest.raises(ProductEvidenceError):
        assess_product_whole_binary(**trial)
