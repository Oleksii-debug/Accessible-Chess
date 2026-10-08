"""Section 37 bilingual advanced workbook from REAL licensed CC0 chess positions.

Creates user-shareable UK/EN TXT, Markdown, HTML, EPUB3 and DOCX documents.
These are transparently DERIVED original educational books, not claimed as
third-party native formats or composed studies. Chess rules and move legality
remain exclusively within canonical Accessible Chess services.

A sixth (PDF) edition is built only when reportlab and a legitimate installed
Unicode font are available; absence is reported instead of false PDF support.
"""
from __future__ import annotations

from hashlib import sha256
from html import escape as html_escape
from io import BytesIO
import json
from pathlib import Path
import re
from typing import Mapping
from xml.sax.saxutils import escape as xml_escape
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

from acs.chesscore import Board
from acs.lawful_corpus_registry import load_catalog, verified_local_source

SOURCE = Path(__file__).resolve().parents[1] / (
    "tests/real_corpus/advanced_training/section37_master_workbook_bilingual.json"
)
OUTNAME = "section37-advanced-workbook"
MAX_LESSONS = 100
LANGS = ("uk", "en")


def load_advanced_workbook(path: Path = SOURCE) -> dict:
    raw = path.read_bytes()
    if not 0 < len(raw) <= 512 * 1024:
        raise ValueError("bilingual workbook exceeds source limit")
    data = json.loads(raw)
    if data.get("schema") != "accessible-chess-advanced-bilingual-source-v1":
        raise ValueError("unknown workbook schema")
    if data.get("language_codes") != ["uk", "en"]:
        raise ValueError("both Ukrainian and English versions are required")
    lessons = data.get("lessons")
    if type(lessons) is not list or not 1 <= len(lessons) <= MAX_LESSONS:
        raise ValueError("empty or excessive advanced workbook")
    ids = set()
    for lesson in lessons:
        ident = lesson.get("lesson_id")
        rating = lesson.get("rating_lichess_puzzle")
        fen = lesson.get("fen_before_opponent_move")
        moves = [lesson.get("opponent_previous_move_uci")] + lesson.get("solution_after_opponent_uci", [])
        if (
            not isinstance(ident, str) or not re.fullmatch(r"S37-[0-9]{2,3}", ident)
            or ident in ids or type(rating) is not int or rating < 2200
            or type(fen) is not str or len(fen.split()) != 6
            or any(type(m) is not str or not re.fullmatch(r"[a-h][1-8][a-h][1-8][qrbn]?", m) for m in moves)
            or len(moves) < 2 or lesson.get("composer_study") is not False
            or not all(type(lesson.get(lang)) is dict and
                       all(type(lesson[lang].get(key)) is str and
                           len(lesson[lang][key]) >= 10 for key in ("title", "prompt"))
                       for lang in LANGS)
        ):
            raise ValueError("unsafe, beginner or incomplete bilingual chess lesson")
        # Fail closed before any shareable EPUB/DOCX/TXT/HTML is emitted.
        # Reuse the one canonical chess authority: source FEN and every Lichess
        # opponent+solution UCI must replay to a legal position.
        try:
            board = Board(fen)
            for uci in moves:
                board.push_text(uci)
            board.fen()
        except (TypeError, ValueError) as exc:
            raise ValueError("bilingual source contains invalid canonical chess play") from exc
        ids.add(ident)
    return data


def _sections(data: dict, lang: str):
    if lang not in LANGS:
        raise ValueError("unsupported workbook language")
    output = [("h1", data["title"][lang]),
              ("p", data["editorial_statement"][lang]),
              ("p", data["level"][lang]),
              ("p", data["position_contract"][lang])]
    for item in data["lessons"]:
        output += [
            ("h2", item["lesson_id"] + " — " + item[lang]["title"]),
            ("p", ("Складність задачі Lichess: " if lang == "uk" else "Lichess puzzle difficulty: ") +
             str(item["rating_lichess_puzzle"])),
            ("fen", item["fen_before_opponent_move"]),
            ("p", ("Попередній хід суперника: " if lang == "uk" else "Opponent's preceding move: ") +
             item["opponent_previous_move_uci"]),
            ("p", item[lang]["prompt"]),
        ]
    output.append(("h2", "Відповіді після самостійного розв'язання" if lang == "uk" else "Solutions — reveal only after independent analysis"))
    for item in data["lessons"]:
        output.append(("p", item["lesson_id"] + ": " + " ".join(item["solution_after_opponent_uci"])))
    output.append(("p", "Джерело позицій: Lichess CC0; не шахові етюди композиторів." if lang == "uk"
                   else "Position data: Lichess CC0; these are practical puzzles, not authored compositions."))
    return output


