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
        "menu_binding_stable": True,
        "poll_snapshot_error": "",
        "menu_from_handle": {
            "automation_id": "AccessibleChessFullProductMenu",
            "control_type": "ControlType.MenuBar",
            "process_id": pid,
            "enabled": True,
            "offscreen": False,
            "native_window_handle": handle,
        },
        "menu_from_handle_error": "",
        "same_process_elements_with_exact_automation_id": [
            {
                "automation_id": "AccessibleChessFullProductMenu",
                "control_type": "ControlType.MenuBar",
                "process_id": pid,
                "enabled": True,
                "offscreen": False,
                "native_window_handle": handle,
            }
        ],
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

    stale_exact_state = {
        **canonical,
        "exact_menu_bars": [
            {
                **canonical["exact_menu_bars"][0],
                "enabled": False,
                "offscreen": True,
            }
        ],
    }
    checks = _uia_menu_handle_binding_checks(
        stale_exact_state,
        pid=pid,
        menu_handle=handle,
    )
    assert checks["uia_exact_row_enabled"] is False
    assert checks["uia_exact_row_onscreen"] is False
    assert checks["uia_from_handle_matches_exact_row"] is False

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

    duplicate_id = {
        **canonical,
        "same_process_elements_with_exact_automation_id": [
            canonical["same_process_elements_with_exact_automation_id"][0],
            {
                **canonical["same_process_elements_with_exact_automation_id"][0],
                "control_type": "ControlType.Pane",
                "native_window_handle": handle + 2,
            },
        ],
    }
    checks = _uia_menu_handle_binding_checks(
        duplicate_id,
        pid=pid,
        menu_handle=handle,
    )
    assert checks["uia_automation_id_unique_in_process"] is False
    assert checks["uia_automation_id_row_binds_same_handle"] is False
    assert checks["uia_from_handle_matches_automation_id_row"] is False


def test_source_uia_probe_waits_for_stable_unique_handle_binding_not_presence_only() -> None:
    source = Path("scripts/p0_native_menubar_uia_probe.ps1").read_text(encoding="utf-8")

    assert "function Test-CanonicalMenuBinding" in source
    assert "$bindingStable = Test-CanonicalMenuBinding" in source
    assert "if($bindingStable){ break }" in source
    assert "menu_binding_stable = [bool]$bindingStable" in source
    assert "poll_snapshot_error = $pollSnapshotError" in source
    assert "$candidateBarDetails += ,(Convert-MenuBarDetail $bars.Item($index))" in source
    assert "$pollSnapshotError = $_.Exception.GetType().Name" in source
    assert "if($exact.Count -eq 1 -and $anyId.Count -eq 1){ break }" not in source
    assert "$exact.Count -eq 1 -or $bars.Count -gt 0" not in source
    assert "[long]$row['native_window_handle'] -ne $ExpectedMenuHandle" in source
    assert "if(-not [bool]$row['enabled'])" in source
    assert "if([bool]$row['offscreen'])" in source


def test_source_uia_oracle_fails_closed_when_from_handle_probe_is_missing_or_errors() -> None:
    from scripts.p0_native_menubar_uia_oracle import _uia_menu_handle_binding_checks

    missing = _uia_menu_handle_binding_checks({}, pid=1, menu_handle=7)
    assert missing["uia_handle_element_present"] is False
    assert missing["uia_probe_binding_stable"] is False
    assert missing["uia_poll_snapshot_clean"] is False
    assert missing["uia_handle_native_handle_matches"] is False
    assert missing["uia_exact_row_binds_same_handle"] is False

    errored = _uia_menu_handle_binding_checks(
        {
            "menu_binding_stable": True,
            "poll_snapshot_error": "",
            "menu_from_handle": {
                "automation_id": "AccessibleChessFullProductMenu",
                "control_type": "ControlType.MenuBar",
                "process_id": 1,
                "enabled": True,
                "offscreen": False,
                "native_window_handle": 7,
            },
            "menu_from_handle_error": "ElementNotAvailableException",
            "same_process_elements_with_exact_automation_id": [
                {
                    "automation_id": "AccessibleChessFullProductMenu",
                    "control_type": "ControlType.MenuBar",
                    "process_id": 1,
                    "enabled": True,
                    "offscreen": False,
                    "native_window_handle": 7,
                }
            ],
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


def test_source_uia_oracle_preserves_the_exact_handle_used_for_probe() -> None:
    source = Path("scripts/p0_native_menubar_uia_oracle.py").read_text(encoding="utf-8")

    assert 'result["probed_menu_handle"] = probed_menu_handle' in source
    assert "menu_handle=int(result[\"winforms\"].get(\"menu_handle\") or 0)" not in source
    assert 'menu_handle = int(result.get("probed_menu_handle") or 0)' in source
    assert '"menu_handle_stable_after_uia"' in source
