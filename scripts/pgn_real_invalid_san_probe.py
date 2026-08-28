from __future__ import annotations

"""One-shot bounded real-corpus INVALID_SAN classifier.

No game text is printed or committed. The probe reports only corpus identity,
record ordinal/digest, structural recovery warnings and the first short SAN token
that the exact D06 validator rejects. The lower structural parser is used only
for diagnosis because D06 ``strict=False`` intentionally still validates SAN.
"""

import hashlib
import json
from pathlib import Path
import tempfile

from acs.gametree import parse_games
from acs.pgn_roundtrip import PgnRoundTripError, PgnRoundTripErrorCode, _validate_san, parse_pgn_text
from scripts.pgn_real_corpus_oracle import (
    CORPORA,
    _download_verified,
    _open_zstd_text,
    iter_complete_records,
)


def _walk_sans(line, prefix: tuple[int, ...] = ()):
    for move_index, node in enumerate(line.moves):
        path = prefix + (move_index,)
        yield path, node.san
        for variation_index, variation in enumerate(node.variations):
            yield from _walk_sans(variation, path + (-(variation_index + 1),))


def main() -> int:
    spec = next(item for item in CORPORA if item.name == "lichess-broadcast-2026-02")
    with tempfile.TemporaryDirectory(prefix="accessible-chess-invalid-san-") as directory:
        destination = Path(directory) / "broadcast.pgn.zst"
        _download_verified(spec, destination)
        source, reader, text = _open_zstd_text(destination)
        try:
            for ordinal, raw in enumerate(iter_complete_records(text, limit=2000), start=1):
                try:
                    parse_pgn_text(raw, strict=True)
                except PgnRoundTripError as exc:
                    if exc.code is not PgnRoundTripErrorCode.INVALID_SAN:
                        continue
                    recovered = parse_games(raw)
                    invalid: list[tuple[tuple[int, ...], str]] = []
                    for game in recovered:
                        for path, san in _walk_sans(game.line):
                            try:
                                _validate_san(san)
                            except PgnRoundTripError as san_exc:
                                if san_exc.code is PgnRoundTripErrorCode.INVALID_SAN:
                                    invalid.append((path, san))
                    if not invalid:
                        raise AssertionError("INVALID_SAN record has no reproducible invalid node")
                    path, san = invalid[0]
                    first = recovered[0]
                    payload = {
                        "schema": 2,
                        "corpus": spec.name,
                        "ordinal": ordinal,
                        "record_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                        "record_chars": len(raw),
                        "structural_warnings": list(first.warnings)[:8],
                        "variant_tag": first.tags.get("Variant"),
                        "invalid_san": san[:64],
                        "invalid_san_sha256": hashlib.sha256(san.encode("utf-8")).hexdigest(),
                        "invalid_san_length": len(san),
                        "node_path": path,
                    }
                    print("PGN_REAL_INVALID_SAN=" + json.dumps(payload, ensure_ascii=False, sort_keys=True))
                    return 2
        finally:
            text.close()
            try:
                reader.close()
            finally:
                source.close()
    print("PGN REAL INVALID SAN PROBE: NONE FOUND")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
