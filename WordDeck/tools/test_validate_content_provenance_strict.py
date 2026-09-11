#!/usr/bin/env python3
from __future__ import annotations

import unittest

import validate_content_provenance_strict as strict
from test_validate_content_provenance import project_asset, manifest, inventory


def evidence(evidence_id: str, kind: str, byte: str = "c") -> dict:
    return {"evidence_id": evidence_id, "type": kind, "uri": f"evidence://{evidence_id}", "sha256": byte * 64}


class StrictOriginPolicyTests(unittest.TestCase):
    def test_project_authored_baseline_still_passes(self):
        asset = project_asset()
        self.assertEqual([], strict.strict_validate(manifest(asset), inventory(asset["asset_id"]), {}))

    def test_oxford_generic_terms_snapshot_is_not_permission(self):
        asset = project_asset()
        asset["origin"]["class"] = "OXFORD_REFERENCE"
        asset["origin"]["reference_only"] = False
        asset["evidence"].append(evidence("oxford-terms", "license_snapshot"))
        errors = strict.strict_validate(manifest(asset), inventory(asset["asset_id"]), {})
        self.assertTrue(any("explicit OUP permission" in error for error in errors), errors)

    def test_tatoeba_text_requires_export_license_and_attribution(self):
        asset = project_asset()
        asset["origin"]["class"] = "TATOEBA_TEXT"
        asset["tatoeba"] = {
            "english_sentence_id": "1", "english_username": "en-user", "english_license": "CC BY 2.0 FR",
            "ukrainian_sentence_id": "2", "ukrainian_username": "uk-user", "ukrainian_license": "CC BY 2.0 FR",
        }
        asset["evidence"].extend([evidence("export", "source_export"), evidence("license", "license_snapshot", "d")])
        errors = strict.strict_validate(manifest(asset), inventory(asset["asset_id"]), {})
        self.assertTrue(any("attribution_record" in error for error in errors), errors)

    def test_tatoeba_audio_requires_separate_text_license_and_attribution(self):
        asset = project_asset()
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
        asset = project_asset()
        asset["origin"]["class"] = "AI_ASSISTED"
        asset["ai"] = {
            "used": True, "provider": "provider", "model": "model", "prompt_ref_or_hash": "prompt",
            "human_editor_id": "editor", "human_contribution_summary": "Substantive rewrite", "similarity_review": "PASS",
        }
        asset["evidence"].append(evidence("terms", "tool_terms"))
        errors = strict.strict_validate(manifest(asset))
        self.assertTrue(any("input_asset_ids" in error for error in errors), errors)
        self.assertTrue(any("output_hash_sha256" in error for error in errors), errors)

    def test_native_audio_requires_recording_packet_and_script_dependency(self):
        asset = project_asset()
        asset["origin"]["class"] = "NATIVE_AUDIO"
        asset["contributors"] = [{"contributor_id": "speaker-1", "display_credit": "Speaker", "role": "speaker", "agreement_id": "AGR-S1"}]
        asset["evidence"].append(evidence("speaker", "performer_release"))
        errors = strict.strict_validate(manifest(asset))
        self.assertTrue(any("recording_owner" in error for error in errors), errors)
        self.assertTrue(any("master_hash_sha256" in error for error in errors), errors)
        self.assertTrue(any("voice_cloning_allowed" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main(verbosity=2)
