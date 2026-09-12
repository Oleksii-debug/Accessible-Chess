#!/usr/bin/env python3
from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import pathlib
import unittest

MODULE_PATH = pathlib.Path(__file__).with_name("validate_content_provenance.py")
spec = importlib.util.spec_from_file_location("validate_content_provenance", MODULE_PATH)
validator = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(validator)

H = "a" * 64
E = "b" * 64


def project_asset() -> dict:
    return {
        "asset_id": "wd:lesson:starter:m01:l01:exercise:001",
        "asset_type": "exercise",
        "language": "en",
        "content_hash_sha256": H,
        "status": "CLEARED_PRODUCTION",
        "origin": {
            "class": "PROJECT_AUTHORED",
            "source_name": "WordDeck project-authored content",
            "source_record_ids": [],
            "source_urls": [],
            "source_snapshot_id": "drive-revision:exact-1",
            "acquisition_method": "project_authorship",
            "acquired_at": "2026-09-11T20:00:00Z"
        },
        "rights": {
            "rights_holder_or_licensor": "WordDeck project",
            "license_id": "PROJECT-CONTRIBUTOR-AGREEMENT",
            "license_version": "1",
            "license_url": None,
            "agreement_id": "AGR-001",
            "commercial_use": True,
            "reproduce": True,
            "redistribute_to_end_users": True,
            "modify_or_adapt": True,
            "translate": True,
            "offline_bundle": True,
            "web_delivery": False,
            "api_delivery": False,
            "sublicense_or_end_user_use": True,
            "ai_training": False,
            "territory": "worldwide",
            "expires_at": None,
            "attribution_required": False,
            "share_alike": False,
            "noncommercial_only": False,
            "no_derivatives": False,
            "notice_template_id": None
        },
        "contributors": [{
            "contributor_id": "author-001",
            "display_credit": "",
            "role": "author",
            "agreement_id": "AGR-001"
        }],
        "dependencies": [],
        "ai": {"used": False},
        "tts": {"used": False},
        "tatoeba": {},
        "public_domain": {},
        "licensed_corpus": {},
        "private_user_book": {},
        "review": {
            "rights_reviewer_id": "rights-reviewer-001",
            "rights_review_state": "PASS",
            "editorial_originality_state": "PASS",
            "source_validation_state": "PASS",
            "reviewed_at": "2026-09-11T21:00:00Z",
            "reviewed_content_hash_sha256": H,
            "notes": "Exact asset reviewed."
        },
        "evidence": [{
            "evidence_id": "ev-agr-001",
            "type": "contributor_release",
            "uri": "drive://agreements/AGR-001",
            "sha256": E
        }],
        "release": {
            "allowed_channels": ["windows_offline"],
            "third_party_notice_entry_id": None,
            "credits_entry_id": None,
            "first_cleared_release": "1.0",
            "last_revalidated_release": "1.0"
        }
    }


def manifest(*assets: dict) -> dict:
    return {"schema_version": "1.0", "assets": list(assets)}


def inventory(asset_id: str, hash_value: str = H) -> dict:
    return {
        "release_id": "worddeck-commercial-test",
        "channel": "windows_offline",
        "assets": [{"asset_id": asset_id, "content_hash_sha256": hash_value}]
    }


