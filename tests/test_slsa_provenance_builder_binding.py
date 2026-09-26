from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.generate_slsa_provenance import main


class SlsaProvenanceBuilderBindingTests(unittest.TestCase):
    def _manifest(self) -> dict[str, object]:
        repository = "https://github.com/Oleksii-debug/Accessible-Chess"
        ref = "refs/heads/work/full-product-teacher-education-reachability-20260911"
        workflow_path = ".github/workflows/version2-windows-package.yml"
        return {
            "artifact": {
                "name": "Accessible-Chess-V2.zip",
                "sha256": "2" * 64,
            },
            "workflow": {
                "repository": repository,
                "ref": ref,
                "workflow_path": workflow_path,
                "source_sha": "1" * 40,
                "builder_id": f"{repository}/{workflow_path}@{ref}",
                "invocation_id": f"{repository}/actions/runs/123456789/attempts/1",
                "event_name": "workflow_dispatch",
                "actor_id": "316471245",
                "repository_id": "1332820974",
                "repository_owner_id": "316471245",
                "triggering_actor_id": None,
            },
            "started_on": "2026-09-26T21:00:00Z",
            "finished_on": "2026-09-26T21:05:00Z",
            "workflow_inputs": {"release": "v2"},
            "repository_vars": {},
            "release_parameters": {},
        }

    def _run(self, manifest: dict[str, object]) -> tuple[int, bool]:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.json"
            output = root / "statement.json"
            source.write_text(json.dumps(manifest), encoding="utf-8")
            code = main(["--input", str(source), "--output", str(output)])
            return code, output.exists()

    def test_builder_repository_path_and_ref_must_match_declared_source(self) -> None:
        mutations = (
            "https://github.com/example/other/.github/workflows/version2-windows-package.yml@refs/heads/work/full-product-teacher-education-reachability-20260911",
            "https://github.com/Oleksii-debug/Accessible-Chess/.github/workflows/other.yml@refs/heads/work/full-product-teacher-education-reachability-20260911",
            "https://github.com/Oleksii-debug/Accessible-Chess/.github/workflows/version2-windows-package.yml@refs/tags/v2",
        )
        for builder_id in mutations:
            with self.subTest(builder_id=builder_id):
                manifest = self._manifest()
                manifest["workflow"]["builder_id"] = builder_id  # type: ignore[index]
                self.assertEqual(self._run(manifest), (2, False))

    def test_exact_builder_source_tuple_still_generates(self) -> None:
        self.assertEqual(self._run(self._manifest()), (0, True))


if __name__ == "__main__":
    unittest.main()
