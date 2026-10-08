from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from acs.protection_boundary import (
    ProtectionDecision,
    ProtectionRuntimeClient,
    authorize_release_startup,
)
from acs.protection_locked_ui import ProtectionLockedAPI
from acs.protection_online_boundary import (
    ProtectionOnlineClient,
    ProtectionOnlineError,
)

SAFE = ["help", "login", "own-data-export", "own-data-read", "recovery", "update"]


def _runtime_v2(*, poll_states=None, authorization_url="https://auth.example.invalid/authorize?flow=1"):
    states = list(poll_states or ["pending"])
    evaluate_state = {"authorized": False}

    def evaluate_startup(**kwargs):
        authorized = evaluate_state["authorized"]
        return {
            "api_version": 2,
            "state": "authorized" if authorized else "locked",
            "reason": "none" if authorized else "login_required",
            "safe_operations": list(SAFE),
            "capabilities": ["local-chess"] if authorized else [],
            "build_id": "build-2",
        }

    def begin_online_access(**kwargs):
        assert set(kwargs) == {"package_root", "state_root", "mode"}
        assert kwargs["mode"] in {"login", "register"}
        return {
            "api_version": 2,
            "flow_id": "abcdefghijklmnop",
            "authorization_url": authorization_url,
            "expires_in_seconds": 300,
        }

    def poll_online_access(**kwargs):
        assert set(kwargs) == {"package_root", "state_root", "flow_id"}
        state = states.pop(0) if states else "pending"
        if state == "completed":
            evaluate_state["authorized"] = True
        return {
            "api_version": 2,
            "state": state,
            "reason": "none" if state in {"pending", "completed"} else "access_denied",
        }

    return SimpleNamespace(
        RUNTIME_API_VERSION=2,
        evaluate_startup=evaluate_startup,
        begin_online_access=begin_online_access,
        poll_online_access=poll_online_access,
        create_activation_request=lambda **kwargs: {"schema_version": 1},
        import_entitlement=lambda **kwargs: None,
    )


def _client(tmp_path, runtime):
    return ProtectionRuntimeClient(
        application_dir=tmp_path / "app",
        state_root=tmp_path / "state",
        module_loader=lambda _name: runtime,
    )


def test_runtime_v2_remains_compatible_with_wave1_startup_contract(tmp_path):
    runtime = _runtime_v2()
    runtime.evaluate_startup = lambda **kwargs: {
        "api_version": 2,
        "state": "authorized",
        "reason": "none",
        "safe_operations": list(SAFE),
        "capabilities": ["local-chess"],
        "build_id": "build-2",
    }
    decision = authorize_release_startup(
        application_dir=tmp_path / "app",
        state_root=tmp_path / "state",
        required=True,
        module_loader=lambda _name: runtime,
    )
    assert decision.authorized
    assert decision.build_id == "build-2"


def test_online_boundary_opens_https_system_browser_without_exposing_identity_inputs(tmp_path):
    runtime = _runtime_v2()
    opened = []
    online = ProtectionOnlineClient(
        _client(tmp_path, runtime),
        browser_open=lambda url: opened.append(url) or True,
    )
    flow = online.begin(mode="login")
    assert flow.flow_id == "abcdefghijklmnop"
    assert flow.expires_in_seconds == 300
    assert opened == ["https://auth.example.invalid/authorize?flow=1"]

    parameters = inspect.signature(online.begin).parameters
    assert set(parameters) == {"mode"}
    for forbidden in ("password", "account_id", "device_id", "client_secret", "refresh_token"):
        assert forbidden not in parameters


