"""Controlled Windows UIA provider experiments for native WinForms menus.

Each process intentionally hosts one tiny WinForms window and waits for external
UIA inspection. Variants distinguish framework accessibility activation from
control architecture. This script is diagnostic evidence only and is never
imported by Product.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


_VARIANTS = (
    "menustrip",
    "menustrip-modern",
    "menustrip-accessibility-object",
    "mainmenu",
)
_ACCESSIBILITY_SWITCHES = (
    "Switch.UseLegacyAccessibilityFeatures",
    "Switch.UseLegacyAccessibilityFeatures.2",
    "Switch.UseLegacyAccessibilityFeatures.3",
    "Switch.UseLegacyAccessibilityFeatures.4",
    "Switch.UseLegacyAccessibilityFeatures.5",
)


def _write_ready(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=_VARIANTS, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()

    if sys.platform != "win32":
        raise SystemExit("Windows required")

    import clr  # type: ignore

    if args.variant == "menustrip-modern":
        # Python/pythonnet is not a normal .NET Framework WinForms executable with
        # a target-framework app.config. Opt into every framework accessibility
        # generation before System.Windows.Forms is loaded, exactly as Microsoft's
        # compatibility guidance describes for older-targeting hosts.
        from System import AppContext  # type: ignore

        for switch in _ACCESSIBILITY_SWITCHES:
            AppContext.SetSwitch(switch, False)

    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Drawing import Size  # type: ignore
    from System.Windows.Forms import (  # type: ignore
        Application,
        Form,
        MainMenu,
        MenuItem,
        MenuStrip,
        ToolStripMenuItem,
    )

    # These process-wide WinForms settings must be established before the first
    # control/window is constructed.
    Application.EnableVisualStyles()
    Application.SetCompatibleTextRenderingDefault(False)

    labels = ["&File", "&Game", "&Help"]
    form = Form()
    form.Text = f"Accessible Chess P0 provider probe - {args.variant}"
    form.Name = "AccessibleChessP0ProviderProbe"
    form.Size = Size(720, 360)

    held: list[object] = []
    menu_handle = 0
    accessibility: dict[str, object] = {}

    if args.variant != "mainmenu":
        menu = MenuStrip()
        menu.Name = "AccessibleChessProbeMenuStrip"
        menu.AccessibleName = "Probe menu strip"
        items = []
        for label in labels:
            top = ToolStripMenuItem(label)
            top.DropDownItems.Add(ToolStripMenuItem("&Action"))
            menu.Items.Add(top)
            items.append(top)
        form.MainMenuStrip = menu
        form.Controls.Add(menu)
        held.extend([menu, *items])
        if args.variant == "menustrip-accessibility-object":
            # Force the managed accessibility objects to exist before external
            # WM_GETOBJECT/UIA probing. This separates lazy AO construction from
            # framework/provider activation.
            try:
                menu_ao = menu.AccessibilityObject
                accessibility["menu_accessible_type"] = str(menu_ao.GetType().FullName)
                accessibility["menu_accessible_role"] = str(menu_ao.Role)
                accessibility["menu_accessible_name"] = str(menu_ao.Name)
            except Exception as exc:
                accessibility["menu_accessible_error"] = type(exc).__name__ + ": " + str(exc)
            item_roles: list[dict[str, str]] = []
            for item in items:
                try:
                    ao = item.AccessibilityObject
                    item_roles.append(
                        {
                            "type": str(ao.GetType().FullName),
                            "role": str(ao.Role),
                            "name": str(ao.Name),
                        }
                    )
                except Exception as exc:
                    item_roles.append({"error": type(exc).__name__ + ": " + str(exc)})
            accessibility["item_accessibility"] = item_roles
    else:
        menu = MainMenu()
        for label in labels:
            top = MenuItem(label)
            top.MenuItems.Add(MenuItem("&Action"))
            menu.MenuItems.Add(top)
        form.Menu = menu
        held.append(menu)

    def on_shown(sender, event) -> None:  # noqa: ANN001
        nonlocal menu_handle
        if args.variant != "mainmenu":
            try:
                menu_handle = int(menu.Handle.ToInt64()) if bool(menu.IsHandleCreated) else 0
            except Exception:
                menu_handle = 0
        switch_values: dict[str, bool] = {}
        try:
            from System import AppContext  # type: ignore

            for switch in _ACCESSIBILITY_SWITCHES:
                found, value = AppContext.TryGetSwitch(switch)
                if found:
                    switch_values[switch] = bool(value)
        except Exception as exc:
            accessibility["switch_read_error"] = type(exc).__name__ + ": " + str(exc)
        _write_ready(
            args.ready_file,
            {
                "pid": os.getpid(),
                "variant": args.variant,
                "form_handle": int(form.Handle.ToInt64()),
                "menu_handle": menu_handle,
                "form_visible": bool(form.Visible),
                "accessibility_switches": switch_values,
                "accessibility": accessibility,
            },
        )

    form.Shown += on_shown
    Application.Run(form)
    _ = held
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
