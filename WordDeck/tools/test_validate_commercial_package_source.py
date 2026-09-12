#!/usr/bin/env python3
"""Regression tests for the authorized WordDeck commercial package-source contract."""
from __future__ import annotations

import copy
import unittest

from validate_commercial_package_source import SourceContractFailure, validate_source_contract


RUN_ID = 123456789
WORKFLOW = ".github/workflows/worddeck-package-recovery.yml"
BRANCH = "worddeck-bootstrap"
SHA = "a" * 40
ARTIFACT = "worddeck-windows-release-candidate"


def valid_run():
    return {
        "id": RUN_ID,
        "path": WORKFLOW,
        "head_branch": BRANCH,
        "head_sha": SHA,
        "conclusion": "success",
    }


def valid_artifacts():
    return [{"id": 987654321, "name": ARTIFACT, "expired": False}]


class CommercialPackageSourceContractTests(unittest.TestCase):
    def validate(self, run=None, artifacts=None, **kwargs):
        return validate_source_contract(
            valid_run() if run is None else run,
            valid_artifacts() if artifacts is None else artifacts,
            expected_run_id=kwargs.get("expected_run_id", RUN_ID),
            expected_workflow_path=kwargs.get("expected_workflow_path", WORKFLOW),
            expected_branch=kwargs.get("expected_branch", BRANCH),
            expected_sha=kwargs.get("expected_sha", SHA),
            expected_artifact_name=kwargs.get("expected_artifact_name", ARTIFACT),
        )

    def test_authorized_package_producer_passes(self):
        result = self.validate()
        self.assertEqual(result["workflow_path"], WORKFLOW)
        self.assertEqual(result["artifact_name"], ARTIFACT)

    def test_successful_non_packaging_worddeck_workflow_is_rejected(self):
        run = valid_run()
        run["path"] = ".github/workflows/worddeck-dev04-grammar.yml"
        with self.assertRaises(SourceContractFailure):
            self.validate(run=run)

    def test_wrong_artifact_name_is_rejected(self):
        artifacts = valid_artifacts()
        artifacts[0]["name"] = "some-other-successful-artifact"
        with self.assertRaises(SourceContractFailure):
            self.validate(artifacts=artifacts)

    def test_duplicate_fixed_artifact_is_rejected(self):
        artifacts = valid_artifacts() + copy.deepcopy(valid_artifacts())
        artifacts[1]["id"] += 1
        with self.assertRaises(SourceContractFailure):
            self.validate(artifacts=artifacts)

    def test_source_sha_mismatch_is_rejected(self):
        run = valid_run()
        run["head_sha"] = "b" * 40
        with self.assertRaises(SourceContractFailure):
            self.validate(run=run)

    def test_unsuccessful_run_is_rejected(self):
        run = valid_run()
        run["conclusion"] = "failure"
        with self.assertRaises(SourceContractFailure):
            self.validate(run=run)

    def test_wrong_branch_is_rejected(self):
        run = valid_run()
        run["head_branch"] = "main"
        with self.assertRaises(SourceContractFailure):
            self.validate(run=run)

    def test_expired_artifact_is_rejected(self):
        artifacts = valid_artifacts()
        artifacts[0]["expired"] = True
        with self.assertRaises(SourceContractFailure):
            self.validate(artifacts=artifacts)

    def test_invalid_expected_sha_is_rejected(self):
        with self.assertRaises(SourceContractFailure):
            self.validate(expected_sha="not-a-sha")


if __name__ == "__main__":
    unittest.main()
