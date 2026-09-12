#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import unittest

import validate_content_provenance_strict as strict
from test_validate_content_provenance import H, project_asset, manifest, inventory


def evidence(evidence_id: str, kind: str, byte: str = "c") -> dict:
    return {"evidence_id": evidence_id, "type": kind, "uri": f"evidence://{evidence_id}", "sha256": byte * 64}


def production_asset() -> dict:
    asset = project_asset()
    asset["version"] = "1.0"
    asset["production_owner"] = "WordDeck content team"
    return asset


def ai_asset(input_ids: list[str]) -> dict:
    asset = production_asset()
    asset["asset_id"] = "wd:ai:output"
    asset["origin"]["class"] = "AI_ASSISTED"
    asset["ai"] = {
        "used": True,
        "provider": "provider",
        "model": "model",
        "prompt_ref_or_hash": "prompt-sha256:example",
        "human_editor_id": "editor",
        "human_contribution_summary": "Substantive human rewrite and review",
        "similarity_review": "PASS",
        "input_asset_ids": input_ids,
        "output_hash_sha256": H,
    }
    asset["evidence"].append(evidence("terms", "tool_terms"))
    return asset


class StrictOriginPolicyTests(unittest.TestCase):
    def test_project_authored_baseline_still_passes(self):
        asset = production_asset()
        self.assertEqual([], strict.strict_validate(manifest(asset), inventory(asset["asset_id"]), {}))

    def test_production_identity_and_rights_basis_are_mandatory(self):
        asset = production_asset()
        del asset["version"]
        del asset["production_owner"]
        del asset["rights"]["license_id"]
        del asset["rights"]["agreement_id"]
        del asset["rights"]["territory"]
        asset["rights"]["sublicense_or_end_user_use"] = False
        errors = strict.strict_validate(manifest(asset), inventory(asset["asset_id"]), {})
        self.assertTrue(any(".version" in error for error in errors), errors)
        self.assertTrue(any("production_owner" in error for error in errors), errors)
        self.assertTrue(any("license_id or agreement_id" in error for error in errors), errors)
        self.assertTrue(any("territory" in error for error in errors), errors)
        self.assertTrue(any("sublicense_or_end_user_use" in error for error in errors), errors)

    def test_oxford_generic_terms_snapshot_is_not_permission(self):
        asset = production_asset()
        asset["origin"]["class"] = "OXFORD_REFERENCE"
        asset["origin"]["reference_only"] = False
        asset["evidence"].append(evidence("oxford-terms", "license_snapshot"))
        errors = strict.strict_validate(manifest(asset), inventory(asset["asset_id"]), {})
        self.assertTrue(any("explicit OUP permission" in error for error in errors), errors)

    def test_tatoeba_text_requires_export_license_and_attribution(self):
        asset = production_asset()
        asset["origin"]["class"] = "TATOEBA_TEXT"
        asset["tatoeba"] = {
            "english_sentence_id": "1", "english_username": "en-user", "english_license": "CC BY 2.0 FR",
            "ukrainian_sentence_id": "2", "ukrainian_username": "uk-user", "ukrainian_license": "CC BY 2.0 FR",
        }
        asset["evidence"].extend([evidence("export", "source_export"), evidence("license", "license_snapshot", "d")])
        errors = strict.strict_validate(manifest(asset), inventory(asset["asset_id"]), {})
        self.assertTrue(any("attribution_record" in error for error in errors), errors)

    def test_tatoeba_audio_requires_separate_text_license_and_attribution(self):
        asset = production_asset()
        asset["origin"]["class"] = "TATOEBA_AUDIO"
        asset["tatoeba"] = {
            "audio_id": "audio-1", "audio_username": "speaker", "audio_license": "CC BY 4.0",
            "attribution_url": "https://example.invalid/audio-1",
        }
        asset["evidence"].append(evidence("license", "license_snapshot"))
        errors = strict.strict_validate(manifest(asset), inventory(asset["asset_id"]), {})
        self.assertTrue(any("source_text_license" in error for error in errors), errors)
        self.assertTrue(any("attribution_record" in error for error in errors), errors)

    def test_ai_requires_material_input_array_and_exact_output_hash(self):
        asset = production_asset()
        asset["origin"]["class"] = "AI_ASSISTED"
        asset["ai"] = {
            "used": True, "provider": "provider", "model": "model", "prompt_ref_or_hash": "prompt",
            "human_editor_id": "editor", "human_contribution_summary": "Substantive rewrite", "similarity_review": "PASS",
        }
        asset["evidence"].append(evidence("terms", "tool_terms"))
        errors = strict.strict_validate(manifest(asset))
        self.assertTrue(any("input_asset_ids" in error for error in errors), errors)
        self.assertTrue(any("output_hash_sha256" in error for error in errors), errors)

    def test_ai_empty_or_dangling_material_inputs_fail_closed(self):
        empty = ai_asset([])
        errors = strict.strict_validate(manifest(empty))
        self.assertTrue(any("must not be empty" in error for error in errors), errors)

        dangling = ai_asset(["wd:ghost:nonexistent"])
        dangling["dependencies"] = [{"asset_id": "wd:ghost:nonexistent", "relationship": "material_input"}]
        errors = strict.strict_validate(manifest(dangling))
        self.assertTrue(any("unresolved in manifest" in error for error in errors), errors)

    def test_ai_material_input_must_be_unique_nonself_and_explicit_dependency(self):
        source = production_asset()
        source["asset_id"] = "wd:source"
        asset = ai_asset(["wd:source", "wd:source", "wd:ai:output"])
        errors = strict.strict_validate(manifest(source, asset))
        self.assertTrue(any("duplicate material-input" in error for error in errors), errors)
        self.assertTrue(any("cannot cite itself" in error for error in errors), errors)
        self.assertTrue(any("must be an explicit dependency" in error for error in errors), errors)

    def test_ai_resolved_material_input_dependency_passes(self):
        source = production_asset()
        source["asset_id"] = "wd:source"
        asset = ai_asset(["wd:source"])
        asset["dependencies"] = [{"asset_id": "wd:source", "relationship": "material_input"}]
        self.assertEqual([], strict.strict_validate(manifest(source, asset), inventory(asset["asset_id"]), {}))

    def test_tts_evidence_references_must_resolve_to_compatible_evidence(self):
        source = production_asset()
        source["asset_id"] = "wd:text"
        asset = production_asset()
        asset["asset_id"] = "wd:tts"
        asset["origin"]["class"] = "TTS_GENERATED"
        asset["dependencies"] = [{"asset_id": "wd:text", "relationship": "source_text"}]
        asset["evidence"].extend([
            evidence("ev-voice", "voice_rights"),
            evidence("ev-output", "output_terms", "d"),
        ])
        asset["tts"] = {
            "used": True,
            "engine": "engine", "model": "model", "model_license": "commercial-license",
            "voice_id": "voice", "voice_file_hash": "f" * 64,
            "voice_rights_evidence_id": "ev-missing",
            "output_terms_evidence_id": "ev-output",
            "source_text_asset_id": "wd:text",
        }
        errors = strict.strict_validate(manifest(source, asset))
        self.assertTrue(any("ev-missing" in error and "unresolved" in error for error in errors), errors)
        asset["tts"]["voice_rights_evidence_id"] = "ev-voice"
        self.assertEqual([], strict.strict_validate(manifest(source, asset), inventory(asset["asset_id"]), {}))

    def test_native_audio_requires_recording_packet_and_script_dependency(self):
        asset = production_asset()
        asset["origin"]["class"] = "NATIVE_AUDIO"
        asset["contributors"] = [{"contributor_id": "speaker-1", "display_credit": "Speaker", "role": "speaker", "agreement_id": "AGR-S1"}]
        asset["evidence"].append(evidence("speaker", "performer_release"))
        errors = strict.strict_validate(manifest(asset))
        self.assertTrue(any("recording_owner" in error for error in errors), errors)
        self.assertTrue(any("master_hash_sha256" in error for error in errors), errors)
        self.assertTrue(any("voice_cloning_allowed" in error for error in errors), errors)
        self.assertTrue(any("speaker_release_evidence_id" in error for error in errors), errors)

    def test_native_audio_speaker_release_reference_must_resolve(self):
        source = production_asset()
        source["asset_id"] = "wd:script"
        asset = production_asset()
        asset["asset_id"] = "wd:native-audio"
        asset["origin"]["class"] = "NATIVE_AUDIO"
        asset["contributors"] = [{"contributor_id": "speaker-1", "display_credit": "Speaker", "role": "speaker", "agreement_id": "AGR-S1"}]
        asset["evidence"].append(evidence("speaker", "performer_release"))
        asset["dependencies"] = [{"asset_id": "wd:script", "relationship": "source_text"}]
        asset["native_audio"] = {
            "recording_owner": "WordDeck",
            "source_text_asset_id": "wd:script",
            "speaker_release_evidence_id": "missing-release",
            "master_hash_sha256": H,
            "voice_cloning_allowed": False,
            "ai_training_allowed": False,
        }
        errors = strict.strict_validate(manifest(source, asset))
        self.assertTrue(any("missing-release" in error and "unresolved" in error for error in errors), errors)
        asset["native_audio"]["speaker_release_evidence_id"] = "speaker"
        self.assertEqual([], strict.strict_validate(manifest(source, asset), inventory(asset["asset_id"]), {}))

    def test_transitive_dependency_expiry_and_channel_incompatibility_propagate(self):
        source = production_asset()
        source["asset_id"] = "wd:source"
        source["rights"]["expires_at"] = "2026-01-01T00:00:00Z"
        source["release"]["allowed_channels"] = []
        derived = production_asset()
        derived["asset_id"] = "wd:derived"
        derived["dependencies"] = [{"asset_id": "wd:source", "relationship": "derived_from"}]
        errors = strict.strict_validate(
            manifest(source, derived), inventory("wd:derived"), {},
            now=dt.datetime(2026, 9, 12, tzinfo=dt.timezone.utc),
        )
        self.assertTrue(any("release dependency 'wd:source'" in error and "rights expired" in error for error in errors), errors)
        self.assertTrue(any("release dependency 'wd:source'" in error and "allowed_channels" in error for error in errors), errors)

    def test_deep_blocked_dependency_propagates_to_shipped_asset(self):
        blocked = production_asset()
        blocked["asset_id"] = "wd:blocked"
        blocked["status"] = "BLOCKED"
        middle = production_asset()
        middle["asset_id"] = "wd:middle"
        middle["dependencies"] = [{"asset_id": "wd:blocked", "relationship": "source"}]
        top = production_asset()
        top["asset_id"] = "wd:top"
        top["dependencies"] = [{"asset_id": "wd:middle", "relationship": "source"}]
        errors = strict.strict_validate(manifest(blocked, middle, top), inventory("wd:top"), {})
        self.assertTrue(any("release dependency 'wd:blocked'" in error and "not CLEARED_PRODUCTION" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
