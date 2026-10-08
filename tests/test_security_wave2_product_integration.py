from __future__ import annotations

from contextlib import nullcontext
import inspect
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from acs import version2_upgrade_status_release as shipping_release
from acs.protection_boundary import (
    ProtectionDecision,
    ProtectionRuntimeClient,
    ProtectionStartupSession,
    authorize_release_startup,
    open_release_protection_session,
)
from acs.protection_locked_ui import ProtectionLockedAPI
from acs.protection_online_boundary import (
    ProtectionOnlineClient,
    ProtectionOnlineError,
)
from acs.protection_entitlement_lifecycle import (
    EntitlementLifecycleSnapshot,
    ProtectionEntitlementLifecycle,
    ProtectionLifecycleError,
)
from acs.protection_privacy_boundary import ProtectionPrivacyClient, ProtectionPrivacyError
from acs.protection_runtime_monitor import ProtectionLifecycleMonitor

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
        assert kwargs["mode"] in {"login", "register", "recover", "transfer_device"}
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


def _runtime_v3(*, lifecycle=None, poll_states=None):
    runtime = _runtime_v2(poll_states=poll_states)
    runtime.RUNTIME_API_VERSION = 3
    original_evaluate = runtime.evaluate_startup
    def evaluate_startup(**kwargs):
        value = dict(original_evaluate(**kwargs))
        value["api_version"] = 3
        return value
    runtime.evaluate_startup = evaluate_startup
    if lifecycle is None:
        lifecycle = {
            "api_version": 3,
            "state": "authorized",
            "reason": "none",
            "actions": [],
            "live_region": "none",
            "retry_after_seconds": 900,
            "lease_remaining_seconds": 3600,
        }
    runtime.synchronize_online_entitlement = lambda **kwargs: dict(lifecycle)
    return runtime


def test_r19_r22_lifecycle_has_no_identity_or_token_inputs(tmp_path):
    lifecycle = ProtectionEntitlementLifecycle(_client(tmp_path, _runtime_v3()))
    params = inspect.signature(lifecycle.synchronize).parameters
    assert params == {}
    snapshot = lifecycle.synchronize()
    assert snapshot.state == "authorized"
    assert snapshot.premium_allowed is True


@pytest.mark.parametrize("state,reason,actions", [
    ("reauth_required", "lease_expired", ["login"]),
    ("revoked", "device_revoked", ["recover"]),
    ("quarantined", "risk_threshold", ["repair", "login"]),
    ("recovery_required", "device_lost", ["recover", "transfer_device"]),
    ("device_limit", "device_limit", ["recover"]),
])
def test_denied_lifecycle_states_fail_closed_for_premium(state, reason, actions, tmp_path):
    runtime = _runtime_v3(lifecycle={
        "api_version": 3,
        "state": state,
        "reason": reason,
        "actions": actions,
        "live_region": "assertive",
        "retry_after_seconds": 0,
        "lease_remaining_seconds": None,
    })
    snapshot = ProtectionEntitlementLifecycle(_client(tmp_path, runtime)).synchronize()
    assert snapshot.premium_allowed is False
    assert snapshot.live_region == "assertive"


def test_network_grace_is_explicit_and_bounded(tmp_path):
    runtime = _runtime_v3(lifecycle={
        "api_version": 3,
        "state": "network_grace",
        "reason": "network_failure",
        "actions": ["retry"],
        "live_region": "assertive",
        "retry_after_seconds": 60,
        "lease_remaining_seconds": -120,
    })
    snapshot = ProtectionEntitlementLifecycle(_client(tmp_path, runtime)).synchronize()
    assert snapshot.premium_allowed is True
    assert snapshot.retry_after_seconds == 60
    assert snapshot.lease_remaining_seconds == -120


def test_malformed_lifecycle_or_secret_extra_fields_fail_closed(tmp_path):
    runtime = _runtime_v3(lifecycle={
        "api_version": 3,
        "state": "authorized",
        "reason": "none",
        "actions": [],
        "live_region": "none",
        "retry_after_seconds": 900,
        "lease_remaining_seconds": 3600,
        "access_token": "must-not-cross-boundary",
    })
    with pytest.raises(ProtectionLifecycleError, match="schema"):
        ProtectionEntitlementLifecycle(_client(tmp_path, runtime)).synchronize()


