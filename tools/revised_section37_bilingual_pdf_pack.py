"""Section 37 source-derived UK/EN advanced PDF reader for external PDF applications.

Never claim PDF input semantic import by Accessible Chess.  Fonts remain
installed system dependencies, not copied or shipped as separate assets.
Generated PDF is project-authored commentary on Lichess CC0 positions.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from xml.sax.saxutils import escape

from tools.revised_section37_bilingual_workbook_pack import (
    LANGS, load_advanced_workbook, _sections,
)

FONTS = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)


def render_pdf(data: dict, lang: str, *, font_file: Path | None = None) -> bytes:
    if lang not in LANGS:
        raise ValueError("unrecognized advanced workbook language")
    try:
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
        from io import BytesIO
    except ImportError as exc:
        raise RuntimeError("PDF authoring needs explicit reportlab dependency") from exc
    selected_font = font_file or next((path for path in FONTS if path.is_file()), None)
    if selected_font is None or not selected_font.is_file():
        raise RuntimeError("embedded Unicode font unavailable: PDF not generated")
    # Register TTFont under a stable name, separate from other project fonts.
    font_label = "Section37BilingualAdvancedUnicode"
    if font_label not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font_label, str(selected_font)))
    title = ParagraphStyle(
        "Section37Title", fontName=font_label, fontSize=16, leading=22,
        spaceAfter=18, textColor=colors.black, alignment=TA_LEFT,
    )
    subtitle = ParagraphStyle(
        "Section37Exercise", fontName=font_label, fontSize=12, leading=16,
        spaceBefore=12, spaceAfter=10,
    )
    text_style = ParagraphStyle(
        "Section37Body", fontName=font_label, fontSize=10, leading=15,
        spaceAfter=9, splitLongWords=True,
    )
    board_style = ParagraphStyle(
        "Section37BoardFEN", fontName=font_label, fontSize=9, leading=13,
        spaceAfter=9, wordWrap="CJK", splitLongWords=True,
    )
    result = BytesIO()
    doc = SimpleDocTemplate(
        result, pagesize=A4, rightMargin=42, leftMargin=42,
        topMargin=48, bottomMargin=48, title=data["title"][lang],
        author="Accessible Chess bilingual learning corpus",
        creator="Accessible Chess - Section 37; Lichess CC0 chess positions",
    )
    story = []
    for kind, value in _sections(data, lang):
        clean = escape(value).replace("\n", "<br/>")
        if kind == "h1":
            story.append(Paragraph(clean, title))
        elif kind == "h2":
            story.append(Paragraph(clean, subtitle))
        elif kind == "fen":
            story.append(Paragraph("FEN: " + clean, board_style))
        else:
            story.append(Paragraph(clean, text_style))
    doc.build(story)
    raw = result.getvalue()
    if not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-2048:]:
        raise RuntimeError("Unicode PDF writer returned malformed file")
    return raw


def main() -> None:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--output-dir", type=Path, required=True)
    cli = p.parse_args()
    source = load_advanced_workbook()
    cli.output_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": "acs-section37-bilingual-advanced-pdf-source-only-v1",
        "external_pdf_original_claim": False,
        "pdf_import_in_accessible_chess": "NOT_QUALIFIED",
        "user_testing": "PDF is for external PDF readers until Accessible Chess PDF ingress explicitly passes",
        "languages": list(LANGS),
        "files": {},
    }
    for lang in LANGS:
        filename = f"section37-advanced-workbook-{lang}.pdf"
        path = cli.output_dir / filename
        if path.exists():
            raise FileExistsError("refuse to overwrite existing user source")
        content = render_pdf(source, lang)
        path.write_bytes(content)
        receipt["files"][filename] = {
            "sha256": sha256(content).hexdigest(), "bytes": len(content),
        }
    (cli.output_dir / "section37-bilingual-pdf-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2)+"\n",
        encoding="utf-8",
    )
    print(json.dumps({"format": "PDF", "actual_files": 2, "native_acs_pdf_import": "NOT_QUALIFIED"}))


if __name__ == "__main__":
    main()
