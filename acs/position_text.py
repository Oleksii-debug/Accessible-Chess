from .position_editor import parse_piece_coordinate_position


def _legacy_message(exc: ValueError) -> str:
    """Preserve the existing Ukrainian text-adapter diagnostics.

    Parsing semantics live in position_editor; this adapter only translates
    canonical validation failures for the legacy Stage1 user-facing surface.
    """

    message = str(exc)
    if message == "position text must contain W: and B: sections":
        return "Потрібні секції W: і B:"
    if message == "each piece must be followed by a square, for example N f3":
        return "Кожна фігура повинна мати поле, наприклад N f3"
    if message.startswith("unknown piece symbol: "):
        return "Невідома фігура: " + message.removeprefix("unknown piece symbol: ")
    if message.startswith("square ") and message.endswith(" is specified more than once"):
        square = message[len("square "):-len(" is specified more than once")]
        return "Поле " + square + " вказане двічі"
    if message == "position text requires exactly one white and one black king":
        return "Потрібно рівно по одному королю"
    if message.startswith("invalid square: "):
        return "Неправильне поле: " + message.removeprefix("invalid square: ")
    return message


def parse_position_text(text, turn="w"):
    """Parse canonical W:/B: piece-coordinate text into a FEN.

    Coordinate grammar and structural validation are owned by the canonical
    position-editor parser. This function remains only as the legacy
    FEN-returning and localized-error adapter.
    """

    try:
        return parse_piece_coordinate_position(text, turn=turn).to_fen()
    except ValueError as exc:
        raise ValueError(_legacy_message(exc)) from exc
