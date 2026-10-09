"""Bundled original Section37 twelve-lesson bilingual master workbook.

This is the immutable original project-authored Section37 source mirrored for
offline packaged Books. The Git-blob digest must equal the canonical
tests/real_corpus/advanced_training/section37_master_workbook_bilingual.json
source. No tests/ path, network, extra router/parser or provider needed in EXE.
Original 20 actual CC0 chess positions are validated against the existing
embedded 16 + 4 Lichess records before any BookDocument is published.
"""
from __future__ import annotations

import base64
import hashlib
import json
import zlib

from .bookdocument import BookDocument, Heading, Paragraph, Position, Exercise
from .chesscore import Board
from .section40_advanced_licensed_dataset import bundled_advanced_puzzles
from .section40_extreme_licensed_dataset import bundled_extreme_puzzles

MATERIAL_ID = "section37-advanced-twelve-bilingual-source-workbook"
BOOK_KEY_PREFIX = "section40:advanced-twelve-source37-workbook"
ORIGINAL_SOURCE_GIT_BLOB = "b847385035edf0cb68c91b47227b8a2591499611"
ORIGINAL_SOURCE_PATH = "tests/real_corpus/advanced_training/section37_master_workbook_bilingual.json"
_ORIGINAL_SOURCE_TEXT = "{\n  \"schema\": \"accessible-chess-advanced-bilingual-source-v1\",\n  \"language_codes\": [\n    \"uk\",\n    \"en\"\n  ],\n  \"title\": {\n    \"uk\": \"Майстерська шахова лабораторія: 12 складних позицій\",\n    \"en\": \"Advanced Chess Laboratory: 12 Critical Positions\"\n  },\n  \"editorial_statement\": {\n    \"uk\": \"Оригінальні двомовні навчальні завдання на реальних позиціях Lichess CC0. Це не переклад захищених шахових книг і не збірник авторських етюдів.\",\n    \"en\": \"New bilingual training prompts built on real Lichess CC0 positions. This is neither a translation of copyrighted books nor a collection of composed studies.\"\n  },\n  \"level\": {\n    \"uk\": \"Лише після I розряду: КМС, майстерська та дуже складна підготовка. Рейтинг задач Lichess не є Ело ФІДЕ.\",\n    \"en\": \"First category and above: candidate-master, master-track and extreme calculation. Lichess puzzle rating is not FIDE Elo.\"\n  },\n  \"position_contract\": {\n    \"uk\": \"Дана FEN-позиція стоїть ДО попереднього ходу суперника. Застосуй цей хід на канонічній дошці, потім шукай власне рішення. Не відкривай розв'язок до самостійної спроби.\",\n    \"en\": \"The FEN is BEFORE the opponent's previous move. Play that move on the canonical chessboard first, then solve. Do not reveal the solution before an independent attempt.\"\n  },\n  \"rights\": \"Original new instructional prose for CC0 chess positions; redistribution of this authored bilingual workbook permitted; attribution to Lichess retained; no third-party proprietary books bundled.\",\n  \"level_floor_lichess_puzzle_rating\": 2200,\n  \"studies_scope\": \"Not an authored composition book; true composed studies are separate bibliography pending licensed material\",\n  \"lessons\": [\n    {\n      \"lesson_id\": \"S37-01\",\n      \"category\": \"calculation\",\n      \"original_puzzle_id\": \"00Ns0\",\n      \"rating_lichess_puzzle\": 2539,\n      \"fen_before_opponent_move\": \"r2qr1k1/pn1p2pp/bp3p2/2p1N3/2P5/1PB3Q1/P1P3PP/R4RK1 w - - 0 18\",\n      \"opponent_previous_move_uci\": \"f1f6\",\n      \"solution_after_opponent_uci\": [\n        \"d8f6\",\n        \"a1f1\",\n        \"f6h6\",\n        \"e5g4\",\n        \"h6g6\",\n        \"c3g7\",\n        \"e8e4\",\n        \"g4f6\",\n        \"g8g7\"\n      ],\n      \"original_lichess_themes\": [\n        \"advantage\",\n        \"hangingPiece\",\n        \"intermezzo\",\n        \"middlegame\",\n        \"veryLong\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Міжходи, форсованість і захист\",\n        \"prompt\": \"Визнач три ходи-кандидати. Після відповіді суперника порахуй кожну форсовану гілку до тихої стабілізації. Порівняй проміжний хід із прямою реалізацією.\"\n      },\n      \"en\": {\n        \"title\": \"Intermediate moves, forcing lines and defence\",\n        \"prompt\": \"Find three candidate moves. Calculate every forcing branch through the defender's strongest reply until a quiet stabilization. Compare intermediate moves with direct conversion.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-02\",\n      \"category\": \"calculation\",\n      \"original_puzzle_id\": \"00KNB\",\n      \"rating_lichess_puzzle\": 2627,\n      \"fen_before_opponent_move\": \"2rr2k1/5p2/4p2p/4N1pQ/1p3P2/4P3/np3P1P/2q2BRK b - - 1 32\",\n      \"opponent_previous_move_uci\": \"c8c7\",\n      \"solution_after_opponent_uci\": [\n        \"h5h6\",\n        \"b2b1q\",\n        \"h6g5\"\n      ],\n      \"original_lichess_themes\": [\n        \"crushing\",\n        \"kingsideAttack\",\n        \"master\",\n        \"middlegame\",\n        \"pin\",\n        \"short\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Розрахунок за взаємних загроз\",\n        \"prompt\": \"Перевір усі шахи, взяття й загрози; знайди тактичний ресурс захисника. Визнач, чи працює ідея за найкращої відповіді.\"\n      },\n      \"en\": {\n        \"title\": \"Calculation under mutual threats\",\n        \"prompt\": \"Check every forcing check, capture and threat; identify the defender's tactical resource. Decide whether the idea survives best defence.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-03\",\n      \"category\": \"combination\",\n      \"original_puzzle_id\": \"00LRq\",\n      \"rating_lichess_puzzle\": 2291,\n      \"fen_before_opponent_move\": \"1k6/1p1q4/P2p3p/1NpPpn1Q/5b2/2P3r1/1P2B1P1/R6K b - - 3 28\",\n      \"opponent_previous_move_uci\": \"g3g7\",\n      \"solution_after_opponent_uci\": [\n        \"a6a7\",\n        \"b8a8\",\n        \"b5c7\",\n        \"d7c7\",\n        \"h5e8\",\n        \"c7b8\",\n        \"a7b8q\"\n      ],\n      \"original_lichess_themes\": [\n        \"advancedPawn\",\n        \"doubleCheck\",\n        \"mate\",\n        \"mateIn4\",\n        \"middlegame\",\n        \"promotion\",\n        \"queensideAttack\",\n        \"sacrifice\",\n        \"veryLong\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Комбінація з перетворенням та жертвою\",\n        \"prompt\": \"Досліди не лише головну форсовану лінію, а й відхилення короля, зустрічні шахи та альтернативи перетворення пішака.\"\n      },\n      \"en\": {\n        \"title\": \"Sacrifice and promotion combination\",\n        \"prompt\": \"Explore the forcing line, king deviations, counter-checks and alternative pawn promotions rather than stopping at the first attractive move.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-04\",\n      \"category\": \"combination\",\n      \"original_puzzle_id\": \"00LZf\",\n      \"rating_lichess_puzzle\": 2205,\n      \"fen_before_opponent_move\": \"r1b1kb1r/pppp1ppp/2n1p3/3nN3/3P2q1/4B3/PPP1BPPP/RN1Q1RK1 b kq - 9 8\",\n      \"opponent_previous_move_uci\": \"d5e3\",\n      \"solution_after_opponent_uci\": [\n        \"f2e3\",\n        \"g4g5\",\n        \"e5f7\",\n        \"g5e3\",\n        \"g1h1\"\n      ],\n      \"original_lichess_themes\": [\n        \"advantage\",\n        \"attackingF2F7\",\n        \"fork\",\n        \"long\",\n        \"opening\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Контрудар у дебюті\",\n        \"prompt\": \"Після останнього ходу суперника оцінюй його найнебезпечнішу загрозу. Побудуй дерево кандидатів і назви позиційні наслідки тактичного вибору.\"\n      },\n      \"en\": {\n        \"title\": \"Counterattack in the opening\",\n        \"prompt\": \"After the opponent's last move, identify the most urgent threat. Build a candidate-move tree and explain the positional consequences of the tactical decision.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-05\",\n      \"category\": \"opening\",\n      \"original_puzzle_id\": \"00M7w\",\n      \"rating_lichess_puzzle\": 2274,\n      \"fen_before_opponent_move\": \"r1b1k2r/ppp2ppp/2n5/2bBp3/2Pq4/3P1QP1/P2B1P1P/1R2K1NR b Kkq - 2 12\",\n      \"opponent_previous_move_uci\": \"f7f6\",\n      \"solution_after_opponent_uci\": [\n        \"g1e2\",\n        \"d4f2\",\n        \"f3f2\",\n        \"c5f2\",\n        \"e1f2\"\n      ],\n      \"original_lichess_themes\": [\n        \"crushing\",\n        \"long\",\n        \"opening\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Дебютний центр і темп розвитку\",\n        \"prompt\": \"Перевір, чи тактичне продовження виправдане перевагою в розвитку. Порівняй природний захист із форсованим варіантом.\"\n      },\n      \"en\": {\n        \"title\": \"Opening central tension and tempi\",\n        \"prompt\": \"Determine whether development justifies the tactical continuation. Compare natural defence with the critical forcing line.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-06\",\n      \"category\": \"opening\",\n      \"original_puzzle_id\": \"00LZf\",\n      \"rating_lichess_puzzle\": 2205,\n      \"fen_before_opponent_move\": \"r1b1kb1r/pppp1ppp/2n1p3/3nN3/3P2q1/4B3/PPP1BPPP/RN1Q1RK1 b kq - 9 8\",\n      \"opponent_previous_move_uci\": \"d5e3\",\n      \"solution_after_opponent_uci\": [\n        \"f2e3\",\n        \"g4g5\",\n        \"e5f7\",\n        \"g5e3\",\n        \"g1h1\"\n      ],\n      \"original_lichess_themes\": [\n        \"advantage\",\n        \"attackingF2F7\",\n        \"fork\",\n        \"long\",\n        \"opening\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Неповнота розвитку та конкретика\",\n        \"prompt\": \"Зваж загрози королю й фігурам перед обговоренням дебютної оцінки. Не називай варіант виграним без перевірки ходів.\"\n      },\n      \"en\": {\n        \"title\": \"Development deficits and concrete lines\",\n        \"prompt\": \"Evaluate king safety and hanging pieces before assigning an opening verdict. Do not call a variation winning without checking the concrete moves.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-07\",\n      \"category\": \"middlegame\",\n      \"original_puzzle_id\": \"00GWg\",\n      \"rating_lichess_puzzle\": 2243,\n      \"fen_before_opponent_move\": \"1r1r2k1/pp4pp/2nNb3/2R2p2/2P1p3/8/P4PPP/3BR1K1 w - - 1 26\",\n      \"opponent_previous_move_uci\": \"d6b7\",\n      \"solution_after_opponent_uci\": [\n        \"b8b7\",\n        \"c5c6\",\n        \"b7b1\",\n        \"g1f1\",\n        \"d8d1\",\n        \"e1d1\",\n        \"b1d1\",\n        \"f1e2\",\n        \"e6d7\"\n      ],\n      \"original_lichess_themes\": [\n        \"crushing\",\n        \"middlegame\",\n        \"veryLong\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Ініціатива й активність важких фігур\",\n        \"prompt\": \"Склади позиційний план, а потім перевір його тактично. Особливу увагу приділи другій горизонталі, зв'язкам та відкритим лініям.\"\n      },\n      \"en\": {\n        \"title\": \"Initiative and heavy-piece activity\",\n        \"prompt\": \"Form a positional plan, then test it concretely. Pay attention to rank penetration, pins and open files.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-08\",\n      \"category\": \"middlegame\",\n      \"original_puzzle_id\": \"004Ys\",\n      \"rating_lichess_puzzle\": 2233,\n      \"fen_before_opponent_move\": \"r4rk1/3q1pbp/p1n1p1p1/2p3NP/1p3B2/3P3Q/PPP3P1/R3R1K1 b - - 2 19\",\n      \"opponent_previous_move_uci\": \"d7d4\",\n      \"solution_after_opponent_uci\": [\n        \"f4e3\",\n        \"d4f6\",\n        \"e1f1\",\n        \"f6e5\",\n        \"h5g6\",\n        \"e5e3\",\n        \"h3e3\"\n      ],\n      \"original_lichess_themes\": [\n        \"advantage\",\n        \"defensiveMove\",\n        \"middlegame\",\n        \"veryLong\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Ресурси захисту під атакою\",\n        \"prompt\": \"Побудуй список реальних загроз, знайди кандидатні захисні ходи й оціни, чи зберігається ініціатива після точного захисту.\"\n      },\n      \"en\": {\n        \"title\": \"Defensive resources under attack\",\n        \"prompt\": \"List concrete threats, find defensive candidate moves and evaluate whether initiative persists against accurate resistance.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-09\",\n      \"category\": \"endgame\",\n      \"original_puzzle_id\": \"00H2L\",\n      \"rating_lichess_puzzle\": 2351,\n      \"fen_before_opponent_move\": \"8/8/2p2p2/p4P1p/Pk5P/4K1P1/8/8 w - - 1 39\",\n      \"opponent_previous_move_uci\": \"e3d3\",\n      \"solution_after_opponent_uci\": [\n        \"c6c5\",\n        \"d3e2\",\n        \"c5c4\",\n        \"g3g4\",\n        \"h5g4\"\n      ],\n      \"original_lichess_themes\": [\n        \"crushing\",\n        \"endgame\",\n        \"long\",\n        \"pawnEndgame\",\n        \"quietMove\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Тихий темп у пішаковому закінченні\",\n        \"prompt\": \"Порахуй пішакові прориви й королівські маршрути. Перевір цугцванг після кожної відповіді, не застосовуючи шаблонного правила без розрахунку.\"\n      },\n      \"en\": {\n        \"title\": \"Quiet tempo in a pawn ending\",\n        \"prompt\": \"Calculate pawn breaks and king routes. Test zugzwang after every defender's reply instead of assuming a textbook rule settles the position.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-10\",\n      \"category\": \"endgame\",\n      \"original_puzzle_id\": \"00FHO\",\n      \"rating_lichess_puzzle\": 2233,\n      \"fen_before_opponent_move\": \"8/1pp5/p2p3p/3P1Pk1/P3K1P1/1P5R/8/2r5 w - - 1 39\",\n      \"opponent_previous_move_uci\": \"e4f3\",\n      \"solution_after_opponent_uci\": [\n        \"c1c3\",\n        \"f3g2\",\n        \"c3h3\",\n        \"g2h3\",\n        \"h6h5\",\n        \"g4h5\",\n        \"g5h5\"\n      ],\n      \"original_lichess_themes\": [\n        \"crushing\",\n        \"endgame\",\n        \"rookEndgame\",\n        \"veryLong\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Ладейна активність і контргра\",\n        \"prompt\": \"Оціни активність короля, відсічні лінії та прохідні пішаки. Шукай ресурси захисту в довгому варіанті.\"\n      },\n      \"en\": {\n        \"title\": \"Rook activity and counterplay\",\n        \"prompt\": \"Evaluate king activity, cut-off ranks and passed pawns. Search for counterplay in the full long variation.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-11\",\n      \"category\": \"extreme\",\n      \"original_puzzle_id\": \"NgGRN\",\n      \"rating_lichess_puzzle\": 3164,\n      \"fen_before_opponent_move\": \"7Q/rpk2p1p/p2b4/q1pp4/3P2b1/2P1P3/PP3PPP/R3K2R b KQ - 0 17\",\n      \"opponent_previous_move_uci\": \"c5d4\",\n      \"solution_after_opponent_uci\": [\n        \"h8d4\",\n        \"g4h5\",\n        \"g2g4\",\n        \"h5g6\",\n        \"d4a7\",\n        \"d6c5\",\n        \"b2b4\",\n        \"c5b4\",\n        \"e1g1\",\n        \"b4c5\",\n        \"a7a8\"\n      ],\n      \"original_lichess_themes\": [],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Екстремальна тактика: форсований розрахунок\",\n        \"prompt\": \"Сформулюй щонайменше три кандидати та заперечення суперника. Не підглядай відповідь, перевір можливу тактичну пастку.\"\n      },\n      \"en\": {\n        \"title\": \"Extreme calculation: forcing tactical play\",\n        \"prompt\": \"Write down at least three candidate moves and the opponent's refutations. Work without seeing the answer; test possible tactical traps.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-12\",\n      \"category\": \"extreme\",\n      \"original_puzzle_id\": \"gWyMk\",\n      \"rating_lichess_puzzle\": 3166,\n      \"fen_before_opponent_move\": \"r1b2r1k/1p5P/1n1pp2B/1Pp2p1B/4P2q/P2P2b1/1P2Q2P/R4R1K b - - 1 20\",\n      \"opponent_previous_move_uci\": \"f8f6\",\n      \"solution_after_opponent_uci\": [\n        \"h6f4\",\n        \"g3h2\",\n        \"e2h2\",\n        \"h4h2\",\n        \"h1h2\"\n      ],\n      \"original_lichess_themes\": [],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Екстремальна тактика: 3166\",\n        \"prompt\": \"Розрахуй найжорсткішу лінію до кінця, порівняй із двома спокусливими помилковими варіантами й поясни роль усіх незахищених фігур.\"\n      },\n      \"en\": {\n        \"title\": \"Extreme tactic: 3166\",\n        \"prompt\": \"Calculate the critical line to completion, compare it with two tempting false lines and account for every loose piece.\"\n      }\n    }\n  ]\n}\n"


