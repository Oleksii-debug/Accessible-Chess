from __future__ import annotations

from pathlib import Path

from .teaching_webapp import TeachingAccessibleChessAPI


def main() -> None:
    import webview

    html = Path(__file__).resolve().parents[1] / "web" / "teaching_board.html"
    if not html.exists():
        raise RuntimeError("Teaching board UI file is missing")
    webview.create_window(
        "Accessible Chess — Дошка тренера",
        url=str(html),
        js_api=TeachingAccessibleChessAPI(),
        width=980,
        height=800,
        min_size=(760, 600),
        text_select=True,
    )
    webview.start(gui="edgechromium", private_mode=True)


if __name__ == "__main__":
    main()
