from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

from acs.slsa_provenance import (
    BUILD_TYPE,
    PREDICATE_TYPE,
    STATEMENT_TYPE,
    GithubWorkflowBuild,
    ProvenanceError,
    build_provenance_statement,
    canonical_provenance_json,
    generate_provenance_file,
    load_provenance_manifest,
    provenance_sha256,
    validate_provenance_statement,
)
from tools.generate_slsa_provenance import main

START = datetime(2026, 9, 26, 21, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 9, 26, 21, 5, 0, tzinfo=timezone.utc)
REPO = "https://github.com/Oleksii-debug/Accessible-Chess"
SOURCE = "1" * 40
ARTIFACT = "2" * 64


def workflow(event: str = "workflow_dispatch") -> GithubWorkflowBuild:
    return GithubWorkflowBuild(
        repository=REPO,
        ref="refs/heads/work/full-product-teacher-education-reachability-20260911",
        workflow_path=".github/workflows/version2-windows-package.yml",
        source_sha=SOURCE,
        builder_id=(
            REPO
            + "/.github/workflows/version2-windows-package.yml"
            + "@refs/heads/work/full-product-teacher-education-reachability-20260911"
        ),
        invocation_id=REPO + "/actions/runs/123456789/attempts/1",
        event_name=event,
        actor_id="316471245",
        repository_id="1332820974",
        repository_owner_id="316471245",
    )


