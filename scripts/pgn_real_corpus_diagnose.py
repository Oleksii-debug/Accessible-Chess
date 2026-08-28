from __future__ import annotations

"""Bounded classifier for a real-corpus strict PGN rejection.

No PGN record is printed or committed.  Evidence is limited to corpus identity,
ordinal, record SHA-256, structural counts and canonical recovery warnings.
PGN semantics remain owned by ``acs.pgn_roundtrip``.
"""

import hashlib
import json
from pathlib import Path
import tempfile

from acs.pgn_roundtrip import PgnRoundTripError, parse_pgn_text
from scripts.pgn_real_corpus_oracle import (
    CORPORA,
    _download_verified,
    _open_zstd_text,
    iter_complete_records,
)


def _safe_warnings(values: list[str]) -> list[str]:
    # Current canonical warnings are taxonomy-like fixed strings.  Bound and
    # deduplicate them so a future parser cannot accidentally dump source text.
    safe: list[str] = []
    for value in values:
        text = str(value).replace("\r", " ").replace("\n", " ")[:160]
        if text not in safe:
            safe.append(text)
        if len(safe) >= 16:
            break
    return safe


def classify(*, game_limit: int = 2000) -> int:
    with tempfile.TemporaryDirectory(prefix="accessible-chess-pgn-diagnose-") as directory:
        root = Path(directory)
        for spec in CORPORA:
            destination = root / f"{spec.name}.pgn.zst"
            _download_verified(spec, destination)
            source, reader, text = _open_zstd_text(destination)
            try:
                for ordinal, raw in enumerate(
                    iter_complete_records(text, limit=game_limit), start=1
                ):
                    try:
                        games = parse_pgn_text(raw, strict=True)
                    except PgnRoundTripError as exc:
                        recovered = parse_pgn_text(raw, strict=False)
                        warnings = [warning for game in recovered for warning in game.warnings]
                        first = recovered[0] if recovered else None
                        payload = {
                            "schema": 1,
                            "corpus": spec.name,
                            "ordinal": ordinal,
                            "record_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                            "record_chars": len(raw),
                            "record_lines": raw.count("\n"),
                            "strict_code": exc.code.value,
                            "recovered_game_count": len(recovered),
                            "warnings": _safe_warnings(warnings),
                            "tag_count": len(first.tags) if first else 0,
                            "tag_keys": sorted(first.tags)[:32] if first else [],
                            "header_result": first.tags.get("Result") if first else None,
                            "movetext_result": first.line.result if first else None,
                            "starts_event_tag": raw.lstrip("\ufeff").startswith('[Event "'),
                        }
                        print(
                            "PGN_REAL_CORPUS_STRICT_REJECTION="
                            + json.dumps(payload, ensure_ascii=False, sort_keys=True)
                        )
                        return 2
                    if len(games) != 1:
                        print(
                            "PGN_REAL_CORPUS_SEGMENTATION_REJECTION="
                            + json.dumps(
                                {
                                    "schema": 1,
                                    "corpus": spec.name,
                                    "ordinal": ordinal,
                                    "record_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                                    "strict_game_count": len(games),
                                },
                                sort_keys=True,
                            )
                        )
                        return 3
            finally:
                text.close()
                try:
                    reader.close()
                finally:
                    source.close()
    print("PGN REAL CORPUS STRICT CLASSIFIER PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(classify())
