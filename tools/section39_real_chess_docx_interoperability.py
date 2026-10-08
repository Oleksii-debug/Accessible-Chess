"""Section 39 actual DOCX interoperability on genuine original chess prose.

Original source is a hash-pinned Capablanca GITenberg text book. DOCX is
generated solely as a disposable interoperability fixture from those real
passages, and is NOT mislabeled an independently sourced upstream DOCX.
Uses the already existing Section38 OPC test factory, production DOCX importer,
BookReader and Version2 Books open path; original prose is never redistributed.
"""
from __future__ import annotations
import hashlib
import json
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from acs.book_docx_import import import_docx_book
from acs.book_progress_store import BookProgressStore
from acs.bookreader import BookReader
from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog, read_verified_source_snapshot
from acs.version2_application import Version2Application
from tests.test_revised_section38_docx_book_integration import _docx, WORD
from tools.revised_sections37_38_offline_manifest import ROOT, _source_head

REPORT = ROOT / "section39-original-chess-derived-docx-qualification.json"
ID = "gitenberg_capablanca_33870_original_txt"


def qualify_source_derived_docx() -> dict:
    records = {record["id"]: record for record in load_catalog()}
    source = records.get(ID)
    if (
        source is None
        or source.get("acquisition") != "VENDORED_SOURCE_VERIFIED"
        or source.get("redistribution") != "NOT_CLEARED"
        or source.get("format") != "txt"
    ):
        raise LawfulCorpusError("original source-book rights/provenance not qualified")
    raw = read_verified_source_snapshot(ROOT / source["local_source"], source)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != source["sha256"] or len(raw) != source["indexed_bytes"]:
        raise LawfulCorpusError("original genuine Capablanca prose bytes mismatch")
    paragraphs = [
        line.strip()
        for line in raw.decode("utf-8-sig").splitlines()
        if len(line.strip()) >= 20
    ][:48]
    if len(paragraphs) != 48:
        raise LawfulCorpusError("original Capablanca book does not contain 48 real paragraphs")
    material = paragraphs[:32]
    markup = (
        f'<w:document xmlns:w="{WORD}"><w:body>'
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        '<w:r><w:t>Original Capablanca chess source - interoperability fixture</w:t></w:r></w:p>'
        + "".join(
            "<w:p><w:r><w:t>" + escape(part) + "</w:t></w:r></w:p>"
            for part in material
        )
        + "</w:body></w:document>"
    ).encode("utf-8")
    generated = _docx(xml=markup)
    local_digest = hashlib.sha256(generated).hexdigest()
    with tempfile.TemporaryDirectory(prefix="acs39-original-derived-docx-") as temp:
        root = Path(temp)
        docx = root / "capablanca-source-derived-not-upstream.docx"
        docx.write_bytes(generated)
        first = Version2Application.prepare_book_open(docx)
        second = Version2Application.prepare_book_open(docx)
        source_import = import_docx_book(generated, source_name=docx.name)
        if (
            first.document.as_dict() != source_import.document.as_dict()
            or first.document.as_dict() != second.document.as_dict()
            or source_import.source_sha256 != local_digest
            or len(first.document.blocks) != 33
            or [node.text for node in first.document.blocks[1:]] != material
        ):
            raise LawfulCorpusError("original prose derived DOCX lost heading/paragraph semantic fidelity")
        reader = BookReader(first.document)
        origin = reader.location()
        moved = reader.next_block()
        reader.save_return_point("original_capablanca_docx_qa")
        if moved.index != origin.index+1:
            raise LawfulCorpusError("derived DOCX cannot navigate original chess paragraphs")
        resumed = BookReader.restore_snapshot(second.document, reader.snapshot())
        if resumed.location() != moved:
            raise LawfulCorpusError("derived real prose DOCX reader cannot reimport and resume")
        state = root / "book-progress.json"
        BookProgressStore(state).save(first.book_key, reader)
        recovered = BookProgressStore(state).restore(second.book_key, second.document)
        if (
            recovered.location() != moved
            or recovered.restore_return_point("original_capablanca_docx_qa") != moved
        ):
            raise LawfulCorpusError("derived real DOCX content lost disk-stored reading position")
    return {
        "schema": "accessible-chess-section39-original-prose-derived-docx-v1",
        "source_id": ID, "original_txt_sha256": digest,
        "original_txt_bytes": len(raw),
        "actual_docx_sha256": local_digest, "generated_docx_bytes": len(generated),
        "actual_importer": "acs.book_docx_import.import_docx_book -> Version2Application.prepare_book_open -> BookReader/BookProgressStore",
        "actual_original_chess_paragraphs": 32,
        "actual_semantic_blocks": 33,
        "read": "PASS", "write": "UNSUPPORTED", "roundtrip": "UNSUPPORTED",
        "qualification": "PARTIAL_DERIVED_REAL_PROSE_NOT_INDEPENDENT_UPSTREAM_DOCX",
        "original_format": "TXT", "derived_format": "DOCX",
        "genuine_original_text": True, "independent_upstream_docx": False,
        "redistribution": "ORIGINAL_NONCLEARED_BYTES_NOT_PACKAGED",
        "mocked": False, "section39_terminal_done": False,
    }


def main():
    REPORT.unlink(missing_ok=True)
    head = _source_head()
    proof = qualify_source_derived_docx()
    proof["source_commit_sha"] = head
    stage = REPORT.with_suffix(".tmp")
    try:
        stage.write_text(json.dumps(proof, ensure_ascii=False, sort_keys=True, indent=2)+"\n",
                         encoding="utf-8")
        stage.replace(REPORT)
    finally:
        stage.unlink(missing_ok=True)
    print(json.dumps({
        "source_commit_sha": head, "original_chess_paragraphs": proof["actual_original_chess_paragraphs"],
        "qualification": proof["qualification"], "section39_done": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
