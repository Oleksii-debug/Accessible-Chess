from __future__ import annotations

"""Create a small/medium/large TEST_COLLECTION catalog without vendoring bytes."""

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import subprocess


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def entry(*, source_id: str, title: str, language: str, format: str, path: Path | None,
          url: str, rights: str, status: str) -> dict[str, object]:
    return {
        "source_id": source_id,
        "title": title,
        "author_or_owner": "Accessible Chess project" if url.startswith("repo://") else "external source",
        "language": language,
        "format": format,
        "source_url": url,
        "size_bytes": path.stat().st_size if path and path.is_file() else None,
        "sha256": sha256(path) if path and path.is_file() else None,
        "rights": rights,
        "import_status": status,
        "reload": "download to an isolated test workspace and rerun the Section 38/39 gates",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.corpus_root
    repo = Path(__file__).resolve().parents[1]
    files = {
        "cotswold": root / "chessit" / "cotswold_2023.pgn",
        "alekhine": root / "extracted" / "alekhine" / "Alekhine.pgn",
        "cbv": root / "chessit" / "cotswold_2023.cbv",
        "txt": root / "gutenberg-33870" / "pg33870.txt",
        "html": root / "gutenberg-33870" / "html" / "pg33870-images.html",
        "epub": root / "gutenberg-33870" / "pg33870.epub3",
    }
    entries = [
        entry(source_id="starter-books-training-uk", title="Accessible Chess starter books and training", language="uk", format="BookDocument/Training", path=repo / "acs/starter_books_training_content.py", url="repo://acs/starter_books_training_content.py", rights="project-authored; redistributable with notice", status="READY"),
        entry(source_id="starter-games-uk", title="Accessible Chess starter games", language="uk", format="PGN", path=repo / "acs/starter_content.py", url="repo://acs/starter_content.py", rights="project-authored; redistributable with notice", status="READY"),
        entry(source_id="gutenberg-33870-txt", title="Chess Fundamentals / Gutenberg text corpus", language="en", format="TXT", path=files["txt"], url="https://www.gutenberg.org/cache/epub/33870/pg33870.txt", rights="public-domain-in-USA source; test-only copy", status="READ_PASS"),
        entry(source_id="gutenberg-33870-html", title="Chess Fundamentals / Gutenberg HTML with images", language="en", format="HTML", path=files["html"], url="https://www.gutenberg.org/cache/epub/33870/pg33870-h.zip", rights="public-domain-in-USA source; test-only copy", status="READ_PASS"),
        entry(source_id="gutenberg-33870-epub3", title="Chess Fundamentals / Gutenberg EPUB3", language="en", format="EPUB3", path=files["epub"], url="https://www.gutenberg.org/ebooks/33870.epub3.images", rights="public-domain-in-USA source; test-only copy", status="READ_PASS"),
        entry(source_id="chessit-cotswold-2023", title="Cotswold Open 2023", language="en", format="PGN", path=files["cotswold"], url="https://www.chessit.co.uk/Congresses/Cotswold/2023/Cotswold_Open_2023.pgn", rights="source terms not stated; test-only copy", status="READ_WRITE_ROUNDTRIP_PASS"),
        entry(source_id="pgnmentor-alekhine", title="Alekhine games", language="multilingual metadata", format="PGN", path=files["alekhine"], url="https://www.pgnmentor.com/players/Alekhine.zip", rights="free download; redistribution unclear; test-only copy", status="READ_WRITE_ROUNDTRIP_PASS"),
        entry(source_id="chessit-cotswold-2023-cbv", title="Cotswold Open 2023 database", language="en", format="CBV/CBH", path=files["cbv"], url="https://www.chessit.co.uk/Congresses/Cotswold/2023/Cotswold_Open_2023.cbv", rights="source terms not stated; test-only copy", status="EXTERNAL_READBACK_PASS"),
    ]
    present = [item for item in entries if item["sha256"]]
    report = {
        "schema_version": 1,
        "section": 40,
        "generated_at": date.today().isoformat(),
        "status": "INTERNAL_COMPLETE_EXTERNAL_BLOCKED",
        "collection_policy": "TEST_COLLECTION is isolated and reloadable; PUBLIC_RELEASE contains links/notices, not uncleared third-party bytes.",
        "languages": {"uk": "project-owned starter corpus present", "en": "real Gutenberg and game corpora present"},
        "size_bands": {"small": [item["source_id"] for item in present if (item["size_bytes"] or 0) < 500_000], "medium": [item["source_id"] for item in present if 500_000 <= (item["size_bytes"] or 0) < 2_000_000], "large": [item["source_id"] for item in present if (item["size_bytes"] or 0) >= 2_000_000]},
        "entries": entries,
        "blocked": ["lawful Ukrainian third-party literature", "PDF", "DOCX", "CBF+CBI", "2CBH", "CBONE", "clean Windows packaged owner acceptance"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
