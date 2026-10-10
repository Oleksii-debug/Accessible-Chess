"""Authentic historical composed endgame study via canonical BookDocument/PGN.

One source of original composition truth. Language changes text only, never
FEN, moves, original composed goal or annotation provenance.
"""
from __future__ import annotations

from .bookdocument import BookDocument, Exercise, Game, Heading, Paragraph, Position
from .gametree import serialize_game
from .pgn_roundtrip import parse_pgn_text
from .section40_historical_reti_dataset import original_reti_source_bytes

HISTORICAL_RETI_MATERIAL_ID = "historical-reti-1921-original-study"
HISTORICAL_RETI_BOOK_KEY = "section40:historical-reti-1921-original-study"
_RETI_FEN = "7K/8/k1P5/7p/8/8/8/8 w - - 0 1"


def build_historical_reti_offline_material(*, language: str = "uk") -> tuple[BookDocument, dict]:
    if language not in ("uk", "en"):
        raise ValueError("historical Reti teaching language must be uk or en")
    raw = original_reti_source_bytes().decode("utf-8")
    source_games = parse_pgn_text(raw, strict=False)
    if (len(source_games) != 1
        or source_games[0].tags.get("FEN") != _RETI_FEN
        or source_games[0].tags.get("SetUp") != "1"
        or len(source_games[0].line.moves) != 11):
        raise ValueError("original Reti 1921 study lost historic FEN/variation")
    canonical = serialize_game(source_games[0]).rstrip() + "\n"
    validated = parse_pgn_text(canonical, strict=True)
    if len(validated) != 1 or len(validated[0].line.moves) != 11:
        raise ValueError("historical 1921 study cannot roundtrip canonical PGN")
    if language == "en":
        title = "Richard Réti's original 1921 endgame study: draw"
        intro = (
            "Authentic historical composition by Richard Réti (1921), not a "
            "modern book quotation. Original study and newly authored bilingual "
            "notes are preserved. White to move and draw; calculate simultaneous "
            "king threats, not only the geometric distance to either pawn."
        )
        prompt = "White to play and draw: find the first move, then follow the complete defence."
        caption = "Réti 1921 original initial position; White to move."
    else:
        title = "Оригінальний етюд Ріхарда Реті 1921 року: нічия"
        intro = (
            "Автентична історична композиція Ріхарда Реті (1921), а не цитата "
            "з сучасного авторського видання. Оригінальний етюд і нові авторські "
            "українсько-англійські коментарі збережено. Хід білих — здобути "
            "нічию, розраховуючи одночасні загрози королем."
        )
        prompt = "Хід білих — нічия. Знайдіть перший хід і розрахуйте всю оборону чорних."
        caption = "Вихідна позиція оригінального етюду Реті 1921 року. Хід білих."
    source_url = (
        "https://www.arves.org/arves/index.php/en/endgamestudies/"
        "studies-by-composer/1550-reti-s-study-is-100-years-old"
    )
    document = BookDocument(
        title=title,
        language=language,
        author="Richard Réti (1889–1929); bilingual commentary by Accessible Chess",
        source_name=source_url,
        source_rights=(
            "Original 1921 composition by Richard Réti, died 1929: historical "
            "public-domain work; editorial notes newly authored; no third-party "
            "modern edition reproduced. Rights vary by jurisdiction."
        ),
        blocks=[
            Heading(text=title, level=1, block_id="section40-reti-1921-h1",
                    source_anchor="section40:reti:1921:title"),
            Paragraph(text=intro, block_id="section40-reti-1921-intro",
                      source_anchor="section40:reti:1921:intro"),
            Position(fen=_RETI_FEN, caption=caption,
                     block_id="section40-reti-1921-start",
                     source_anchor="section40:reti:1921:start"),
            Exercise(fen=_RETI_FEN, prompt=prompt, answer_text="Kg7!",
                     difficulty="Authentic composed endgame study (1921), not FIDE",
                     block_id="section40-reti-1921-exercise",
                     source_anchor="section40:reti:1921:exercise"),
            Game(pgn=canonical, title="Original full annotated 1921 Réti study",
                 block_id="section40-reti-1921-game",
                 source_anchor="section40:reti:1921:game"),
        ],
    )
    doc_wire = document.as_dict()
    if BookDocument.from_dict(doc_wire).as_dict() != doc_wire:
        raise ValueError("original endgame-study BookDocument roundtrip failed")
    return document, {
        "source_id": "historical_reti_1921_original_bilingual_study_pgn",
        "fen": _RETI_FEN,
        "first_solution_san": "Kg7",
        "full_solution_pgn": canonical,
        "game_count": 1,
        "language": "uk,en",
        "original_study_not_rating": True,
    }
