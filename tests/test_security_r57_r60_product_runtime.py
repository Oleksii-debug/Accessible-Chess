"""R57-R60 product private-runtime admission; no synthetic native PASS claims."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from acs.protection_boundary import (
    ProtectionDecision, ProtectionRuntimeClient, ProtectionStartupSession,
    ProtectedStartupLocked,
)
from acs.protection_hardened_boundary import (
    HardenedReleaseBoundary, ProtectionHardenedError,
    REQUIRED_COMMERCIAL_RUNTIME_CHECKS, REQUIRED_HARDENED_CHECKS,
)


def private_client(tmp_path: Path, *, edit=None, api=5, verifier=True):
    calls = []

    def verify_hardened_release_check(**kwargs):
        calls.append(dict(kwargs))
        value = {
            "api_version": 5, "check_id": kwargs["check_id"],
            "build_id": kwargs["build_id"], "authorized": True,
            "reason": "none",
        }
        return edit(value, kwargs) if edit is not None else value

    runtime = SimpleNamespace(RUNTIME_API_VERSION=api)
    if verifier:
        runtime.verify_hardened_release_check = verify_hardened_release_check
    client = ProtectionRuntimeClient(
        application_dir=tmp_path / "app", state_root=tmp_path / "user",
        module_loader=lambda _name: runtime,
    )
    return client, calls, runtime


def test_r57_r60_each_check_has_independent_private_receipt(tmp_path):
    client, calls, _ = private_client(tmp_path)
    HardenedReleaseBoundary(client).require_commercial_runtime(build_id="build-1")
    assert tuple(x["check_id"] for x in calls) == REQUIRED_COMMERCIAL_RUNTIME_CHECKS
    assert len(set(x["check_id"] for x in calls)) == len(calls) == 4
    assert not (set(REQUIRED_COMMERCIAL_RUNTIME_CHECKS) & set(REQUIRED_HARDENED_CHECKS))
    assert all(x["build_id"] == "build-1" for x in calls)


@pytest.mark.parametrize("bad", ["", "has space", "x" * 257, None, True])
def test_invalid_identity_denied_before_provider_call(tmp_path, bad):
    client, calls, _ = private_client(tmp_path)
    with pytest.raises(ProtectionHardenedError):
        HardenedReleaseBoundary(client).require_commercial_runtime(build_id=bad)
    assert calls == []


@pytest.mark.parametrize("api", [1, 2, 3, 4, 6, True, 5.0, "5"])
def test_missing_v5_provider_never_downgrades(tmp_path, api):
    client, calls, _ = private_client(tmp_path, api=api)
    with pytest.raises(ProtectionHardenedError):
        HardenedReleaseBoundary(client).require_commercial_runtime(build_id="build-1")
    assert calls == []


def test_absent_native_verifier_denied(tmp_path):
    client, calls, _ = private_client(tmp_path, verifier=False)
    with pytest.raises(ProtectionHardenedError, match="unavailable"):
        HardenedReleaseBoundary(client).require_commercial_runtime(build_id="build-1")
    assert calls == []


@pytest.mark.parametrize("mutation", [
    lambda r: {**r, "authorized": 1},
    lambda r: {**r, "authorized": "yes"},
    lambda r: {**r, "authorized": False, "reason": "native_integrity_denied"},
    lambda r: {**r, "api_version": 5.0},
    lambda r: {**r, "api_version": True},
    lambda r: {**r, "check_id": "instrumentation-clear"},
    lambda r: {**r, "build_id": "replayed-build"},
    lambda r: {**r, "extra": "forged"},
    lambda r: {k: v for k, v in r.items() if k != "reason"},
    lambda r: None,
])
def test_r57_forged_or_replayed_private_verdict_rejected(tmp_path, mutation):
    def edit(receipt, kwargs):
        if kwargs["check_id"] == "protected-runtime-integrity":
            return mutation(receipt)
        return receipt

    client, calls, _ = private_client(tmp_path, edit=edit)
    with pytest.raises(ProtectionHardenedError):
        HardenedReleaseBoundary(client).require_commercial_runtime(build_id="build-1")
    assert len(calls) == 1


@pytest.mark.parametrize("deny", REQUIRED_COMMERCIAL_RUNTIME_CHECKS)
def test_each_denial_stops_later_checks_but_allows_fresh_recovery(tmp_path, deny):
    active = {"deny": deny}

    def edit(receipt, kwargs):
        if kwargs["check_id"] == active["deny"]:
            return {**receipt, "authorized": False, "reason": "native_denied"}
        return receipt

    client, calls, _ = private_client(tmp_path, edit=edit)
    with pytest.raises(ProtectionHardenedError, match="native_denied"):
        HardenedReleaseBoundary(client).require_commercial_runtime(build_id="build-1")
    assert calls[-1]["check_id"] == deny
    assert len(calls) == REQUIRED_COMMERCIAL_RUNTIME_CHECKS.index(deny) + 1
    active["deny"] = None
    calls.clear()
    HardenedReleaseBoundary(client).require_commercial_runtime(build_id="build-1")
    assert len(calls) == 4


def test_verifier_exception_never_exposes_provider_secret(tmp_path):
    client, calls, runtime = private_client(tmp_path)

    def fail(**_kwargs):
        raise RuntimeError("secret-key=PRIVATE_NEVER_SHOW")

    runtime.verify_hardened_release_check = fail
    with pytest.raises(ProtectionHardenedError) as error:
        HardenedReleaseBoundary(client).require_commercial_runtime(build_id="build-1")
    assert "PRIVATE_NEVER_SHOW" not in str(error.value)
    assert error.value.__cause__ is None
    assert calls == []


def test_r57_denial_prevents_user_data_and_engine_start(tmp_path, monkeypatch):
    from acs import version2_release_app as app

    def edit(receipt, kwargs):
        if kwargs["check_id"] == "protected-runtime-integrity":
            return {**receipt, "authorized": False, "reason": "native_denied"}
        return receipt

    client, calls, _ = private_client(tmp_path, edit=edit)
    session = ProtectionStartupSession(
        decision=ProtectionDecision(
            state="authorized", reason="none",
            safe_operations=frozenset({"recovery", "login", "update", "help", "own-data-read", "own-data-export"}),
            capabilities=frozenset({"local-chess"}), build_id="build-1",
        ), client=client,
    )
    monkeypatch.setattr(app, "ProtectionEntitlementLifecycle", lambda _client:
                        SimpleNamespace(synchronize=lambda: SimpleNamespace(premium_allowed=True)))
    monkeypatch.setattr(app, "ProtectionTrustBoundary", lambda _client:
                        SimpleNamespace(synchronize=lambda: SimpleNamespace(state="trusted")))
    monkeypatch.setattr(app, "require_private_license_container", lambda *_args, **_kwargs: None)
    engine_calls = []

    def engine(_config):
        engine_calls.append(1)
        raise AssertionError("engine should not start")

    with pytest.raises(ProtectedStartupLocked) as exc:
        app.create_version2_release_application(
            application_dir=tmp_path / "app", data_root=tmp_path / "not-created",
            runtime_factory=engine,
            protection_authorizer=lambda **_kwargs: session, defer_ui=True,
        )
    assert exc.value.decision.reason == "advanced_security_unavailable"
    assert [x["check_id"] for x in calls] == [
        *REQUIRED_HARDENED_CHECKS, "protected-runtime-integrity"
    ]
    assert engine_calls == []
    assert not (tmp_path / "not-created").exists()


def test_accessibility_tools_are_not_client_side_punished():
    # R58 native instrumentation interpretation belongs to the independently
    # verified private implementation. There is no local NVDA/debugger heuristic
    # or client-side kill/suspend/secret release in this product contract.
    assert "instrumentation-clear" in REQUIRED_COMMERCIAL_RUNTIME_CHECKS
    assert all("nvda" not in x and "screen-reader" not in x for x in REQUIRED_COMMERCIAL_RUNTIME_CHECKS)
