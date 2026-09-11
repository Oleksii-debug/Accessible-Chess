from __future__ import annotations

"""P0-F quality layer for the built-in Ukrainian Books/Training starter corpus.

This module does not introduce another chess, Books, or Training engine. It expands
existing project-authored tutorial material into substantial self-contained learning
materials and derives position-specific exercises through the canonical ``Board``.
"""

from dataclasses import dataclass

from .bookdocument import BookDocument, Diagram, Exercise, Heading, ListBlock, Paragraph, VariationTree
from .chesscore import Board, Move
from .squares import square_name
from .starter_books_training_content import STARTER_CONTENT_LANGUAGE, build_starter_materials


STARTER_QUALITY_SCHEMA_VERSION = 2
STARTER_QUALITY_LICENSE_ID = "CC-BY-4.0"
STARTER_QUALITY_LICENSE_NAME = "Creative Commons Attribution 4.0 International"
STARTER_QUALITY_ATTRIBUTION = "Accessible Chess project"
STARTER_QUALITY_LICENSE_TERMS = (
    "Project-authored starter Books/Training content is distributed under CC-BY-4.0: "
    "copying, redistribution and adaptation are permitted with attribution to the "
    "Accessible Chess project; no warranty is provided."
)
STARTER_QUALITY_SOURCE_NAME = "Accessible Chess project-authored Ukrainian starter corpus"
STARTER_QUALITY_COURSE_KEY = "accessible-chess-v2-starter-uk-v2"
MIN_SUBSTANTIAL_WORDS = 500


@dataclass(frozen=True, slots=True)
class PositionSeed:
    seed_id: str
    title: str
    goal: str
    opening_moves: tuple[str, ...] = ()
    fen: str | None = None


def _opening(seed_id: str, title: str, goal: str, *moves: str) -> PositionSeed:
    return PositionSeed(seed_id, title, goal, tuple(moves), None)


def _fen(seed_id: str, title: str, goal: str, fen: str) -> PositionSeed:
    return PositionSeed(seed_id, title, goal, (), fen)


_POSITION_SEEDS: tuple[PositionSeed, ...] = (
    _opening("start", "Початкова позиція", "координати, розвиток і контроль центру"),
    _opening("e4", "Після 1.e4", "відкрити лінії та відповісти на центральний хід", "e2e4"),
    _opening("d4", "Після 1.d4", "побудувати стійкий пішаковий центр", "d2d4"),
    _opening("c4", "Після 1.c4", "контролювати центр фланговим пішаком", "c2c4"),
    _opening("nf3", "Після 1.Nf3", "розвинути фігуру без раннього зобов'язання пішакової структури", "g1f3"),
    _opening("open-game", "Відкрита гра", "розвивати фігури після симетричного центру", "e2e4", "e7e5"),
    _opening("sicilian", "Сицилійська структура", "працювати з асиметричним центром", "e2e4", "c7c5"),
    _opening("french", "Французька структура", "планувати гру проти ланцюга e4-e6", "e2e4", "e7e6"),
    _opening("caro-kann", "Каро-Канн", "підготувати ...d5 без блокування слона c8", "e2e4", "c7c6"),
    _opening("queen-pawn", "Ферзевий пішак", "розвиватися після симетричного d-пішакового центру", "d2d4", "d7d5"),
    _opening("indian", "Індійський початок", "контролювати e4 та d5 фігурами", "d2d4", "g8f6"),
    _opening("english", "Англійський початок", "оцінювати простір після c4-e5", "c2c4", "e7e5"),
    _opening("reti", "Реті", "поєднати розвиток коня з тиском на центр", "g1f3", "d7d5"),
    _opening("open-nf3", "Відкрита гра після Nf3", "розвивати фігури з темпом на e5", "e2e4", "e7e5", "g1f3"),
    _opening("sicilian-nf3", "Сицилійська після Nf3", "підготувати d4 або іншу центральну операцію", "e2e4", "c7c5", "g1f3"),
    _opening("qgambit", "Ферзевий гамбіт", "тиснути на d5 ходом c4", "d2d4", "d7d5", "c2c4"),
    _opening("nimzo-shell", "Індійська структура після c4", "розвиватися проти контролю e4", "d2d4", "g8f6", "c2c4"),
    _opening("ruy-nc6", "Відкрита гра після ...Nc6", "підсилити тиск на e5", "e2e4", "e7e5", "g1f3", "b8c6"),
    _opening("ruy-bb5", "Іспанська побудова", "зв'язати розвиток із тиском на захисника e5", "e2e4", "e7e5", "g1f3", "b8c6", "f1b5"),
    _opening("sicilian-d6", "Сицилійська з ...d6", "підготувати центральне d4 та безпечний розвиток", "e2e4", "c7c5", "g1f3", "d7d6"),
    _fen("rook", "Тура на відкритій дошці", "лінійний рух тури та безпека короля", "4k3/8/8/8/8/8/4K3/R7 w - - 0 1"),
    _fen("bishop", "Слон і діагоналі", "далекобійний контроль діагоналей", "4k3/8/8/8/8/8/4K3/2B5 w - - 0 1"),
    _fen("knight", "Кінь у центрі", "стрибки коня та контроль центральних полів", "4k3/8/8/8/8/2N5/4K3/8 w - - 0 1"),
    _fen("queen", "Ферзь на відкритій дошці", "поєднання горизонталей, вертикалей і діагоналей", "4k3/8/8/8/8/8/4K3/3Q4 w - - 0 1"),
    _fen("pawn-endgame", "Пішаковий ендшпіль", "пішакові контакти, король і темп", "4k3/8/8/3p4/4P3/8/4K3/8 w - - 0 1"),
    _fen("castling", "Позиція для рокіровки", "перевірити права рокіровки та безпечні королівські ходи", "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"),
    _fen("promotion", "Перетворення пішака", "побачити варіанти перетворення та королівську безпеку", "7k/4P3/8/8/8/8/4K3/8 w - - 0 1"),
)


