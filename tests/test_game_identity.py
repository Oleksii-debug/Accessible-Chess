from acs.game_identity import IDENTITY_SCHEMA_VERSION, identity_for_game, same_game_record, same_game_tree
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
    assert ia.schema_version == IDENTITY_SCHEMA_VERSION == 1
    assert ia.tree_digest == ib.tree_digest
    assert ia.record_digest == ib.record_digest
    assert same_game_tree(a, b)
    assert same_game_record(a, b)


def test_tag_change_changes_record_but_not_tree_identity():
    a = one('[Event "One"]\n[Result "*"]\n\n1. e4 e5 *\n')
    b = one('[Event "Two"]\n[Result "*"]\n\n1. e4 e5 *\n')
    assert same_game_tree(a, b)
    assert not same_game_record(a, b)


def test_recursive_variation_change_changes_tree_identity():
    a = one('[Result "*"]\n\n1. e4 (1. d4 d5) e5 *\n')
    b = one('[Result "*"]\n\n1. e4 (1. d4 Nf6) e5 *\n')
    assert not same_game_tree(a, b)


def test_comments_and_nags_are_loss_sensitive_for_duplicate_identity():
    a = one('[Result "*"]\n\n1. e4 $1 {main idea} e5 *\n')
    b = one('[Result "*"]\n\n1. e4 $2 {different idea} e5 *\n')
    assert not same_game_tree(a, b)