class SlsaProvenanceTests(unittest.TestCase):
    def build(self, **overrides):
        values = {
            "artifact_name": "Accessible-Chess-V2.zip",
            "artifact_sha256": ARTIFACT,
            "workflow": workflow(),
            "started_on": START,
            "finished_on": END,
            "workflow_inputs": {"release": "v2"},
        }
        values.update(overrides)
        return build_provenance_statement(**values)

    def manifest(self):
        item = workflow()
        return {
            "artifact": {
                "name": "Accessible-Chess-V2.zip",
                "sha256": ARTIFACT,
            },
            "workflow": {
                "repository": item.repository,
                "ref": item.ref,
                "workflow_path": item.workflow_path,
                "source_sha": item.source_sha,
                "builder_id": item.builder_id,
                "invocation_id": item.invocation_id,
                "event_name": item.event_name,
                "actor_id": item.actor_id,
                "repository_id": item.repository_id,
                "repository_owner_id": item.repository_owner_id,
                "triggering_actor_id": None,
            },
            "started_on": "2026-09-26T21:00:00Z",
            "finished_on": "2026-09-26T21:05:00Z",
            "workflow_inputs": {"release": "v2"},
            "repository_vars": {},
            "release_parameters": {},
        }

    def test_statement_uses_approved_v1_shape_and_workflow_buildtype(self):
        statement = self.build()
        self.assertEqual(statement["_type"], STATEMENT_TYPE)
        self.assertEqual(statement["predicateType"], PREDICATE_TYPE)
        definition = statement["predicate"]["buildDefinition"]
        self.assertEqual(definition["buildType"], BUILD_TYPE)
        self.assertEqual(
            statement["subject"],
            [{
                "name": "Accessible-Chess-V2.zip",
                "digest": {"sha256": ARTIFACT},
            }],
        )
        self.assertEqual(
            definition["resolvedDependencies"][0]["digest"],
            {"gitCommit": SOURCE},
        )
        self.assertEqual(
            statement["predicate"]["runDetails"]["builder"]["id"],
            workflow().builder_id,
        )
        validate_provenance_statement(statement)

    def test_canonical_output_is_deterministic_for_mapping_order(self):
        first = self.build(workflow_inputs={"b": 2, "a": 1})
        second = self.build(workflow_inputs={"a": 1, "b": 2})
        self.assertEqual(
            canonical_provenance_json(first),
            canonical_provenance_json(second),
        )
        self.assertEqual(provenance_sha256(first), provenance_sha256(second))

    def test_unsupported_event_and_event_specific_parameters_fail_closed(self):
        with self.assertRaises(ProvenanceError):
            workflow("pull_request")
        with self.assertRaises(ProvenanceError):
            build_provenance_statement(
                artifact_name="a.zip",
                artifact_sha256=ARTIFACT,
                workflow=workflow("push"),
                started_on=START,
                finished_on=END,
                workflow_inputs={"x": "y"},
            )
        with self.assertRaises(ProvenanceError):
            build_provenance_statement(
                artifact_name="a.zip",
                artifact_sha256=ARTIFACT,
                workflow=workflow(),
                started_on=START,
                finished_on=END,
                release_parameters={"draft": False},
            )

    def test_tampering_is_rejected(self):
        statement = self.build()
        bad = deepcopy(statement)
        bad["predicate"]["buildDefinition"]["resolvedDependencies"][0][
            "digest"
        ]["gitCommit"] = "A" * 40
        with self.assertRaises(ProvenanceError):
            validate_provenance_statement(bad)

        bad = deepcopy(statement)
        bad["predicate"]["buildDefinition"]["externalParameters"]["evil"] = 1
        with self.assertRaises(ProvenanceError):
            validate_provenance_statement(bad)

        bad = deepcopy(statement)
        bad["predicate"]["runDetails"]["metadata"][
            "finishedOn"
        ] = "2026-09-26T20:00:00Z"
        with self.assertRaises(ProvenanceError):
            validate_provenance_statement(bad)

    def test_repository_artifact_time_and_json_bounds_are_strict(self):
        with self.assertRaises(ProvenanceError):
            GithubWorkflowBuild(
                repository="http://github.com/a/b",
                ref="refs/heads/main",
                workflow_path=".github/workflows/x.yml",
                source_sha=SOURCE,
                builder_id="https://github.com/a/b/.github/workflows/x.yml@refs/heads/main",
                invocation_id="https://github.com/a/b/actions/runs/1/attempts/1",
                event_name="push",
                actor_id="1",
                repository_id="2",
                repository_owner_id="1",
            )
        with self.assertRaises(ProvenanceError):
            self.build(artifact_name="../x.zip")
        with self.assertRaises(ProvenanceError):
            self.build(finished_on=START.replace(hour=20))
        with self.assertRaises(ProvenanceError):
            self.build(workflow_inputs={"x": float("nan")})

    def test_manifest_generation_is_atomic_and_deterministic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "input.json"
            output_path = root / "statement.json"
            input_path.write_text(json.dumps(self.manifest()), encoding="utf-8")
            first = generate_provenance_file(input_path, output_path)
            second = generate_provenance_file(input_path, output_path)
            self.assertEqual(first, second)
            self.assertEqual(first, output_path.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(first)["_type"], STATEMENT_TYPE)

    def test_duplicate_key_and_symlink_input_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"artifact":{},"artifact":{}}', encoding="utf-8")
            with self.assertRaisesRegex(ProvenanceError, "duplicate JSON key"):
                load_provenance_manifest(duplicate)

            real = root / "real.json"
            real.write_text(json.dumps(self.manifest()), encoding="utf-8")
            link = root / "link.json"
            try:
                link.symlink_to(real.name)
            except (OSError, NotImplementedError):
                self.skipTest("symlink unavailable")
            with self.assertRaisesRegex(ProvenanceError, "non-symlink"):
                load_provenance_manifest(link)

    def test_direct_script_execution_resolves_repo_package(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "input.json"
            output_path = root / "statement.json"
            input_path.write_text(json.dumps(self.manifest()), encoding="utf-8")
            repo_root = Path(__file__).resolve().parents[1]
            completed = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "tools" / "generate_slsa_provenance.py"),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                cwd=repo_root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(output_path.is_file())
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8"))["_type"], STATEMENT_TYPE)

    def test_cli_fails_without_publishing_invalid_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = self.manifest()
            value["artifact"]["sha256"] = "bad"
            input_path = root / "input.json"
            output_path = root / "statement.json"
            input_path.write_text(json.dumps(value), encoding="utf-8")
            self.assertEqual(
                main(["--input", str(input_path), "--output", str(output_path)]),
                2,
            )
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
