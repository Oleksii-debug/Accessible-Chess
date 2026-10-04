from acs.acsdb import AcsDatabase
from acs.duplicate_detection import detect_pgn_duplicates


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
