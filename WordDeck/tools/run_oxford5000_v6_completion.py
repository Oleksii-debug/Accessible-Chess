#!/usr/bin/env python3
"""Heavy V6 Oxford5000 runner with explicit exact-head Windows CI dispatch."""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import run_oxford5000_v5_completion as runner

ORIGINAL_RUN = runner.run
runner.TMP = Path("/tmp/worddeck-v6")
runner.ART = runner.ROOT / "artifacts" / "emergency-v6"


def run_v6(*args: str, capture: bool = False) -> str:
    rewritten = tuple(
        "WordDeck/tools/complete_oxford5000_emergency_v6.py"
        if arg == "WordDeck/tools/complete_oxford5000_emergency_v5.py" else arg
        for arg in args
    )
    return ORIGINAL_RUN(*rewritten, capture=capture)

runner.run = run_v6


def wait_windows_ci_v6(sha: str) -> tuple[dict, dict]:
    branch = runner.gh_json(f"repos/{runner.REPO}/branches/worddeck-bootstrap")
    live_sha = branch.get("commit", {}).get("sha")
    if live_sha != sha:
        raise RuntimeError(f"V6 refuses CI dispatch for non-live head: expected {sha}, branch has {live_sha}")

    # Bot-authored pushes do not recursively trigger push workflows. Explicit dispatch is mandatory.
    runner.run("gh", "workflow", "run", "worddeck-windows.yml", "--repo", runner.REPO, "--ref", "worddeck-bootstrap")
    run_id = None
    for _ in range(180):
        payload = runner.gh_json(
            f"repos/{runner.REPO}/actions/workflows/worddeck-windows.yml/runs?branch=worddeck-bootstrap&event=workflow_dispatch&per_page=50"
        )
        for item in payload.get("workflow_runs", []):
            if item.get("head_sha") == sha and item.get("head_branch") == "worddeck-bootstrap":
                run_id = int(item["id"])
                break
        if run_id:
            break
        time.sleep(5)
    if not run_id:
        raise RuntimeError(f"V6 explicit dispatch produced no exact-head Windows run for {sha}")

    for _ in range(240):
        info = runner.gh_json(f"repos/{runner.REPO}/actions/runs/{run_id}")
        if info.get("head_sha") != sha or info.get("head_branch") != "worddeck-bootstrap" or info.get("event") != "workflow_dispatch":
            raise RuntimeError(f"V6 Windows run identity mismatch for run {run_id}")
        if info.get("status") == "completed":
            if info.get("conclusion") != "success":
                raise RuntimeError(f"V6 Windows run {run_id} failed for {sha}: {info.get('conclusion')}")
            artifacts = runner.gh_json(f"repos/{runner.REPO}/actions/runs/{run_id}/artifacts?per_page=100")
            live = [a for a in artifacts.get("artifacts", []) if not a.get("expired")]
            if len(live) < 8:
                raise RuntimeError(f"V6 Windows run {run_id} has only {len(live)} nonexpired artifacts")
            logs = runner.run("gh", "run", "view", str(run_id), "--repo", runner.REPO, "--log", capture=True)
            (runner.ART / f"windows-run-{sha}.log").write_text(logs, encoding="utf-8")
            for marker in ["Traceback (most recent call last)", "##[error]", "Process completed with exit code 1"]:
                if marker in logs:
                    raise RuntimeError(f"Decoded V6 Windows log contains hidden failure marker {marker!r} for run {run_id}")
            for marker in ["Oxford 3000 baseline verified: rows=3308", "Build succeeded.", "0 Error(s)", "WordDeck self-test passed"]:
                if marker not in logs:
                    raise RuntimeError(f"Decoded V6 Windows log lacks required marker {marker!r} for run {run_id}")
            runner.write_json(runner.ART / f"windows-run-{sha}.json", info)
            runner.write_json(runner.ART / f"windows-artifacts-{sha}.json", artifacts)
            with (runner.ART / "windows-run-ids.txt").open("a", encoding="utf-8") as handle:
                handle.write(f"{sha}\t{run_id}\tworkflow_dispatch\n")
            return info, artifacts
        time.sleep(10)
    raise RuntimeError(f"Timed out waiting for V6 authoritative Windows run {run_id}")


def rename_manual_slices_v6(txdir: Path, round_id: str) -> None:
    op = txdir / "orchestration.json"
    tp = txdir / "transaction" / "transaction.json"
    sp = txdir / "transaction" / "prepared-slices"
    orch = json.loads(op.read_text(encoding="utf-8"))
    tx = json.loads(tp.read_text(encoding="utf-8"))
    by_index: dict[int, str] = {}
    for checkpoint in tx["checkpoints"]:
        old = checkpoint["file_name"]
        new = old.replace("oxford5000_source_after_auto_", f"oxford5000_source_after_manual_v6_{round_id}_")
        if new == old:
            raise RuntimeError(f"Unexpected V6 prepared filename {old}")
        (sp / old).rename(sp / new)
        checkpoint["file_name"] = new
        by_index[int(checkpoint["index"])] = new
    for checkpoint in orch["checkpoints"]:
        checkpoint["file"] = by_index[int(checkpoint["index"])]
    runner.write_json(tp, tx)
    runner.write_json(op, orch)


