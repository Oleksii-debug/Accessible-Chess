"""R73 build-only product evidence intake. Never issues release authorization.

The independent upstream continuum R73 verifier owns the signed evidence
semantics. This adapter pins those statements to the actual Accessible Chess
artifact and an externally approved verifier-key inventory. It is not imported
by the chess runtime, does not select a vendor, and never grants entitlements.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from continuum_runtime.protection_convergence import (
    CONTROL_LAYERS, ConvergenceDenied, LayerAttestation, evaluate_convergence,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MAX_EVIDENCE = 1024 * 1024
_MAX_TRUST = 64 * 1024
_MAX_ARTIFACT = 8 * 1024 * 1024 * 1024
_FIELDS = frozenset(LayerAttestation.__dataclass_fields__)


class ProductEvidenceError(ValueError):
    pass


def _sha256_file(path: Path, *, maximum: int) -> str:
    if not isinstance(path, Path) or type(maximum) is not int or maximum < 1:
        raise ProductEvidenceError("FILE_CONTEXT_INVALID")
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise ProductEvidenceError("FILE_MISSING_OR_UNSAFE")
        if not 0 < before.st_size <= maximum:
            raise ProductEvidenceError("FILE_SIZE_INVALID")
        digest = hashlib.sha256()
        n = 0
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
                raise ProductEvidenceError("FILE_MUTATED_DURING_REVIEW")
            while block := stream.read(1024 * 1024):
                n += len(block)
                if n > maximum:
                    raise ProductEvidenceError("FILE_SIZE_INVALID")
                digest.update(block)
            open_stat = os.fstat(stream.fileno())
        after_path = path.lstat()
        if (n != before.st_size or not os.path.samestat(before, open_stat)
                or not os.path.samestat(before, after_path)
                or (before.st_mtime_ns, before.st_ctime_ns)
                   != (open_stat.st_mtime_ns, open_stat.st_ctime_ns)
                or (before.st_mtime_ns, before.st_ctime_ns)
                   != (after_path.st_mtime_ns, after_path.st_ctime_ns)):
            raise ProductEvidenceError("FILE_MUTATED_DURING_REVIEW")
        return digest.hexdigest()
    except ProductEvidenceError:
        raise
    except OSError:
        raise ProductEvidenceError("FILE_UNAVAILABLE") from None


def _strict_json(
    path: Path, *, maximum: int,
    expected_sha256: str | None = None,
    mismatch_code: str = "EVIDENCE_DIGEST_MISMATCH",
) -> dict:
    """Parse exactly the regular-file bytes whose digest was authenticated.

    Do not hash one path lookup and parse another: swapping an independently
    pinned verifier-key inventory between those reads would replace trust.
    Both identity and content are checked on the same opened file snapshot.
    """
    if type(path) is not Path and not isinstance(path, Path):
        raise ProductEvidenceError("EVIDENCE_FILE_UNSAFE")
    if type(maximum) is not int or maximum <= 0:
        raise ProductEvidenceError("EVIDENCE_LIMIT_INVALID")
    if expected_sha256 is not None and (
        type(expected_sha256) is not str
        or not _HEX64.fullmatch(expected_sha256)
    ):
        raise ProductEvidenceError("EVIDENCE_DIGEST_INVALID")
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise ProductEvidenceError("FILE_MISSING_OR_UNSAFE")
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
                raise ProductEvidenceError("EVIDENCE_FILE_MUTATED")
            data = handle.read(maximum + 1)
            after_open = os.fstat(handle.fileno())
        after_path = path.lstat()
        if (len(data) != before.st_size or len(data) > maximum
                or not os.path.samestat(before, after_open)
                or not os.path.samestat(before, after_path)
                or (before.st_mtime_ns, before.st_ctime_ns)
                   != (after_open.st_mtime_ns, after_open.st_ctime_ns)
                or (before.st_mtime_ns, before.st_ctime_ns)
                   != (after_path.st_mtime_ns, after_path.st_ctime_ns)):
            raise ProductEvidenceError("EVIDENCE_FILE_MUTATED")
        if (expected_sha256 is not None
                and hashlib.sha256(data).hexdigest() != expected_sha256):
            raise ProductEvidenceError(mismatch_code)

        def pairs(values):
            result = {}
            for k, v in values:
                if k in result:
                    raise ProductEvidenceError("EVIDENCE_DUPLICATE_KEY")
                result[k] = v
            return result

        obj = json.loads(
            data.decode("utf-8", "strict"),
            object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except ProductEvidenceError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError):
        raise ProductEvidenceError("EVIDENCE_MALFORMED") from None
    if type(obj) is not dict:
        raise ProductEvidenceError("EVIDENCE_OBJECT_REQUIRED")
    return obj

def _digest_arg(value: str, label: str) -> str:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise ProductEvidenceError(label + "_DIGEST_INVALID")
    return value


def assess_product_release(
    *, artifact: Path, evidence: Path, approved_keys: Path,
    approved_keys_sha256: str, source_sha256: str, scope_sha256: str,
    residual_risks_sha256: str, build_id: str, channel: str, now: int | None = None,
) -> dict[str, object]:
    """A cryptographic review only; even valid physical proof is not release PASS."""
    _digest_arg(approved_keys_sha256, "KEY_INVENTORY")
    _digest_arg(source_sha256, "SOURCE")
    _digest_arg(scope_sha256, "SCOPE")
    _digest_arg(residual_risks_sha256, "RESIDUAL_RISKS")
    artifact_sha256 = _sha256_file(artifact, maximum=_MAX_ARTIFACT)
    trusted = _strict_json(
        approved_keys, maximum=_MAX_TRUST,
        expected_sha256=approved_keys_sha256,
        mismatch_code="INDEPENDENT_VERIFIER_KEY_INVENTORY_MISMATCH",
    )
    if set(trusted) != {"schema_version", "verifier_public_keys"} or type(trusted["schema_version"]) is not int or trusted["schema_version"] != 1:
        raise ProductEvidenceError("INDEPENDENT_VERIFIER_KEY_INVENTORY_INVALID")
    raw_keys = trusted["verifier_public_keys"]
    if type(raw_keys) is not dict or not 1 <= len(raw_keys) <= 32:
        raise ProductEvidenceError("INDEPENDENT_VERIFIER_KEY_INVENTORY_INVALID")
    keys = {}
    for name, token in raw_keys.items():
        if type(name) is not str or type(token) is not str or not _HEX64.fullmatch(token) or not 1 <= len(name) <= 96:
            raise ProductEvidenceError("INDEPENDENT_VERIFIER_KEY_INVENTORY_INVALID")
        keys[name] = bytes.fromhex(token)
    packet = _strict_json(evidence, maximum=_MAX_EVIDENCE)
    if set(packet) != {"schema_version", "layers"} or type(packet["schema_version"]) is not int or packet["schema_version"] != 1 or type(packet["layers"]) is not list or len(packet["layers"]) > len(CONTROL_LAYERS):
        raise ProductEvidenceError("R73_EVIDENCE_SCHEMA_INVALID")
    layers = []
    for item in packet["layers"]:
        if type(item) is not dict or set(item) != _FIELDS:
            raise ProductEvidenceError("R73_LAYER_SCHEMA_INVALID")
        layers.append(LayerAttestation(**item))
    timestamp = int(time.time()) if now is None else now
    try:
        assessment = evaluate_convergence(
            layers=layers,
            expected_source_sha256=source_sha256,
            expected_artifact_sha256=artifact_sha256,
            expected_scope_sha256=scope_sha256,
            expected_residual_risks_sha256=residual_risks_sha256,
            expected_build_id=build_id,
            expected_channel=channel,
            verifier_public_keys=keys,
            now=timestamp,
        )
    except (ConvergenceDenied, ValueError, TypeError):
        raise ProductEvidenceError("R73_INDEPENDENT_EVIDENCE_DENIED") from None
    return {
        "schema_version": 1,
        "release_approved": False,
        "status": assessment.status,
        "covered": list(assessment.covered),
        "missing": list(assessment.missing),
        "unintegrated": list(assessment.unintegrated),
        "artifact_sha256": artifact_sha256,
        "source_sha256": source_sha256,
        "build_id": build_id,
        "evidence_class": assessment.evidence_class,
        "required_next_gate": "independent_release_decision",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--trusted-keys", required=True, type=Path)
    parser.add_argument("--trusted-keys-sha256", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--scope-sha256", required=True)
    parser.add_argument("--residual-risks-sha256", required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--channel", required=True)
    args = parser.parse_args(argv)
    try:
        report = assess_product_release(
            artifact=args.artifact, evidence=args.evidence,
            approved_keys=args.trusted_keys,
            approved_keys_sha256=args.trusted_keys_sha256,
            source_sha256=args.source_sha256,
            scope_sha256=args.scope_sha256,
            residual_risks_sha256=args.residual_risks_sha256,
            build_id=args.build_id, channel=args.channel,
        )
    except ProductEvidenceError as exc:
        print(json.dumps({"release_approved": False, "status": "DENIED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    # A complete independently signed physical REPORT is still NOT a final
    # independent shipping decision. Never return process success merely
    # because the evidence review completed: build/release scripts MUST NOT
    # interpret this gate as publish permission.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