_PIECE_UA = {
    "P": "пішаком",
    "N": "конем",
    "B": "слоном",
    "R": "турою",
    "Q": "ферзем",
    "K": "королем",
}


def _uci(move: Move) -> str:
    suffix = (move.promotion or "").lower()
    return f"{square_name(move.frm)}{square_name(move.to)}{suffix}"


def _board_for_seed(seed: PositionSeed) -> Board:
    if seed.fen is not None:
        return Board(seed.fen)
    board = Board()
    for move_text in seed.opening_moves:
        board.push_text(move_text)
    return board


def _select_five_moves(board: Board) -> tuple[Move, ...]:
    legal = sorted(board.legal_moves(), key=_uci)
    if len(legal) < 5:
        raise ValueError("starter position must expose at least five legal moves")
    selected: list[Move] = []
    seen_piece_types: set[str] = set()
    for move in legal:
        piece = board.board[move.frm]
        piece_type = piece.upper() if piece else "?"
        if piece_type not in seen_piece_types:
            selected.append(move)
            seen_piece_types.add(piece_type)
        if len(selected) == 5:
            return tuple(selected)
    for move in legal:
        if move not in selected:
            selected.append(move)
        if len(selected) == 5:
            return tuple(selected)
    raise AssertionError("unreachable: legal move count changed during selection")


def _variation_pgn(board: Board, move: Move) -> str:
    prefix = f"{board.fullmove}." if board.turn == "w" else f"{board.fullmove}..."
    return f'[SetUp "1"]\n[FEN "{board.fen()}"]\n\n{prefix} {board.san(move)} *'


def _base_text(material: BookDocument) -> tuple[list[str], list[tuple[str, str]]]:
    paragraphs = [block.text for block in material.blocks if isinstance(block, Paragraph)]
    checks = [
        (block.prompt, block.answer_text or "")
        for block in material.blocks
        if isinstance(block, Exercise)
    ]
    if len(paragraphs) < 3 or len(checks) < 5:
        raise ValueError("legacy starter material no longer has the expected authored seed content")
    return paragraphs[:3], checks[:5]


