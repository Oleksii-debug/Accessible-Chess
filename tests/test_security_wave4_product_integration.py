from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from acs.protection_boundary import (
    HARDENED_SECURITY_RUNTIME_API_VERSION,
    ProtectionRuntimeClient,
)
from acs.protection_hardened_boundary import (
    HardenedReleaseBoundary,
    ProtectionHardenedError,
    REQUIRED_HARDENED_CHECKS,
)


def make_client(tmp_path: Path, *, edit=None, version=5):
    calls = []

    def verify_hardened_release_check(**kwargs):
        calls.append(kwargs)
        value = {
            "api_version": 5,
            "check_id": kwargs["check_id"],
            "build_id": kwargs["build_id"],
            "authorized": True,
            "reason": "none",
        }
        return edit(value, kwargs) if edit else value

    runtime = SimpleNamespace(
        RUNTIME_API_VERSION=version,
        verify_hardened_release_check=verify_hardened_release_check,
    )
    client = ProtectionRuntimeClient(
        application_dir=tmp_path / "app",
        state_root=tmp_path / "state",
        module_loader=lambda _: runtime,
    )
    return client, calls, runtime


def test_independent_hardened_checks_all_execute_without_single_global_unlock(tmp_path):
    client, calls, _ = make_client(tmp_path)
    HardenedReleaseBoundary(client).require_all(build_id="release-123")
    assert tuple(call["check_id"] for call in calls) == REQUIRED_HARDENED_CHECKS
    assert len({call["check_id"] for call in calls}) == len(calls)
    assert all(call["build_id"] == "release-123" for call in calls)
    assert HARDENED_SECURITY_RUNTIME_API_VERSION == 5


@pytest.mark.parametrize("invalid", ["", "a b", "x" * 257, None, 42, True])
def test_bad_build_identity_fails_before_private_call(tmp_path, invalid):
    client, calls, _ = make_client(tmp_path)
    with pytest.raises(ProtectionHardenedError):
        HardenedReleaseBoundary(client).require_all(build_id=invalid)
    assert calls == []


@pytest.mark.parametrize("mutation", [
    lambda r: {**r, "authorized": 1},
    lambda r: {**r, "authorized": "yes"},
    lambda r: {**r, "api_version": True},
    lambda r: {**r, "api_version": 4},
    lambda r: {**r, "check_id": "wrong-check"},
    lambda r: {**r, "build_id": "other-release"},
    lambda r: {**r, "reason": "none", "authorized": False},
    lambda r: {**r, "reason": "secret value"},
    lambda r: {**r, "reason": "expired"},
    lambda r: {**r, "extra": 1},
    lambda r: {k: v for k, v in r.items() if k != "authorized"},
    lambda r: None,
])
def test_malformed_or_forged_verdict_fails_closed(tmp_path, mutation):
    def edit(value, kwargs):
        if kwargs["check_id"] == "device-key-binding":
            return mutation(value)
        return value
    client, calls, _ = make_client(tmp_path, edit=edit)
    with pytest.raises(ProtectionHardenedError):
        HardenedReleaseBoundary(client).require_all(build_id="build-1")
    assert [c["check_id"] for c in calls] == list(REQUIRED_HARDENED_CHECKS[:4])


@pytest.mark.parametrize("version", [1, 2, 3, 4, 6, True, None])
def test_missing_or_unsupported_private_v5_fails_closed(tmp_path, version):
    client, calls, _ = make_client(tmp_path, version=version)
    with pytest.raises(ProtectionHardenedError):
        HardenedReleaseBoundary(client).require_all(build_id="build-1")
    assert not calls


def test_provider_exception_does_not_leak_private_detail(tmp_path):
    client, calls, runtime = make_client(tmp_path)

    def raise_secret(**_kwargs):
        raise RuntimeError("secret-token=NEVER-PUBLISH")

    runtime.verify_hardened_release_check = raise_secret
    with pytest.raises(ProtectionHardenedError) as caught:
        HardenedReleaseBoundary(client).require_all(build_id="build-1")
    assert "NEVER-PUBLISH" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert not calls


def test_each_individual_denial_stops_later_checks_and_preserves_retry(tmp_path):
    denied = {"check_id": REQUIRED_HARDENED_CHECKS[0]}

    def edit(value, kwargs):
        if kwargs["check_id"] == denied["check_id"]:
            return {**value, "authorized": False, "reason": "policy_denied"}
        return value

    client, calls, _ = make_client(tmp_path, edit=edit)
    for check in REQUIRED_HARDENED_CHECKS:
        denied["check_id"] = check
        calls.clear()
        with pytest.raises(ProtectionHardenedError, match="policy_denied"):
            HardenedReleaseBoundary(client).require_all(build_id="build-1")
        assert calls[-1]["check_id"] == check
    denied["check_id"] = ""
    calls.clear()
    HardenedReleaseBoundary(client).require_all(build_id="build-1")
    assert len(calls) == len(REQUIRED_HARDENED_CHECKS)
