"""Bundled original Section37 twelve-lesson bilingual master workbook.

This is the immutable original project-authored Section37 source mirrored for
offline packaged Books. The Git-blob digest must equal the canonical
tests/real_corpus/advanced_training/section37_master_workbook_bilingual.json
source. No tests/ path, network, extra router/parser or provider needed in EXE.
Original 20 actual CC0 chess positions are validated against the existing
embedded 16 + 4 Lichess records before any BookDocument is published.
"""
from __future__ import annotations

import hashlib
import json

from .bookdocument import BookDocument, Heading, Paragraph, Position, Exercise
from .chesscore import Board
from .section40_advanced_licensed_dataset import bundled_advanced_puzzles
from .section40_extreme_licensed_dataset import bundled_extreme_puzzles

MATERIAL_ID = "section37-advanced-twelve-bilingual-source-workbook"
BOOK_KEY_PREFIX = "section40:advanced-twelve-source37-workbook"
ORIGINAL_SOURCE_GIT_BLOB = "b836b763f814087d45c2a3481cd9bcb22d13be05"
ORIGINAL_SOURCE_PATH = "tests/real_corpus/advanced_training/section37_master_workbook_bilingual.json"
_ORIGINAL_SOURCE_TEXT = "{\n  \"schema\": \"accessible-chess-advanced-bilingual-source-v1\",\n  \"language_codes\": [\n    \"uk\",\n    \"en\"\n  ],\n  \"title\": {\n    \"uk\": \"Майстерська шахова лабораторія: 12 складних позицій\",\n    \"en\": \"Advanced Chess Laboratory: 12 Critical Positions\"\n  },\n  \"editorial_statement\": {\n    \"uk\": \"Оригінальні двомовні навчальні завдання на реальних позиціях Lichess CC0. Це не переклад захищених шахових книг і не збірник авторських етюдів.\",\n    \"en\": \"New bilingual training prompts built on real Lichess CC0 positions. This is neither a translation of copyrighted books nor a collection of composed studies.\"\n  },\n  \"level\": {\n    \"uk\": \"Лише після I розряду: КМС, майстерська та дуже складна підготовка. Рейтинг задач Lichess не є Ело ФІДЕ.\",\n    \"en\": \"First category and above: candidate-master, master-track and extreme calculation. Lichess puzzle rating is not FIDE Elo.\"\n  },\n  \"position_contract\": {\n    \"uk\": \"Дана FEN-позиція стоїть ДО попереднього ходу суперника. Застосуй цей хід на канонічній дошці, потім шукай власне рішення. Не відкривай розв'язок до самостійної спроби.\",\n    \"en\": \"The FEN is BEFORE the opponent's previous move. Play that move on the canonical chessboard first, then solve. Do not reveal the solution before an independent attempt.\"\n  },\n  \"rights\": \"Original new instructional prose for CC0 chess positions; redistribution of this authored bilingual workbook permitted; attribution to Lichess retained; no third-party proprietary books bundled.\",\n  \"level_floor_lichess_puzzle_rating\": 2200,\n  \"studies_scope\": \"Not an authored composition book; true composed studies are separate bibliography pending licensed material\",\n  \"lessons\": [\n    {\n      \"lesson_id\": \"S37-01\",\n      \"category\": \"calculation\",\n      \"original_puzzle_id\": \"00Ns0\",\n      \"rating_lichess_puzzle\": 2539,\n      \"fen_before_opponent_move\": \"r2qr1k1/pn1p2pp/bp3p2/2p1N3/2P5/1PB3Q1/P1P3PP/R4RK1 w - - 0 18\",\n      \"opponent_previous_move_uci\": \"f1f6\",\n      \"solution_after_opponent_uci\": [\n        \"d8f6\",\n        \"a1f1\",\n        \"f6h6\",\n        \"e5g4\",\n        \"h6g6\",\n        \"c3g7\",\n        \"e8e4\",\n        \"g4f6\",\n        \"g8g7\"\n      ],\n      \"original_lichess_themes\": [\n        \"advantage\",\n        \"hangingPiece\",\n        \"intermezzo\",\n        \"middlegame\",\n        \"veryLong\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Міжходи, форсованість і захист\",\n        \"prompt\": \"Визнач три ходи-кандидати. Після відповіді суперника порахуй кожну форсовану гілку до тихої стабілізації. Порівняй проміжний хід із прямою реалізацією.\"\n      },\n      \"en\": {\n        \"title\": \"Intermediate moves, forcing lines and defence\",\n        \"prompt\": \"Find three candidate moves. Calculate every forcing branch through the defender's strongest reply until a quiet stabilization. Compare intermediate moves with direct conversion.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-02\",\n      \"category\": \"calculation\",\n      \"original_puzzle_id\": \"00KNB\",\n      \"rating_lichess_puzzle\": 2627,\n      \"fen_before_opponent_move\": \"2rr2k1/5p2/4p2p/4N1pQ/1p3P2/4P3/np3P1P/2q2BRK b - - 1 32\",\n      \"opponent_previous_move_uci\": \"c8c7\",\n      \"solution_after_opponent_uci\": [\n        \"h5h6\",\n        \"b2b1q\",\n        \"h6g5\"\n      ],\n      \"original_lichess_themes\": [\n        \"crushing\",\n        \"kingsideAttack\",\n        \"master\",\n        \"middlegame\",\n        \"pin\",\n        \"short\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Розрахунок за взаємних загроз\",\n        \"prompt\": \"Перевір усі шахи, взяття й загрози; знайди тактичний ресурс захисника. Визнач, чи працює ідея за найкращої відповіді.\"\n      },\n      \"en\": {\n        \"title\": \"Calculation under mutual threats\",\n        \"prompt\": \"Check every forcing check, capture and threat; identify the defender's tactical resource. Decide whether the idea survives best defence.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-03\",\n      \"category\": \"combination\",\n      \"original_puzzle_id\": \"00LRq\",\n      \"rating_lichess_puzzle\": 2291,\n      \"fen_before_opponent_move\": \"1k6/1p1q4/P2p3p/1NpPpn1Q/5b2/2P3r1/1P2B1P1/R6K b - - 3 28\",\n      \"opponent_previous_move_uci\": \"g3g7\",\n      \"solution_after_opponent_uci\": [\n        \"a6a7\",\n        \"b8a8\",\n        \"b5c7\",\n        \"d7c7\",\n        \"h5e8\",\n        \"c7b8\",\n        \"a7b8q\"\n      ],\n      \"original_lichess_themes\": [\n        \"advancedPawn\",\n        \"doubleCheck\",\n        \"mate\",\n        \"mateIn4\",\n        \"middlegame\",\n        \"promotion\",\n        \"queensideAttack\",\n        \"sacrifice\",\n        \"veryLong\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Комбінація з перетворенням та жертвою\",\n        \"prompt\": \"Досліди не лише головну форсовану лінію, а й відхилення короля, зустрічні шахи та альтернативи перетворення пішака.\"\n      },\n      \"en\": {\n        \"title\": \"Sacrifice and promotion combination\",\n        \"prompt\": \"Explore the forcing line, king deviations, counter-checks and alternative pawn promotions rather than stopping at the first attractive move.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-04\",\n      \"category\": \"combination\",\n      \"original_puzzle_id\": \"00LZf\",\n      \"rating_lichess_puzzle\": 2205,\n      \"fen_before_opponent_move\": \"r1b1kb1r/pppp1ppp/2n1p3/3nN3/3P2q1/4B3/PPP1BPPP/RN1Q1RK1 b kq - 9 8\",\n      \"opponent_previous_move_uci\": \"d5e3\",\n      \"solution_after_opponent_uci\": [\n        \"f2e3\",\n        \"g4g5\",\n        \"e5f7\",\n        \"g5e3\",\n        \"g1h1\"\n      ],\n      \"original_lichess_themes\": [\n        \"advantage\",\n        \"attackingF2F7\",\n        \"fork\",\n        \"long\",\n        \"opening\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Контрудар у дебюті\",\n        \"prompt\": \"Після останнього ходу суперника оцінюй його найнебезпечнішу загрозу. Побудуй дерево кандидатів і назви позиційні наслідки тактичного вибору.\"\n      },\n      \"en\": {\n        \"title\": \"Counterattack in the opening\",\n        \"prompt\": \"After the opponent's last move, identify the most urgent threat. Build a candidate-move tree and explain the positional consequences of the tactical decision.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-05\",\n      \"category\": \"opening\",\n      \"original_puzzle_id\": \"00M7w\",\n      \"rating_lichess_puzzle\": 2274,\n      \"fen_before_opponent_move\": \"r1b1k2r/ppp2ppp/2n5/2bBp3/2Pq4/3P1QP1/P2B1P1P/1R2K1NR b Kkq - 2 12\",\n      \"opponent_previous_move_uci\": \"f7f6\",\n      \"solution_after_opponent_uci\": [\n        \"g1e2\",\n        \"d4f2\",\n        \"f3f2\",\n        \"c5f2\",\n        \"e1f2\"\n      ],\n      \"original_lichess_themes\": [\n        \"crushing\",\n        \"long\",\n        \"opening\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Дебютний центр і темп розвитку\",\n        \"prompt\": \"Перевір, чи тактичне продовження виправдане перевагою в розвитку. Порівняй природний захист із форсованим варіантом.\"\n      },\n      \"en\": {\n        \"title\": \"Opening central tension and tempi\",\n        \"prompt\": \"Determine whether development justifies the tactical continuation. Compare natural defence with the critical forcing line.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-06\",\n      \"category\": \"opening\",\n      \"original_puzzle_id\": \"00LZf\",\n      \"rating_lichess_puzzle\": 2205,\n      \"fen_before_opponent_move\": \"r1b1kb1r/pppp1ppp/2n1p3/3nN3/3P2q1/4B3/PPP1BPPP/RN1Q1RK1 b kq - 9 8\",\n      \"opponent_previous_move_uci\": \"d5e3\",\n      \"solution_after_opponent_uci\": [\n        \"f2e3\",\n        \"g4g5\",\n        \"e5f7\",\n        \"g5e3\",\n        \"g1h1\"\n      ],\n      \"original_lichess_themes\": [\n        \"advantage\",\n        \"attackingF2F7\",\n        \"fork\",\n        \"long\",\n        \"opening\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Неповнота розвитку та конкретика\",\n        \"prompt\": \"Зваж загрози королю й фігурам перед обговоренням дебютної оцінки. Не називай варіант виграним без перевірки ходів.\"\n      },\n      \"en\": {\n        \"title\": \"Development deficits and concrete lines\",\n        \"prompt\": \"Evaluate king safety and hanging pieces before assigning an opening verdict. Do not call a variation winning without checking the concrete moves.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-07\",\n      \"category\": \"middlegame\",\n      \"original_puzzle_id\": \"00GWg\",\n      \"rating_lichess_puzzle\": 2243,\n      \"fen_before_opponent_move\": \"1r1r2k1/pp4pp/2nNb3/2R2p2/2P1p3/8/P4PPP/3BR1K1 w - - 1 26\",\n      \"opponent_previous_move_uci\": \"d6b7\",\n      \"solution_after_opponent_uci\": [\n        \"b8b7\",\n        \"c5c6\",\n        \"b7b1\",\n        \"g1f1\",\n        \"d8d1\",\n        \"e1d1\",\n        \"b1d1\",\n        \"f1e2\",\n        \"e6d7\"\n      ],\n      \"original_lichess_themes\": [\n        \"crushing\",\n        \"middlegame\",\n        \"veryLong\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Ініціатива й активність важких фігур\",\n        \"prompt\": \"Склади позиційний план, а потім перевір його тактично. Особливу увагу приділи другій горизонталі, зв'язкам та відкритим лініям.\"\n      },\n      \"en\": {\n        \"title\": \"Initiative and heavy-piece activity\",\n        \"prompt\": \"Form a positional plan, then test it concretely. Pay attention to rank penetration, pins and open files.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-08\",\n      \"category\": \"middlegame\",\n      \"original_puzzle_id\": \"004Ys\",\n      \"rating_lichess_puzzle\": 2233,\n      \"fen_before_opponent_move\": \"r4rk1/3q1pbp/p1n1p1p1/2p3NP/1p3B2/3P3Q/PPP3P1/R3R1K1 b - - 2 19\",\n      \"opponent_previous_move_uci\": \"d7d4\",\n      \"solution_after_opponent_uci\": [\n        \"f4e3\",\n        \"d4f6\",\n        \"e1f1\",\n        \"f6e5\",\n        \"h5g6\",\n        \"e5e3\",\n        \"h3e3\"\n      ],\n      \"original_lichess_themes\": [\n        \"advantage\",\n        \"defensiveMove\",\n        \"middlegame\",\n        \"veryLong\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Ресурси захисту під атакою\",\n        \"prompt\": \"Побудуй список реальних загроз, знайди кандидатні захисні ходи й оціни, чи зберігається ініціатива після точного захисту.\"\n      },\n      \"en\": {\n        \"title\": \"Defensive resources under attack\",\n        \"prompt\": \"List concrete threats, find defensive candidate moves and evaluate whether initiative persists against accurate resistance.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-09\",\n      \"category\": \"endgame\",\n      \"original_puzzle_id\": \"00H2L\",\n      \"rating_lichess_puzzle\": 2351,\n      \"fen_before_opponent_move\": \"8/8/2p2p2/p4P1p/Pk5P/4K1P1/8/8 w - - 1 39\",\n      \"opponent_previous_move_uci\": \"e3d3\",\n      \"solution_after_opponent_uci\": [\n        \"c6c5\",\n        \"d3e2\",\n        \"c5c4\",\n        \"g3g4\",\n        \"h5g4\"\n      ],\n      \"original_lichess_themes\": [\n        \"crushing\",\n        \"endgame\",\n        \"long\",\n        \"pawnEndgame\",\n        \"quietMove\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Тихий темп у пішаковому закінченні\",\n        \"prompt\": \"Порахуй пішакові прориви й королівські маршрути. Перевір цугцванг після кожної відповіді, не застосовуючи шаблонного правила без розрахунку.\"\n      },\n      \"en\": {\n        \"title\": \"Quiet tempo in a pawn ending\",\n        \"prompt\": \"Calculate pawn breaks and king routes. Test zugzwang after every defender's reply instead of assuming a textbook rule settles the position.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-10\",\n      \"category\": \"endgame\",\n      \"original_puzzle_id\": \"00FHO\",\n      \"rating_lichess_puzzle\": 2233,\n      \"fen_before_opponent_move\": \"8/1pp5/p2p3p/3P1Pk1/P3K1P1/1P5R/8/2r5 w - - 1 39\",\n      \"opponent_previous_move_uci\": \"e4f3\",\n      \"solution_after_opponent_uci\": [\n        \"c1c3\",\n        \"f3g2\",\n        \"c3h3\",\n        \"g2h3\",\n        \"h6h5\",\n        \"g4h5\",\n        \"g5h5\"\n      ],\n      \"original_lichess_themes\": [\n        \"crushing\",\n        \"endgame\",\n        \"rookEndgame\",\n        \"veryLong\"\n      ],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Ладейна активність і контргра\",\n        \"prompt\": \"Оціни активність короля, відсічні лінії та прохідні пішаки. Шукай ресурси захисту в довгому варіанті.\"\n      },\n      \"en\": {\n        \"title\": \"Rook activity and counterplay\",\n        \"prompt\": \"Evaluate king activity, cut-off ranks and passed pawns. Search for counterplay in the full long variation.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-11\",\n      \"category\": \"extreme\",\n      \"original_puzzle_id\": \"NgGRN\",\n      \"rating_lichess_puzzle\": 3164,\n      \"fen_before_opponent_move\": \"7Q/rpk2p1p/p2b4/q1pp4/3P2b1/2P1P3/PP3PPP/R3K2R b KQ - 0 17\",\n      \"opponent_previous_move_uci\": \"c5d4\",\n      \"solution_after_opponent_uci\": [\n        \"h8d4\",\n        \"g4h5\",\n        \"g2g4\",\n        \"h5g6\",\n        \"d4a7\",\n        \"d6c5\",\n        \"b2b4\",\n        \"c5b4\",\n        \"e1g1\",\n        \"b4c5\",\n        \"a7a8\"\n      ],\n      \"original_lichess_themes\": [],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Екстремальна тактика: форсований розрахунок\",\n        \"prompt\": \"Сформулюй щонайменше три кандидати та заперечення суперника. Не підглядай відповідь, перевір можливу тактичну пастку.\"\n      },\n      \"en\": {\n        \"title\": \"Extreme calculation: forcing tactical play\",\n        \"prompt\": \"Write down at least three candidate moves and the opponent's refutations. Work without seeing the answer; test possible tactical traps.\"\n      }\n    },\n    {\n      \"lesson_id\": \"S37-12\",\n      \"category\": \"extreme\",\n      \"original_puzzle_id\": \"gWyMk\",\n      \"rating_lichess_puzzle\": 3166,\n      \"fen_before_opponent_move\": \"r1b2r1k/1p5P/1n1pp2B/1Pp2p1B/4P2q/P2P2b1/1P2Q2P/R4R1K b - - 1 20\",\n      \"opponent_previous_move_uci\": \"f8f6\",\n      \"solution_after_opponent_uci\": [\n        \"h6f4\",\n        \"g3h2\",\n        \"e2h2\",\n        \"h4h2\",\n        \"h1h2\"\n      ],\n      \"original_lichess_themes\": [],\n      \"original_source\": \"Lichess CC0 puzzle source, see repository registered SHA256\",\n      \"composer_study\": false,\n      \"uk\": {\n        \"title\": \"Екстремальна тактика: 3166\",\n        \"prompt\": \"Розрахуй найжорсткішу лінію до кінця, порівняй із двома спокусливими помилковими варіантами й поясни роль усіх незахищених фігур.\"\n      },\n      \"en\": {\n        \"title\": \"Extreme tactic: 3166\",\n        \"prompt\": \"Calculate the critical line to completion, compare it with two tempting false lines and account for every loose piece.\"\n      }\n    }\n  ]\n}\n"


def _canonical_source() -> dict:
    raw = _ORIGINAL_SOURCE_TEXT.encode("utf-8")
    digest = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\\0" + raw).hexdigest()
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
                title=("Position before opponent move" if language == "en"
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