def _expanded_paragraphs(title: str, seed: PositionSeed, originals: list[str], checks: list[tuple[str, str]]) -> list[str]:
    q1, q2, q3, q4, q5 = (item[0] for item in checks)
    a1, a2, a3, a4, a5 = (item[1] for item in checks)
    p1, p2, p3 = originals
    return [
        f"Мета матеріалу «{title}» — дати завершений робочий цикл: зрозуміти правило, знайти його на позиції, виконати хід клавіатурою та перевірити результат у канонічному стані дошки. {p1} Цю тезу треба не лише запам'ятати, а вміти застосувати без візуальної підказки. Перед кожним рішенням назви сторону ходу, ключові поля та фігури, а після ходу перевір, що позиція змінилася саме очікуваним способом. Такий порядок однаково корисний у звичайній партії, PGN, Training і під час роботи з NVDA.",
        f"Ключова ідея теми розкривається через зв'язок правил і простору. {p2} Для практики розділяй завдання на три короткі питання: що атаковано зараз, що зміниться після мого ходу і чи не залишиться власний король під шахом. Якщо відповідь невпевнена, повернися до координат та перерахуйте можливі поля системно, а не навмання. У навчальній позиції «{seed.title}» цей метод використовується для мети: {seed.goal}. Він дисциплінує розрахунок і не залежить від кольору клітин або розташування елементів на екрані.",
        f"Практичний алгоритм починається з повного читання позиції. {p3} Спочатку встанови, чия черга ходу; далі знайди королів, активні фігури та пішакові контакти; потім сформуй два або три законні кандидати. Для кожного кандидата перевір маршрут фігури, зайняті поля, можливе взяття, шах власному королю та наслідок для важливих полів. Лише після цього вводь координатний або SAN-хід. Якщо програма відхилила хід, не виправляй його випадково: повторно прочитай початкове й цільове поле та визнач, яке саме правило було порушено.",
        f"Тема має бути корисною не лише як текст. У позиції «{seed.title}» тренування прив'язане до реального FEN і до legal-move contract спільного chess core. Завдання не підміняє шаховий сенс довільною відповіддю: prompt описує конкретну фігуру та конкретне переміщення у поточній позиції, а відповідь перевіряється тим самим Board, що використовується продуктом. П'ять вправ у цьому матеріалі дають кілька законних напрямків і змушують працювати з фактичним станом дошки. Це робить вправу відтворюваною, придатною для клавіатури та незалежною від мережі.",
        f"Самоперевірка потрібна для понять, які не зводяться до одного ходу. Питання «{q1}» має відповідь «{a1}», а «{q2}» — «{a2}». Поясни кожну відповідь власними словами і знайди на дошці приклад, який її підтверджує. Далі перевір «{q3}» — «{a3}». Якщо відповідь правильна лише на пам'ять, але ти не можеш показати відповідне поле, лінію або фігуру, тема ще не завершена. Мета — з'єднати термін, координату, позицію та legal move в одну послідовність дій.",
        f"Типові помилки у темі «{title}» виникають, коли гравець бачить одну локальну деталь і перестає перевіряти всю позицію. Контрольні питання «{q4}» — «{a4}» та «{q5}» — «{a5}» нагадують, що навіть простий факт треба співвіднести з поточним станом. Не плутай атаку з легальним ходом, не припускай, що далекобійна фігура може перестрибнути блокер, і не ігноруй шах власному королю. У пішакових ситуаціях окремо перевір напрямок руху, взяття, перетворення та en passant. У королівських — суміжність королів і атаковані поля.",
        f"Клавіатурний сценарій має бути передбачуваним. Спочатку сфокусуй дошку або поле введення ходу, прочитай поточну позицію, введи хід і дочекайся детермінованого результату. Для screen reader важливі змістовні назви полів і стан після дії, а не колір або анімація. Якщо переміщення не відбулося, збережи початковий стан і повтори перевірку без миші. У цьому матеріалі координатні відповіді спеціально придатні для такого маршруту: вони однозначно задають початкове та цільове поле і проходять canonical `Board.parse_move` перед публікацією Training.",
        f"Зв'язок із PGN, FEN і GameTree допомагає переносити навичку між поверхнями програми. FEN описує позицію до вправи, PGN або SAN описує шаховий хід, а GameTree зберігає основну лінію та варіанти. Коли відкриваєш навчальну позицію, спочатку звір FEN-стан, потім виконай один із вправних ходів і уяви, як він буде записаний у PGN. Для «{seed.title}» така процедура показує, що одна й та сама шахова істина не повинна розходитись між Books, Training, дошкою, Library чи експортом.",
        f"Закріплення теми варто робити короткими серіями. Виконай п'ять позиційних вправ матеріалу без миші, після кожної назви фігуру, поле старту, поле призначення і причину легальності. Потім повернися до п'яти текстових самоперевірок та поясни відповіді без підказки. Якщо помилка повторюється, сформулюй її як правило: наприклад, «не перевірив блокер», «переплутав сторону ходу» або «не перевірив шах». Такий журнал причин корисніший за механічне повторення, бо наступного разу ти перевіряєш конкретний ризик до введення ходу.",
        f"Матеріал вважається завершеним, коли ти можеш відтворити головне правило теми «{title}», впевнено прочитати навчальну позицію «{seed.title}», виконати всі п'ять legal-move вправ і пояснити, чому кожен хід дозволений. Додатковий критерій — вміти описати ту саму ситуацію через координати та FEN/PGN терміни без посилання на візуальне розташування. Після цього переходь до наступної теми, але повертайся до попередньої через інтервали. Саме поєднання змісту, позиції, клавіатури та перевірки робить курс практичним, а не просто набором коротких довідкових абзаців.",
    ]


