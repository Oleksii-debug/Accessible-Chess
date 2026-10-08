"""R53 build-only product intake for an existing neutral protector candidate.

Checks actual file bytes and externally pinned tool/recipe/source/build identity
through the canonical neutral R53 check_candidate verifier. A candidate receipt
is never independent vendor qualification or permission to distribute an EXE.
This module is NOT imported by the shipped application.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from continuum_runtime.commercial_protector import (
    ProtectedCandidate, ProtectorError, ProtectorProfile, check_candidate,
)
from scripts.security_r73_product_evidence_gate import (
    ProductEvidenceError, _digest_arg, _sha256_file, _strict_json,
)

_MAX_IMAGE = 64 * 1024 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_PROFILE_FIELDS = frozenset(ProtectorProfile.__dataclass_fields__)
_CANDIDATE_FIELDS = frozenset(ProtectedCandidate.__dataclass_fields__)


def _safe_image(path: Path) -> bytes:
    """Read one bounded regular file, rejecting symlinks and path substitution."""
    if not isinstance(path, Path):
        raise ProductEvidenceError("R53_IMAGE_PATH_INVALID")
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= _MAX_IMAGE:
            raise ProductEvidenceError("R53_IMAGE_UNSAFE_OR_TOO_LARGE")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
                raise ProductEvidenceError("R53_IMAGE_CHANGED")
            raw = stream.read(_MAX_IMAGE + 1)
            end_handle = os.fstat(stream.fileno())
        after = path.lstat()
        if (len(raw) != before.st_size or len(raw) > _MAX_IMAGE
                or not os.path.samestat(before, end_handle)
                or not os.path.samestat(before, after)
                or (before.st_mtime_ns, before.st_ctime_ns)
                   != (end_handle.st_mtime_ns, end_handle.st_ctime_ns)
                or (before.st_mtime_ns, before.st_ctime_ns)
                   != (after.st_mtime_ns, after.st_ctime_ns)):
            raise ProductEvidenceError("R53_IMAGE_CHANGED")
        return raw
    except ProductEvidenceError:
        raise
    except OSError:
        raise ProductEvidenceError("R53_IMAGE_UNAVAILABLE") from None


def assess_protected_candidate(
    *, original: Path, protected: Path, profile_file: Path,
    candidate_file: Path, expected_source_sha256: str,
    expected_tool_sha256: str, expected_recipe_sha256: str,
    expected_build_id: str,
) -> dict[str, object]:
    """Return file-integrity evidence only; production release remains denied."""
    for name, value in (
        ("SOURCE", expected_source_sha256),
        ("TOOL", expected_tool_sha256),
        ("RECIPE", expected_recipe_sha256),
    ):
        _digest_arg(value, "R53_" + name)
    if type(expected_build_id) is not str or _ID.fullmatch(expected_build_id) is None:
        raise ProductEvidenceError("R53_BUILD_ID_INVALID")
    source_sha256 = _sha256_file(original, maximum=_MAX_IMAGE)
    if source_sha256 != expected_source_sha256:
        raise ProductEvidenceError("R53_SOURCE_DIGEST_MISMATCH")
    profile_json = _strict_json(profile_file, maximum=16 * 1024)
    candidate_json = _strict_json(candidate_file, maximum=16 * 1024)
    if set(profile_json) != _PROFILE_FIELDS or set(candidate_json) != _CANDIDATE_FIELDS:
        raise ProductEvidenceError("R53_CANDIDATE_SCHEMA_INVALID")
    if (profile_json["input_sha256"] != expected_source_sha256
            or profile_json["tool_sha256"] != expected_tool_sha256
            or profile_json["recipe_sha256"] != expected_recipe_sha256
            or profile_json["build_id"] != expected_build_id):
        raise ProductEvidenceError("R53_TRUSTED_BUILD_BINDING_MISMATCH")
    if (type(candidate_json["protected_size"]) is not int
            or candidate_json["protected_size"] < 1
            or candidate_json["release_status"]
            != "EXTERNAL_VENDOR_QUALIFICATION_REQUIRED"):
        raise ProductEvidenceError("R53_CANDIDATE_TYPE_OR_STATUS_INVALID")
    try:
        profile = ProtectorProfile(**profile_json)
        candidate = ProtectedCandidate(**candidate_json)
        protected_bytes = _safe_image(protected)
        if hashlib.sha256(protected_bytes).hexdigest() == expected_source_sha256:
            raise ProductEvidenceError("R53_UNPROTECTED_COPY")
        if check_candidate(
            profile=profile, candidate=candidate,
            protected_bytes=protected_bytes,
        ) is not True:
            raise ProductEvidenceError("R53_CANONICAL_VERIFIER_DENIED")
    except (ProtectorError, TypeError, ValueError):
        raise ProductEvidenceError("R53_CANONICAL_VERIFIER_DENIED") from None
    return {
        "schema_version": 1,
        "status": "CANDIDATE_BYTE_INTEGRITY_ONLY",
        "build_id": expected_build_id,
        "source_sha256": source_sha256,
        "protected_sha256": candidate.protected_sha256,
        "profile_sha256": profile.fingerprint(),
        "vendor": profile.vendor,
        "release_approved": False,
        "independent_vendor_qualification": "REQUIRED",
        "protected_windows_nvda_qualification": "REQUIRED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--protected", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--tool-sha256", required=True)
    parser.add_argument("--recipe-sha256", required=True)
    parser.add_argument("--build-id", required=True)
    args = parser.parse_args(argv)
    try:
        report = assess_protected_candidate(
            original=args.original, protected=args.protected,
            profile_file=args.profile, candidate_file=args.candidate,
            expected_source_sha256=args.source_sha256,
            expected_tool_sha256=args.tool_sha256,
            expected_recipe_sha256=args.recipe_sha256,
            expected_build_id=args.build_id,
        )
    except ProductEvidenceError as exc:
        print(json.dumps({"release_approved": False, "status": "DENIED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0  # Candidate inspection only, NEVER production release authorization.


if __name__ == "__main__":
    raise SystemExit(main())
