from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from acs.protection_advanced_boundary import (
    ProtectionAdvancedError,
    ProtectionCapabilityGate,
    ProtectionTrustBoundary,
    ProtectionTrustedTimeSource,
    ProtectionUpdateChannel,
    ProtectionUpdateInstaller,
    ProtectionUpdateSignatureVerifier,
)
from acs.protection_boundary import ProtectionRuntimeClient
from acs.release_update_center import ReleaseUpdateCenter


def _client(tmp_path: Path, runtime) -> ProtectionRuntimeClient:
    return ProtectionRuntimeClient(
        application_dir=tmp_path / "app",
        state_root=tmp_path / "state",
        module_loader=lambda _name: runtime,
    )


def _runtime_v4(tmp_path: Path):
    calls: list[tuple[str, object]] = []
    state_root = tmp_path / "state"
    staged_root = state_root / "security-updates"
    staged_root.mkdir(parents=True, exist_ok=True)
    package = staged_root / "candidate.package"
    package_bytes = b"wave3-update-package"
    package.write_bytes(package_bytes)
    digest = hashlib.sha256(package_bytes).hexdigest()

    signed = {
        "schema_version": 1,
        "product": "accessible-chess",
        "key_id": "prod-update-1",
        "version": "0.3.3",
        "minimum_current_version": "0.3.0",
        "download_url": "https://updates.example.invalid/accessible-chess-0.3.3.zip",
        "package_sha256": digest,
        "package_size": len(package_bytes),
        "published_at": "2026-10-08T02:00:00Z",
        "expires_at": "2026-10-09T02:00:00Z",
    }
    metadata = json.dumps(
        {
            "signed": signed,
            "signature": base64.b64encode(b"runtime-signature").decode("ascii"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    def evaluate_startup(**kwargs):
        return {
            "api_version": 4,
            "state": "authorized",
            "reason": "none",
            "safe_operations": ["recovery", "login", "update", "help", "own-data-read", "own-data-export"],
            "capabilities": ["local-chess"],
            "build_id": "build-wave3",
        }

    def authorize_product_boundary(**kwargs):
        boundary_id = kwargs["boundary_id"]
        calls.append(("boundary", boundary_id))
        if boundary_id == "denied.family":
            return {
                "api_version": 4,
                "boundary_id": boundary_id,
                "authorized": False,
                "reason": "entitlement_required",
                "live_region": "assertive",
                "action": "login",
            }
        return {
            "api_version": 4,
            "boundary_id": boundary_id,
            "authorized": True,
            "reason": "none",
            "live_region": "none",
            "action": "none",
        }

    def read_trust_status(**kwargs):
        calls.append(("trust", "read"))
        return {
            "api_version": 4,
            "state": "trusted",
            "reason": "none",
            "sequence": 12,
            "live_region": "none",
            "action": "none",
        }

    def synchronize_trust_state(**kwargs):
        calls.append(("trust", "sync"))
        return None

    def stage_secure_update(**kwargs):
        calls.append(("update", ("stage", kwargs["current_version"])))
        return {
            "api_version": 4,
            "metadata_utf8": metadata,
            "package_path": str(package),
            "source_url": signed["download_url"],
        }

    def verify_update_signature(**kwargs):
        calls.append(("update", ("verify", kwargs["key_id"])))
        return kwargs["key_id"] == "prod-update-1"

    def trusted_update_time(**kwargs):
        calls.append(("update", "time"))
        return "2026-10-08T03:00:00Z"

    def install_verified_update_handoff(**kwargs):
        path = Path(kwargs["verified_handoff_path"])
        calls.append(("update", ("install", kwargs["version"], path.read_bytes())))
        return path.read_bytes() == package_bytes and kwargs["version"] == "0.3.3"

    runtime = SimpleNamespace(
        RUNTIME_API_VERSION=4,
        evaluate_startup=evaluate_startup,
        authorize_product_boundary=authorize_product_boundary,
        read_trust_status=read_trust_status,
        synchronize_trust_state=synchronize_trust_state,
        stage_secure_update=stage_secure_update,
        verify_update_signature=verify_update_signature,
        trusted_update_time=trusted_update_time,
        install_verified_update_handoff=install_verified_update_handoff,
    )
    return runtime, calls, package_bytes


def test_capability_gate_uses_independent_boundary_ids_without_global_unlock(tmp_path):
    runtime, calls, _ = _runtime_v4(tmp_path)
    gate = ProtectionCapabilityGate(_client(tmp_path, runtime))
    gate.require("engine.analysis")
    gate.require("library.database")
    with pytest.raises(ProtectionAdvancedError, match="entitlement_required"):
        gate.require("denied.family")
    gate.require("books.training")
    assert [value for kind, value in calls if kind == "boundary"] == [
        "engine.analysis",
        "library.database",
        "denied.family",
        "books.training",
    ]


def test_trust_boundary_synchronizes_and_requires_monotonic_public_status(tmp_path):
    runtime, calls, _ = _runtime_v4(tmp_path)
    status = ProtectionTrustBoundary(_client(tmp_path, runtime)).synchronize()
    assert status.state == "trusted"
    assert status.sequence == 12
    assert ("trust", "sync") in calls
    assert ("trust", "read") in calls


def test_existing_release_update_center_runs_on_private_wave3_adapters(tmp_path):
    runtime, calls, package_bytes = _runtime_v4(tmp_path)
    client = _client(tmp_path, runtime)
    center = ReleaseUpdateCenter(
        current_version="0.3.2",
        channel=ProtectionUpdateChannel(client),
        verifier=ProtectionUpdateSignatureVerifier(client),
        time_source=ProtectionTrustedTimeSource(client),
        installer=ProtectionUpdateInstaller(client),
    )
    ready = center.check(language="en")
    assert ready.state == "ready"
    assert ready.target_version == "0.3.3"
    installed = center.apply(language="en")
    assert installed.state == "installed"
    installs = [
        value for kind, value in calls
        if kind == "update" and isinstance(value, tuple) and value[0] == "install"
    ]
    assert installs == [("install", "0.3.3", package_bytes)]


def test_update_staging_rejects_path_outside_private_update_root(tmp_path):
    runtime, calls, _ = _runtime_v4(tmp_path)
    outside = tmp_path / "outside.package"
    outside.write_bytes(b"x")

    def bad_stage(**kwargs):
        return {
            "api_version": 4,
            "metadata_utf8": "{}",
            "package_path": str(outside),
            "source_url": "https://updates.example.invalid/x",
        }

    runtime.stage_secure_update = bad_stage
    with pytest.raises(ProtectionAdvancedError, match="escaped staging root"):
        ProtectionUpdateChannel(_client(tmp_path, runtime)).stage(current_version="0.3.2")


def test_update_signature_failure_is_fail_closed(tmp_path):
    runtime, calls, _ = _runtime_v4(tmp_path)
    runtime.verify_update_signature = lambda **kwargs: False
    verifier = ProtectionUpdateSignatureVerifier(_client(tmp_path, runtime))
    assert verifier.verify(key_id="prod-update-1", message=b"m", signature=b"s") is False


def test_release_composition_contains_distinct_wave3_service_gates():
    """The shipping root gates canonical *surfaces*, not obsolete free-text IDs."""
    source = (Path(__file__).resolve().parents[1] / "acs" / "version2_release_app.py").read_text(encoding="utf-8")
    from acs.protection_product_boundaries import boundaries_for_surface

    for surface in (
        "licensing.local",
        "persistence.local",
        "integration.local",
        "engine.local",
        "chess.local",
        "library.local",
        "books.training",
        "classroom.local",
        "formats.core",
    ):
        assert boundaries_for_surface(surface), surface
        assert f'capability_gate.require_surface("{surface}")' in source, surface
    assert "release_update_center=release_update_center" in source
    assert '_product_version.split("-", 1)[0]' in source


def test_wave3_all_canonical_ids_admitted_without_broadening_id_grammar(tmp_path):
    """The exact published 48-ID inventory works without accepting arbitrary uppercase IDs."""
    from acs.protection_product_boundaries import CANONICAL_PRODUCT_BOUNDARY_IDS

    runtime, calls, _ = _runtime_v4(tmp_path)
    gate = ProtectionCapabilityGate(_client(tmp_path, runtime))
    for boundary in CANONICAL_PRODUCT_BOUNDARY_IDS:
        gate.require(boundary)
    assert [value for kind, value in calls if kind == "boundary"] == list(
        CANONICAL_PRODUCT_BOUNDARY_IDS
    )


@pytest.mark.parametrize(
    "invalid_id",
    [
        "BND.AC-S99-UNKNOWN",
        "BND.AC-S13-engine",
        "BND.AC-S13-ENGINE ",
        "BND.AC-S13-ENGINE/../x",
        "BND.AC-S13-ENGINE\\x00",
        "ENGINE.ANALYSIS",
    ],
)
def test_wave3_noncanonical_uppercase_ids_fail_before_private_authorization(tmp_path, invalid_id):
    runtime, calls, _ = _runtime_v4(tmp_path)
    gate = ProtectionCapabilityGate(_client(tmp_path, runtime))
    with pytest.raises(ProtectionAdvancedError, match="product boundary id is invalid"):
        gate.require(invalid_id)
    assert not calls


def test_wave3_surface_expansion_uses_canonical_boundaries_and_fails_closed(tmp_path):
    """Every mapped boundary must be individually authorized; one deny blocks."""
    from acs.protection_product_boundaries import boundaries_for_surface

    runtime, calls, _ = _runtime_v4(tmp_path)
    gate = ProtectionCapabilityGate(_client(tmp_path, runtime))
    surfaces = ("engine.local", "library.local", "books.training")
    for surface in surfaces:
        gate.require_surface(surface)
    assert [value for kind, value in calls if kind == "boundary"] == [
        boundary for surface in surfaces
        for boundary in boundaries_for_surface(surface)
    ]

    denied = boundaries_for_surface("engine.local")[0]

    def deny_engine(**kwargs):
        boundary = kwargs["boundary_id"]
        return {
            "api_version": 4,
            "boundary_id": boundary,
            "authorized": boundary != denied,
            "reason": "entitlement_required" if boundary == denied else "none",
            "live_region": "assertive" if boundary == denied else "none",
            "action": "login" if boundary == denied else "none",
        }

    runtime.authorize_product_boundary = deny_engine
    with pytest.raises(ProtectionAdvancedError, match="entitlement_required"):
        gate.require_surface("engine.local")