def test_registration_uses_same_bounded_system_browser_contract(tmp_path):
    runtime = _runtime_v2()
    seen = []
    online = ProtectionOnlineClient(
        _client(tmp_path, runtime),
        browser_open=lambda url: seen.append(url) or True,
    )
    flow = online.begin(mode="register")
    assert flow.mode == "register"
    assert len(seen) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://auth.example.invalid/authorize",
        "https://user:password@auth.example.invalid/authorize",
        "https://auth.example.invalid/authorize#token",
        "file:///tmp/login.html",
        "javascript:alert(1)",
    ],
)
def test_unsafe_authorization_urls_fail_closed_before_browser_open(tmp_path, url):
    runtime = _runtime_v2(authorization_url=url)
    opened = []
    online = ProtectionOnlineClient(
        _client(tmp_path, runtime),
        browser_open=lambda value: opened.append(value) or True,
    )
    with pytest.raises(ProtectionOnlineError, match="unsafe"):
        online.begin(mode="login")
    assert opened == []


def test_browser_open_failure_fails_closed(tmp_path):
    online = ProtectionOnlineClient(
        _client(tmp_path, _runtime_v2()),
        browser_open=lambda _url: False,
    )
    with pytest.raises(ProtectionOnlineError, match="system browser"):
        online.begin(mode="login")


def test_runtime_v1_keeps_manual_wave1_path_but_cannot_claim_online_support(tmp_path):
    runtime = SimpleNamespace(
        RUNTIME_API_VERSION=1,
        evaluate_startup=lambda **kwargs: {
            "api_version": 1,
            "state": "locked",
            "reason": "manual_activation_required",
            "safe_operations": list(SAFE),
            "capabilities": [],
            "build_id": "build-1",
        },
        create_activation_request=lambda **kwargs: {"schema_version": 1},
        import_entitlement=lambda **kwargs: None,
    )
    client = _client(tmp_path, runtime)
    assert client.runtime_api_version() == 1
    online = ProtectionOnlineClient(client, browser_open=lambda _url: True)
    with pytest.raises(ProtectionOnlineError, match=r"v2\+"):
        online.begin(mode="login")


def test_locked_shell_completes_online_flow_only_after_private_runtime_authorizes(tmp_path):
    runtime = _runtime_v2(poll_states=["pending", "completed"])
    client = _client(tmp_path, runtime)
    online = ProtectionOnlineClient(client, browser_open=lambda _url: True)
    locked = ProtectionDecision(
        state="locked",
        reason="login_required",
        safe_operations=frozenset(SAFE),
        capabilities=frozenset(),
        build_id="build-2",
    )

    class Window:
        def __init__(self):
            self.destroyed = False

        def destroy(self):
            self.destroyed = True

    api = ProtectionLockedAPI(client, locked, online_client=online)
    window = Window()
    api.bind_window(window)

    start = api.begin_online_login()
    assert start == {"ok": True, "mode": "login", "expires_in_seconds": 300}
    assert window.destroyed is False

    pending = api.poll_online_access()
    assert pending["state"] == "pending"
    assert pending["authorized"] is False
    assert window.destroyed is False

    complete = api.poll_online_access()
    assert complete["state"] == "completed"
    assert complete["authorized"] is True
    assert api.authorized is True
    assert window.destroyed is True


def test_locked_shell_status_exposes_only_online_availability_not_session_secrets(tmp_path):
    client = _client(tmp_path, _runtime_v2())
    decision = ProtectionDecision(
        state="locked",
        reason="login_required",
        safe_operations=frozenset(SAFE),
        capabilities=frozenset(),
        build_id="build-2",
    )
    status = ProtectionLockedAPI(
        client,
        decision,
        online_client=ProtectionOnlineClient(client, browser_open=lambda _url: True),
    ).status()
    assert status["online_available"] is True
    assert set(status) == {"state", "reason", "safe_operations", "build_id", "online_available"}


def test_public_browser_ui_does_not_embed_password_or_client_secret_fields():
    root = Path(__file__).resolve().parents[1]
    html = (root / "web" / "protection_locked.html").read_text(encoding="utf-8").lower()
    js = (root / "web" / "protection_locked.js").read_text(encoding="utf-8").lower()
    assert 'type="password"' not in html
    assert "client_secret" not in html
    assert "client_secret" not in js
    assert "refresh_token" not in html
    assert "refresh_token" not in js
