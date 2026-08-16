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
