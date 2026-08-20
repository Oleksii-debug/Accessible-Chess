#!/usr/bin/env python3
"""Heavy V5 Oxford5000 sense-bound completion orchestrator.

Starts only from auditor-trusted 982/1156, performs a full V5 review, integrates
all V5 PASS rows through <=120 transactional checkpoints with exact-head Windows
CI, preserves unresolved rows as explicit holds, and starts full British audio
only when the lexical tail reaches zero.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path.cwd()
WORDDECK = ROOT / "WordDeck"
TMP = Path("/tmp/worddeck-v5")
ART = ROOT / "artifacts" / "emergency-v5"
REPO = os.environ["GITHUB_REPOSITORY"]
GH_ENV = Path(os.environ["GITHUB_ENV"])

def run(*args: str, capture: bool = False) -> str:
    result = subprocess.run(args, cwd=ROOT, text=True, check=True, stdout=subprocess.PIPE if capture else None, stderr=subprocess.STDOUT if capture else None)
    return (result.stdout or "").strip()

def count_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig") as handle:
        return max(0, sum(1 for _ in handle) - 1)

def gh_json(endpoint: str) -> dict:
    return json.loads(run("gh", "api", endpoint, capture=True))

def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def wait_windows_ci(sha: str) -> tuple[dict, dict]:
    run_id = None
    for _ in range(180):
        payload = gh_json(f"repos/{REPO}/actions/workflows/worddeck-windows.yml/runs?branch=worddeck-bootstrap&event=push&per_page=50")
        for item in payload.get("workflow_runs", []):
            if item.get("head_sha") == sha:
                run_id = int(item["id"])
                break
        if run_id:
            break
        time.sleep(5)
    if not run_id:
        raise RuntimeError(f"No authoritative Windows run found for exact HEAD {sha}")
    for _ in range(240):
        info = gh_json(f"repos/{REPO}/actions/runs/{run_id}")
        if info.get("status") == "completed":
            if info.get("conclusion") != "success":
                raise RuntimeError(f"Windows run {run_id} failed for {sha}: {info.get('conclusion')}")
            artifacts = gh_json(f"repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100")
            live = [a for a in artifacts.get("artifacts", []) if not a.get("expired")]
            if len(live) < 8:
                raise RuntimeError(f"Windows run {run_id} has only {len(live)} nonexpired artifacts")
            logs = run("gh", "run", "view", str(run_id), "--repo", REPO, "--log", capture=True)
            (ART / f"windows-run-{sha}.log").write_text(logs, encoding="utf-8")
            for marker in ["Traceback (most recent call last)", "##[error]", "Process completed with exit code 1"]:
                if marker in logs:
                    raise RuntimeError(f"Decoded Windows log contains hidden failure marker {marker!r} for run {run_id}")
            for marker in ["Oxford 3000 baseline verified: rows=3308", "Build succeeded.", "0 Error(s)", "WordDeck self-test passed"]:
                if marker not in logs:
                    raise RuntimeError(f"Decoded Windows log lacks required marker {marker!r} for run {run_id}")
            write_json(ART / f"windows-run-{sha}.json", info)
            write_json(ART / f"windows-artifacts-{sha}.json", artifacts)
            with (ART / "windows-run-ids.txt").open("a", encoding="utf-8") as handle:
                handle.write(f"{sha}\t{run_id}\n")
            return info, artifacts
        time.sleep(10)
    raise RuntimeError(f"Timed out waiting for authoritative Windows run {run_id}")

def ledger(prefix: str) -> tuple[Path, Path, Path]:
    runtime = TMP / f"{prefix}-runtime.tsv"
    accounting = TMP / f"{prefix}-accounting.tsv"
    unaccounted = TMP / f"{prefix}-unaccounted.tsv"
    run("python", "WordDeck/tools/validate_oxford5000_runtime_ledger.py", "--official-html", str(TMP / "official.html"), "--ledger", str(runtime), "--report", str(accounting), "--unaccounted", str(unaccounted))
    return runtime, accounting, unaccounted

def rename_manual_slices(txdir: Path, round_id: str) -> None:
    op = txdir / "orchestration.json"
    tp = txdir / "transaction" / "transaction.json"
    sp = txdir / "transaction" / "prepared-slices"
    orch = json.loads(op.read_text(encoding="utf-8"))
    tx = json.loads(tp.read_text(encoding="utf-8"))
    by_index: dict[int, str] = {}
    for checkpoint in tx["checkpoints"]:
        old = checkpoint["file_name"]
        new = old.replace("oxford5000_source_after_auto_", f"oxford5000_source_after_manual_v5_{round_id}_")
        if new == old:
            raise RuntimeError(f"Unexpected prepared filename {old}")
        (sp / old).rename(sp / new)
        checkpoint["file_name"] = new
        by_index[int(checkpoint["index"])] = new
    for checkpoint in orch["checkpoints"]:
        checkpoint["file"] = by_index[int(checkpoint["index"])]
    write_json(tp, tx)
    write_json(op, orch)

def stage_review_evidence(qadir: Path, round_id: str) -> list[str]:
    mapping = {"first-pass.tsv":f"WordDeck/QA/oxford5000_manual_emergency_v5_{round_id}_first_pass.tsv","second-pass.tsv":f"WordDeck/QA/oxford5000_manual_emergency_v5_{round_id}_second_pass.tsv","holds.tsv":f"WordDeck/QA/oxford5000_manual_emergency_v5_{round_id}_holds.tsv","summary.json":f"WordDeck/QA/oxford5000_manual_emergency_v5_{round_id}_summary.json"}
    targets: list[str] = []
    for source, target in mapping.items():
        shutil.copyfile(qadir / source, ROOT / target)
        targets.append(target)
    return targets

def integrate_round(round_id: str, qadir: Path, pre_runtime: Path, pre_unaccounted: Path, passed: int) -> int:
    txdir = TMP / f"tx-{round_id}"
    run("python", "WordDeck/tools/orchestrate_oxford5000_bulk_run.py", "start", "--worddeck-dir", "WordDeck", "--run-dir", str(txdir), "--official-html", str(TMP / "official.html"), "--pre-runtime", str(pre_runtime), "--pre-unaccounted", str(pre_unaccounted), "--data-factory", str(qadir / "first-pass.tsv"), "--content-qa", str(qadir / "second-pass.tsv"), "--checkpoint-size", "120")
    rename_manual_slices(txdir, round_id)
    plan = json.loads((txdir / "orchestration.json").read_text(encoding="utf-8"))
    checkpoints = plan["checkpoints"]
    if sum(int(cp["rows"]) for cp in checkpoints) != passed:
        raise RuntimeError("V5 checkpoint rows do not equal V5 PASS count")
    for ordinal, checkpoint in enumerate(checkpoints, 1):
        run("python", "WordDeck/tools/orchestrate_oxford5000_bulk_run.py", "apply-next", "--worddeck-dir", "WordDeck", "--run-dir", str(txdir))
        filename = checkpoint["file"]
        paths = ["WordDeck/ReviewedOxford5000Bootstrap.cs", "WordDeck/WordDeck.csproj", f"WordDeck/QA/{filename}"]
        if ordinal == 1:
            paths.extend(stage_review_evidence(qadir, round_id))
        run("git", "add", "--", *paths)
        run("git", "diff", "--cached", "--check")
        run("git", "commit", "-m", f"WordDeck: integrate V5 Oxford 5000 {round_id} checkpoint {ordinal:02d}")
        sha = run("git", "rev-parse", "HEAD", capture=True)
        run("git", "push", "origin", "HEAD:worddeck-bootstrap")
        info, artifacts = wait_windows_ci(sha)
        run_json = TMP / "ci-run.json"
        artifacts_json = TMP / "ci-artifacts.json"
        write_json(run_json, info)
        write_json(artifacts_json, artifacts)
        run("python", "WordDeck/tools/orchestrate_oxford5000_bulk_run.py", "mark-ci-green", "--worddeck-dir", "WordDeck", "--run-dir", str(txdir), "--run-json", str(run_json), "--artifacts-json", str(artifacts_json))
    run("python", "WordDeck/tools/orchestrate_oxford5000_bulk_run.py", "finalize", "--worddeck-dir", "WordDeck", "--run-dir", str(txdir))
    shutil.copyfile(txdir / "final-summary.json", ART / f"{round_id}-orchestration-final-summary.json")
    return sum(int(cp["rows"]) for cp in checkpoints)

def commit_review_only(qadir: Path, round_id: str) -> str:
    paths = stage_review_evidence(qadir, round_id)
    run("git", "add", "--", *paths)
    run("git", "diff", "--cached", "--check")
    run("git", "commit", "-m", f"WordDeck: record V5 Oxford 5000 {round_id} sense-bound review")
    sha = run("git", "rev-parse", "HEAD", capture=True)
    run("git", "push", "origin", "HEAD:worddeck-bootstrap")
    wait_windows_ci(sha)
    return sha

def write_audio_request() -> None:
    path = WORDDECK / "Audio" / "generation-request.json"
    path.write_text(json.dumps({"source":"oxford5000","start":0,"limit":0,"accent":"en-GB","femaleVoice":"bf_emma","maleVoice":"bm_george","speed":1.0,"format":"mp3"}, indent=2) + "\n", encoding="utf-8")

def wait_audio(final_sha: str) -> tuple[dict, dict]:
    run_id = None
    for _ in range(240):
        payload = gh_json(f"repos/{REPO}/actions/workflows/worddeck-audio.yml/runs?branch=worddeck-bootstrap&event=push&per_page=50")
        for item in payload.get("workflow_runs", []):
            if item.get("head_sha") == final_sha:
                run_id = int(item["id"])
                break
        if run_id:
            break
        time.sleep(5)
    if not run_id:
        raise RuntimeError(f"No audio workflow found for exact final HEAD {final_sha}")
    for _ in range(360):
        info = gh_json(f"repos/{REPO}/actions/runs/{run_id}")
        if info.get("status") == "completed":
            if info.get("conclusion") != "success":
                raise RuntimeError(f"Audio workflow {run_id} failed: {info.get('conclusion')}")
            artifacts = gh_json(f"repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100")
            names = {a.get("name") for a in artifacts.get("artifacts", []) if not a.get("expired")}
            required = {"worddeck-oxford5000-en-gb-0-0", "WordDeck-win-x64-with-oxford5000-audio"}
            if not required <= names:
                raise RuntimeError(f"Audio run missing required artifacts: {sorted(required - names)}")
            write_json(ART / "final-audio-run.json", info)
            write_json(ART / "final-audio-artifacts.json", artifacts)
            return info, artifacts
        time.sleep(10)
    raise RuntimeError(f"Timed out waiting for full audio workflow {run_id}")

def main() -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    run("python", "WordDeck/tools/fetch_oxford5000_official_html.py", "--output", str(TMP / "official.html"))
    start_runtime, _, start_unaccounted = ledger("start")
    if count_rows(start_runtime) != 982 or count_rows(start_unaccounted) != 1156:
        raise RuntimeError("V5 must start from exact auditor-trusted 982/1156 baseline")
    run("python", "WordDeck/tools/validate_oxford3000_baseline_files.py", "--report", str(TMP / "oxford3000-start.tsv"))
    if "rows\t3308" not in (TMP / "oxford3000-start.tsv").read_text(encoding="utf-8"):
        raise RuntimeError("Oxford3000 frozen baseline drift")
    run("python", "WordDeck/tools/complete_oxford5000_emergency_v5.py", "--self-test")
    initial_sha = run("git", "rev-parse", "HEAD", capture=True)
    wait_windows_ci(initial_sha)
    round_id = "round01"
    qadir = TMP / round_id
    qadir.mkdir(parents=True, exist_ok=True)
    args = ["python", "WordDeck/tools/complete_oxford5000_emergency_v5.py", "--unaccounted", str(start_unaccounted), "--qa-dir", str(qadir), "--expected-tail", "1156", "--round-id", round_id]
    overrides = WORDDECK / "QA" / "oxford5000_manual_emergency_overrides_20260820.tsv"
    if overrides.is_file():
        args += ["--overrides", str(overrides)]
    run(*args)
    summary = json.loads((qadir / "summary.json").read_text(encoding="utf-8"))
    passed = int(summary["pass"])
    blocked = int(summary["blocked"])
    if passed + blocked != 1156:
        raise RuntimeError("V5 PASS/BLOCKED partition does not reconcile exact tail")
    shutil.copyfile(qadir / "summary.json", ART / "round01-semantic-summary.json")
    shutil.copyfile(qadir / "holds.tsv", ART / "round01-holds.tsv")
    shutil.copyfile(qadir / "second-pass.tsv", ART / "round01-second-pass.tsv")
    print(f"V5 round01: total=1156 PASS={passed} BLOCKED={blocked}")
    integrated = 0
    if passed:
        integrated = integrate_round(round_id, qadir, start_runtime, start_unaccounted, passed)
    else:
        commit_review_only(qadir, round_id)
    final_runtime_path, final_accounting, final_unaccounted_path = ledger("final")
    final_runtime = count_rows(final_runtime_path)
    final_remaining = count_rows(final_unaccounted_path)
    if final_runtime + final_remaining != 2138:
        raise RuntimeError("Final Oxford5000 equation does not equal 2138")
    if integrated != final_runtime - 982:
        raise RuntimeError("Final runtime increase does not equal integrated V5 PASS count")
    if final_remaining != 1156 - integrated:
        raise RuntimeError("Final unaccounted reduction does not equal integrated V5 PASS count")
    shutil.copyfile(final_runtime_path, ART / "final-runtime.tsv")
    shutil.copyfile(final_accounting, ART / "final-accounting.tsv")
    shutil.copyfile(final_unaccounted_path, ART / "final-unaccounted.tsv")
    run("python", "WordDeck/tools/validate_oxford3000_baseline_files.py", "--report", str(ART / "oxford3000-final.tsv"))
    final_sha = run("git", "rev-parse", "HEAD", capture=True)
    audio_run_id = ""
    audio_complete = False
    if final_remaining == 0:
        write_audio_request()
        run("git", "add", "--", "WordDeck/Audio/generation-request.json")
        run("git", "diff", "--cached", "--check")
        if run("git", "diff", "--cached", "--name-only", capture=True):
            run("git", "commit", "-m", "WordDeck: request complete British Oxford 5000 AudioPack after V5 lexical completion")
            final_sha = run("git", "rev-parse", "HEAD", capture=True)
            run("git", "push", "origin", "HEAD:worddeck-bootstrap")
            wait_windows_ci(final_sha)
        audio_info, _ = wait_audio(final_sha)
        audio_run_id = str(audio_info["id"])
        audio_complete = True
    final = {"start_activated":982,"start_remaining":1156,"v5_pass":passed,"v5_blocked":blocked,"newly_activated_v5":integrated,"final_activated":final_runtime,"final_remaining":final_remaining,"final_sha":final_sha,"audio_complete":audio_complete,"audio_run_id":audio_run_id,"unresolved_evidence_file":"WordDeck/QA/oxford5000_manual_emergency_v5_round01_holds.tsv"}
    write_json(ART / "final-summary.json", final)
    with GH_ENV.open("a", encoding="utf-8") as handle:
        handle.write(f"FINAL_RUNTIME={final_runtime}\nFINAL_REMAINING={final_remaining}\nFINAL_SHA={final_sha}\nTOTAL_INTEGRATED={integrated}\nV5_PASS={passed}\nV5_BLOCKED={blocked}\nAUDIO_RUN_ID={audio_run_id}\n")
    print(json.dumps(final, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
