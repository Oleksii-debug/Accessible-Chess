from .position_editor import parse_piece_coordinate_position


def _localized_message(exc: ValueError, language: str) -> str:
    """Translate canonical parser errors at the legacy presentation boundary."""

    message = str(exc)
    if language != "uk":
        return message
    if message == "position text must be text":
        return "Текст позиції має бути текстовим значенням"
    if message == "position text is too long":
        return "Текст позиції занадто довгий"
    if message == "position text must contain W: and B: sections":
        return "Потрібні секції W: і B:"
    if message == "turn must be 'w' or 'b'":
        return "Хід має бути 'w' або 'b'"
    if message == "each piece must be followed by a square, for example N f3":
        return "Кожна фігура повинна мати поле, наприклад N f3"
    if message == "position text contains too many piece-square tokens":
        return "Текст позиції містить забагато описів фігур"
    if message.startswith("unknown piece symbol: "):
        return "Невідома фігура: " + message.removeprefix("unknown piece symbol: ")
    if message.startswith("square ") and message.endswith(" is specified more than once"):
        square = message[len("square "):-len(" is specified more than once")]
        return "Поле " + square + " вказане двічі"
    if message == "position text requires exactly one white and one black king":
        return "Потрібно рівно по одному королю"
    if message.startswith("invalid square: "):
        return "Неправильне поле: " + message.removeprefix("invalid square: ")
    if message == "invalid square":
        return "Неправильне поле"
    return message


def parse_position_text(text, turn="w", *, language="uk"):
    """Parse canonical W:/B: piece-coordinate text into a FEN.

    Coordinate grammar and structural validation are owned by the canonical
    position-editor parser. This function remains only as the legacy
    FEN-returning and localized-error adapter. The default language preserves
    the pre-existing direct-call Ukrainian diagnostics.
    """

    if type(language) is not str or language not in {"uk", "en"}:
        raise ValueError("language must be 'uk' or 'en'")
    try:
        return parse_piece_coordinate_position(text, turn=turn).to_fen()
    except ValueError as exc:
        raise ValueError(_localized_message(exc, language)) from exc
