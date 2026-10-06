from __future__ import annotations

from pathlib import Path
from threading import get_ident
from types import SimpleNamespace

from acs.agent_webview_bridge import AgentConversationWebViewBridge
from acs.agent_webview_projection import AgentConversationProjection
from acs.full_product_ui_shell import UILanguage
from acs.version2_final_product_application import Version2FinalProductApplication
from acs.version2_final_product_profile import (
    build_final_product_action_registry,
    build_final_product_menu_spec,
    build_final_product_router,
    build_final_product_shell,
    build_final_product_webview_adapter,
)


def test_agent_route_is_final_product_only_and_keyboard_reachable():
    registry = build_final_product_action_registry()
    ids = {definition.action_id for definition in registry.definitions()}
    assert "screen.agent" in ids
    assert "agent.submit" not in ids
    assert "agent.cancel" not in ids

    shell = build_final_product_shell(language=UILanguage.EN)
    router = build_final_product_router(shell, lambda action_id, payload: None, registry=registry)
    adapter = build_final_product_webview_adapter(shell, router)
    navigation = tuple(item["route_id"] for item in adapter.snapshot()["navigation"])
    assert "agent" in navigation

    result = adapter.activate_action("screen.agent", current_focus_id="v2-nav-agent")
    assert result.kind != "error"
    assert shell.current_route.route_id == "agent"
    assert shell.restore_focus_target() == "agent-input"


def test_agent_has_native_menu_reachability_without_exposing_runtime_commands():
    registry = build_final_product_action_registry()
    spec = build_final_product_menu_spec(registry, language=UILanguage.UA)
    menu = next(item for item in spec if item.menu_id == "agent")
    action_ids = tuple(
        item.action_id
        for item in menu.items
        if getattr(item, "action_id", "")
    )
    assert action_ids == ("screen.agent",)


def test_final_application_agent_browser_area_binds_trusted_host_callbacks():
    app = Version2FinalProductApplication.__new__(Version2FinalProductApplication)
    app._thread = get_ident()
    app.shell = SimpleNamespace(language=UILanguage.EN)
    app.agent = AgentConversationWebViewBridge(
        AgentConversationProjection(language="en")
    )

    starts: list[tuple[str, str]] = []
    cancels: list[str] = []
    projection = app.bind_agent_conversation(
        start_run=lambda run_id, text: starts.append((run_id, text)),
        cancel_run=lambda run_id: cancels.append(run_id),
    )
    accepted = app.browser_command(
        "agent",
        "agent.submit",
        {"text": "Describe the current canonical position."},
    )
    assert accepted["kind"] == "accepted"
    assert starts == [("agent-ui-1", "Describe the current canonical position.")]

    assert projection.complete(
        "agent-ui-1",
        "White to move.",
        model_calls=1,
        tool_calls=1,
        steps=1,
    )
    rendered = app.browser_command("agent", "agent.snapshot", {})
    assert rendered["kind"] == "render"
    assert rendered["payload"]["snapshot"]["transcript"][-1]["text"] == "White to move."

    app.unbind_agent_conversation()
    unavailable = app.browser_command("agent", "agent.submit", {"text": "Again"})
    assert unavailable["kind"] == "error"


def test_bootstrap_and_final_release_package_the_agent_surface():
    bootstrap = Path("web/version2_final_product_bootstrap.js").read_text(encoding="utf-8")
    release = Path("acs/version2_final_release.py").read_text(encoding="utf-8")
    surface = Path("web/full_product_agent.js").read_text(encoding="utf-8")

    assert '"agent"' in bootstrap
    assert "AccessibleChessAgentSurface" in bootstrap
    assert 'areaInvoke("agent")' in bootstrap
    assert "full_product_agent.js" in release
    assert "innerHTML" not in surface
    assert 'setAttribute("role", "status")' in surface
    assert 'setAttribute("aria-live", "off")' in surface
    assert 'style.whiteSpace = "pre-wrap"' in surface