def _build_material(index: int, base: BookDocument, seed: PositionSeed) -> BookDocument:
    originals, checks = _base_text(base)
    board = _board_for_seed(seed)
    moves = _select_five_moves(board)
    material_id = f"starter-material-{index + 1:02d}"
    paragraphs = _expanded_paragraphs(base.title, seed, originals, checks)
    blocks = [
        Heading(text=base.title, level=1, block_id=f"{material_id}-heading", source_anchor=f"{material_id}:heading"),
        *[
            Paragraph(text=text, block_id=f"{material_id}-p-{paragraph_index + 1:02d}", source_anchor=f"{material_id}:paragraph:{paragraph_index + 1}")
            for paragraph_index, text in enumerate(paragraphs)
        ],
        ListBlock(
            items=[f"{question} — {answer}" for question, answer in checks],
            ordered=True,
            block_id=f"{material_id}-self-check",
            source_anchor=f"{material_id}:self-check",
        ),
        Diagram(
            fen=board.fen(),
            caption=f"Навчальна позиція: {seed.title}",
            side_to_move_note="Знайди сторону ходу з FEN перед виконанням вправи.",
            alt_text=f"Шахова позиція для теми «{base.title}»: {seed.title}; мета — {seed.goal}.",
            block_id=f"{material_id}-diagram",
            source_anchor=f"{material_id}:diagram",
        ),
        VariationTree(
            root_fen=board.fen(),
            pgn=_variation_pgn(board, moves[0]),
            title=f"Базовий варіант: {seed.title}",
            block_id=f"{material_id}-variation",
            source_anchor=f"{material_id}:variation",
        ),
    ]
    for exercise_index, move in enumerate(moves, start=1):
        piece = board.board[move.frm]
        piece_name = _PIECE_UA[(piece or "P").upper()]
        start = square_name(move.frm)
        target = square_name(move.to)
        prompt = (
            f"{seed.goal.capitalize()}. Вправа {exercise_index}: у позиції «{seed.title}» "
            f"виконайте законний хід {piece_name} з {start} на {target}. "
            "Перед введенням перевірте сторону ходу, шлях фігури та безпеку власного короля."
        )
        blocks.append(
            Exercise(
                fen=board.fen(),
                prompt=prompt,
                answer_text=_uci(move),
                difficulty="початковий-середній",
                block_id=f"{material_id}-exercise-{exercise_index:02d}",
                source_anchor=f"{material_id}:exercise:{exercise_index}",
            )
        )

    document = BookDocument(
        title=base.title,
        blocks=blocks,
        language=STARTER_CONTENT_LANGUAGE,
        author=STARTER_QUALITY_ATTRIBUTION,
        source_name=STARTER_QUALITY_SOURCE_NAME,
        source_uri=f"urn:accessible-chess:starter:{material_id}",
        source_rights=f"{STARTER_QUALITY_LICENSE_ID}: {STARTER_QUALITY_LICENSE_TERMS}",
    )
    document.as_dict()
    return document


