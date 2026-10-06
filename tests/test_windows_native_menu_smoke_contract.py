from pathlib import Path

from acs.ui_native_menu import native_menu_attachment_state


def test_packaged_native_menu_smoke_contract_is_explicit() -> None:
    text = Path("docs/WINDOWS_NATIVE_MENU_SMOKE.md").read_text(encoding="utf-8")
    assert "ControlType.MenuBar" in text
    assert "AccessibleChessMainMenu" in text
    assert "Alt" in text
    assert "ArrowRight" in text
    assert "ArrowDown" in text
    assert "Enter" in text
    assert "Esc" in text
    assert "NVDA" in text
    assert "native_menu_attachment_state" in text


def test_structural_diagnostic_is_a_callable_product_contract() -> None:
    assert callable(native_menu_attachment_state)


def test_source_uia_oracle_uses_canonical_full_product_menu_profile() -> None:
    from scripts.p0_native_menubar_uia_oracle import _canonical_top_level_profiles

    workflow = Path(".github/workflows/p0-native-menubar-uia-runtime.yml").read_text(encoding="utf-8")
    expected_en, expected_ua = _canonical_top_level_profiles()

    assert len(expected_en) == 14
    assert len(expected_ua) == 14
    assert expected_en[10] == "Training"
    assert expected_ua[10] == "Тренування"
    assert expected_en[11] == "Teacher/Classroom"
    assert expected_ua[11] == "Учитель/Клас"
    assert "converge/current-shipping-recovery-hardening-v2-20261006-c2mbezb" in workflow


def test_source_uia_oracle_binds_concrete_menu_handle_to_canonical_menubar() -> None:
    from scripts.p0_native_menubar_uia_oracle import _uia_menu_handle_binding_checks

    pid = 4242
    handle = 9001
    canonical = {
        "menu_from_handle": {
            "automation_id": "AccessibleChessFullProductMenu",
            "control_type": "ControlType.MenuBar",
            "process_id": pid,
            "enabled": True,
            "offscreen": False,
            "native_window_handle": handle,
        },
        "menu_from_handle_error": "",
        "exact_menu_bars": [
            {
                "automation_id": "AccessibleChessFullProductMenu",
                "control_type": "ControlType.MenuBar",
                "process_id": pid,
                "enabled": True,
                "offscreen": False,
                "native_window_handle": handle,
            }
        ],
    }
    assert all(
        _uia_menu_handle_binding_checks(canonical, pid=pid, menu_handle=handle).values()
    )

    stale = {
        **canonical,
        "menu_from_handle": {
            **canonical["menu_from_handle"],
            "native_window_handle": handle + 1,
        },
    }
    checks = _uia_menu_handle_binding_checks(stale, pid=pid, menu_handle=handle)
    assert checks["uia_handle_native_handle_matches"] is False

    stale_exact = {
        **canonical,
        "exact_menu_bars": [
            {
                **canonical["exact_menu_bars"][0],
                "native_window_handle": handle + 1,
            }
        ],
    }
    checks = _uia_menu_handle_binding_checks(
        stale_exact,
        pid=pid,
        menu_handle=handle,
    )
    assert checks["uia_exact_row_binds_same_handle"] is False

    wrong_identity = {
        **canonical,
        "menu_from_handle": {
            **canonical["menu_from_handle"],
            "automation_id": "AccessibleChessMainMenu",
        },
    }
    checks = _uia_menu_handle_binding_checks(
        wrong_identity,
        pid=pid,
        menu_handle=handle,
    )
    assert checks["uia_handle_automation_id_canonical"] is False


def test_source_uia_oracle_fails_closed_when_from_handle_probe_is_missing_or_errors() -> None:
    from scripts.p0_native_menubar_uia_oracle import _uia_menu_handle_binding_checks

    missing = _uia_menu_handle_binding_checks({}, pid=1, menu_handle=7)
    assert missing["uia_handle_element_present"] is False
    assert missing["uia_handle_native_handle_matches"] is False
    assert missing["uia_exact_row_binds_same_handle"] is False

    errored = _uia_menu_handle_binding_checks(
        {
            "menu_from_handle": {
                "automation_id": "AccessibleChessFullProductMenu",
                "control_type": "ControlType.MenuBar",
                "process_id": 1,
                "enabled": True,
                "offscreen": False,
                "native_window_handle": 7,
            },
            "menu_from_handle_error": "ElementNotAvailableException",
            "exact_menu_bars": [
                {
                    "automation_id": "AccessibleChessFullProductMenu",
                    "control_type": "ControlType.MenuBar",
                    "process_id": 1,
                    "enabled": True,
                    "offscreen": False,
                    "native_window_handle": 7,
                }
            ],
        },
        pid=1,
        menu_handle=7,
    )
    assert errored["uia_handle_probe_clean"] is False
