from acs.acsdb import AcsDatabase
from acs.duplicate_detection import (
    DuplicateInputErrorCode,
    DuplicateInputValidationError,
    DuplicateMatch,
    DuplicateReport,
    detect_pgn_duplicates,
)
from acs.game_identity import IDENTITY_SCHEMA_VERSION
from acs.import_contract import sha256_utf8_text
import pytest


BASE = '''[Event "Club"]
[White "A"]
[Black "B"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 1-0
'''


def test_exact_source_and_record_duplicate_are_reported_without_mutation():
    with AcsDatabase() as db:
        imported = db.import_pgn_text(BASE, "first.pgn")
        before_sources = db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        before_games = db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        report = detect_pgn_duplicates(db, BASE)
        assert report.has_exact_source
        assert report.has_semantic_duplicates
        assert any(match.kind == "record" for match in report.matches)
        assert all(match.existing_source_id == imported.source_id for match in report.matches)
        assert db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == before_sources
        assert db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == before_games


def test_header_change_reports_tree_duplicate_not_record_duplicate():
    changed = BASE.replace('[Event "Club"]', '[Event "Other"]')
    with AcsDatabase() as db:
        db.import_pgn_text(BASE, "first.pgn")
        report = detect_pgn_duplicates(db, changed)
        kinds = [match.kind for match in report.matches]
        assert "tree" in kinds
        assert "record" not in kinds
        assert "exact_source" not in kinds


def test_recursive_variation_change_is_not_semantic_duplicate():
    first = '''[Result "*"]

1. e4 (1. d4 d5) e5 *
'''
    changed = '''[Result "*"]

1. e4 (1. d4 Nf6) e5 *
'''
    with AcsDatabase() as db:
        db.import_pgn_text(first, "first.pgn")
        report = detect_pgn_duplicates(db, changed)
        assert not report.has_exact_source
        assert not report.has_semantic_duplicates


def test_multi_game_input_preserves_incoming_game_index_in_evidence():
    second = '''[Event "Second"]
[Result "*"]

1. d4 d5 *
'''
    with AcsDatabase() as db:
        db.import_pgn_text(second, "stored.pgn")
        report = detect_pgn_duplicates(db, BASE + "\n" + second)
        record_matches = [match for match in report.matches if match.kind == "record"]
        assert len(record_matches) == 1
        assert record_matches[0].incoming_game_index == 1
        assert record_matches[0].identity_schema_version == 1


def test_duplicate_dtos_enforce_kind_specific_and_report_invariants():
    source_digest = "0" * 64
    semantic_digest = "1" * 64
    exact = DuplicateMatch("exact_source", 1, digest=source_digest)
    semantic = DuplicateMatch(
        "record",
        1,
        existing_game_id=2,
        incoming_game_index=0,
        identity_schema_version=IDENTITY_SCHEMA_VERSION,
        digest=semantic_digest,
    )
    report = DuplicateReport(source_digest, (exact, semantic), (3,))
    assert report.has_exact_source
    assert report.has_semantic_duplicates
    assert report.has_incomplete_evidence

    invalid_matches = (
        ("unknown", 1, None, None, None, source_digest),
        ("exact_source", True, None, None, None, source_digest),
        ("exact_source", 1, 2, None, None, source_digest),
        ("record", 1, None, 0, 1, semantic_digest),
        ("record", 1, 2, True, 1, semantic_digest),
        ("record", 1, 2, 0, True, semantic_digest),
        ("tree", 1, 2, 0, 1, "A" * 64),
    )
    for values in invalid_matches:
        with pytest.raises((TypeError, ValueError)):
            DuplicateMatch(*values)

    with pytest.raises(TypeError):
        DuplicateReport(source_digest, [exact])
    with pytest.raises(ValueError):
        DuplicateReport("2" * 64, (exact,))
    for skipped in ((True,), (0,), (3, 3), [3]):
        with pytest.raises((TypeError, ValueError)):
            DuplicateReport(source_digest, (), skipped)


