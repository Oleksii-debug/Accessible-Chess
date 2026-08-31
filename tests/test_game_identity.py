from acs.game_identity import (
    IDENTITY_SCHEMA_VERSION,
    MOVE_IDENTITY_SCHEMA_VERSION,
    identity_for_game,
    move_identity_for_game,
    same_game_moves,
    same_game_record,
    same_game_tree,
)
from acs.gametree import parse_games


def one(text: str):
    games = parse_games(text)
    assert len(games) == 1
    return games[0]


def test_identity_is_versioned_and_stable_across_header_order_and_move_numbers():
    a = one('''[Event "Club"]\n[White "A"]\n[Black "B"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 1-0\n''')
    b = one('''[Black "B"]\n[Result "1-0"]\n[Event "Club"]\n[White "A"]\n\n1.e4 e5 2.Nf3 Nc6 1-0\n''')
    ia = identity_for_game(a)
    ib = identity_for_game(b)
    ma = move_identity_for_game(a)
    mb = move_identity_for_game(b)
    assert ia.schema_version == IDENTITY_SCHEMA_VERSION == 1
    assert ma.schema_version == MOVE_IDENTITY_SCHEMA_VERSION == 1
    assert ia.tree_digest == ib.tree_digest
    assert ia.record_digest == ib.record_digest
    assert ma.move_digest == mb.move_digest
    assert same_game_tree(a, b)
    assert same_game_record(a, b)
    assert same_game_moves(a, b)


def test_tag_change_changes_record_but_not_tree_or_move_identity():
    a = one('[Event "One"]\n[Result "*"]\n\n1. e4 e5 *\n')
    b = one('[Event "Two"]\n[Result "*"]\n\n1. e4 e5 *\n')
    assert same_game_tree(a, b)
    assert same_game_moves(a, b)
    assert not same_game_record(a, b)


def test_recursive_variation_change_changes_tree_and_move_identity():
    a = one('[Result "*"]\n\n1. e4 (1. d4 d5) e5 *\n')
    b = one('[Result "*"]\n\n1. e4 (1. d4 Nf6) e5 *\n')
    assert not same_game_tree(a, b)
    assert not same_game_moves(a, b)


def test_comments_and_nags_are_loss_sensitive_but_move_identity_preserves_same_game_evidence():
    a = one('[Result "*"]\n\n1. e4 $1 {main idea} e5 *\n')
    b = one('[Result "*"]\n\n1. e4 $2 {different idea} e5 *\n')
    assert not same_game_tree(a, b)
    assert same_game_moves(a, b)


def test_attached_symbolic_nag_and_numeric_nag_share_move_identity_without_rewriting_tree():
    attached = one('[Result "*"]\n\n1. e4?! e5 *\n')
    separated = one('[Result "*"]\n\n1. e4 $6 e5 *\n')
    assert not same_game_tree(attached, separated)
    assert same_game_moves(attached, separated)
    assert attached.line.moves[0].san == "e4?!"
    assert separated.line.moves[0].san == "e4"


def test_result_and_richer_metadata_do_not_change_move_identity_but_remain_record_distinct():
    sparse = one('[Result "*"]\n\n1. e4 e5 *\n')
    rich = one(
        '[Event "Championship"]\n[Site "Kyiv"]\n[Date "2026.08.31"]\n'
        '[White "A"]\n[Black "B"]\n[Result "1-0"]\n\n1. e4 e5 1-0\n'
    )
    assert same_game_moves(sparse, rich)
    assert not same_game_tree(sparse, rich)
    assert not same_game_record(sparse, rich)


def test_same_players_and_date_with_different_moves_are_not_same_move_identity():
    tags = '[White "A"]\n[Black "B"]\n[Date "2026.08.31"]\n[Result "*"]\n\n'
    a = one(tags + '1. e4 e5 *\n')
    b = one(tags + '1. d4 d5 *\n')
    assert not same_game_moves(a, b)


def test_same_moves_from_different_start_positions_are_not_same_move_identity():
    normal = one('[Result "*"]\n\n1. e4 *\n')
    custom = one(
        '[SetUp "1"]\n'
        '[FEN "8/8/8/8/8/8/4P3/4K2k w - - 0 1"]\n'
        '[Result "*"]\n\n1. e4 *\n'
    )
    assert not same_game_moves(normal, custom)
