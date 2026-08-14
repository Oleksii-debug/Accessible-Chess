from pathlib import Path

from acs.chessbase_inspection import (
    INSPECTION_SCHEMA_VERSION,
    inspect_chessbase_source,
    inspect_many_chessbase_sources,
    summarize_chessbase_inspections,
)


def test_cbh_with_component_collects_evidence_without_claiming_decode(tmp_path: Path):
    cbh = tmp_path / "sample.cbh"
    cbg = tmp_path / "sample.cbg"
    cbh.write_bytes(b"header")
    cbg.write_bytes(b"moves")

    report = inspect_chessbase_source(cbh)

    assert report.schema_version == INSPECTION_SCHEMA_VERSION
    assert report.recognized is True
    assert report.is_primary_source is True
    assert report.read_only is True
    assert report.source_kind == "component_set"
    assert report.source_status == "evidence_collected"
    assert report.decoder_available is False
    assert report.can_decode is False
    assert report.decode_status == "unavailable"
    assert report.evidence_files == 2
    assert report.evidence_bytes == len(b"header") + len(b"moves")
    assert any("not decoding" in warning for warning in report.warnings)


def test_lonely_cbh_is_partial_not_full_compatibility(tmp_path: Path):
    cbh = tmp_path / "lonely.cbh"
    cbh.write_bytes(b"header")

    report = inspect_chessbase_source(cbh)

    assert report.source_status == "partial"
    assert report.safe_for_source_preserving_workflow is True
    assert report.can_decode is False


def test_missing_primary_is_damaged(tmp_path: Path):
    report = inspect_chessbase_source(tmp_path / "missing.cbh")

    assert report.recognized is True
    assert report.source_status == "damaged"
    assert report.evidence_files == 0
    assert report.safe_for_source_preserving_workflow is False


def test_component_only_is_reported_without_hashing_as_primary(tmp_path: Path):
    cbg = tmp_path / "sample.cbg"
    cbg.write_bytes(b"moves")

    report = inspect_chessbase_source(cbg)

    assert report.recognized is True
    assert report.is_primary_source is False
    assert report.source_status == "component_only"
    assert report.evidence_files == 0
    assert report.can_decode is False


def test_unknown_source_is_unsupported(tmp_path: Path):
    source = tmp_path / "sample.bin"
    source.write_bytes(b"unknown")

    report = inspect_chessbase_source(source)

    assert report.recognized is False
    assert report.source_status == "unsupported"
    assert report.safe_for_source_preserving_workflow is False


def test_batch_continues_across_mixed_sources_and_summarizes(tmp_path: Path):
    cbv = tmp_path / "archive.cbv"
    cbv.write_bytes(b"archive")
    missing = tmp_path / "missing.cbh"
    component = tmp_path / "piece.cbp"
    component.write_bytes(b"players")

    reports = inspect_many_chessbase_sources((cbv, missing, component))
    counts = summarize_chessbase_inspections(reports)

    assert len(reports) == 3
    assert counts["evidence_collected"] == 1
    assert counts["damaged"] == 1
    assert counts["component_only"] == 1
    assert counts["decoder_unavailable"] == 3
    assert counts["decoder_available"] == 0


def test_report_dict_is_neutral_and_serializable_shape(tmp_path: Path):
    source = tmp_path / "single.cbone"
    source.write_bytes(b"single")

    data = inspect_chessbase_source(source).as_dict()

    assert data["source_kind"] == "single_file_database"
    assert data["read_only"] is True
    assert data["decoder_available"] is False
    assert data["can_decode"] is False
    assert isinstance(data["warnings"], list)