def test_malformed_stored_text_is_explicitly_skipped_without_coercion_or_mutation():
    with AcsDatabase() as db:
        imported = db.import_pgn_text(BASE, "stored.pgn")
        game_id = imported.game_ids[0]
        before_sources = db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        before_games = db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        db.conn.execute(
            "UPDATE games SET pgn_text=? WHERE id=?",
            (b"binary-pgn", game_id),
        )

        report = detect_pgn_duplicates(db, BASE)

        assert report.skipped_stored_game_ids == (game_id,)
        assert report.has_incomplete_evidence
        assert not report.has_semantic_duplicates
        assert db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == before_sources
        assert db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == before_games
        assert db.conn.execute(
            "SELECT pgn_text FROM games WHERE id=?", (game_id,)
        ).fetchone()[0] == b"binary-pgn"


def test_duplicate_detection_rejects_database_and_text_coercion():
    with AcsDatabase() as db:
        for database, text in ((object(), BASE), (db, b"pgn"), (db, True)):
            with pytest.raises(TypeError):
                detect_pgn_duplicates(database, text)


def test_illegal_incoming_collection_fails_closed_before_exact_or_semantic_claims():
    illegal = '''[Event "Illegal"]
[Result "*"]

1. e4 e5 2. Bh6 *
'''
    with AcsDatabase() as db:
        db.add_source("legacy-illegal.pgn", "pgn", sha256_utf8_text(illegal))
        before = db.conn.total_changes

        with pytest.raises(DuplicateInputValidationError) as blocked:
            detect_pgn_duplicates(db, illegal)

        assert blocked.value.code is DuplicateInputErrorCode.LEGALITY_DAMAGE
        assert blocked.value.source_index == 0
        assert blocked.value.evidence_codes == ("illegal_san",)
        assert db.conn.total_changes == before


def test_structurally_damaged_incoming_game_has_stable_recovery_evidence():
    damaged = '[Result "*"]\n\n$1 1. e4 *\n'
    with AcsDatabase() as db:
        with pytest.raises(DuplicateInputValidationError) as blocked:
            detect_pgn_duplicates(db, damaged)

        assert blocked.value.code is DuplicateInputErrorCode.STRUCTURAL_DAMAGE
        assert blocked.value.source_index == 0
        assert "orphan_annotation" in blocked.value.evidence_codes


def test_one_illegal_incoming_game_blocks_partial_collection_evidence():
    collection = BASE + '''
[Event "Illegal second"]
[Result "*"]

1. Nf3 Nf6 2. Bh6 *
'''
    with AcsDatabase() as db:
        db.import_pgn_text(BASE, "stored.pgn")

        with pytest.raises(DuplicateInputValidationError) as blocked:
            detect_pgn_duplicates(db, collection)

        assert blocked.value.code is DuplicateInputErrorCode.LEGALITY_DAMAGE
        assert blocked.value.source_index == 1


def test_illegal_legacy_stored_game_is_skipped_without_semantic_claim():
    illegal = '[Result "*"]\n\n1. e4 e5 2. Bh6 *\n'
    with AcsDatabase() as db:
        imported = db.import_pgn_text(BASE, "stored.pgn")
        game_id = imported.game_ids[0]
        db.conn.execute(
            "UPDATE games SET pgn_text=? WHERE id=?",
            (illegal, game_id),
        )

        report = detect_pgn_duplicates(db, BASE)

        assert report.has_exact_source
        assert not report.has_semantic_duplicates
        assert report.skipped_stored_game_ids == (game_id,)
        assert report.has_incomplete_evidence


def test_duplicate_input_error_enforces_bounded_immutable_evidence():
    valid = DuplicateInputValidationError(
        "blocked",
        code=DuplicateInputErrorCode.STRUCTURAL_DAMAGE,
        source_index=0,
        evidence_codes=("orphan_annotation",),
    )
    assert valid.evidence_codes == ("orphan_annotation",)

    invalid = (
        {"source_index": True, "evidence_codes": ("x",)},
        {"source_index": 0, "evidence_codes": ["x"]},
        {"source_index": 0, "evidence_codes": ("x", "x")},
        {"source_index": 0, "evidence_codes": tuple(str(i) for i in range(17))},
    )
    for values in invalid:
        with pytest.raises((TypeError, ValueError)):
            DuplicateInputValidationError(
                "blocked",
                code=DuplicateInputErrorCode.STRUCTURAL_DAMAGE,
                **values,
            )
