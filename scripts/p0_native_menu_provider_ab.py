"""Controlled Windows UIA provider A/B for WinForms MenuStrip vs MainMenu.

The process intentionally hosts one tiny WinForms window and waits for external
UIA inspection. It is diagnostic evidence only and is never imported by Product.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def _write_ready(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=("menustrip", "mainmenu"), required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()

    if sys.platform != "win32":
        raise SystemExit("Windows required")

    import clr  # type: ignore

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

    labels = ["&File", "&Game", "&Help"]
    form = Form()
    form.Text = f"Accessible Chess P0 provider probe - {args.variant}"
    form.Name = "AccessibleChessP0ProviderProbe"
    form.Size = Size(720, 360)

    held: list[object] = []
    menu_handle = 0

    if args.variant == "menustrip":
        menu = MenuStrip()
        menu.Name = "AccessibleChessProbeMenuStrip"
        menu.AccessibleName = "Probe menu strip"
        for label in labels:
            top = ToolStripMenuItem(label)
            top.DropDownItems.Add(ToolStripMenuItem("&Action"))
            menu.Items.Add(top)
        form.MainMenuStrip = menu
        form.Controls.Add(menu)
        held.append(menu)
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
        if args.variant == "menustrip":
            try:
                menu_handle = int(menu.Handle.ToInt64()) if bool(menu.IsHandleCreated) else 0
            except Exception:
                menu_handle = 0
        _write_ready(
            args.ready_file,
            {
                "pid": os.getpid(),
                "variant": args.variant,
                "form_handle": int(form.Handle.ToInt64()),
                "menu_handle": menu_handle,
                "form_visible": bool(form.Visible),
            },
        )

    form.Shown += on_shown
    Application.EnableVisualStyles()
    Application.SetCompatibleTextRenderingDefault(False)
    Application.Run(form)
    _ = held
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
