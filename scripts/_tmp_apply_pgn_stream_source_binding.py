from __future__ import annotations

from pathlib import Path


TARGET = Path("acs/pgn_streaming_import.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "import hashlib\nfrom pathlib import Path\nimport tempfile\n",
        "import hashlib\nimport os\nfrom pathlib import Path\nimport stat\nimport tempfile\n",
        "imports",
    )

    anchor = '''\n\nclass StreamingPgnLibraryImporter:\n'''
    helper = '''\n\ndef _open_bound_source_fd(\n    source: SourceFingerprint,\n    *,\n    chunk_size: int,\n    accepted_games: int,\n) -> int:\n    \"\"\"Open the already-fingerprinted source without a path-reopen TOCTOU read.\n\n    The descriptor is opened non-blocking/no-follow where the platform supports\n    those flags, then the path is fingerprinted again *while that descriptor is\n    held*.  No source bytes are consumed until the descriptor is proven to refer\n    to the same regular-file identity and byte snapshot as the preliminary\n    fingerprint.  Later path replacement cannot redirect the held descriptor;\n    the existing pre-publication fingerprint still rejects any changed path.\n    \"\"\"\n\n    flags = (\n        os.O_RDONLY\n        | getattr(os, \"O_BINARY\", 0)\n        | getattr(os, \"O_NOFOLLOW\", 0)\n        | getattr(os, \"O_NONBLOCK\", 0)\n    )\n    try:\n        fd = os.open(source.path, flags)\n    except OSError as exc:\n        raise StreamingPgnImportError(\n            \"PGN source changed before streaming\",\n            code=StreamingPgnErrorCode.SOURCE_CHANGED,\n            accepted_games=accepted_games,\n        ) from exc\n\n    try:\n        opened = os.fstat(fd)\n        if not stat.S_ISREG(opened.st_mode):\n            raise StreamingPgnImportError(\n                \"PGN source changed before streaming\",\n                code=StreamingPgnErrorCode.SOURCE_CHANGED,\n                accepted_games=accepted_games,\n            )\n        rebound = fingerprint(source.path, chunk_size=chunk_size)\n        rebound_stat = os.stat(rebound.path, follow_symlinks=False)\n        same_identity = (opened.st_dev, opened.st_ino) == (\n            rebound_stat.st_dev,\n            rebound_stat.st_ino,\n        )\n        same_snapshot = (\n            rebound.size == source.size\n            and rebound.sha256 == source.sha256\n        )\n        if not same_identity or not same_snapshot:\n            raise StreamingPgnImportError(\n                \"PGN source changed before streaming\",\n                code=StreamingPgnErrorCode.SOURCE_CHANGED,\n                accepted_games=accepted_games,\n            )\n        return fd\n    except StreamingPgnImportError:\n        os.close(fd)\n        raise\n    except Exception as exc:\n        os.close(fd)\n        raise StreamingPgnImportError(\n            \"PGN source changed before streaming\",\n            code=StreamingPgnErrorCode.SOURCE_CHANGED,\n            accepted_games=accepted_games,\n        ) from exc\n\n\nclass StreamingPgnLibraryImporter:\n'''
    text = replace_once(text, anchor, helper, "safe-open helper")

    text = replace_once(
        text,
        '''        try:\n            with open(source.path, "rb", buffering=0) as handle:\n                while True:\n''',
        '''        try:\n            fd = _open_bound_source_fd(\n                source,\n                chunk_size=limits.read_chunk_bytes,\n                accepted_games=len(spool),\n            )\n            try:\n                while True:\n''',
        "stream open",
    )
    text = replace_once(
        text,
        "                    chunk = handle.read(limits.read_chunk_bytes)\n",
        "                    chunk = os.read(fd, limits.read_chunk_bytes)\n",
        "stream read",
    )
    text = replace_once(
        text,
        '''                completed = framer.finish()\n                if completed is not None:\n                    failure = accept_frame(completed.text)\n                    if failure is not None:\n                        return failure\n        except StreamingPgnImportError:\n''',
        '''                completed = framer.finish()\n                if completed is not None:\n                    failure = accept_frame(completed.text)\n                    if failure is not None:\n                        return failure\n            finally:\n                os.close(fd)\n        except StreamingPgnImportError:\n''',
        "descriptor close",
    )

    TARGET.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
