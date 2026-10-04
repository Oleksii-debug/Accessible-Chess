from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts.verify_owner_w4_run_provenance import (
    DEFAULT_W4_WORKFLOW_PATH,
    W4RunProvenanceError,
    main,
    validate_w4_run_provenance,
)


RUN_ID = 37174317097
WORKFLOW_ID = 123456789
WORKFLOW_SHA = "a" * 40
PRODUCT_SHA = "b" * 40
REPOSITORY = "Oleksii-debug/Accessible-Chess"
DEFAULT_BRANCH = "main"


def _run(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "id": RUN_ID,
        "workflow_id": WORKFLOW_ID,
        "run_attempt": 2,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "head_branch": DEFAULT_BRANCH,
        "head_sha": WORKFLOW_SHA,
        "path": DEFAULT_W4_WORKFLOW_PATH,
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
    }
    value.update(overrides)
    return value


class OwnerW4RunProvenanceTests(unittest.TestCase):
    def test_accepts_successful_dispatch_and_keeps_workflow_sha_separate_from_product(self) -> None:
        provenance = validate_w4_run_provenance(
            _run(),
            expected_run_id=RUN_ID,
            expected_repository=REPOSITORY,
            expected_branch=DEFAULT_BRANCH,
        )
        self.assertEqual(provenance.workflow_sha, WORKFLOW_SHA)
        self.assertNotEqual(provenance.workflow_sha, PRODUCT_SHA)
        self.assertEqual(provenance.workflow_id, WORKFLOW_ID)
        self.assertEqual(provenance.run_attempt, 2)

    def test_accepts_exact_branch_authority_suffix_on_workflow_path(self) -> None:
        value = _run(
            path=f"{DEFAULT_W4_WORKFLOW_PATH}@refs/heads/{DEFAULT_BRANCH}"
        )
        provenance = validate_w4_run_provenance(
            value,
            expected_run_id=RUN_ID,
            expected_repository=REPOSITORY,
            expected_branch=DEFAULT_BRANCH,
        )
        self.assertEqual(provenance.workflow_path, DEFAULT_W4_WORKFLOW_PATH)

    def test_rejects_wrong_run_id_repository_or_head_repository(self) -> None:
        cases = (
            (_run(id=RUN_ID + 1), "requested run"),
            (_run(repository={"full_name": "attacker/fork"}), "repository provenance"),
            (_run(head_repository={"full_name": "attacker/fork"}), "repository provenance"),
        )
        for value, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                W4RunProvenanceError,
                message,
            ):
                validate_w4_run_provenance(
                    value,
                    expected_run_id=RUN_ID,
                    expected_repository=REPOSITORY,
                    expected_branch=DEFAULT_BRANCH,
                )

    def test_rejects_noncanonical_workflow_path_or_branch_authority(self) -> None:
        cases = (
            (_run(path=".github/workflows/not-w4.yml"), "canonical workflow path"),
            (
                _run(path=f"{DEFAULT_W4_WORKFLOW_PATH}@refs/heads/attacker"),
                "workflow path authority",
            ),
            (_run(path=f"{DEFAULT_W4_WORKFLOW_PATH}@refs/tags/v1"), "workflow path authority"),
            (_run(head_branch="feature/not-default"), "head branch"),
        )
        for value, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                W4RunProvenanceError,
                message,
            ):
                validate_w4_run_provenance(
                    value,
                    expected_run_id=RUN_ID,
                    expected_repository=REPOSITORY,
                    expected_branch=DEFAULT_BRANCH,
                )

    def test_rejects_non_dispatch_nonterminal_or_unsuccessful_run(self) -> None:
        cases = (
            (_run(event="push"), "workflow_dispatch"),
            (_run(status="in_progress"), "must be completed"),
            (_run(conclusion="failure"), "must be success"),
        )
        for value, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                W4RunProvenanceError,
                message,
            ):
                validate_w4_run_provenance(
                    value,
                    expected_run_id=RUN_ID,
                    expected_repository=REPOSITORY,
                    expected_branch=DEFAULT_BRANCH,
                )

    def test_rejects_malformed_or_uppercase_workflow_sha(self) -> None:
        for sha in ("a" * 39, "A" * 40, "g" * 40):
            with self.subTest(sha=sha), self.assertRaisesRegex(
                W4RunProvenanceError,
                "lowercase exact 40-hex",
            ):
                validate_w4_run_provenance(
                    _run(head_sha=sha),
                    expected_run_id=RUN_ID,
                    expected_repository=REPOSITORY,
                    expected_branch=DEFAULT_BRANCH,
                )

    def test_rejects_boolean_or_nonpositive_numeric_authorities(self) -> None:
        for field, value in (
            ("id", True),
            ("workflow_id", False),
            ("workflow_id", 0),
            ("run_attempt", 0),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(
                W4RunProvenanceError
            ):
                validate_w4_run_provenance(
                    _run(**{field: value}),
                    expected_run_id=RUN_ID,
                    expected_repository=REPOSITORY,
                    expected_branch=DEFAULT_BRANCH,
                )

    def test_cli_writes_only_validated_authority_to_github_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            run_json = root / "run.json"
            output = root / "github-output.txt"
            run_json.write_text(json.dumps(_run()), encoding="utf-8")
            result = main(
                [
                    "--run-json",
                    str(run_json),
                    "--run-id",
                    str(RUN_ID),
                    "--repository",
                    REPOSITORY,
                    "--default-branch",
                    DEFAULT_BRANCH,
                    "--github-output",
                    str(output),
                ]
            )
            self.assertEqual(result, 0)
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                (
                    f"workflow_sha={WORKFLOW_SHA}\n"
                    f"workflow_id={WORKFLOW_ID}\n"
                    "run_attempt=2\n"
                ),
            )

    def test_cli_rejects_run_json_path_swap_between_inspection_and_open(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            run_json = root / "run.json"
            replacement = root / "replacement.json"
            output = root / "github-output.txt"
            run_json.write_text(json.dumps(_run()), encoding="utf-8")
            replacement.write_text(
                json.dumps(_run(head_sha="c" * 40)),
                encoding="utf-8",
            )
            real_open = Path.open
            swapped = False

            def swap_before_binary_open(path: Path, *args: object, **kwargs: object):
                nonlocal swapped
                if path == run_json and args and args[0] == "rb" and not swapped:
                    swapped = True
                    replacement.replace(run_json)
                return real_open(path, *args, **kwargs)

            with mock.patch.object(
                Path,
                "open",
                autospec=True,
                side_effect=swap_before_binary_open,
            ):
                result = main(
                    [
                        "--run-json",
                        str(run_json),
                        "--run-id",
                        str(RUN_ID),
                        "--repository",
                        REPOSITORY,
                        "--default-branch",
                        DEFAULT_BRANCH,
                        "--github-output",
                        str(output),
                    ]
                )
            self.assertTrue(swapped)
            self.assertEqual(result, 1)
            self.assertFalse(output.exists())

    def test_cli_does_not_write_outputs_for_rejected_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            run_json = root / "run.json"
            output = root / "github-output.txt"
            run_json.write_text(
                json.dumps(_run(conclusion="cancelled")),
                encoding="utf-8",
            )
            result = main(
                [
                    "--run-json",
                    str(run_json),
                    "--run-id",
                    str(RUN_ID),
                    "--repository",
                    REPOSITORY,
                    "--default-branch",
                    DEFAULT_BRANCH,
                    "--github-output",
                    str(output),
                ]
            )
            self.assertEqual(result, 1)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
