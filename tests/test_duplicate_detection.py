from acs.acsdb import AcsDatabase
from acs.duplicate_detection import detect_pgn_duplicates, source_record_identity


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
        assert report.source_format == "pgn"
        assert report.has_exact_source
        assert report.has_semantic_duplicates
        assert any(match.kind == "record" for match in report.matches)
        assert all(match.existing_source_id == imported.source_id for match in report.matches)
        record = next(match for match in report.matches if match.kind == "record")
        assert record.existing_source_record is not None
        assert record.incoming_source_record is not None
        assert record.existing_source_record == record.incoming_source_record
        assert db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == before_sources
        assert db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == before_games


def test_exact_source_identity_includes_source_format():
    with AcsDatabase() as db:
        db.import_pgn_text(BASE, "first.pgn")
        db.conn.execute("UPDATE sources SET source_format='cbh'")
        db.conn.commit()
        report = detect_pgn_duplicates(db, BASE)
        assert not report.has_exact_source
        assert any(match.kind == "record" for match in report.matches)
        record = next(match for match in report.matches if match.kind == "record")
        assert record.existing_source_record is not None
        assert record.existing_source_record.source_format == "cbh"
        assert record.incoming_source_record is not None
        assert record.incoming_source_record.source_format == "pgn"
        assert record.existing_source_record != record.incoming_source_record


def test_header_change_reports_tree_duplicate_not_record_duplicate():
    changed = BASE.replace('[Event "Club"]', '[Event "Other"]')
    with AcsDatabase() as db:
        db.import_pgn_text(BASE, "first.pgn")
        report = detect_pgn_duplicates(db, changed)
        kinds = [match.kind for match in report.matches]
        assert "tree" in kinds
        assert "record" not in kinds
        assert "exact_source" not in kinds


def test_comment_and_nag_variants_report_moves_duplicate_without_silent_merge():
    first = '''[Event "Study"]
[Result "*"]

1. e4 $1 {main idea} e5 *
'''
    changed = '''[Event "Study"]
[Result "*"]

1. e4 $2 {different annotation} e5 *
'''
    with AcsDatabase() as db:
        original = db.import_pgn_text(first, "annotated-a.pgn")
        before = db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        report = detect_pgn_duplicates(db, changed)
        move_matches = [match for match in report.matches if match.kind == "moves"]
        assert len(move_matches) == 1
        assert move_matches[0].existing_game_id == original.game_ids[0]
        assert not any(match.kind in {"record", "tree"} for match in report.matches)
        assert db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == before

        # Detection is read-only, and a caller that chooses to import the variant
        # still gets a separate provenance-bearing row. No annotation is merged.
        second = db.import_pgn_text(changed, "annotated-b.pgn")
        assert second.source_id != original.source_id
        rows = db.conn.execute("SELECT pgn_text FROM games ORDER BY id").fetchall()
        assert len(rows) == 2
        assert "main idea" in rows[0][0]
        assert "different annotation" in rows[1][0]


def test_attached_symbolic_nag_matches_numeric_nag_at_moves_strength_only():
    attached = '''[Result "*"]

1. e4?! e5 *
'''
    numeric = '''[Result "*"]

1. e4 $6 e5 *
'''
    with AcsDatabase() as db:
        db.import_pgn_text(attached, "attached.pgn")
        report = detect_pgn_duplicates(db, numeric)
        assert [match.kind for match in report.matches] == ["moves"]


def test_richer_metadata_is_classified_without_overwriting_sparse_record():
    sparse = '''[Result "*"]

1. e4 e5 *
'''
    rich = '''[Event "Championship"]
[Site "Kyiv"]
[Date "2026.08.31"]
[White "A"]
[Black "B"]
[Result "1-0"]

1. e4 e5 1-0
'''
    with AcsDatabase() as db:
        first = db.import_pgn_text(sparse, "sparse.pgn")
        report = detect_pgn_duplicates(db, rich)
        assert [match.kind for match in report.matches] == ["moves"]
        assert report.matches[0].existing_source_id == first.source_id
        assert db.conn.execute("SELECT result FROM games").fetchone()[0] == "*"

        db.import_pgn_text(rich, "rich.pgn")
        rows = db.conn.execute(
            "SELECT event, site, game_date, result FROM games ORDER BY id"
        ).fetchall()
        assert len(rows) == 2
        assert tuple(rows[0]) == (None, None, None, "*")
        assert tuple(rows[1]) == ("Championship", "Kyiv", "2026.08.31", "1-0")


def test_same_players_and_date_but_different_moves_are_not_duplicates():
    tags = '''[White "A"]
[Black "B"]
[Date "2026.08.31"]
[Result "*"]

'''
    with AcsDatabase() as db:
        db.import_pgn_text(tags + "1. e4 e5 *\n", "game-a.pgn")
        report = detect_pgn_duplicates(db, tags + "1. d4 d5 *\n")
        assert not report.has_exact_source
        assert not report.has_semantic_duplicates


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
        assert record_matches[0].incoming_source_record is not None
        assert record_matches[0].incoming_source_record.source_index == 1


def test_source_record_identity_keeps_cross_format_and_container_records_distinct():
    payload_sha = "a" * 64
    cbv = source_record_identity("CBV", payload_sha, 7)
    cbh = source_record_identity("cbh", payload_sha, 7)
    pgn = source_record_identity("pgn", payload_sha, 7)
    assert cbv.source_format == "cbv"
    assert cbv != cbh != pgn
    assert source_record_identity(" CBH ", payload_sha.upper(), 7) == cbh


def test_source_record_identity_is_stable_for_same_source_record_and_distinguishes_index():
    payload_sha = "b" * 64
    first = source_record_identity("pgn", payload_sha, 3)
    repeat = source_record_identity("PGN", payload_sha.upper(), 3)
    next_record = source_record_identity("pgn", payload_sha, 4)
    assert first == repeat
    assert first != next_record


def test_many_incoming_games_match_without_cross_product_duplicates():
    stored = '''[Event "Target"]
[Result "*"]

1. e4 e5 *
'''
    incoming = []
    for index in range(250):
        if index == 149:
            incoming.append(stored.replace('[Event "Target"]', '[Event "Variant"]'))
        else:
            incoming.append(
                f'''[Event "Game {index}"]\n[Result "*"]\n\n1. d4 d5 2. c4 e6 *\n'''
            )
    with AcsDatabase() as db:
        db.import_pgn_text(stored, "stored.pgn")
        report = detect_pgn_duplicates(db, "\n".join(incoming))
        semantic = [match for match in report.matches if match.kind in {"record", "tree", "moves"}]
        assert len(semantic) == 1
        assert semantic[0].kind == "tree"
        assert semantic[0].incoming_game_index == 149
