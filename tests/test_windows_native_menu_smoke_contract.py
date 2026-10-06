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