class ContentProvenanceTests(unittest.TestCase):
    def test_minimal_project_asset_release_passes(self):
        asset = project_asset()
        self.assertEqual([], validator.validate(manifest(asset), inventory(asset["asset_id"]), {}))

    def test_missing_permission_defaults_to_denial(self):
        asset = project_asset()
        del asset["rights"]["commercial_use"]
        errors = validator.validate(manifest(asset), inventory(asset["asset_id"]), {})
        self.assertTrue(any("commercial_use" in e for e in errors), errors)

    def test_hash_change_invalidates_review_and_release(self):
        asset = project_asset()
        asset["content_hash_sha256"] = "c" * 64
        errors = validator.validate(manifest(asset), inventory(asset["asset_id"], "c" * 64), {})
        self.assertTrue(any("rights-reviewed content hash" in e for e in errors), errors)

    def test_release_hash_mismatch_fails(self):
        asset = project_asset()
        errors = validator.validate(manifest(asset), inventory(asset["asset_id"], "d" * 64), {})
        self.assertTrue(any("shipped hash differs" in e for e in errors), errors)

    def test_quarantined_asset_cannot_ship(self):
        asset = project_asset()
        asset["status"] = "QUARANTINED"
        errors = validator.validate(manifest(asset), inventory(asset["asset_id"]), {})
        self.assertTrue(any("not CLEARED_PRODUCTION" in e for e in errors), errors)

    def test_unknown_release_asset_fails(self):
        asset = project_asset()
        errors = validator.validate(manifest(asset), inventory("wd:missing"), {})
        self.assertTrue(any("no manifest entry" in e for e in errors), errors)

    def test_empty_release_inventory_fails(self):
        asset = project_asset()
        inv = {"release_id": "x", "channel": "windows_offline", "assets": []}
        errors = validator.validate(manifest(asset), inv, {})
        self.assertTrue(any("must not be empty" in e for e in errors), errors)

    def test_required_notice_must_resolve(self):
        asset = project_asset()
        asset["rights"]["attribution_required"] = True
        asset["release"]["third_party_notice_entry_id"] = "notice-1"
        errors = validator.validate(manifest(asset), inventory(asset["asset_id"]), {})
        self.assertTrue(any("unresolved" in e for e in errors), errors)
        self.assertEqual([], validator.validate(
            manifest(asset), inventory(asset["asset_id"]),
            {"entries": {"notice-1": {"text": "Credit"}}}
        ))

    def test_expired_rights_fail_release(self):
        asset = project_asset()
        asset["rights"]["expires_at"] = "2026-01-01T00:00:00Z"
        errors = validator.validate(
            manifest(asset), inventory(asset["asset_id"]), {},
            now=dt.datetime(2026, 9, 11, tzinfo=dt.timezone.utc)
        )
        self.assertTrue(any("rights expired" in e for e in errors), errors)

    def test_dependency_must_exist_and_be_production_cleared(self):
        source = project_asset()
        source["asset_id"] = "wd:source"
        source["status"] = "CLEARED_INTERNAL_ONLY"
        derived = project_asset()
        derived["asset_id"] = "wd:derived"
        derived["dependencies"] = [{"asset_id": "wd:source", "relationship": "derived_from"}]
        errors = validator.validate(manifest(source, derived), inventory("wd:derived"), {})
        self.assertTrue(any("dependency 'wd:source'" in e and "not CLEARED_PRODUCTION" in e for e in errors), errors)

    def test_dependency_cycle_fails(self):
        a = project_asset()
        a["asset_id"] = "wd:a"
        a["dependencies"] = [{"asset_id": "wd:b", "relationship": "contains"}]
        b = project_asset()
        b["asset_id"] = "wd:b"
        b["dependencies"] = [{"asset_id": "wd:a", "relationship": "contains"}]
        errors = validator.validate(manifest(a, b))
        self.assertTrue(any("dependency cycle" in e for e in errors), errors)

    def test_private_user_book_is_always_local_only(self):
        asset = project_asset()
        asset["origin"]["class"] = "USER_PRIVATE_BOOK"
        asset["status"] = "PRIVATE_LOCAL_ONLY"
        asset["private_user_book"] = {
            "user_supplied": True,
            "local_only": True,
            "cloud_upload_allowed": False,
            "training_allowed": False,
            "shared_corpus_allowed": False,
            "export_excerpt_default": False
        }
        self.assertEqual([], validator.validate(manifest(asset)))
        errors = validator.validate(manifest(asset), inventory(asset["asset_id"]), {})
        self.assertTrue(any("private-user-book" in e for e in errors), errors)

    def test_oxford_reference_does_not_self_clear(self):
        asset = project_asset()
        asset["origin"]["class"] = "OXFORD_REFERENCE"
        asset["origin"]["reference_only"] = True
        errors = validator.validate(manifest(asset), inventory(asset["asset_id"]), {})
        self.assertTrue(any("Oxford" in e or "OXFORD_REFERENCE" in e for e in errors), errors)

    def test_tts_requires_source_dependency_and_rights_packet(self):
        asset = project_asset()
        asset["origin"]["class"] = "TTS_GENERATED"
        asset["tts"] = {
            "used": True,
            "engine": "engine",
            "model": "model",
            "model_license": "Apache-2.0",
            "voice_id": "voice",
            "voice_file_hash": "f" * 64,
            "voice_rights_evidence_id": "ev-voice",
            "output_terms_evidence_id": "ev-output",
            "source_text_asset_id": "wd:text"
        }
        errors = validator.validate(manifest(asset))
        self.assertTrue(any("source_text_asset_id" in e or "missing from manifest" in e for e in errors), errors)
        self.assertTrue(any("voice/model rights evidence" in e for e in errors), errors)

    def test_duplicate_asset_id_fails(self):
        a = project_asset()
        b = copy.deepcopy(a)
        errors = validator.validate(manifest(a, b))
        self.assertTrue(any("duplicate stable ID" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