# Keep the compiled Books source byte-identical to the checked-in, verified
# workbook.  The preceding literal is kept solely for source-history review;
# this compact immutable payload is the current packaged authority.
_ORIGINAL_SOURCE_TEXT = zlib.decompress(base64.b64decode("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")).decode("utf-8")


def _canonical_source() -> dict:
    raw = _ORIGINAL_SOURCE_TEXT.encode("utf-8")
    digest = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + bytes((0,)) + raw).hexdigest()
    if digest != ORIGINAL_SOURCE_GIT_BLOB:
        raise ValueError("original Section37 bilingual workbook Git source identity changed")
    data = json.loads(raw)
    if (data.get("schema") != "accessible-chess-advanced-bilingual-source-v1"
        or data.get("language_codes") != ["uk", "en"]
        or type(data.get("lessons")) is not list
        or len(data["lessons"]) != 12):
        raise ValueError("source37 original 12 advanced lessons are unavailable")
    return data


def build_real_bilingual_master_workbook(*, language: str = "uk") -> tuple[BookDocument, tuple]:
    """Create native readable Books/Training using only canonical position rules."""
    if language not in ("uk", "en"):
        raise ValueError("source37 workbook language must be uk/en")
    data = _canonical_source()
    originals = {}
    for record in bundled_advanced_puzzles():
        originals[record["puzzle_id"]] = (
            record["fen_before_opponent_move"],
            record["uci_moves_with_opponent_first"].split(),
            record["rating"],
        )
    for record in bundled_extreme_puzzles():
        ident = record["puzzle_id"]
        if ident in originals:
            raise ValueError("original advanced workbook puzzle IDs collide")
        originals[ident] = (
            record["fen_before_opponent_move"],
            record["uci_moves_opponent_first"].split(),
            record["puzzle_rating"],
        )
    blocks = [
        Heading(text=data["title"][language], level=1,
                source_anchor="section37:master-workbook:title"),
        Paragraph(text=data["editorial_statement"][language],
                  source_anchor="section37:master-workbook:license"),
        Paragraph(text=data["level"][language],
                  source_anchor="section37:master-workbook:level"),
        Paragraph(text=data["position_contract"][language],
                  source_anchor="section37:master-workbook:position-contract"),
    ]
    cases = []
    used = set()
    for lesson in data["lessons"]:
        name = lesson["lesson_id"]
        source_id = lesson["original_puzzle_id"]
        original = originals.get(source_id)
        original_moves = [lesson["opponent_previous_move_uci"]] + lesson["solution_after_opponent_uci"]
        if (
            not name.startswith("S37-") or name in used
            or original is None
            or original[0] != lesson["fen_before_opponent_move"]
            or original[1] != original_moves
            or original[2] != lesson["rating_lichess_puzzle"]
            or original[2] < 2200
            or lesson["composer_study"] is not False
            or not lesson["solution_after_opponent_uci"]
        ):
            raise ValueError("Section37 original bilingual master workbook source changed")
        used.add(name)
        board = Board(original[0])
        before = board.fen()
        board.push_text(original_moves[0])
        solver_fen = board.fen()
        for san_or_uci in original_moves[1:]:
            board.push_text(san_or_uci)
        blocks.extend((
            Heading(
                text=name + " — " + lesson[language]["title"],
                level=2,
                source_anchor="section37:master-workbook:" + name + ":heading",
            ),
            Position(
                fen=before,
                caption=("Position before opponent move" if language == "en"
                       else "Позиція перед ходом суперника"),
                source_anchor="section37:master-workbook:" + name + ":original-position",
            ),
            Paragraph(
                text=("Opponent's preceding move: " if language == "en" else
                      "Попередній хід суперника: ") + original_moves[0],
                source_anchor="section37:master-workbook:" + name + ":opponent-move",
            ),
            Exercise(
                fen=solver_fen,
                prompt=lesson[language]["prompt"],
                answer_text=original_moves[1],
                difficulty=f"Lichess {original[2]} puzzle rating (not FIDE Elo)",
                source_anchor="section37:master-workbook:" + name + ":exercise",
            ),
        ))
        cases.append((
            name, source_id, original[2], before,
            solver_fen, tuple(original_moves[1:]),
        ))
    blocks.append(Heading(
        text=("Solutions — review only after calculating" if language == "en"
              else "Розв'язання — лише після самостійного розрахунку"),
        level=2, source_anchor="section37:master-workbook:solutions",
    ))
    for name, _, _, _, _, solution in cases:
        blocks.append(Paragraph(
            text=name + ": " + " ".join(solution),
            source_anchor="section37:master-workbook:solution:" + name,
        ))
    document = BookDocument(
        title=data["title"][language],
        author="Accessible Chess original educational narrative; Lichess CC0 positions",
        language=language,
        source_name="Canonical Section37 original bilingual 12-lesson source",
        source_rights="Original project-authored text plus separately pinned original Lichess CC0 puzzle data; not copyrighted publisher book",
        blocks=blocks,
    )
    BookDocument.from_dict(document.as_dict())
    if len(document.exercises()) != 12:
        raise ValueError("genuine source37 workbook Exercises not published")
    return document, tuple(cases)