def render_markdown(data: dict, lang: str) -> bytes:
    lines = []
    for kind, value in _sections(data, lang):
        if kind == "h1":
            lines += ["# " + value, ""]
        elif kind == "h2":
            lines += ["## " + value, ""]
        elif kind == "fen":
            lines += ["```fen", value, "```", ""]
        else:
            lines += [value, ""]
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def render_text(data: dict, lang: str) -> bytes:
    lines = []
    for kind, value in _sections(data, lang):
        if kind == "h1":
            lines += [value, "=" * min(70, len(value))]
        elif kind == "h2":
            lines += [value, "-" * min(50, len(value))]
        elif kind == "fen":
            lines += ["FEN: " + value]
        else:
            lines += [value]
        lines.append("")
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def render_html(data: dict, lang: str, *, xhtml: bool = False) -> bytes:
    langtag = html_escape(lang, quote=True)
    title = html_escape(data["title"][lang], quote=True)
    rows = []
    for kind, value in _sections(data, lang):
        if kind == "fen":
            a = html_escape(value, quote=True)
            rows.append('<p data-acs-fen="' + a + '">FEN: ' + html_escape(value) + '</p>')
        elif kind in ("h1", "h2"):
            lesson_anchor = ""
            if kind == "h2":
                lesson_id = value.split(" — ", 1)[0]
                if re.fullmatch(r"S37-[0-9]{2,3}", lesson_id):
                    lesson_anchor = ' id="' + lesson_id + '"'
            rows.append(f"<{kind}{lesson_anchor}>" + html_escape(value) + f"</{kind}>")
        else:
            rows.append("<p>" + html_escape(value) + "</p>")
    root = '<html xmlns="http://www.w3.org/1999/xhtml"' if xhtml else "<html"
    doc = (
        ('<?xml version="1.0" encoding="utf-8"?>\n' if xhtml else "<!doctype html>\n")
        + f'{root} lang="{langtag}"><head><meta charset="utf-8" />'
        + f"<title>{title}</title></head><body><main>"
        + "\n".join(rows) + "</main></body></html>\n"
    )
    return doc.encode("utf-8")


def render_docx(data: dict, lang: str) -> bytes:
    # Pure OpenXML, no external templates/macros or image-backed inaccessible diagrams.
    parts = []
    for kind, value in _sections(data, lang):
        style = ""
        if kind in ("h1", "h2"):
            n = "Heading1" if kind == "h1" else "Heading2"
            style = '<w:pPr><w:pStyle w:val="' + n + '"/></w:pPr>'
        if kind == "fen":
            value = "FEN: " + value
        escaped = xml_escape(value)
        voice_locale = "uk-UA" if lang == "uk" else "en-US"
        parts.append("<w:p>" + style + '<w:r><w:rPr><w:lang w:val="' +
                     voice_locale + '"/></w:rPr><w:t xml:space="preserve">' +
                     escaped + "</w:t></w:r></w:p>")
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>' + "".join(parts) + '</w:body></w:document>'
    ).encode("utf-8")
    title = xml_escape(data["title"][lang])
    core = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:title>' + title + '</dc:title><dc:creator>Accessible Chess teaching corpus</dc:creator>'
        '</cp:coreProperties>'
    ).encode("utf-8")
    contents = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '</Types>'
    ).encode("utf-8")
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
        '</Relationships>'
    ).encode("utf-8")
    buf = BytesIO()
    with ZipFile(buf, "w", compression=ZIP_DEFLATED) as z:
        for name, body in {
            "[Content_Types].xml": contents, "_rels/.rels": rels,
            "word/document.xml": document, "docProps/core.xml": core,
        }.items():
            z.writestr(name, body)
    return buf.getvalue()


