#!/usr/bin/env python3
"""Heavy V7 Oxford5000 same-sense completion orchestrator.

Starts from auditor-trusted 982/1156, runs a full V7 same-sense review, integrates
safe rows through <=120 exact-head Windows checkpoints, then performs repeated
blocked-resolution rounds in the same invocation while productive. Full British
offline audio is explicitly dispatched only after lexical remaining reaches 0.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import run_oxford5000_v5_completion as runner

ORIGINAL_RUN = runner.run
runner.TMP = Path("/tmp/worddeck-v7")
runner.ART = runner.ROOT / "artifacts" / "emergency-v7"


def run_v7(*args: str, capture: bool = False) -> str:
    rewritten = tuple(
        "WordDeck/tools/complete_oxford5000_emergency_v7.py"
        if arg == "WordDeck/tools/complete_oxford5000_emergency_v5.py" else arg
        for arg in args
    )
    return ORIGINAL_RUN(*rewritten, capture=capture)


runner.run = run_v7


def wait_windows_ci_v7(sha: str) -> tuple[dict, dict]:
    branch = runner.gh_json(f"repos/{runner.REPO}/branches/worddeck-bootstrap")
    live_sha = branch.get("commit", {}).get("sha")
    if live_sha != sha:
        raise RuntimeError(f"V7 refuses CI dispatch for non-live head: expected {sha}, branch has {live_sha}")
    runner.run("gh", "workflow", "run", "worddeck-windows.yml", "--repo", runner.REPO, "--ref", "worddeck-bootstrap")
    run_id = None
    for _ in range(180):
        payload = runner.gh_json(f"repos/{runner.REPO}/actions/workflows/worddeck-windows.yml/runs?branch=worddeck-bootstrap&event=workflow_dispatch&per_page=50")
        for item in payload.get("workflow_runs", []):
            if item.get("head_sha") == sha and item.get("head_branch") == "worddeck-bootstrap":
                run_id = int(item["id"])
                break
        if run_id:
            break
        time.sleep(5)
    if not run_id:
        raise RuntimeError(f"V7 explicit dispatch produced no exact-head Windows run for {sha}")
    for _ in range(240):
        info = runner.gh_json(f"repos/{runner.REPO}/actions/runs/{run_id}")
        if info.get("head_sha") != sha or info.get("head_branch") != "worddeck-bootstrap" or info.get("event") != "workflow_dispatch":
            raise RuntimeError(f"V7 Windows run identity mismatch for run {run_id}")
        if info.get("status") == "completed":
            if info.get("conclusion") != "success":
                raise RuntimeError(f"V7 Windows run {run_id} failed for {sha}: {info.get('conclusion')}")
            artifacts = runner.gh_json(f"repos/{runner.REPO}/actions/runs/{run_id}/artifacts?per_page=100")
            live = [a for a in artifacts.get("artifacts", []) if not a.get("expired")]
            if len(live) < 8:
                raise RuntimeError(f"V7 Windows run {run_id} has only {len(live)} nonexpired artifacts")
            logs = runner.run("gh", "run", "view", str(run_id), "--repo", runner.REPO, "--log", capture=True)
            (runner.ART / f"windows-run-{sha}.log").write_text(logs, encoding="utf-8")
            for marker in ["Traceback (most recent call last)", "##[error]", "Process completed with exit code 1"]:
                if marker in logs:
                    raise RuntimeError(f"Decoded V7 Windows log contains hidden failure marker {marker!r} for run {run_id}")
            for marker in ["Oxford 3000 baseline verified: rows=3308", "Build succeeded.", "0 Error(s)", "WordDeck self-test passed"]:
                if marker not in logs:
                    raise RuntimeError(f"Decoded V7 Windows log lacks required marker {marker!r} for run {run_id}")
            runner.write_json(runner.ART / f"windows-run-{sha}.json", info)
            runner.write_json(runner.ART / f"windows-artifacts-{sha}.json", artifacts)
            with (runner.ART / "windows-run-ids.txt").open("a", encoding="utf-8") as handle:
                handle.write(f"{sha}\t{run_id}\tworkflow_dispatch\n")
            return info, artifacts
        time.sleep(10)
    raise RuntimeError(f"Timed out waiting for V7 authoritative Windows run {run_id}")


def rename_manual_slices_v7(txdir: Path, round_id: str) -> None:
    op = txdir / "orchestration.json"
    tp = txdir / "transaction" / "transaction.json"
    sp = txdir / "transaction" / "prepared-slices"
    orch = json.loads(op.read_text(encoding="utf-8"))
    tx = json.loads(tp.read_text(encoding="utf-8"))
    by_index: dict[int, str] = {}
    for checkpoint in tx["checkpoints"]:
        old = checkpoint["file_name"]
        new = old.replace("oxford5000_source_after_auto_", f"oxford5000_source_after_manual_v7_{round_id}_")
        if new == old:
            raise RuntimeError(f"Unexpected V7 prepared filename {old}")
        (sp / old).rename(sp / new)
        checkpoint["file_name"] = new
        by_index[int(checkpoint["index"])] = new
    for checkpoint in orch["checkpoints"]:
        checkpoint["file"] = by_index[int(checkpoint["index"])]
    runner.write_json(tp, tx)
    runner.write_json(op, orch)


def stage_review_evidence_v7(qadir: Path, round_id: str) -> list[str]:
    mapping = {
        "first-pass.tsv": f"WordDeck/QA/oxford5000_manual_emergency_v7_{round_id}_first_pass.tsv",
        "second-pass.tsv": f"WordDeck/QA/oxford5000_manual_emergency_v7_{round_id}_second_pass.tsv",
        "holds.tsv": f"WordDeck/QA/oxford5000_manual_emergency_v7_{round_id}_holds.tsv",
        "summary.json": f"WordDeck/QA/oxford5000_manual_emergency_v7_{round_id}_summary.json",
    }
    targets: list[str] = []
    for source, target in mapping.items():
        shutil.copyfile(qadir / source, runner.ROOT / target)
        targets.append(target)
    return targets


def integrate_round_v7(round_id: str, qadir: Path, pre_runtime: Path, pre_unaccounted: Path, passed: int) -> tuple[int, list[dict[str, object]]]:
    txdir = runner.TMP / f"tx-{round_id}"
    runner.run("python", "WordDeck/tools/orchestrate_oxford5000_bulk_run.py", "start", "--worddeck-dir", "WordDeck", "--run-dir", str(txdir), "--official-html", str(runner.TMP / "official.html"), "--pre-runtime", str(pre_runtime), "--pre-unaccounted", str(pre_unaccounted), "--data-factory", str(qadir / "first-pass.tsv"), "--content-qa", str(qadir / "second-pass.tsv"), "--checkpoint-size", "120")
    rename_manual_slices_v7(txdir, round_id)
    plan = json.loads((txdir / "orchestration.json").read_text(encoding="utf-8"))
    checkpoints = plan["checkpoints"]
    if sum(int(cp["rows"]) for cp in checkpoints) != passed:
        raise RuntimeError("V7 checkpoint rows do not equal V7 PASS count")
    checkpoint_evidence: list[dict[str, object]] = []
    for ordinal, checkpoint in enumerate(checkpoints, 1):
        runner.run("python", "WordDeck/tools/orchestrate_oxford5000_bulk_run.py", "apply-next", "--worddeck-dir", "WordDeck", "--run-dir", str(txdir))
        filename = checkpoint["file"]
        paths = ["WordDeck/ReviewedOxford5000Bootstrap.cs", "WordDeck/WordDeck.csproj", f"WordDeck/QA/{filename}"]
        if ordinal == 1:
            paths.extend(stage_review_evidence_v7(qadir, round_id))
        runner.run("git", "add", "--", *paths)
        runner.run("git", "diff", "--cached", "--check")
        runner.run("git", "commit", "-m", f"WordDeck: integrate V7 Oxford 5000 {round_id} checkpoint {ordinal:02d}")
        sha = runner.run("git", "rev-parse", "HEAD", capture=True)
        runner.run("git", "push", "origin", "HEAD:worddeck-bootstrap")
        info, artifacts = wait_windows_ci_v7(sha)
        run_json = runner.TMP / "ci-run.json"
        artifacts_json = runner.TMP / "ci-artifacts.json"
        runner.write_json(run_json, info)
        runner.write_json(artifacts_json, artifacts)
        runner.run("python", "WordDeck/tools/orchestrate_oxford5000_bulk_run.py", "mark-ci-green", "--worddeck-dir", "WordDeck", "--run-dir", str(txdir), "--run-json", str(run_json), "--artifacts-json", str(artifacts_json))
        checkpoint_evidence.append({"ordinal": ordinal, "rows": int(checkpoint["rows"]), "sha": sha, "windows_run_id": int(info["id"])})
    runner.run("python", "WordDeck/tools/orchestrate_oxford5000_bulk_run.py", "finalize", "--worddeck-dir", "WordDeck", "--run-dir", str(txdir))
    shutil.copyfile(txdir / "final-summary.json", runner.ART / f"{round_id}-orchestration-final-summary.json")
    return sum(int(cp["rows"]) for cp in checkpoints), checkpoint_evidence


def commit_review_only_v7(qadir: Path, round_id: str) -> tuple[str, int]:
    paths = stage_review_evidence_v7(qadir, round_id)
    runner.run("git", "add", "--", *paths)
    runner.run("git", "diff", "--cached", "--check")
    runner.run("git", "commit", "-m", f"WordDeck: record V7 Oxford 5000 {round_id} same-sense review")
    sha = runner.run("git", "rev-parse", "HEAD", capture=True)
    runner.run("git", "push", "origin", "HEAD:worddeck-bootstrap")
    info, _ = wait_windows_ci_v7(sha)
    return sha, int(info["id"])


def write_audio_request() -> None:
    path = runner.WORDDECK / "Audio" / "generation-request.json"
    path.write_text(json.dumps({"source":"oxford5000","start":0,"limit":0,"accent":"en-GB","femaleVoice":"bf_emma","maleVoice":"bm_george","speed":1.0,"format":"mp3"}, indent=2) + "\n", encoding="utf-8")


def wait_audio_v7(final_sha: str) -> tuple[dict, dict]:
    branch = runner.gh_json(f"repos/{runner.REPO}/branches/worddeck-bootstrap")
    if branch.get("commit", {}).get("sha") != final_sha:
        raise RuntimeError("V7 refuses audio dispatch for non-live final HEAD")
    runner.run("gh", "workflow", "run", "worddeck-audio.yml", "--repo", runner.REPO, "--ref", "worddeck-bootstrap")
    run_id = None
    for _ in range(180):
        payload = runner.gh_json(f"repos/{runner.REPO}/actions/workflows/worddeck-audio.yml/runs?branch=worddeck-bootstrap&event=workflow_dispatch&per_page=50")
        for item in payload.get("workflow_runs", []):
            if item.get("head_sha") == final_sha:
                run_id = int(item["id"])
                break
        if run_id:
            break
        time.sleep(5)
    if not run_id:
        raise RuntimeError(f"No explicitly dispatched audio run found for exact HEAD {final_sha}")
    for _ in range(360):
        info = runner.gh_json(f"repos/{runner.REPO}/actions/runs/{run_id}")
        if info.get("head_sha") != final_sha or info.get("event") != "workflow_dispatch":
            raise RuntimeError("V7 audio run identity mismatch")
        if info.get("status") == "completed":
            if info.get("conclusion") != "success":
                raise RuntimeError(f"Audio workflow {run_id} failed: {info.get('conclusion')}")
            artifacts = runner.gh_json(f"repos/{runner.REPO}/actions/runs/{run_id}/artifacts?per_page=100")
            live_names = {a.get("name") for a in artifacts.get("artifacts", []) if not a.get("expired")}
            required = {"worddeck-oxford5000-en-gb-0-0", "WordDeck-win-x64-with-oxford5000-audio"}
            if not required <= live_names:
                raise RuntimeError(f"Audio run missing required artifacts: {sorted(required - live_names)}")
            runner.write_json(runner.ART / "final-audio-run.json", info)
            runner.write_json(runner.ART / "final-audio-artifacts.json", artifacts)
            return info, artifacts
        time.sleep(10)
    raise RuntimeError(f"Timed out waiting for V7 full audio workflow {run_id}")


def self_test_dispatch_contract() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    forbidden = "event=" + "push"
    assert "event=workflow_dispatch" in source
    assert '"gh", "workflow", "run", "worddeck-windows.yml"' in source
    assert '"gh", "workflow", "run", "worddeck-audio.yml"' in source
    assert forbidden not in source
    print("V7 dispatch regression passed: lexical checkpoints and final audio explicitly dispatch exact-head workflows.")


def _copy_round_artifacts(qadir: Path, round_id: str) -> None:
    shutil.copyfile(qadir / "summary.json", runner.ART / f"{round_id}-semantic-summary.json")
    shutil.copyfile(qadir / "holds.tsv", runner.ART / f"{round_id}-holds.tsv")
    shutil.copyfile(qadir / "second-pass.tsv", runner.ART / f"{round_id}-second-pass.tsv")


def main() -> int:
    self_test_dispatch_contract()
    runner.TMP.mkdir(parents=True, exist_ok=True)
    runner.ART.mkdir(parents=True, exist_ok=True)
    runner.run("git", "config", "user.name", "github-actions[bot]")
    runner.run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    runner.run("python", "WordDeck/tools/fetch_oxford5000_official_html.py", "--output", str(runner.TMP / "official.html"))
    start_runtime, _, start_unaccounted = runner.ledger("start")
    if runner.count_rows(start_runtime) != 982 or runner.count_rows(start_unaccounted) != 1156:
        raise RuntimeError("V7 must start from exact auditor-trusted 982/1156 baseline")
    runner.run("python", "WordDeck/tools/validate_oxford3000_baseline_files.py", "--report", str(runner.TMP / "oxford3000-start.tsv"))
    if "rows\t3308" not in (runner.TMP / "oxford3000-start.tsv").read_text(encoding="utf-8"):
        raise RuntimeError("Oxford3000 frozen baseline drift")
    runner.run("python", "WordDeck/tools/complete_oxford5000_emergency_v7.py", "--self-test")
    initial_sha = runner.run("git", "rev-parse", "HEAD", capture=True)
    wait_windows_ci_v7(initial_sha)

    current_runtime = start_runtime
    current_unaccounted = start_unaccounted
    total_integrated = 0
    no_progress_rounds = 0
    round_records: list[dict[str, object]] = []
    last_qadir: Path | None = None

    for round_number in range(1, 5):
        remaining_before = runner.count_rows(current_unaccounted)
        if remaining_before == 0:
            break
        round_id = f"round{round_number:02d}"
        qadir = runner.TMP / round_id
        qadir.mkdir(parents=True, exist_ok=True)
        last_qadir = qadir
        args = ["python", "WordDeck/tools/complete_oxford5000_emergency_v7.py", "--unaccounted", str(current_unaccounted), "--qa-dir", str(qadir), "--expected-tail", str(remaining_before), "--round-id", round_id]
        overrides = runner.WORDDECK / "QA" / "oxford5000_manual_emergency_overrides_20260820.tsv"
        if overrides.is_file():
            args += ["--overrides", str(overrides)]
        runner.run(*args)
        summary = json.loads((qadir / "summary.json").read_text(encoding="utf-8"))
        passed = int(summary["pass"])
        blocked = int(summary["blocked"])
        if passed + blocked != remaining_before:
            raise RuntimeError(f"V7 {round_id} PASS/BLOCKED partition does not reconcile exact remaining tail")
        _copy_round_artifacts(qadir, round_id)
        print(f"V7 {round_id}: total={remaining_before} PASS={passed} BLOCKED={blocked}")
        checkpoints: list[dict[str, object]] = []
        if passed:
            integrated, checkpoints = integrate_round_v7(round_id, qadir, current_runtime, current_unaccounted, passed)
        else:
            integrated = 0
            review_sha, review_windows = commit_review_only_v7(qadir, round_id)
            checkpoints = [{"ordinal": 0, "rows": 0, "sha": review_sha, "windows_run_id": review_windows, "review_only": True}]
        next_runtime, _, next_unaccounted = runner.ledger(f"after-{round_id}")
        remaining_after = runner.count_rows(next_unaccounted)
        activated_after = runner.count_rows(next_runtime)
        if activated_after + remaining_after != 2138:
            raise RuntimeError("V7 Oxford5000 equation does not equal 2138")
        if integrated != remaining_before - remaining_after:
            raise RuntimeError("V7 unaccounted reduction does not equal integrated PASS count")
        total_integrated += integrated
        round_records.append({
            "round_id": round_id,
            "remaining_before": remaining_before,
            "pass": passed,
            "blocked": blocked,
            "integrated": integrated,
            "activated_after": activated_after,
            "remaining_after": remaining_after,
            "checkpoints": checkpoints,
        })
        current_runtime, current_unaccounted = next_runtime, next_unaccounted
        if remaining_after == 0:
            break
        if integrated == 0:
            no_progress_rounds += 1
        else:
            no_progress_rounds = 0
        if no_progress_rounds >= 2:
            print("V7 blocked-resolution stop condition: two consecutive fully re-reviewed rounds produced no new source-defensible PASS rows.")
            break
        time.sleep(20)

    final_runtime_path, final_accounting, final_unaccounted_path = runner.ledger("final")
    final_runtime = runner.count_rows(final_runtime_path)
    final_remaining = runner.count_rows(final_unaccounted_path)
    if final_runtime + final_remaining != 2138:
        raise RuntimeError("Final V7 Oxford5000 equation does not equal 2138")
    if total_integrated != final_runtime - 982:
        raise RuntimeError("Final runtime increase does not equal total V7 integrated rows")
    shutil.copyfile(final_runtime_path, runner.ART / "final-runtime.tsv")
    shutil.copyfile(final_accounting, runner.ART / "final-accounting.tsv")
    shutil.copyfile(final_unaccounted_path, runner.ART / "final-unaccounted.tsv")
    runner.run("python", "WordDeck/tools/validate_oxford3000_baseline_files.py", "--report", str(runner.ART / "oxford3000-final.tsv"))

    if final_remaining and last_qadir is not None:
        final_holds = runner.ROOT / "WordDeck/QA/oxford5000_manual_emergency_v7_final_unresolved.tsv"
        final_rounds = runner.ROOT / "WordDeck/QA/oxford5000_manual_emergency_v7_resolution_summary.json"
        shutil.copyfile(last_qadir / "holds.tsv", final_holds)
        final_rounds.write_text(json.dumps({"rounds": round_records, "final_activated": final_runtime, "final_remaining": final_remaining}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        runner.run("git", "add", "--", str(final_holds.relative_to(runner.ROOT)), str(final_rounds.relative_to(runner.ROOT)))
        runner.run("git", "diff", "--cached", "--check")
        if runner.run("git", "diff", "--cached", "--name-only", capture=True):
            runner.run("git", "commit", "-m", "WordDeck: record V7 final unresolved corpus evidence")
            evidence_sha = runner.run("git", "rev-parse", "HEAD", capture=True)
            runner.run("git", "push", "origin", "HEAD:worddeck-bootstrap")
            wait_windows_ci_v7(evidence_sha)

    final_sha = runner.run("git", "rev-parse", "HEAD", capture=True)
    audio_complete = False
    audio_run_id = ""
    audio_asset_count = 0
    if final_remaining == 0:
        write_audio_request()
        runner.run("git", "add", "--", "WordDeck/Audio/generation-request.json")
        runner.run("git", "diff", "--cached", "--check")
        if runner.run("git", "diff", "--cached", "--name-only", capture=True):
            runner.run("git", "commit", "-m", "WordDeck: request complete British Oxford 5000 AudioPack after V7 lexical completion")
            final_sha = runner.run("git", "rev-parse", "HEAD", capture=True)
            runner.run("git", "push", "origin", "HEAD:worddeck-bootstrap")
            wait_windows_ci_v7(final_sha)
        audio_info, audio_artifacts = wait_audio_v7(final_sha)
        audio_run_id = str(audio_info["id"])
        audio_complete = True
        audio_asset_count = 2138
        runner.write_json(runner.ART / "final-audio-artifacts.json", audio_artifacts)

    final = {
        "start_activated": 982,
        "start_remaining": 1156,
        "rounds": round_records,
        "newly_activated_v7": total_integrated,
        "final_activated": final_runtime,
        "final_remaining": final_remaining,
        "final_sha": final_sha,
        "audio_complete": audio_complete,
        "audio_run_id": audio_run_id,
        "audio_covered_ids": audio_asset_count,
        "unresolved_evidence_file": "WordDeck/QA/oxford5000_manual_emergency_v7_final_unresolved.tsv" if final_remaining else "",
    }
    runner.write_json(runner.ART / "final-summary.json", final)
    with runner.GH_ENV.open("a", encoding="utf-8") as handle:
        handle.write(f"FINAL_RUNTIME={final_runtime}\nFINAL_REMAINING={final_remaining}\nFINAL_SHA={final_sha}\nTOTAL_INTEGRATED={total_integrated}\nAUDIO_RUN_ID={audio_run_id}\nAUDIO_COMPLETE={str(audio_complete).lower()}\n")
    print(json.dumps(final, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if "--self-test-dispatch" in sys.argv:
        self_test_dispatch_contract()
        raise SystemExit(0)
    raise SystemExit(main())
