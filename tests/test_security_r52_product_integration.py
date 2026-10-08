"""R52 product-side private container check, no public modes/account IDs."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import pytest

from acs.protection_boundary import ProtectionRuntimeClient
from acs.protection_license_container_boundary import (
    ProductLicenseContainerDenied, require_private_license_container,
)


def client_for(tmp_path: Path, *, mutate=None, version=5):
    calls = []
    def private_verify(**kwargs):
        calls.append(kwargs)
        receipt = {
            "api_version": 5, "build_id": kwargs["build_id"],
            "authorized": True, "reason": "none",
        }
        return mutate(receipt) if mutate is not None else receipt
    private = SimpleNamespace(
        RUNTIME_API_VERSION=version,
        verify_license_container=private_verify,
    )
    client = ProtectionRuntimeClient(
        application_dir=tmp_path / "app",
        state_root=tmp_path / "state",
        module_loader=lambda _: private,
    )
    return client, calls, private


def test_r52_exact_private_build_binding_no_user_selected_mode(tmp_path):
    client, calls, _ = client_for(tmp_path)
    assert require_private_license_container(client, build_id="release-1") is None
    assert calls == [{
        "package_root": tmp_path / "app",
        "state_root": tmp_path / "state",
        "build_id": "release-1",
    }]
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize("bad", ["", "x y", "x"*257, 1, True, None])
def test_r52_invalid_build_denied_before_any_private_effect(tmp_path, bad):
    client, calls, _ = client_for(tmp_path)
    with pytest.raises(ProductLicenseContainerDenied):
        require_private_license_container(client, build_id=bad)
    assert calls == []


@pytest.mark.parametrize("mutation", [
    lambda r: {**r, "authorized": 1},
    lambda r: {**r, "authorized": "yes"},
    lambda r: {**r, "authorized": False, "reason": "not_configured"},
    lambda r: {**r, "authorized": True, "reason": "fallback"},
    lambda r: {**r, "api_version": True},
    lambda r: {**r, "api_version": 5.0},
    lambda r: {**r, "api_version": 6},
    lambda r: {**r, "build_id": "other-build"},
    lambda r: {**r, "reason": "secret token"},
    lambda r: {**r, "mode": "cloud"},
    lambda r: {k: v for k, v in r.items() if k != "authorized"},
    lambda r: None,
])
def test_r52_fake_success_transport_switch_malformed_receipts_denied(tmp_path, mutation):
    client, calls, _ = client_for(tmp_path, mutate=mutation)
    with pytest.raises(ProductLicenseContainerDenied):
        require_private_license_container(client, build_id="release-1")
    assert len(calls) == 1


def test_r52_missing_provider_or_stale_api_never_falls_back(tmp_path):
    client, calls, runtime = client_for(tmp_path)
    del runtime.verify_license_container
    with pytest.raises(ProductLicenseContainerDenied, match="unavailable"):
        require_private_license_container(client, build_id="release-1")
    assert calls == []
    client, calls, _ = client_for(tmp_path, version=4)
    with pytest.raises(ProductLicenseContainerDenied, match="unavailable"):
        require_private_license_container(client, build_id="release-1")
    assert calls == []


def test_r52_provider_exception_is_redacted(tmp_path):
    client, calls, runtime = client_for(tmp_path)
    def fail(**_kwargs):
        raise RuntimeError("PRIVATE-NATIVE-SECRET-NEVER-LOG")
    runtime.verify_license_container = fail
    with pytest.raises(ProductLicenseContainerDenied) as err:
        require_private_license_container(client, build_id="release-1")
    assert "PRIVATE-NATIVE" not in str(err.value)
    assert err.value.__cause__ is None
    assert calls == []