def render_epub3(data: dict, lang: str) -> bytes:
    opf = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="pub-id">urn:uuid:acs-section37-advanced-' + lang + '</dc:identifier>'
        '<dc:title>' + xml_escape(data["title"][lang]) + '</dc:title>'
        '<dc:language>' + lang + '</dc:language>'
        '</metadata><manifest>'
        '<item id="lesson" href="lesson.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '</manifest><spine><itemref idref="lesson"/></spine></package>'
    ).encode("utf-8")
    container = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/book.opf" media-type="application/oebps-package+xml"/>'
        '</rootfiles></container>'
    ).encode("utf-8")
    navigation_links = "".join(
        '<li><a href="lesson.xhtml#' + item["lesson_id"] + '">' +
        xml_escape(item[lang]["title"]) + '</a></li>'
        for item in data["lessons"]
    )
    nav = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" lang="' + lang + '">'
        '<head><title>Navigation</title></head><body>'
        '<nav epub:type="toc" xmlns:epub="http://www.idpf.org/2007/ops">'
        '<h1>Contents</h1><ol>' + navigation_links + '</ol>'
        '</nav></body></html>'
    ).encode("utf-8")
    buf = BytesIO()
    with ZipFile(buf, "w") as z:
        z.writestr("mimetype", b"application/epub+zip", compress_type=ZIP_STORED)
        for name, body in {
            "META-INF/container.xml": container,
            "OEBPS/book.opf": opf,
            "OEBPS/lesson.xhtml": render_html(data, lang, xhtml=True),
            "OEBPS/nav.xhtml": nav,
        }.items():
            z.writestr(name, body, compress_type=ZIP_DEFLATED)
    return buf.getvalue()


def make_pack(data: dict) -> dict[str, bytes]:
    result = {}
    for lang in LANGS:
        for extension, fn in (
            ("md", render_markdown), ("txt", render_text), ("html", render_html),
            ("docx", render_docx), ("epub", render_epub3),
        ):
            result[f"{OUTNAME}-{lang}.{extension}"] = fn(data, lang)
    return result


def source_receipt(data: dict, outputs: Mapping[str, bytes]) -> dict:
    return {
        "schema": "acs-section37-bilingual-generated-lawmful-derived-content-v1",
        "genuine_cc0_source_licensing": "Lichess CC0; original attributed dataset separately qualified",
        "derived_material_is_newly_authored": True,
        "languages": list(LANGS),
        "excludes_beginner_lessons": True,
        "minimum_puzzle_rating": min(x["rating_lichess_puzzle"] for x in data["lessons"]),
        "lesson_count_per_language": len(data["lessons"]),
        "format_family_count": 5,
        "source_sha256": sha256(SOURCE.read_bytes()).hexdigest(),
        "generated_files": {
            name: {"sha256": sha256(body).hexdigest(), "bytes": len(body)}
            for name, body in sorted(outputs.items())
        },
        "original_foreign_EPUB_DOCX_claim": False,
        "native_app_acceptance": "REQUIRES_CANONICAL_IMPORT_TESTS",
        "external_unlicensed_material_included": False,
        "section37_terminal_done": False,
    }