def test_completed_v3_browser_flow_runs_device_lease_revocation_lifecycle_before_unlock(tmp_path):
    runtime = _runtime_v3(poll_states=["completed"])
    calls = {"sync": 0}
    def synchronize(**kwargs):
        calls["sync"] += 1
        assert set(kwargs) == {"package_root", "state_root"}
        return {
            "api_version": 3,
            "state": "authorized",
            "reason": "none",
            "actions": [],
            "live_region": "none",
            "retry_after_seconds": 900,
            "lease_remaining_seconds": 3600,
        }
    runtime.synchronize_online_entitlement = synchronize
    client = _client(tmp_path, runtime)
    online = ProtectionOnlineClient(client, browser_open=lambda _url: True)
    locked = ProtectionDecision(
        state="locked",
        reason="login_required",
        safe_operations=frozenset(SAFE),
        capabilities=frozenset(),
        build_id="build-3",
    )

    class Window:
        def __init__(self):
            self.destroyed = False
        def destroy(self):
            self.destroyed = True

    api = ProtectionLockedAPI(client, locked, online_client=online)
    window = Window()
    api.bind_window(window)
    assert api.begin_online_login()["ok"] is True
    result = api.poll_online_access()
    assert calls["sync"] == 1
    assert result["authorized"] is True
    assert window.destroyed is True


def test_public_lifecycle_surface_has_no_admin_or_revocation_subject_mutators():
    public = set(dir(ProtectionEntitlementLifecycle))
    for forbidden in (
        "revoke",
        "restore",
        "list_revocations",
        "admin_login",
        "set_account_id",
        "set_device_id",
        "set_access_token",
        "set_refresh_token",
    ):
        assert forbidden not in public


def test_open_release_session_retains_private_client_without_exposing_it_in_decision(tmp_path):
    runtime = _runtime_v2()
    runtime.evaluate_startup = lambda **kwargs: {
        "api_version": 2,
        "state": "authorized",
        "reason": "none",
        "safe_operations": list(SAFE),
        "capabilities": ["local-chess"],
        "build_id": "build-2",
    }
    session = open_release_protection_session(
        application_dir=tmp_path / "app",
        state_root=tmp_path / "state",
        required=True,
        module_loader=lambda _name: runtime,
    )
    assert isinstance(session, ProtectionStartupSession)
    assert session.decision.authorized
    assert isinstance(session.client, ProtectionRuntimeClient)
    assert not hasattr(session.decision, "access_token")
    assert not hasattr(session.decision, "refresh_token")


def test_r24_notice_and_consent_surface_never_accepts_telemetry_payload(tmp_path):
    calls = []
    runtime = _runtime_v3()
    runtime.security_notice = lambda **kwargs: {
        "api_version": 3,
        "notice_version": "security-v1",
        "summary": "Integrity, update and lease diagnostics only.",
        "consent_required": True,
        "consent_granted": False,
    }
    def set_consent(**kwargs):
        calls.append(kwargs)
        return {
            "api_version": 3,
            "notice_version": kwargs["notice_version"],
            "summary": "Integrity, update and lease diagnostics only.",
            "consent_required": True,
            "consent_granted": kwargs["granted"],
        }
    runtime.set_security_consent = set_consent
    privacy = ProtectionPrivacyClient(_client(tmp_path, runtime))
    notice = privacy.notice()
    assert notice["notice_version"] == "security-v1"
    updated = privacy.set_consent(granted=True, notice_version="security-v1")
    assert updated["consent_granted"] is True
    assert set(calls[0]) == {"package_root", "state_root", "notice_version", "granted"}
    assert "event" not in inspect.signature(privacy.set_consent).parameters
    assert "anomaly_code" not in inspect.signature(privacy.set_consent).parameters


def test_r24_notice_rejects_extra_raw_telemetry_fields(tmp_path):
    runtime = _runtime_v3()
    runtime.security_notice = lambda **kwargs: {
        "api_version": 3,
        "notice_version": "security-v1",
        "summary": "Bounded diagnostics.",
        "consent_required": True,
        "consent_granted": False,
        "raw_path": "C:/Users/example/private.txt",
    }
    with pytest.raises(ProtectionPrivacyError, match="schema"):
        ProtectionPrivacyClient(_client(tmp_path, runtime)).notice()