def stage_review_evidence_v6(qadir: Path, round_id: str) -> list[str]:
    mapping = {
        "first-pass.tsv": f"WordDeck/QA/oxford5000_manual_emergency_v6_{round_id}_first_pass.tsv",
        "second-pass.tsv": f"WordDeck/QA/oxford5000_manual_emergency_v6_{round_id}_second_pass.tsv",
        "holds.tsv": f"WordDeck/QA/oxford5000_manual_emergency_v6_{round_id}_holds.tsv",
        "summary.json": f"WordDeck/QA/oxford5000_manual_emergency_v6_{round_id}_summary.json",
    }
    targets: list[str] = []
    for source, target in mapping.items():
        shutil.copyfile(qadir / source, runner.ROOT / target)
        targets.append(target)
    return targets


def integrate_round_v6(round_id: str, qadir: Path, pre_runtime: Path, pre_unaccounted: Path, passed: int) -> int:
    txdir = runner.TMP / f"tx-{round_id}"
    runner.run("python", "WordDeck/tools/orchestrate_oxford5000_bulk_run.py", "start", "--worddeck-dir", "WordDeck", "--run-dir", str(txdir), "--official-html", str(runner.TMP / "official.html"), "--pre-runtime", str(pre_runtime), "--pre-unaccounted", str(pre_unaccounted), "--data-factory", str(qadir / "first-pass.tsv"), "--content-qa", str(qadir / "second-pass.tsv"), "--checkpoint-size", "120")
    rename_manual_slices_v6(txdir, round_id)
    plan = json.loads((txdir / "orchestration.json").read_text(encoding="utf-8"))
    checkpoints = plan["checkpoints"]
    if sum(int(cp["rows"]) for cp in checkpoints) != passed:
        raise RuntimeError("V6 checkpoint rows do not equal V6 PASS count")
    for ordinal, checkpoint in enumerate(checkpoints, 1):
        runner.run("python", "WordDeck/tools/orchestrate_oxford5000_bulk_run.py", "apply-next", "--worddeck-dir", "WordDeck", "--run-dir", str(txdir))
        filename = checkpoint["file"]
        paths = ["WordDeck/ReviewedOxford5000Bootstrap.cs", "WordDeck/WordDeck.csproj", f"WordDeck/QA/{filename}"]
        if ordinal == 1:
            paths.extend(stage_review_evidence_v6(qadir, round_id))
        runner.run("git", "add", "--", *paths)
        runner.run("git", "diff", "--cached", "--check")
        runner.run("git", "commit", "-m", f"WordDeck: integrate V6 Oxford 5000 {round_id} checkpoint {ordinal:02d}")
        sha = runner.run("git", "rev-parse", "HEAD", capture=True)
        runner.run("git", "push", "origin", "HEAD:worddeck-bootstrap")
        info, artifacts = wait_windows_ci_v6(sha)
        run_json = runner.TMP / "ci-run.json"
        artifacts_json = runner.TMP / "ci-artifacts.json"
        runner.write_json(run_json, info)
        runner.write_json(artifacts_json, artifacts)
        runner.run("python", "WordDeck/tools/orchestrate_oxford5000_bulk_run.py", "mark-ci-green", "--worddeck-dir", "WordDeck", "--run-dir", str(txdir), "--run-json", str(run_json), "--artifacts-json", str(artifacts_json))
    runner.run("python", "WordDeck/tools/orchestrate_oxford5000_bulk_run.py", "finalize", "--worddeck-dir", "WordDeck", "--run-dir", str(txdir))
    shutil.copyfile(txdir / "final-summary.json", runner.ART / f"{round_id}-orchestration-final-summary.json")
    return sum(int(cp["rows"]) for cp in checkpoints)


def commit_review_only_v6(qadir: Path, round_id: str) -> str:
    paths = stage_review_evidence_v6(qadir, round_id)
    runner.run("git", "add", "--", *paths)
    runner.run("git", "diff", "--cached", "--check")
    runner.run("git", "commit", "-m", f"WordDeck: record V6 Oxford 5000 {round_id} candidate-evidence review")
    sha = runner.run("git", "rev-parse", "HEAD", capture=True)
    runner.run("git", "push", "origin", "HEAD:worddeck-bootstrap")
    wait_windows_ci_v6(sha)
    return sha


def self_test_dispatch_contract() -> None:
    # Regression: the V6 gate never searches only event=push; bot commits require workflow_dispatch.
    source = Path(__file__).read_text(encoding="utf-8")
    assert "event=workflow_dispatch" in source
    assert '"gh", "workflow", "run", "worddeck-windows.yml"' in source
    assert "event=push" not in source
    print("V6 CI-dispatch regression passed: bot-authored checkpoints explicitly dispatch exact-head Windows workflow.")


def main() -> int:
    self_test_dispatch_contract()
    runner.wait_windows_ci = wait_windows_ci_v6
    runner.rename_manual_slices = rename_manual_slices_v6
    runner.stage_review_evidence = stage_review_evidence_v6
    runner.integrate_round = integrate_round_v6
    runner.commit_review_only = commit_review_only_v6
    return runner.main()


if __name__ == "__main__":
    raise SystemExit(main())
