#!/usr/bin/env python3
"""Strict MASS089 origin-policy layer for WordDeck commercial provenance.

The base validator owns common manifest/release invariants. This module adds
origin-specific evidence requirements that must never be inferred from a
technical integration, generic terms page, or source popularity. Commercial
release tooling should invoke this entry point.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any, List, Mapping, Sequence, Set

import validate_content_provenance as base


def _evidence_types(asset: Mapping[str, Any]) -> Set[str]:
    out: Set[str] = set()
    evidence = asset.get("evidence")
    if not isinstance(evidence, list):
        return out
    for item in evidence:
        if isinstance(item, dict) and isinstance(item.get("type"), str) and item["type"].strip():
            out.add(item["type"].strip())
    return out


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in base.PLACEHOLDER_TOKENS


def _sha(value: Any) -> bool:
    return isinstance(value, str) and bool(base.SHA256_RE.fullmatch(value.strip().lower()))


def _asset_errors(asset: Mapping[str, Any], index: int) -> List[str]:
    errors: List[str] = []
    prefix = f"assets[{index}]"
    status = asset.get("status")
    origin = asset.get("origin") if isinstance(asset.get("origin"), dict) else {}
    cls = origin.get("class")
    evidence = _evidence_types(asset)

    if cls == "OXFORD_REFERENCE" and status == "CLEARED_PRODUCTION":
        if not ({"contract", "permission", "legal_opinion"} & evidence):
            errors.append(
                f"{prefix}: OXFORD_REFERENCE production clearance requires explicit OUP permission/license contract or scoped legal opinion; a generic terms/license snapshot is not permission"
            )

    elif cls == "TATOEBA_TEXT" and status == "CLEARED_PRODUCTION":
        required = {"source_export", "license_snapshot", "attribution_record"}
        missing = sorted(required - evidence)
        if missing:
            errors.append(f"{prefix}: TATOEBA_TEXT production evidence missing: {', '.join(missing)}")

    elif cls == "TATOEBA_AUDIO" and status == "CLEARED_PRODUCTION":
        t = asset.get("tatoeba") if isinstance(asset.get("tatoeba"), dict) else {}
        if not _text(t.get("source_text_license")):
            errors.append(f"{prefix}.tatoeba.source_text_license: explicit source-text license required")
        license_id = str(t.get("audio_license", "")).strip().lower()
        if not license_id or "unknown" in license_id or "noncommercial" in license_id or "-nc" in license_id:
            errors.append(f"{prefix}: Tatoeba audio has missing/unknown/noncommercial audio license")
        required = {"license_snapshot", "attribution_record"}
        missing = sorted(required - evidence)
        if missing:
            errors.append(f"{prefix}: TATOEBA_AUDIO production evidence missing: {', '.join(missing)}")

    elif cls == "AI_ASSISTED":
        ai = asset.get("ai") if isinstance(asset.get("ai"), dict) else {}
        if not isinstance(ai.get("input_asset_ids"), list):
            errors.append(f"{prefix}.ai.input_asset_ids: required array for material-input traceability")
        if not _sha(ai.get("output_hash_sha256")):
            errors.append(f"{prefix}.ai.output_hash_sha256: exact SHA-256 required")
        elif _sha(asset.get("content_hash_sha256")) and ai["output_hash_sha256"].lower() != str(asset["content_hash_sha256"]).lower():
            errors.append(f"{prefix}: AI output hash must equal the exact asset content hash")

    elif cls == "NATIVE_AUDIO" and status == "CLEARED_PRODUCTION":
        native = asset.get("native_audio") if isinstance(asset.get("native_audio"), dict) else {}
        for key in ("recording_owner", "source_text_asset_id", "speaker_release_evidence_id"):
            if not _text(native.get(key)):
                errors.append(f"{prefix}.native_audio.{key}: required")
        if not _sha(native.get("master_hash_sha256")):
            errors.append(f"{prefix}.native_audio.master_hash_sha256: exact SHA-256 required")
        for key in ("voice_cloning_allowed", "ai_training_allowed"):
            if native.get(key) not in (True, False):
                errors.append(f"{prefix}.native_audio.{key}: explicit boolean required")
        dep_ids = {
            dep.get("asset_id") for dep in asset.get("dependencies", [])
            if isinstance(dep, dict) and isinstance(dep.get("asset_id"), str)
        } if isinstance(asset.get("dependencies"), list) else set()
        if _text(native.get("source_text_asset_id")) and native.get("source_text_asset_id") not in dep_ids:
            errors.append(f"{prefix}: native audio source_text_asset_id must be an explicit dependency")

    return errors


def strict_validate(manifest: Any, inventory: Any | None = None, notices_doc: Any | None = None,
                    now: dt.datetime | None = None) -> List[str]:
    errors = list(base.validate(manifest, inventory, notices_doc, now=now))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("assets"), list):
        return errors
    for i, asset in enumerate(manifest["assets"]):
        if isinstance(asset, dict):
            errors.extend(_asset_errors(asset, i))
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--notices", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = base._load_json(args.manifest)
        inventory = base._load_json(args.inventory) if args.inventory else None
        notices = base._load_json(args.notices) if args.notices else None
        errors = strict_validate(manifest, inventory, notices)
    except base.ValidationFailure as exc:
        print(f"CONTENT_PROVENANCE_STRICT_FAIL: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("CONTENT_PROVENANCE_STRICT_FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    mode = "release" if inventory is not None else "manifest"
    print(f"CONTENT_PROVENANCE_STRICT_PASS mode={mode} assets={len(manifest.get('assets', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