@pytest.mark.parametrize("mode", ["recover", "transfer_device"])
def test_r27_recovery_and_transfer_use_opaque_browser_flow_without_device_inputs(mode, tmp_path):
    runtime = _runtime_v3()
    opened = []
    client = ProtectionOnlineClient(
        _client(tmp_path, runtime),
        browser_open=lambda url: opened.append(url) or True,
    )
    flow = client.begin(mode=mode)
    assert flow.mode == mode
    assert len(opened) == 1
    params = inspect.signature(client.begin).parameters
    assert set(params) == {"mode"}
    for forbidden in ("account_id", "old_device_id", "new_device_id", "access_token"):
        assert forbidden not in params


def test_r24_consent_required_lifecycle_blocks_premium_until_notice_action(tmp_path):
    runtime = _runtime_v3(lifecycle={
        "api_version": 3,
        "state": "consent_required",
        "reason": "security_notice_required",
        "actions": ["review_privacy"],
        "live_region": "assertive",
        "retry_after_seconds": 0,
        "lease_remaining_seconds": None,
    })
    snapshot = ProtectionEntitlementLifecycle(_client(tmp_path, runtime)).synchronize()
    assert snapshot.premium_allowed is False
    assert snapshot.actions == ("review_privacy",)


def test_r26_monitor_blocks_immediately_on_revocation_without_waiting_for_next_app_start(tmp_path):
    client = _client(tmp_path, _runtime_v3())
    class Lifecycle:
        def synchronize(self):
            return EntitlementLifecycleSnapshot(
                state="revoked",
                reason="device_revoked",
                actions=("recover",),
                live_region="assertive",
                retry_after_seconds=0,
                lease_remaining_seconds=None,
            )
    monitor = ProtectionLifecycleMonitor(client, lifecycle=Lifecycle())
    blocked = []
    blocked_event = threading.Event()
    def on_block(snapshot):
        blocked.append(snapshot)
        blocked_event.set()
    monitor.start(
        warning_callback=lambda snapshot: None,
        block_callback=on_block,
    )
    assert blocked_event.wait(2.0)
    monitor.stop()
    assert monitor.blocked_or_failed
    assert monitor.blocked is not None
    assert monitor.blocked.state == "revoked"
    assert blocked and blocked[0].state == "revoked"


def test_r26_monitor_reports_bounded_warning_before_later_block(tmp_path):
    client = _client(tmp_path, _runtime_v3())
    sequence = [
        EntitlementLifecycleSnapshot(
            state="renewal_due",
            reason="renewal_due",
            actions=("retry",),
            live_region="polite",
            retry_after_seconds=1,
            lease_remaining_seconds=120,
        ),
        EntitlementLifecycleSnapshot(
            state="reauth_required",
            reason="lease_expired",
            actions=("login",),
            live_region="assertive",
            retry_after_seconds=0,
            lease_remaining_seconds=None,
        ),
    ]
    class Lifecycle:
        def synchronize(self):
            return sequence.pop(0)
    monitor = ProtectionLifecycleMonitor(client, lifecycle=Lifecycle())
    first = monitor.poll_once()
    assert first.state == "renewal_due"
    assert monitor._delay(first) == 30
    second = monitor.poll_once()
    assert second.state == "reauth_required"
    assert monitor.blocked_or_failed


def test_r23_end_user_product_has_no_admin_control_plane_methods(tmp_path):
    runtime = _runtime_v3()
    client = _client(tmp_path, runtime)
    surfaces = [
        ProtectionOnlineClient(client, browser_open=lambda _url: True),
        ProtectionEntitlementLifecycle(client),
        ProtectionPrivacyClient(client),
    ]
    forbidden = {
        "admin_login",
        "admin_session",
        "revoke_account",
        "restore_account",
        "list_revocations",
        "signing_key",
        "factor_assertion",
    }
    for surface in surfaces:
        assert forbidden.isdisjoint(set(dir(surface)))


def test_compiled_launcher_requires_private_protection_runtime_package():
    launcher = (Path(__file__).resolve().parents[1] / "run_accessible_chess_v2.py").read_text(
        encoding="utf-8"
    )
    assert "--include-package=accessible_chess_protection_runtime" in launcher


