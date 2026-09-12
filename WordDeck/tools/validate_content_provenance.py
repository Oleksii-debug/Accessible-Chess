#!/usr/bin/env python3
"""Fail-closed WordDeck commercial-content provenance validator.

Implements the machine-enforceable core of WD-MASS120-089 using only the
Python standard library. Missing or unknown permission is denial; this tool
never upgrades a rights state or infers legal clearance from source popularity,
AI/TTS origin, or technical integration.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Set, Tuple

SCHEMA_VERSION = "1.0"
STATUSES = {
    "CLEARED_PRODUCTION", "CLEARED_INTERNAL_ONLY", "PRIVATE_LOCAL_ONLY",
    "QUARANTINED", "BLOCKED", "RETIRED",
}
ORIGIN_CLASSES = {
    "PROJECT_AUTHORED", "AI_ASSISTED", "TTS_GENERATED", "NATIVE_AUDIO",
    "OXFORD_REFERENCE", "TATOEBA_TEXT", "TATOEBA_AUDIO", "PUBLIC_DOMAIN",
    "LICENSED_CORPUS", "USER_PRIVATE_BOOK", "COMPETITOR_RESEARCH",
}
REVIEW_STATES = {"PASS", "FAIL", "NEEDS_COUNSEL"}
ORIGINALITY_STATES = {"PASS", "FAIL", "NA"}
SOURCE_VALIDATION_STATES = {"PASS", "FAIL"}
RELEASE_CHANNEL_PERMISSION = {
    "windows_offline": "offline_bundle",
    "downloadable_content_pack": "redistribute_to_end_users",
    "web_delivery": "web_delivery",
    "api_delivery": "api_delivery",
    "print_export": "redistribute_to_end_users",
}
PLACEHOLDER_TOKENS = {"", "...", "unknown", "tbd", "todo", "pending", "n/a?"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ValidationFailure(Exception):
    pass


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValidationFailure(f"missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationFailure(f"invalid JSON in {path}: {exc}") from exc


def _is_placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() in PLACEHOLDER_TOKENS


def _text_present(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not _is_placeholder(value)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value.strip().lower()))


def _bool_true(mapping: Mapping[str, Any], key: str) -> bool:
    # Fail closed: absent/null/non-boolean/false all deny permission.
    return mapping.get(key) is True


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _require_text(errors: List[str], prefix: str, mapping: Mapping[str, Any], key: str) -> None:
    if not _text_present(mapping.get(key)):
        errors.append(f"{prefix}.{key}: required non-placeholder text")


def _require_sha(errors: List[str], prefix: str, mapping: Mapping[str, Any], key: str) -> None:
    if not _is_sha256(mapping.get(key)):
        errors.append(f"{prefix}.{key}: required SHA-256 hex")


def _parse_date_or_datetime(value: str) -> dt.datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        parsed_date = dt.date.fromisoformat(normalized)
        parsed = dt.datetime.combine(parsed_date, dt.time.min)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _evidence_types(asset: Mapping[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for evidence in _as_list(asset.get("evidence")):
        if isinstance(evidence, dict) and _text_present(evidence.get("type")):
            out.add(str(evidence["type"]))
    return out


def _validate_evidence(errors: List[str], prefix: str, asset: Mapping[str, Any]) -> None:
    evidence = asset.get("evidence")
    if not isinstance(evidence, list):
        errors.append(f"{prefix}.evidence: required array")
        return
    for i, item in enumerate(evidence):
        ep = f"{prefix}.evidence[{i}]"
        if not isinstance(item, dict):
            errors.append(f"{ep}: required object")
            continue
        _require_text(errors, ep, item, "evidence_id")
        _require_text(errors, ep, item, "type")
        _require_text(errors, ep, item, "uri")
        _require_sha(errors, ep, item, "sha256")


def _validate_contributors(errors: List[str], prefix: str, asset: Mapping[str, Any]) -> None:
    contributors = asset.get("contributors")
    if not isinstance(contributors, list):
        errors.append(f"{prefix}.contributors: required array")
        return
    for i, contributor in enumerate(contributors):
        cp = f"{prefix}.contributors[{i}]"
        if not isinstance(contributor, dict):
            errors.append(f"{cp}: required object")
            continue
        _require_text(errors, cp, contributor, "contributor_id")
        _require_text(errors, cp, contributor, "role")
        if asset.get("status") == "CLEARED_PRODUCTION":
            _require_text(errors, cp, contributor, "agreement_id")


def _validate_review(errors: List[str], prefix: str, asset: Mapping[str, Any]) -> None:
    review = asset.get("review")
    if not isinstance(review, dict):
        errors.append(f"{prefix}.review: required object")
        return
    _require_text(errors, f"{prefix}.review", review, "rights_reviewer_id")
    if review.get("rights_review_state") not in REVIEW_STATES:
        errors.append(f"{prefix}.review.rights_review_state: invalid state")
    if review.get("editorial_originality_state") not in ORIGINALITY_STATES:
        errors.append(f"{prefix}.review.editorial_originality_state: invalid state")
    if review.get("source_validation_state") not in SOURCE_VALIDATION_STATES:
        errors.append(f"{prefix}.review.source_validation_state: invalid state")
    _require_text(errors, f"{prefix}.review", review, "reviewed_at")
    if _text_present(review.get("reviewed_at")):
        try:
            _parse_date_or_datetime(str(review["reviewed_at"]))
        except ValueError:
            errors.append(f"{prefix}.review.reviewed_at: invalid ISO date/datetime")
    # Makes MASS089 rule 13.5 machine-enforceable: a content hash change
    # invalidates prior review until the reviewer binds the new exact hash.
    _require_sha(errors, f"{prefix}.review", review, "reviewed_content_hash_sha256")
    if _is_sha256(asset.get("content_hash_sha256")) and _is_sha256(review.get("reviewed_content_hash_sha256")):
        if str(asset["content_hash_sha256"]).lower() != str(review["reviewed_content_hash_sha256"]).lower():
            errors.append(f"{prefix}: content hash differs from rights-reviewed content hash")


def _validate_origin_specific(errors: List[str], prefix: str, asset: Mapping[str, Any]) -> None:
    origin = asset.get("origin") if isinstance(asset.get("origin"), dict) else {}
    cls = origin.get("class")
    status = asset.get("status")
    evidence_types = _evidence_types(asset)

    if cls == "PROJECT_AUTHORED":
        if status == "CLEARED_PRODUCTION":
            if not _as_list(asset.get("contributors")):
                errors.append(f"{prefix}: PROJECT_AUTHORED production asset requires contributor(s)")
            if not ({"contributor_release", "contract", "rights_assignment"} & evidence_types):
                errors.append(f"{prefix}: PROJECT_AUTHORED production asset lacks contributor rights evidence")
            review = asset.get("review") if isinstance(asset.get("review"), dict) else {}
            if review.get("editorial_originality_state") != "PASS":
                errors.append(f"{prefix}: PROJECT_AUTHORED production asset requires originality PASS")

    elif cls == "AI_ASSISTED":
        ai = asset.get("ai") if isinstance(asset.get("ai"), dict) else {}
        if ai.get("used") is not True:
            errors.append(f"{prefix}.ai.used: AI_ASSISTED requires true")
        for key in ("provider", "model", "prompt_ref_or_hash", "human_editor_id", "human_contribution_summary", "similarity_review"):
            _require_text(errors, f"{prefix}.ai", ai, key)
        if not ({"tool_terms", "provider_terms"} & evidence_types):
            errors.append(f"{prefix}: AI_ASSISTED lacks tool/provider terms evidence")
        if status == "CLEARED_PRODUCTION":
            review = asset.get("review") if isinstance(asset.get("review"), dict) else {}
            if review.get("editorial_originality_state") != "PASS":
                errors.append(f"{prefix}: AI_ASSISTED production asset requires originality PASS")

    elif cls == "TTS_GENERATED":
        tts = asset.get("tts") if isinstance(asset.get("tts"), dict) else {}
        if tts.get("used") is not True:
            errors.append(f"{prefix}.tts.used: TTS_GENERATED requires true")
        for key in ("engine", "model", "model_license", "voice_id", "voice_file_hash", "voice_rights_evidence_id", "output_terms_evidence_id", "source_text_asset_id"):
            _require_text(errors, f"{prefix}.tts", tts, key)
        if _text_present(tts.get("voice_file_hash")) and not _is_sha256(tts.get("voice_file_hash")):
            errors.append(f"{prefix}.tts.voice_file_hash: required SHA-256")
        dep_ids = {d.get("asset_id") for d in _as_list(asset.get("dependencies")) if isinstance(d, dict)}
        if _text_present(tts.get("source_text_asset_id")) and tts.get("source_text_asset_id") not in dep_ids:
            errors.append(f"{prefix}: TTS source_text_asset_id must also be an explicit dependency")
        if not ({"voice_rights", "contract", "license_snapshot"} & evidence_types):
            errors.append(f"{prefix}: TTS_GENERATED lacks voice/model rights evidence")
        if not ({"tool_terms", "output_terms", "license_snapshot"} & evidence_types):
            errors.append(f"{prefix}: TTS_GENERATED lacks output/tool terms evidence")

    elif cls == "NATIVE_AUDIO":
        contributors = _as_list(asset.get("contributors"))
        if status == "CLEARED_PRODUCTION" and not any(isinstance(c, dict) and c.get("role") == "speaker" for c in contributors):
            errors.append(f"{prefix}: NATIVE_AUDIO production asset requires speaker contributor")
        if status == "CLEARED_PRODUCTION" and not ({"contributor_release", "performer_release", "contract"} & evidence_types):
            errors.append(f"{prefix}: NATIVE_AUDIO production asset lacks performer/recording rights evidence")

    elif cls == "OXFORD_REFERENCE":
        if status == "CLEARED_PRODUCTION":
            if not ({"contract", "license_snapshot", "legal_opinion"} & evidence_types):
                errors.append(f"{prefix}: OXFORD_REFERENCE cannot be production-cleared without explicit license/legal evidence")
            if origin.get("reference_only") is not False:
                errors.append(f"{prefix}.origin.reference_only: must explicitly be false for licensed/legally-cleared production use")

    elif cls == "TATOEBA_TEXT":
        t = asset.get("tatoeba") if isinstance(asset.get("tatoeba"), dict) else {}
        for key in ("english_sentence_id", "english_username", "english_license", "ukrainian_sentence_id", "ukrainian_username", "ukrainian_license"):
            _require_text(errors, f"{prefix}.tatoeba", t, key)
        _require_text(errors, f"{prefix}.origin", origin, "source_snapshot_id")
        if status == "CLEARED_PRODUCTION" and not ({"source_export", "license_snapshot"} <= evidence_types or {"source_export", "attribution_record"} <= evidence_types):
            errors.append(f"{prefix}: TATOEBA_TEXT production asset lacks source-export + license/attribution evidence")

    elif cls == "TATOEBA_AUDIO":
        t = asset.get("tatoeba") if isinstance(asset.get("tatoeba"), dict) else {}
        for key in ("audio_id", "audio_username", "audio_license", "attribution_url"):
            _require_text(errors, f"{prefix}.tatoeba", t, key)
        license_id = str(t.get("audio_license", "")).strip().lower()
        if status == "CLEARED_PRODUCTION" and (not license_id or "unknown" in license_id or "noncommercial" in license_id or "-nc" in license_id):
            errors.append(f"{prefix}: Tatoeba audio has missing/unknown/noncommercial license")

    elif cls == "PUBLIC_DOMAIN":
        pd = asset.get("public_domain") if isinstance(asset.get("public_domain"), dict) else {}
        for key in ("basis", "asserting_party"):
            _require_text(errors, f"{prefix}.public_domain", pd, key)
        if status == "CLEARED_PRODUCTION":
            if not _as_list(pd.get("jurisdictions_checked")):
                errors.append(f"{prefix}.public_domain.jurisdictions_checked: required for production")
            if pd.get("edition_translation_recording_separately_checked") is not True:
                errors.append(f"{prefix}: exact edition/translation/recording must be separately checked")

    elif cls == "LICENSED_CORPUS":
        lc = asset.get("licensed_corpus") if isinstance(asset.get("licensed_corpus"), dict) else {}
        _require_text(errors, f"{prefix}.licensed_corpus", lc, "contract_id")
        _require_text(errors, f"{prefix}.licensed_corpus", lc, "deployment_pattern")
        if status == "CLEARED_PRODUCTION" and "contract" not in evidence_types:
            errors.append(f"{prefix}: LICENSED_CORPUS production asset lacks contract evidence")

    elif cls == "USER_PRIVATE_BOOK":
        p = asset.get("private_user_book") if isinstance(asset.get("private_user_book"), dict) else {}
        if status != "PRIVATE_LOCAL_ONLY":
            errors.append(f"{prefix}: USER_PRIVATE_BOOK must be PRIVATE_LOCAL_ONLY")
        for key in ("cloud_upload_allowed", "training_allowed", "shared_corpus_allowed", "export_excerpt_default"):
            if p.get(key) is not False:
                errors.append(f"{prefix}.private_user_book.{key}: must explicitly be false")
        if p.get("user_supplied") is not True or p.get("local_only") is not True:
            errors.append(f"{prefix}: USER_PRIVATE_BOOK requires user_supplied=true and local_only=true")

    elif cls == "COMPETITOR_RESEARCH":
        if status == "CLEARED_PRODUCTION":
            errors.append(f"{prefix}: COMPETITOR_RESEARCH cannot ship as production content")
        _require_text(errors, f"{prefix}.origin", origin, "source_name")


def _validate_asset_base(errors: List[str], asset: Any, index: int) -> None:
    prefix = f"assets[{index}]"
    if not isinstance(asset, dict):
        errors.append(f"{prefix}: required object")
        return
    _require_text(errors, prefix, asset, "asset_id")
    _require_text(errors, prefix, asset, "asset_type")
    _require_text(errors, prefix, asset, "language")
    _require_sha(errors, prefix, asset, "content_hash_sha256")
    status = asset.get("status")
    if status not in STATUSES:
        errors.append(f"{prefix}.status: invalid or missing status")

    origin = asset.get("origin")
    if not isinstance(origin, dict):
        errors.append(f"{prefix}.origin: required object")
    else:
        if origin.get("class") not in ORIGIN_CLASSES:
            errors.append(f"{prefix}.origin.class: invalid or missing origin class")
        _require_text(errors, f"{prefix}.origin", origin, "source_name")
        _require_text(errors, f"{prefix}.origin", origin, "source_snapshot_id")

    rights = asset.get("rights")
    if not isinstance(rights, dict):
        errors.append(f"{prefix}.rights: required object")
    else:
        if status == "CLEARED_PRODUCTION" and rights.get("noncommercial_only") is not False:
            errors.append(f"{prefix}.rights.noncommercial_only: must explicitly be false for production")
        expires = rights.get("expires_at")
        if expires not in (None, ""):
            if not isinstance(expires, str):
                errors.append(f"{prefix}.rights.expires_at: must be null or ISO date/datetime")
            else:
                try:
                    _parse_date_or_datetime(expires)
                except ValueError:
                    errors.append(f"{prefix}.rights.expires_at: invalid ISO date/datetime")

    deps = asset.get("dependencies")
    if not isinstance(deps, list):
        errors.append(f"{prefix}.dependencies: required array")
    else:
        for j, dep in enumerate(deps):
            dp = f"{prefix}.dependencies[{j}]"
            if not isinstance(dep, dict):
                errors.append(f"{dp}: required object")
                continue
            _require_text(errors, dp, dep, "asset_id")
            _require_text(errors, dp, dep, "relationship")

    release = asset.get("release")
    if not isinstance(release, dict):
        errors.append(f"{prefix}.release: required object")
    elif not isinstance(release.get("allowed_channels"), list):
        errors.append(f"{prefix}.release.allowed_channels: required array")

    _validate_contributors(errors, prefix, asset)
    _validate_review(errors, prefix, asset)
    _validate_evidence(errors, prefix, asset)
    _validate_origin_specific(errors, prefix, asset)


def _validate_manifest_structure(manifest: Any) -> Tuple[List[str], Dict[str, Mapping[str, Any]]]:
    errors: List[str] = []
    index: Dict[str, Mapping[str, Any]] = {}
    if not isinstance(manifest, dict):
        return ["manifest: required JSON object"], index
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"manifest.schema_version: expected {SCHEMA_VERSION!r}")
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        errors.append("manifest.assets: required array")
        return errors, index
    for i, asset in enumerate(assets):
        _validate_asset_base(errors, asset, i)
        if isinstance(asset, dict) and _text_present(asset.get("asset_id")):
            asset_id = str(asset["asset_id"])
            if asset_id in index:
                errors.append(f"assets[{i}].asset_id: duplicate stable ID {asset_id!r}")
            else:
                index[asset_id] = asset

    graph: Dict[str, List[str]] = {}
    for asset_id, asset in index.items():
        dep_ids: List[str] = []
        for dep in _as_list(asset.get("dependencies")):
            if not isinstance(dep, dict) or not _text_present(dep.get("asset_id")):
                continue
            dep_id = str(dep["asset_id"])
            dep_ids.append(dep_id)
            if dep_id not in index:
                errors.append(f"asset {asset_id!r}: dependency {dep_id!r} missing from manifest")
        graph[asset_id] = dep_ids

    visiting: Set[str] = set()
    visited: Set[str] = set()

    def visit(node: str, stack: List[str]) -> None:
        if node in visiting:
            errors.append("dependency cycle: " + " -> ".join(stack + [node]))
            return
        if node in visited:
            return
        visiting.add(node)
        for dep in graph.get(node, []):
            if dep in graph:
                visit(dep, stack + [node])
        visiting.remove(node)
        visited.add(node)

    for asset_id in graph:
        visit(asset_id, [])
    return errors, index


def _validate_release_asset(errors: List[str], item: Any, item_index: int,
                            assets: Mapping[str, Mapping[str, Any]], channel: str,
                            notices: Mapping[str, Any], now: dt.datetime) -> None:
    prefix = f"release.assets[{item_index}]"
    if not isinstance(item, dict):
        errors.append(f"{prefix}: required object")
        return
    asset_id = item.get("asset_id")
    if not _text_present(asset_id):
        errors.append(f"{prefix}.asset_id: required")
        return
    asset_id = str(asset_id)
    if not _is_sha256(item.get("content_hash_sha256")):
        errors.append(f"{prefix}.content_hash_sha256: required SHA-256")
    asset = assets.get(asset_id)
    if asset is None:
        errors.append(f"{prefix}: shipped asset {asset_id!r} has no manifest entry")
        return

    manifest_hash = str(asset.get("content_hash_sha256", "")).lower()
    inventory_hash = str(item.get("content_hash_sha256", "")).lower()
    if manifest_hash != inventory_hash:
        errors.append(f"{prefix}: shipped hash differs from manifest hash for {asset_id!r}")
    if asset.get("status") != "CLEARED_PRODUCTION":
        errors.append(f"{prefix}: status is {asset.get('status')!r}, not CLEARED_PRODUCTION")

    review = asset.get("review") if isinstance(asset.get("review"), dict) else {}
    if review.get("rights_review_state") != "PASS" or review.get("source_validation_state") != "PASS":
        errors.append(f"{prefix}: release requires rights_review_state=PASS and source_validation_state=PASS")

    rights = asset.get("rights") if isinstance(asset.get("rights"), dict) else {}
    for key in ("commercial_use", "reproduce", "redistribute_to_end_users"):
        if not _bool_true(rights, key):
            errors.append(f"{prefix}: required permission rights.{key}=true")
    channel_permission = RELEASE_CHANNEL_PERMISSION.get(channel)
    if channel_permission and not _bool_true(rights, channel_permission):
        errors.append(f"{prefix}: channel {channel!r} requires rights.{channel_permission}=true")
    if item.get("requires_modification") is True and not _bool_true(rights, "modify_or_adapt"):
        errors.append(f"{prefix}: modified asset requires rights.modify_or_adapt=true")
    if item.get("requires_translation") is True and not _bool_true(rights, "translate"):
        errors.append(f"{prefix}: translated asset requires rights.translate=true")

    release = asset.get("release") if isinstance(asset.get("release"), dict) else {}
    if channel not in _as_list(release.get("allowed_channels")):
        errors.append(f"{prefix}: channel {channel!r} absent from release.allowed_channels")

    expires = rights.get("expires_at")
    if isinstance(expires, str) and expires.strip():
        try:
            if _parse_date_or_datetime(expires) <= now:
                errors.append(f"{prefix}: rights expired at {expires}")
        except ValueError:
            pass

    if rights.get("attribution_required") is True:
        notice_id = release.get("third_party_notice_entry_id")
        if not _text_present(notice_id):
            errors.append(f"{prefix}: attribution required but no third_party_notice_entry_id")
        elif str(notice_id) not in notices:
            errors.append(f"{prefix}: notice entry {notice_id!r} is unresolved")

    origin = asset.get("origin") if isinstance(asset.get("origin"), dict) else {}
    cls = origin.get("class")
    if cls == "USER_PRIVATE_BOOK":
        errors.append(f"{prefix}: private-user-book asset is forbidden in public/commercial release")
    if cls == "COMPETITOR_RESEARCH":
        errors.append(f"{prefix}: competitor-research asset is forbidden in public/commercial release")
    if cls == "OXFORD_REFERENCE" and origin.get("reference_only") is not False:
        errors.append(f"{prefix}: Oxford reference-only asset cannot be distributed")

    for dep in _as_list(asset.get("dependencies")):
        if not isinstance(dep, dict) or not _text_present(dep.get("asset_id")):
            continue
        dep_id = str(dep["asset_id"])
        dep_asset = assets.get(dep_id)
        if dep_asset is not None and dep_asset.get("status") != "CLEARED_PRODUCTION":
            errors.append(f"{prefix}: dependency {dep_id!r} is {dep_asset.get('status')!r}, not CLEARED_PRODUCTION")


def validate(manifest: Any, inventory: Any | None = None, notices_doc: Any | None = None,
             now: dt.datetime | None = None) -> List[str]:
    errors, assets = _validate_manifest_structure(manifest)
    if inventory is None:
        return errors
    if not isinstance(inventory, dict):
        return errors + ["release inventory: required JSON object"]
    channel = inventory.get("channel")
    if channel not in RELEASE_CHANNEL_PERMISSION:
        errors.append(f"release.channel: unsupported or missing channel {channel!r}")
        return errors
    release_assets = inventory.get("assets")
    if not isinstance(release_assets, list):
        errors.append("release.assets: required array")
        return errors
    if not release_assets:
        errors.append("release.assets: commercial/public content inventory must not be empty")

    notices: Dict[str, Any] = {}
    if notices_doc is not None:
        if isinstance(notices_doc, dict):
            raw_entries = notices_doc.get("entries", notices_doc)
            if isinstance(raw_entries, dict):
                notices = raw_entries
            elif isinstance(raw_entries, list):
                for entry in raw_entries:
                    if isinstance(entry, dict) and _text_present(entry.get("notice_id")):
                        notices[str(entry["notice_id"])] = entry
        else:
            errors.append("notice catalogue: required JSON object")

    seen: Set[str] = set()
    moment = now or dt.datetime.now(dt.timezone.utc)
    for i, item in enumerate(release_assets):
        if isinstance(item, dict) and _text_present(item.get("asset_id")):
            asset_id = str(item["asset_id"])
            if asset_id in seen:
                errors.append(f"release.assets[{i}].asset_id: duplicate release asset {asset_id!r}")
            seen.add(asset_id)
        _validate_release_asset(errors, item, i, assets, str(channel), notices, moment)
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--inventory", type=Path, help="Exact public/commercial release content inventory")
    parser.add_argument("--notices", type=Path, help="Machine-readable notice catalogue keyed by notice_id")
    args = parser.parse_args(argv)
    try:
        manifest = _load_json(args.manifest)
        inventory = _load_json(args.inventory) if args.inventory else None
        notices = _load_json(args.notices) if args.notices else None
        errors = validate(manifest, inventory, notices)
    except ValidationFailure as exc:
        print(f"CONTENT_PROVENANCE_FAIL: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("CONTENT_PROVENANCE_FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    mode = "release" if inventory is not None else "manifest"
    print(f"CONTENT_PROVENANCE_PASS mode={mode} assets={len(manifest.get('assets', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