def build_substantial_starter_materials() -> tuple[BookDocument, ...]:
    base_materials = tuple(build_starter_materials())
    if len(base_materials) != len(_POSITION_SEEDS):
        raise ValueError("starter material/position seed counts must stay aligned")
    return tuple(
        _build_material(index, base, seed)
        for index, (base, seed) in enumerate(zip(base_materials, _POSITION_SEEDS, strict=True))
    )


def build_p0f_starter_course() -> BookDocument:
    materials = build_substantial_starter_materials()
    blocks = [
        Heading(text="Accessible Chess: стартовий курс", level=1, block_id="starter-quality-course-heading", source_anchor="starter-quality:heading"),
        Paragraph(
            text=(
                "Цей автономний український курс складається з 27 самодостатніх навчальних матеріалів. "
                "Кожен матеріал містить розгорнуте пояснення, семантичну діаграму, варіант і п'ять "
                "позиційних вправ, які проходять через той самий canonical Board і Training, що й "
                "імпортований користувацький контент. Курс не потребує мережі або ручного пошуку файлів."
            ),
            block_id="starter-quality-course-intro",
            source_anchor="starter-quality:intro",
        ),
    ]
    for material_index, material in enumerate(materials, start=1):
        blocks.append(
            Heading(
                text=f"Матеріал {material_index}: {material.title}",
                level=2,
                block_id=f"starter-quality-course-material-{material_index:02d}",
                source_anchor=f"starter-quality:material:{material_index}",
            )
        )
        blocks.extend(material.blocks[1:])

    course = BookDocument(
        title="Accessible Chess: стартовий курс",
        blocks=blocks,
        language=STARTER_CONTENT_LANGUAGE,
        author=STARTER_QUALITY_ATTRIBUTION,
        source_name=STARTER_QUALITY_SOURCE_NAME,
        source_uri="urn:accessible-chess:starter:course:v2",
        source_rights=f"{STARTER_QUALITY_LICENSE_ID}: {STARTER_QUALITY_LICENSE_TERMS}",
    )
    course.as_dict()
    return course


def starter_quality_manifest() -> dict[str, object]:
    materials = build_substantial_starter_materials()
    entries: list[dict[str, object]] = []
    all_exercises = 0
    for index, material in enumerate(materials, start=1):
        word_count = sum(
            len(block.text.split()) for block in material.blocks if isinstance(block, Paragraph)
        )
        exercises = material.exercises()
        all_exercises += len(exercises)
        entries.append(
            {
                "material_id": f"starter-material-{index:02d}",
                "title": material.title,
                "source_type": "project-authored",
                "source_uri": material.source_uri,
                "license_id": STARTER_QUALITY_LICENSE_ID,
                "license_name": STARTER_QUALITY_LICENSE_NAME,
                "license_terms": STARTER_QUALITY_LICENSE_TERMS,
                "attribution": STARTER_QUALITY_ATTRIBUTION,
                "word_count": word_count,
                "exercise_count": len(exercises),
                "position_fens": sorted({exercise.fen for exercise in exercises}),
                "has_diagram": any(isinstance(block, Diagram) for block in material.blocks),
                "has_variation_tree": any(isinstance(block, VariationTree) for block in material.blocks),
            }
        )
    return {
        "schema_version": STARTER_QUALITY_SCHEMA_VERSION,
        "language": STARTER_CONTENT_LANGUAGE,
        "source_type": "project-authored",
        "license_id": STARTER_QUALITY_LICENSE_ID,
        "license_name": STARTER_QUALITY_LICENSE_NAME,
        "license_terms": STARTER_QUALITY_LICENSE_TERMS,
        "attribution": STARTER_QUALITY_ATTRIBUTION,
        "material_count": len(materials),
        "exercise_count": all_exercises,
        "materials": entries,
    }


__all__ = [
    "MIN_SUBSTANTIAL_WORDS",
    "STARTER_QUALITY_ATTRIBUTION",
    "STARTER_QUALITY_COURSE_KEY",
    "STARTER_QUALITY_LICENSE_ID",
    "STARTER_QUALITY_LICENSE_NAME",
    "STARTER_QUALITY_LICENSE_TERMS",
    "STARTER_QUALITY_SCHEMA_VERSION",
    "build_p0f_starter_course",
    "build_substantial_starter_materials",
    "starter_quality_manifest",
]