def main() -> None:
    import argparse
    cli = argparse.ArgumentParser()
    cli.add_argument("--output-dir", required=True, type=Path)
    cli.add_argument("--zip-output", type=Path, default=None)
    args = cli.parse_args()
    data = load_advanced_workbook()
    pack = make_pack(data)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, body in pack.items():
        path = args.output_dir / name
        if path.exists():
            raise FileExistsError("refusing to replace preexisting workbook")
        path.write_bytes(body)
    receipt = source_receipt(data, pack)
    # Source-qualified real chess formats accompany each bilingual book: one
    # historically authored composed study and four annotated high-level games.
    # Both pass the exact real-source SHA256 verifier before copying.
    registry = {item["id"]: item for item in load_catalog()}
    for source_id, name in (
        ("historical_reti_1921_original_bilingual_study_pgn", "original-reti-1921-uk-en-study.pgn"),
        ("lichess_cc0_high_level_4_original_annotated_games", "original-lichess-2200-plus-annotated-games.pgn"),
    ):
        original = registry[source_id]
        source = SOURCE.parents[3] / original["local_source"]
        verified_local_source(source, original)
        content = source.read_bytes()
        if sha256(content).hexdigest() != original["sha256"]:
            raise ValueError("qualified real PGN changed after source snapshot")
        target = args.output_dir / name
        if target.exists():
            raise FileExistsError("refusing to overwrite existing PGN export")
        target.write_bytes(content)
        receipt["generated_files"][name] = {
            "sha256": sha256(content).hexdigest(),
            "bytes": len(content),
            "source_id": source_id,
            "real_original_pgn": True,
        }
    # FEN text is a factual export of real CC0 source positions, before the
    # preceding opponent's move. No second FEN parser/chess rules authority.
    fen_bytes = ("\n".join(item["fen_before_opponent_move"] for item in data["lessons"]) + "\n").encode("utf-8")
    name = "original-advanced-before-opponent-move.fen"
    (args.output_dir / name).write_bytes(fen_bytes)
    receipt["generated_files"][name] = {
        "sha256": sha256(fen_bytes).hexdigest(),
        "bytes": len(fen_bytes),
        "position_count": len(data["lessons"]),
        "real_original_licensing": "Lichess CC0",
        "first_opponent_move_not_applied": True,
    }
    (args.output_dir / "section37-bilingual-manifest.json").write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.zip_output is not None:
        # The exact publication candidate must be scanned and read back
        # BEFORE any user-facing archive is declared complete. No external
        # publisher files are silently added to this reproducible package.
        from tools.revised_section37_release_exclusion import audit_public_archive
        if args.zip_output.exists() or args.zip_output.is_symlink():
            raise FileExistsError("refuse existing release ZIP")
        if args.zip_output.parent.resolve() == args.output_dir.resolve():
            raise ValueError("release ZIP must be stored outside its input directory")
        entries = tuple(sorted((*receipt["generated_files"], "section37-bilingual-manifest.json")))
        if len(entries) != 14:
            raise ValueError("unexpected user share package inventory")
        staging = args.zip_output.with_name(args.zip_output.name + ".partial")
        if staging.exists():
            raise FileExistsError("stale unqualified release stage exists")
        try:
            with ZipFile(staging, "x", compression=ZIP_DEFLATED, compresslevel=6) as archive:
                for entry in entries:
                    content = (args.output_dir / entry).read_bytes()
                    if entry in receipt["generated_files"]:
                        recorded = receipt["generated_files"][entry]
                        if sha256(content).hexdigest() != recorded["sha256"] or len(content) != recorded["bytes"]:
                            raise ValueError("user file changed before archive publication")
                    item = ZipInfo(entry, date_time=(2020, 1, 1, 0, 0, 0))
                    item.compress_type = ZIP_DEFLATED
                    item.external_attr = 0o100644 << 16
                    archive.writestr(item, content, compress_type=ZIP_DEFLATED)
            proven = audit_public_archive(staging)
            if proven["result"] != "PASS_ONLY_FOR_TESTED_ZIP_BYTES":
                raise ValueError("user ZIP external source exclusion audit refused")
            # Exact output bytes have been inspected, preventing leaks of
            # noncleared original ChessBase or chess-book corpora by SHA/name.
            staging.rename(args.zip_output)
            with ZipFile(args.zip_output, "r") as archive:
                if set(archive.namelist()) != set(entries) or archive.testzip() is not None:
                    raise ValueError("public ZIP readback failed")
            print(json.dumps({
                "zip_created": args.zip_output.name,
                "member_count": len(entries),
                "excluded_source_check": proven["result"],
                "zip_sha256": sha256(args.zip_output.read_bytes()).hexdigest(),
            }, sort_keys=True))
        finally:
            staging.unlink(missing_ok=True)
    print(json.dumps({"books": len(pack), "game_and_position_files": 3,
                      "languages": list(LANGS),
                      "lessons_per_language": len(data["lessons"])}, sort_keys=True))


if __name__ == "__main__":
    main()
