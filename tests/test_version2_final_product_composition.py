from __future__ import annotations

from pathlib import Path

from acs.full_product_ui_shell import UILanguage
from acs.version2_final_product_profile import (
    FINAL_PRODUCT_ACTION_IDS,
    build_final_product_action_registry,
    build_final_product_menu_spec,
    build_final_product_router,
    build_final_product_shell,
    build_final_product_webview_adapter,
)


def test_final_profile_exposes_teacher_and_classes_but_not_remote_or_mutations():
    registry = build_final_product_action_registry()
    ids = {definition.action_id for definition in registry.definitions()}

    assert {"screen.teacher", "screen.classes"} <= ids
    assert ids.issuperset(FINAL_PRODUCT_ACTION_IDS)
    assert not any(action_id.startswith("remote.") for action_id in ids)
    assert "teacher.pointer_input" not in ids
    assert "classes.new" not in ids


def test_final_shell_has_keyboard_reachable_teacher_and_classes_routes():
    shell = build_final_product_shell(language=UILanguage.UA)
    router = build_final_product_router(shell, lambda action_id, payload: None)
    adapter = build_final_product_webview_adapter(shell, router)

    route_ids = tuple(item["route_id"] for item in adapter.snapshot()["navigation"])
    assert "teacher" in route_ids
    assert "classes" in route_ids

    teacher = adapter.activate_action("screen.teacher", current_focus_id="v2-nav-teacher")
    assert teacher.kind != "error"
    assert shell.current_route.route_id == "teacher"

    classes = adapter.activate_action("screen.classes", current_focus_id="teacher-pointer-input")
    assert classes.kind != "error"
    assert shell.current_route.route_id == "classes"


def test_final_native_menu_adds_only_safe_teacher_navigation():
    registry = build_final_product_action_registry()
    spec = build_final_product_menu_spec(registry, language=UILanguage.UA)
    teacher = next(menu for menu in spec if menu.menu_id == "teacher")
    action_ids = tuple(
        item.action_id for item in teacher.items if getattr(item, "action_id", "")
    )
    assert action_ids == ("screen.teacher", "screen.classes")
    assert not any(action_id.startswith("remote.") for action_id in action_ids)


def test_final_bootstrap_is_packaged_and_remote_transport_is_absent():
    source = Path("web/version2_final_product_bootstrap.js").read_text(encoding="utf-8")
    assert '"teacher"' in source
    assert '"classes"' in source
    assert "AccessibleChessTeacherSurface" in source
    assert "AccessibleChessEducationSurface" in source
    assert "remote.connect" not in source
