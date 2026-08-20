import pytest

from acs.game_identity import (
    IDENTITY_SCHEMA_VERSION,
    GameIdentity,
    GameIdentityContractError,
    GameIdentityErrorCode,
    identity_for_game,
    same_game_record,
    same_game_tree,
)
from acs.gametree import MoveNode, PgnGame, VariationLine, parse_games


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


def test_attached_and_separated_nags_have_one_canonical_identity():
    attached = one('[Result "*"]\n\n1.e4!?$0 e5$255 2.Nf3!! *\n')
    separated = one('[Result "*"]\n\n1. e4 !? $0 e5 $255 2. Nf3 !! *\n')

    assert same_game_tree(attached, separated)
    assert same_game_record(attached, separated)
    assert attached.line.moves[0].san == "e4"
    assert attached.line.moves[0].nags == ["!?", "$0"]


def test_semicolon_comment_identity_survives_pgn_round_trip():
    from acs.gametree import serialize_games

    original = one('[Result "*"]\n\n1. e4 ;literal } brace\n e5 *\n')
    reparsed = one(serialize_games([original]))

    assert same_game_tree(original, reparsed)
    assert same_game_record(original, reparsed)


def test_identity_dto_requires_exact_version_and_sha256_digests():
    digest = "0" * 64
    assert GameIdentity(IDENTITY_SCHEMA_VERSION, digest, digest).tree_digest == digest
    for values in (
        (True, digest, digest),
        (2, digest, digest),
        (1, "A" * 64, digest),
        (1, "0" * 63, digest),
        (1, digest, b"0" * 64),
    ):
        with pytest.raises(GameIdentityContractError):
            GameIdentity(*values)


def test_identity_rejects_mutated_game_tree_shapes_with_stable_codes():
    with pytest.raises(GameIdentityContractError) as wrong_game:
        identity_for_game(object())
    assert wrong_game.value.code is GameIdentityErrorCode.INVALID_GAME

    game = one('[Result "*"]\n\n1. e4 *\n')
    game.tags = {1: "bad"}
    with pytest.raises(GameIdentityContractError) as bad_tags:
        identity_for_game(game)
    assert bad_tags.value.code is GameIdentityErrorCode.INVALID_TAGS

    game = one('[Result "*"]\n\n1. e4 *\n')
    game.line.moves = tuple(game.line.moves)
    with pytest.raises(GameIdentityContractError) as bad_line:
        identity_for_game(game)
    assert bad_line.value.code is GameIdentityErrorCode.INVALID_LINE

    game = one('[Result "*"]\n\n1. e4 *\n')
    game.line.moves[0].san = True
    with pytest.raises(GameIdentityContractError) as bad_move:
        identity_for_game(game)
    assert bad_move.value.code is GameIdentityErrorCode.INVALID_MOVE

    game = one('[Result "*"]\n\n1. e4 {idea} *\n')
    game.line.moves[0].comments_after[0].style = "brace"
    with pytest.raises(GameIdentityContractError) as bad_comment:
        identity_for_game(game)
    assert bad_comment.value.code is GameIdentityErrorCode.INVALID_COMMENT


def test_identity_detects_cycles_and_depth_before_python_recursion_failure():
    cyclic = one('[Result "*"]\n\n1. e4 *\n')
    cyclic.line.moves[0].variations.append(cyclic.line)
    with pytest.raises(GameIdentityContractError) as cycle:
        identity_for_game(cyclic)
    assert cycle.value.code is GameIdentityErrorCode.CYCLIC_TREE

    deep = PgnGame()
    line = deep.line
    for _ in range(130):
        move = MoveNode("e4")
        child = VariationLine()
        move.variations.append(child)
        line.moves.append(move)
        line = child
    with pytest.raises(GameIdentityContractError) as limit:
        identity_for_game(deep)
    assert limit.value.code is GameIdentityErrorCode.TREE_LIMIT_EXCEEDED
