from .position_editor import parse_piece_coordinate_position


def parse_position_text(text, turn="w"):
    """Parse canonical W:/B: piece-coordinate text into a FEN.

    Coordinate grammar and structural validation are owned by the canonical
    position-editor parser. This function remains only as the legacy
    FEN-returning adapter.
    """

    return parse_piece_coordinate_position(text, turn=turn).to_fen()