def test_shipping_host_passes_v3_monitor_into_real_product_window(monkeypatch, tmp_path):
    runtime = _runtime_v3()
    runtime.evaluate_startup = lambda **kwargs: {
        "api_version": 3,
        "state": "authorized",
        "reason": "none",
        "safe_operations": list(SAFE),
        "capabilities": ["local-chess"],
        "build_id": "build-3",
    }
    client = _client(tmp_path, runtime)
    session = ProtectionStartupSession(
        decision=ProtectionDecision(
            state="authorized",
            reason="none",
            safe_operations=frozenset(SAFE),
            capabilities=frozenset({"local-chess"}),
            build_id="build-3",
        ),
        client=client,
    )
    api = SimpleNamespace(_protection_session=session)
    monitor = SimpleNamespace(blocked_or_failed=False)
    seen = {}

    monkeypatch.setattr(
        shipping_release._education_release,
        "_final_product_mutation_bindings",
        lambda: nullcontext(),
    )
    monkeypatch.setattr(
        shipping_release,
        "create_version2_release_application",
        lambda **kwargs: (api, "application", "runtime", "native-files"),
    )
    monkeypatch.setattr(
        shipping_release,
        "ProtectionLifecycleMonitor",
        lambda actual_client: monitor if actual_client is client else (_ for _ in ()).throw(AssertionError()),
    )
    def run_window(api_value, application, runtime_value, **kwargs):
        seen["monitor"] = kwargs.get("protection_monitor")
    monkeypatch.setattr(shipping_release._release_ui, "run_version2_release_window", run_window)

    shipping_release.main()
    assert seen["monitor"] is monitor


def test_shipping_host_returns_live_revocation_to_locked_shell(monkeypatch, tmp_path):
    runtime = _runtime_v3()
    client = _client(tmp_path, runtime)
    session = ProtectionStartupSession(
        decision=ProtectionDecision(
            state="authorized",
            reason="none",
            safe_operations=frozenset(SAFE),
            capabilities=frozenset({"local-chess"}),
            build_id="build-3",
        ),
        client=client,
    )
    api = SimpleNamespace(_protection_session=session)
    blocked = EntitlementLifecycleSnapshot(
        state="revoked",
        reason="device_revoked",
        actions=("recover",),
        live_region="assertive",
        retry_after_seconds=0,
        lease_remaining_seconds=None,
    )
    monitor = SimpleNamespace(
        blocked_or_failed=True,
        blocked=blocked,
        failure_reason=None,
    )
    shell = []

    monkeypatch.setattr(
        shipping_release._education_release,
        "_final_product_mutation_bindings",
        lambda: nullcontext(),
    )
    monkeypatch.setattr(
        shipping_release,
        "create_version2_release_application",
        lambda **kwargs: (api, "application", "runtime", "native-files"),
    )
    monkeypatch.setattr(shipping_release, "ProtectionLifecycleMonitor", lambda _client: monitor)
    monkeypatch.setattr(
        shipping_release._release_ui,
        "run_version2_release_window",
        lambda *args, **kwargs: None,
    )
    def locked_shell(actual_client, decision):
        shell.append((actual_client, decision))
        return False
    monkeypatch.setattr(shipping_release._release_app, "run_locked_security_window", locked_shell)

    shipping_release.main()
    assert len(shell) == 1
    assert shell[0][0] is client
    assert shell[0][1].reason == "device_revoked"
    assert shell[0][1].state == "locked"


def test_v3_revocation_blocks_before_engine_database_or_user_data_composition(tmp_path):
    runtime = _runtime_v3(lifecycle={
        "api_version": 3,
        "state": "revoked",
        "reason": "device_revoked",
        "actions": ["recover"],
        "live_region": "assertive",
        "retry_after_seconds": 0,
        "lease_remaining_seconds": None,
    })
    runtime.evaluate_startup = lambda **kwargs: {
        "api_version": 3,
        "state": "authorized",
        "reason": "none",
        "safe_operations": list(SAFE),
        "capabilities": ["local-chess"],
        "build_id": "build-3",
    }
    client = _client(tmp_path, runtime)
    session = ProtectionStartupSession(
        decision=ProtectionDecision(
            state="authorized",
            reason="none",
            safe_operations=frozenset(SAFE),
            capabilities=frozenset({"local-chess"}),
            build_id="build-3",
        ),
        client=client,
    )
    events = []
    def engine(_config):
        events.append("engine")
        raise AssertionError("engine must not start after revoked lifecycle")

    from acs.version2_release_app import create_version2_release_application

    with pytest.raises(Exception) as caught:
        create_version2_release_application(
            application_dir=tmp_path / "app",
            data_root=tmp_path / "user-data",
            runtime_factory=engine,
            protection_authorizer=lambda **kwargs: session,
            defer_ui=True,
        )
    assert "device_revoked" in str(caught.value)
    assert events == []
    assert not (tmp_path / "user-data").exists()
