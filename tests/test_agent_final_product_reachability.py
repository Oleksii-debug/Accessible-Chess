from __future__ import annotations

from pathlib import Path
from threading import get_ident
from types import SimpleNamespace
import unittest

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


class AgentFinalProductReachabilityTests(unittest.TestCase):
    def test_agent_route_is_final_product_only_and_keyboard_reachable(self):
        registry = build_final_product_action_registry()
        ids = {definition.action_id for definition in registry.definitions()}
        self.assertIn("screen.agent", ids)
        self.assertNotIn("agent.submit", ids)
        self.assertNotIn("agent.cancel", ids)

        shell = build_final_product_shell(language=UILanguage.EN)
        router = build_final_product_router(
            shell,
            lambda action_id, payload: None,
            registry=registry,
        )
        adapter = build_final_product_webview_adapter(shell, router)
        navigation = tuple(item["route_id"] for item in adapter.snapshot()["navigation"])
        self.assertIn("agent", navigation)

        result = adapter.activate_action(
            "screen.agent",
            current_focus_id="v2-nav-agent",
        )
        self.assertNotEqual(result.kind, "error")
        self.assertEqual(shell.current_route.route_id, "agent")
        self.assertEqual(shell.restore_focus_target(), "agent-input")

    def test_agent_has_native_menu_reachability_without_runtime_commands(self):
        registry = build_final_product_action_registry()
        spec = build_final_product_menu_spec(registry, language=UILanguage.UA)
        menu = next(item for item in spec if item.menu_id == "agent")
        self.assertEqual(menu.label, "П&омічник")
        action_ids = tuple(
            item.action_id
            for item in menu.items
            if getattr(item, "action_id", "")
        )
        self.assertEqual(action_ids, ("screen.agent",))

    def test_final_application_browser_area_binds_trusted_host_callbacks(self):
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
        self.assertEqual(accepted["kind"], "accepted")
        self.assertEqual(
            starts,
            [("agent-ui-1", "Describe the current canonical position.")],
        )

        self.assertTrue(
            projection.complete(
                "agent-ui-1",
                "White to move.",
                model_calls=1,
                tool_calls=1,
                steps=1,
            )
        )
        rendered = app.browser_command("agent", "agent.snapshot", {})
        self.assertEqual(rendered["kind"], "render")
        self.assertEqual(
            rendered["payload"]["snapshot"]["transcript"][-1]["text"],
            "White to move.",
        )

        app.unbind_agent_conversation()
        unavailable = app.browser_command(
            "agent",
            "agent.submit",
            {"text": "Again"},
        )
        self.assertEqual(unavailable["kind"], "error")

    def test_bootstrap_and_final_release_package_agent_surface(self):
        bootstrap = Path("web/version2_final_product_bootstrap.js").read_text(
            encoding="utf-8"
        )
        release = Path("acs/version2_final_release.py").read_text(encoding="utf-8")
        surface = Path("web/full_product_agent.js").read_text(encoding="utf-8")

        self.assertIn('"agent"', bootstrap)
        self.assertIn("AccessibleChessAgentSurface", bootstrap)
        self.assertIn('areaInvoke("agent")', bootstrap)
        self.assertIn("full_product_agent.js", release)
        self.assertNotIn("innerHTML", surface)
        self.assertIn('setAttribute("role", "status")', surface)
        self.assertIn('setAttribute("aria-live", "off")', surface)
        self.assertIn('style.whiteSpace = "pre-wrap"', surface)


if __name__ == "__main__":
    unittest.main()
