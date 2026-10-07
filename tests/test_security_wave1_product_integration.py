from pathlib import Path
from types import SimpleNamespace

import pytest

from acs.protection_boundary import (
    ProtectionDecision,
    ProtectedStartupLocked,
    ProtectionRuntimeClient,
    authorize_release_startup,
    protection_required,
)
from acs.protection_locked_ui import ProtectionLockedAPI
from acs.version2_release_app import create_version2_release_application

SAFE = ["help", "login", "own-data-export", "own-data-read", "recovery", "update"]


def _module(*, state="authorized", reason="none", build_id="build-1", capabilities=None):
    if capabilities is None:
        capabilities = ["local-chess"] if state == "authorized" else []
    imported = []
    return SimpleNamespace(
        RUNTIME_API_VERSION=1,
        evaluate_startup=lambda **kwargs: {
            "api_version": 1,
            "state": state,
            "reason": reason,
            "safe_operations": list(SAFE),
            "capabilities": list(capabilities),
            "build_id": build_id,
        },
        create_activation_request=lambda **kwargs: {
            "schema_version": 1,
            "request_id": "req-1",
        },
        import_entitlement=lambda **kwargs: imported.append(kwargs["envelope"]),
        imported=imported,
    )


def test_source_tree_is_not_silently_treated_as_packaged_release(tmp_path):
    assert protection_required(tmp_path, frozen=False) is False
    (tmp_path / "RELEASE_MANIFEST.json").write_text("{}", encoding="utf-8")
    assert protection_required(tmp_path, frozen=False) is True
    assert protection_required(tmp_path, frozen=True) is True


def test_authorized_private_runtime_allows_product_startup(tmp_path):
    module = _module()
    decision = authorize_release_startup(
        application_dir=tmp_path / "app",
        state_root=tmp_path / "state",
        required=True,
        module_loader=lambda name: module,
    )
    assert decision.authorized
    assert decision.build_id == "build-1"
    assert decision.capabilities == frozenset({"local-chess"})


def test_locked_private_runtime_blocks_product_but_keeps_activation_client(tmp_path):
    module = _module(state="locked", reason="unverified", build_id="build-1")
    with pytest.raises(ProtectedStartupLocked) as caught:
        authorize_release_startup(
            application_dir=tmp_path / "app",
            state_root=tmp_path / "state",
            required=True,
            module_loader=lambda name: module,
        )
    locked = caught.value
    assert locked.decision.reason == "unverified"
    request = locked.client.create_activation_request()
    assert request["request_id"] == "req-1"
    locked.client.import_entitlement_json('{"schema_version": 1}')
    assert module.imported == [{"schema_version": 1}]


def test_missing_or_malformed_private_runtime_fails_closed(tmp_path):
    def missing(_name):
        raise ImportError("not installed")

    with pytest.raises(ProtectedStartupLocked) as absent:
        authorize_release_startup(
            application_dir=tmp_path,
            state_root=tmp_path / "state",
            required=True,
            module_loader=missing,
        )
    assert absent.value.decision.reason == "runtime_unavailable_or_invalid"

    bad = _module()
    bad.evaluate_startup = lambda **kwargs: {
        "api_version": 1,
        "state": "authorized",
        "reason": "none",
        "safe_operations": ["help"],
        "capabilities": ["local-chess"],
        "build_id": "build-1",
    }
    with pytest.raises(ProtectedStartupLocked) as malformed:
        authorize_release_startup(
            application_dir=tmp_path,
            state_root=tmp_path / "state2",
            required=True,
            module_loader=lambda name: bad,
        )
    assert malformed.value.decision.reason == "runtime_unavailable_or_invalid"


def test_protection_gate_runs_before_engine_or_user_data_composition(tmp_path):
    events = []
    decision = ProtectionDecision(
        state="locked",
        reason="expired",
        safe_operations=frozenset(SAFE),
        capabilities=frozenset(),
        build_id="build-1",
    )
    client = ProtectionRuntimeClient(
        application_dir=tmp_path / "app",
        state_root=tmp_path / "state",
        module_loader=lambda name: _module(state="locked", reason="expired"),
    )

    def gate(**kwargs):
        events.append("protection")
        raise ProtectedStartupLocked(decision, client)

    def engine(_config):
        events.append("engine")
        raise AssertionError("engine must not be constructed while locked")

    with pytest.raises(ProtectedStartupLocked):
        create_version2_release_application(
            application_dir=tmp_path / "app",
            data_root=tmp_path / "state",
            runtime_factory=engine,
            protection_authorizer=gate,
            defer_ui=True,
        )
    assert events == ["protection"]
    assert not (tmp_path / "state").exists()


def test_locked_ui_retry_closes_only_after_authorization():
    locked = ProtectionDecision(
        state="locked",
        reason="unverified",
        safe_operations=frozenset(SAFE),
        capabilities=frozenset(),
        build_id="build-1",
    )
    authorized = ProtectionDecision(
        state="authorized",
        reason="none",
        safe_operations=frozenset(SAFE),
        capabilities=frozenset({"local-chess"}),
        build_id="build-1",
    )

    class Client:
        def __init__(self):
            self.calls = 0
        def evaluate(self):
            self.calls += 1
            return locked if self.calls == 1 else authorized
        def create_activation_request(self):
            return {"schema_version": 1}
        def import_entitlement_json(self, raw):
            return None

    class Window:
        def __init__(self):
            self.destroyed = False
        def destroy(self):
            self.destroyed = True

    api = ProtectionLockedAPI(Client(), locked)
    window = Window()
    api.bind_window(window)
    first = api.retry()
    assert first["authorized"] is False
    assert window.destroyed is False
    second = api.retry()
    assert second["authorized"] is True
    assert api.authorized is True
    assert window.destroyed is True
