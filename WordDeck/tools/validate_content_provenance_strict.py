#!/usr/bin/env python3
"""Strict MASS089 origin/release policy for WordDeck commercial provenance.

The base validator owns common manifest/release invariants. This module adds
origin-specific evidence requirements, referential integrity and transitive
release-rights checks that must never be inferred from technical integration,
generic terms pages, or source popularity. Commercial release tooling must
invoke this entry point with the exact shipped-content inventory.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Set

import validate_content_provenance as base


_ALLOWED_VOICE_EVIDENCE = {"voice_rights", "contract", "license_snapshot", "permission", "performer_release", "contributor_release"}
_ALLOWED_OUTPUT_EVIDENCE = {"tool_terms", "provider_terms", "output_terms", "license_snapshot", "contract", "permission"}
_ALLOWED_SPEAKER_EVIDENCE = {"performer_release", "contributor_release", "contract", "permission"}


def _evidence_types(asset: Mapping[str, Any]) -> Set[str]:
    out: Set[str] = set()
    evidence = asset.get("evidence")
    if not isinstance(evidence, list):
        return out
    for item in evidence:
        if isinstance(item, dict) and isinstance(item.get("type"), str) and item["type"].strip():
            out.add(item["type"].strip())
    return out


def _evidence_index(asset: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    out: Dict[str, Mapping[str, Any]] = {}
    evidence = asset.get("evidence")
    if not isinstance(evidence, list):
        return out
    for item in evidence:
        if not isinstance(item, dict) or not _text(item.get("evidence_id")):
            continue
        evidence_id = str(item["evidence_id"]).strip()
        if evidence_id not in out:
            out[evidence_id] = item
    return out


def _dependency_ids(asset: Mapping[str, Any]) -> Set[str]:
    out: Set[str] = set()
    dependencies = asset.get("dependencies")
    if not isinstance(dependencies, list):
        return out
    for dep in dependencies:
        if isinstance(dep, dict) and _text(dep.get("asset_id")):
            out.add(str(dep["asset_id"]).strip())
    return out


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in base.PLACEHOLDER_TOKENS


def _sha(value: Any) -> bool:
    return isinstance(value, str) and bool(base.SHA256_RE.fullmatch(value.strip().lower()))


def _notice_ids(notices_doc: Any | None) -> Set[str]:
    if not isinstance(notices_doc, dict):
        return set()
    raw = notices_doc.get("entries", notices_doc)
    if isinstance(raw, dict):
        return {str(key) for key in raw.keys()}
    if isinstance(raw, list):
        return {
            str(item["notice_id"])
            for item in raw
            if isinstance(item, dict) and _text(item.get("notice_id"))
        }
    return set()


def _asset_index(manifest: Any) -> Dict[str, Mapping[str, Any]]:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("assets"), list):
        return {}
    out: Dict[str, Mapping[str, Any]] = {}
    for asset in manifest["assets"]:
        if isinstance(asset, dict) and _text(asset.get("asset_id")):
            asset_id = str(asset["asset_id"]).strip()
            if asset_id not in out:
                out[asset_id] = asset
    return out


def _require_evidence_ref(errors: List[str], prefix: str, asset: Mapping[str, Any],
                          field_name: str, evidence_id: Any, allowed_types: Set[str]) -> None:
    if not _text(evidence_id):
        errors.append(f"{prefix}.{field_name}: required evidence reference")
        return
    ref = str(evidence_id).strip()
    evidence = _evidence_index(asset).get(ref)
    if evidence is None:
        errors.append(f"{prefix}.{field_name}: evidence reference {ref!r} is unresolved")
        return
    evidence_type = str(evidence.get("type", "")).strip()
    if evidence_type not in allowed_types:
        errors.append(
            f"{prefix}.{field_name}: evidence reference {ref!r} has incompatible type {evidence_type!r}"
        )


def _production_identity_errors(asset: Mapping[str, Any], index: int) -> List[str]:
    errors: List[str] = []
    if asset.get("status") != "CLEARED_PRODUCTION":
        return errors
    prefix = f"assets[{index}]"
    if not _text(asset.get("version")):
        errors.append(f"{prefix}.version: required production asset version")
    if not _text(asset.get("production_owner")):
        errors.append(f"{prefix}.production_owner: required production owner")
    rights = asset.get("rights") if isinstance(asset.get("rights"), dict) else {}
    if not _text(rights.get("rights_holder_or_licensor")):
        errors.append(f"{prefix}.rights.rights_holder_or_licensor: required production rightsholder/licensor")
    if not (_text(rights.get("license_id")) or _text(rights.get("agreement_id"))):
        errors.append(f"{prefix}.rights: production requires concrete license_id or agreement_id")
    if not _text(rights.get("territory")):
        errors.append(f"{prefix}.rights.territory: required production territory")
    if rights.get("sublicense_or_end_user_use") is not True:
        errors.append(f"{prefix}.rights.sublicense_or_end_user_use: must explicitly be true for end-user release")
    return errors


def _asset_errors(asset: Mapping[str, Any], index: int,
                  assets: Mapping[str, Mapping[str, Any]]) -> List[str]:
    errors: List[str] = []
    prefix = f"assets[{index}]"
    status = asset.get("status")
    origin = asset.get("origin") if isinstance(asset.get("origin"), dict) else {}
    cls = origin.get("class")
    evidence = _evidence_types(asset)
    dep_ids = _dependency_ids(asset)
    asset_id = str(asset.get("asset_id", "")).strip()

    errors.extend(_production_identity_errors(asset, index))

    # Stable evidence IDs are references elsewhere in the contract; duplicates
    # would make those references ambiguous even when the evidence payloads match.
    seen_evidence: Set[str] = set()
    raw_evidence = asset.get("evidence")
    if isinstance(raw_evidence, list):
        for evidence_index, item in enumerate(raw_evidence):
            if not isinstance(item, dict) or not _text(item.get("evidence_id")):
                continue
            evidence_id = str(item["evidence_id"]).strip()
            if evidence_id in seen_evidence:
                errors.append(f"{prefix}.evidence[{evidence_index}].evidence_id: duplicate evidence ID {evidence_id!r}")
            seen_evidence.add(evidence_id)

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
        input_ids = ai.get("input_asset_ids")
        if not isinstance(input_ids, list):
            errors.append(f"{prefix}.ai.input_asset_ids: required array for material-input traceability")
        elif not input_ids:
            errors.append(f"{prefix}.ai.input_asset_ids: material-input traceability array must not be empty")
        else:
            seen_inputs: Set[str] = set()
            for input_index, value in enumerate(input_ids):
                input_prefix = f"{prefix}.ai.input_asset_ids[{input_index}]"
                if not _text(value):
                    errors.append(f"{input_prefix}: required non-placeholder stable asset ID")
                    continue
                input_id = str(value).strip()
                if input_id in seen_inputs:
                    errors.append(f"{input_prefix}: duplicate material-input asset ID {input_id!r}")
                seen_inputs.add(input_id)
                if input_id == asset_id:
                    errors.append(f"{input_prefix}: AI asset cannot cite itself as a material input")
                if input_id not in assets:
                    errors.append(f"{input_prefix}: material-input asset {input_id!r} is unresolved in manifest")
                if input_id not in dep_ids:
                    errors.append(f"{input_prefix}: material-input asset {input_id!r} must be an explicit dependency")
        if not _sha(ai.get("output_hash_sha256")):
            errors.append(f"{prefix}.ai.output_hash_sha256: exact SHA-256 required")
        elif _sha(asset.get("content_hash_sha256")) and ai["output_hash_sha256"].lower() != str(asset["content_hash_sha256"]).lower():
            errors.append(f"{prefix}: AI output hash must equal the exact asset content hash")

    elif cls == "TTS_GENERATED":
        tts = asset.get("tts") if isinstance(asset.get("tts"), dict) else {}
        _require_evidence_ref(errors, f"{prefix}.tts", asset, "voice_rights_evidence_id",
                              tts.get("voice_rights_evidence_id"), _ALLOWED_VOICE_EVIDENCE)
        _require_evidence_ref(errors, f"{prefix}.tts", asset, "output_terms_evidence_id",
                              tts.get("output_terms_evidence_id"), _ALLOWED_OUTPUT_EVIDENCE)
        source_id = tts.get("source_text_asset_id")
        if _text(source_id):
            source_ref = str(source_id).strip()
            if source_ref not in assets:
                errors.append(f"{prefix}.tts.source_text_asset_id: source asset {source_ref!r} is unresolved in manifest")
            if source_ref not in dep_ids:
                errors.append(f"{prefix}: TTS source_text_asset_id must be an explicit dependency")

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
        _require_evidence_ref(errors, f"{prefix}.native_audio", asset, "speaker_release_evidence_id",
                              native.get("speaker_release_evidence_id"), _ALLOWED_SPEAKER_EVIDENCE)
        source_id = native.get("source_text_asset_id")
        if _text(source_id):
            source_ref = str(source_id).strip()
            if source_ref not in assets:
                errors.append(f"{prefix}.native_audio.source_text_asset_id: source asset {source_ref!r} is unresolved in manifest")
            if source_ref not in dep_ids:
                errors.append(f"{prefix}: native audio source_text_asset_id must be an explicit dependency")

    return errors


def _dependency_release_errors(root_id: str, assets: Mapping[str, Mapping[str, Any]],
                               channel: str, notice_ids: Set[str], now: dt.datetime) -> List[str]:
    """Validate the complete upstream rights chain for one shipped asset.

    The base validator validates the shipped root and manifest graph. This walk
    applies the same release-critical invariants to every transitive dependency,
    so an expired, review-failed or channel-incompatible source cannot be hidden
    behind a CLEARED_PRODUCTION immediate child.
    """
    errors: List[str] = []
    checked: Set[str] = set()

    def visit(parent_id: str, asset_id: str, stack: List[str]) -> None:
        if asset_id in stack:
            # Base validation already reports the graph cycle. Do not recurse forever.
            return
        if asset_id in checked:
            return
        checked.add(asset_id)
        asset = assets.get(asset_id)
        if asset is None:
            return
        prefix = f"release dependency {asset_id!r} required by {parent_id!r}"
        if asset.get("status") != "CLEARED_PRODUCTION":
            errors.append(f"{prefix}: status is {asset.get('status')!r}, not CLEARED_PRODUCTION")

        review = asset.get("review") if isinstance(asset.get("review"), dict) else {}
        if review.get("rights_review_state") != "PASS" or review.get("source_validation_state") != "PASS":
            errors.append(f"{prefix}: requires rights_review_state=PASS and source_validation_state=PASS")

        rights = asset.get("rights") if isinstance(asset.get("rights"), dict) else {}
        for key in ("commercial_use", "reproduce", "redistribute_to_end_users"):
            if rights.get(key) is not True:
                errors.append(f"{prefix}: required permission rights.{key}=true")
        channel_permission = base.RELEASE_CHANNEL_PERMISSION.get(channel)
        if channel_permission and rights.get(channel_permission) is not True:
            errors.append(f"{prefix}: channel {channel!r} requires rights.{channel_permission}=true")
        if rights.get("sublicense_or_end_user_use") is not True:
            errors.append(f"{prefix}: rights.sublicense_or_end_user_use must be true")

        release = asset.get("release") if isinstance(asset.get("release"), dict) else {}
        allowed = release.get("allowed_channels") if isinstance(release.get("allowed_channels"), list) else []
        if channel not in allowed:
            errors.append(f"{prefix}: channel {channel!r} absent from release.allowed_channels")

        expires = rights.get("expires_at")
        if isinstance(expires, str) and expires.strip():
            try:
                if base._parse_date_or_datetime(expires) <= now:
                    errors.append(f"{prefix}: rights expired at {expires}")
            except ValueError:
                pass

        if rights.get("attribution_required") is True:
            notice_id = release.get("third_party_notice_entry_id")
            if not _text(notice_id):
                errors.append(f"{prefix}: attribution required but no third_party_notice_entry_id")
            elif str(notice_id) not in notice_ids:
                errors.append(f"{prefix}: notice entry {notice_id!r} is unresolved")

        origin = asset.get("origin") if isinstance(asset.get("origin"), dict) else {}
        cls = origin.get("class")
        if cls == "USER_PRIVATE_BOOK":
            errors.append(f"{prefix}: private-user-book dependency is forbidden in public/commercial release")
        if cls == "COMPETITOR_RESEARCH":
            errors.append(f"{prefix}: competitor-research dependency is forbidden in public/commercial release")
        if cls == "OXFORD_REFERENCE" and origin.get("reference_only") is not False:
            errors.append(f"{prefix}: Oxford reference-only dependency cannot be distributed")

        next_stack = stack + [asset_id]
        for child_id in _dependency_ids(asset):
            visit(asset_id, child_id, next_stack)

    root = assets.get(root_id)
    if root is None:
        return errors
    for dep_id in _dependency_ids(root):
        visit(root_id, dep_id, [root_id])
    return errors


def strict_validate(manifest: Any, inventory: Any | None = None, notices_doc: Any | None = None,
                    now: dt.datetime | None = None) -> List[str]:
    errors = list(base.validate(manifest, inventory, notices_doc, now=now))
    assets = _asset_index(manifest)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("assets"), list):
        return errors
    for i, asset in enumerate(manifest["assets"]):
        if isinstance(asset, dict):
            errors.extend(_asset_errors(asset, i, assets))

    if isinstance(inventory, dict) and inventory.get("channel") in base.RELEASE_CHANNEL_PERMISSION:
        channel = str(inventory["channel"])
        moment = now or dt.datetime.now(dt.timezone.utc)
        notices = _notice_ids(notices_doc)
        release_assets = inventory.get("assets")
        if isinstance(release_assets, list):
            for item in release_assets:
                if isinstance(item, dict) and _text(item.get("asset_id")):
                    errors.extend(_dependency_release_errors(str(item["asset_id"]), assets, channel, notices, moment))
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--inventory", type=Path, help="Exact shipped commercial/public content inventory")
    parser.add_argument("--notices", type=Path, help="Machine-readable notice catalogue keyed by notice_id")
    parser.add_argument(
        "--require-inventory", action="store_true",
        help="Fail unless an exact shipped-content inventory is supplied; commercial package/release workflows must use this."
    )
    args = parser.parse_args(argv)
    if args.require_inventory and args.inventory is None:
        print("CONTENT_PROVENANCE_STRICT_FAIL: exact shipped-content inventory is required", file=sys.stderr)
        return 2
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
