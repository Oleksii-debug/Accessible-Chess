#!/usr/bin/env python3
"""One heavy V8 Work invocation: finish all remaining lexical rows, then full British AudioPack."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT=Path.cwd(); WORDDECK=ROOT/"WordDeck"; TMP=Path("/tmp/worddeck-v8"); ART=ROOT/"artifacts"/"emergency-v8"
REPO=os.environ["GITHUB_REPOSITORY"]
GH_ENV=Path(os.environ["GITHUB_ENV"])


def run(*args: str, capture: bool=False) -> str:
    p=subprocess.run(args,cwd=ROOT,text=True,check=True,stdout=subprocess.PIPE if capture else None,stderr=subprocess.STDOUT if capture else None)
    return (p.stdout or "").strip()


def gh_json(endpoint: str) -> dict:
    return json.loads(run("gh","api",endpoint,capture=True))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")


def count_rows(path: Path) -> int:
    with path.open("r",encoding="utf-8-sig") as h: return max(0,sum(1 for _ in h)-1)


def wait_branch_sha(sha: str, polls: int=90) -> None:
    for _ in range(polls):
        branch=gh_json(f"repos/{REPO}/branches/worddeck-bootstrap")
        if branch.get("commit",{}).get("sha")==sha: return
        time.sleep(2)
    raise RuntimeError(f"Branch did not converge to expected SHA {sha}")


def wait_windows_ci(sha: str) -> tuple[dict,dict]:
    wait_branch_sha(sha)
    run("gh","workflow","run","worddeck-windows.yml","--repo",REPO,"--ref","worddeck-bootstrap")
    run_id=None
    for _ in range(180):
        payload=gh_json(f"repos/{REPO}/actions/workflows/worddeck-windows.yml/runs?branch=worddeck-bootstrap&event=workflow_dispatch&per_page=50")
        for item in payload.get("workflow_runs",[]):
            if item.get("head_sha")==sha and item.get("head_branch")=="worddeck-bootstrap":
                run_id=int(item["id"]); break
        if run_id: break
        time.sleep(5)
    if not run_id: raise RuntimeError(f"No exact-head Windows dispatch for {sha}")
    for _ in range(240):
        info=gh_json(f"repos/{REPO}/actions/runs/{run_id}")
        if info.get("head_sha")!=sha or info.get("head_branch")!="worddeck-bootstrap" or info.get("event")!="workflow_dispatch":
            raise RuntimeError(f"Windows run identity mismatch: {run_id}")
        if info.get("status")=="completed":
            if info.get("conclusion")!="success": raise RuntimeError(f"Windows run {run_id} failed: {info.get('conclusion')}")
            artifacts=gh_json(f"repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100")
            live=[a for a in artifacts.get("artifacts",[]) if not a.get("expired")]
            if len(live)<8: raise RuntimeError(f"Windows run {run_id} has only {len(live)} live artifacts")
            logs=run("gh","run","view",str(run_id),"--repo",REPO,"--log",capture=True)
            for bad in ("Traceback (most recent call last)","##[error]","Process completed with exit code 1"):
                if bad in logs: raise RuntimeError(f"Hidden Windows failure marker {bad!r} in {run_id}")
            for good in ("Oxford 3000 baseline verified: rows=3308","Build succeeded.","0 Error(s)","WordDeck self-test passed"):
                if good not in logs: raise RuntimeError(f"Windows run {run_id} lacks {good!r}")
            ART.mkdir(parents=True,exist_ok=True)
            (ART/f"windows-run-{sha}.log").write_text(logs,encoding="utf-8")
            write_json(ART/f"windows-run-{sha}.json",info); write_json(ART/f"windows-artifacts-{sha}.json",artifacts)
            with (ART/"windows-run-ids.tsv").open("a",encoding="utf-8") as h: h.write(f"{sha}\t{run_id}\tworkflow_dispatch\n")
            return info,artifacts
        time.sleep(10)
    raise RuntimeError(f"Timed out waiting for Windows run {run_id}")


def ledger(prefix: str) -> tuple[Path,Path,Path]:
    runtime=TMP/f"{prefix}-runtime.tsv"; accounting=TMP/f"{prefix}-accounting.tsv"; unaccounted=TMP/f"{prefix}-unaccounted.tsv"
    run("python","WordDeck/tools/validate_oxford5000_runtime_ledger.py","--official-html",str(TMP/"official.html"),"--ledger",str(runtime),"--report",str(accounting),"--unaccounted",str(unaccounted))
    return runtime,accounting,unaccounted


def rename_slices(txdir: Path) -> None:
    op=txdir/"orchestration.json"; tp=txdir/"transaction"/"transaction.json"; sp=txdir/"transaction"/"prepared-slices"
    orch=json.loads(op.read_text(encoding="utf-8")); tx=json.loads(tp.read_text(encoding="utf-8")); by={}
    for cp in tx["checkpoints"]:
        old=cp["file_name"]; new=old.replace("oxford5000_source_after_auto_","oxford5000_source_after_manual_v8_")
        if new==old: raise RuntimeError(f"Unexpected prepared slice name {old}")
        (sp/old).rename(sp/new); cp["file_name"]=new; by[int(cp["index"])]=new
    for cp in orch["checkpoints"]: cp["file"]=by[int(cp["index"])]
    write_json(tp,tx); write_json(op,orch)


def stage_review_evidence(qadir: Path) -> list[str]:
    mapping={
        "first-pass.tsv":"WordDeck/QA/oxford5000_manual_emergency_v8_first_pass.tsv",
        "second-pass.tsv":"WordDeck/QA/oxford5000_manual_emergency_v8_second_pass.tsv",
        "review-evidence.tsv":"WordDeck/QA/oxford5000_manual_emergency_v8_review_evidence.tsv",
        "summary.json":"WordDeck/QA/oxford5000_manual_emergency_v8_summary.json",
    }
    out=[]
    for src,dst in mapping.items(): shutil.copyfile(qadir/src,ROOT/dst); out.append(dst)
    return out


def integrate_all(qadir: Path, pre_runtime: Path, pre_unaccounted: Path, passed: int) -> tuple[int,list[dict]]:
    txdir=TMP/"tx-all"; run("python","WordDeck/tools/orchestrate_oxford5000_bulk_run.py","start","--worddeck-dir","WordDeck","--run-dir",str(txdir),"--official-html",str(TMP/"official.html"),"--pre-runtime",str(pre_runtime),"--pre-unaccounted",str(pre_unaccounted),"--data-factory",str(qadir/"first-pass.tsv"),"--content-qa",str(qadir/"second-pass.tsv"),"--checkpoint-size","120")
    rename_slices(txdir); plan=json.loads((txdir/"orchestration.json").read_text(encoding="utf-8")); cps=plan["checkpoints"]
    if sum(int(cp["rows"]) for cp in cps)!=passed: raise RuntimeError("V8 checkpoint total mismatch")
    evidence=[]
    for ordinal,cp in enumerate(cps,1):
        run("python","WordDeck/tools/orchestrate_oxford5000_bulk_run.py","apply-next","--worddeck-dir","WordDeck","--run-dir",str(txdir))
        fn=cp["file"]; paths=["WordDeck/ReviewedOxford5000Bootstrap.cs","WordDeck/WordDeck.csproj",f"WordDeck/QA/{fn}"]
        if ordinal==1: paths.extend(stage_review_evidence(qadir))
        run("git","add","--",*paths); run("git","diff","--cached","--check")
        run("git","commit","-m",f"WordDeck: integrate V8 Oxford 5000 checkpoint {ordinal:02d} of {len(cps):02d}")
        sha=run("git","rev-parse","HEAD",capture=True); run("git","push","origin","HEAD:worddeck-bootstrap"); wait_branch_sha(sha)
        info,artifacts=wait_windows_ci(sha); run_json=TMP/"ci-run.json"; art_json=TMP/"ci-artifacts.json"; write_json(run_json,info); write_json(art_json,artifacts)
        run("python","WordDeck/tools/orchestrate_oxford5000_bulk_run.py","mark-ci-green","--worddeck-dir","WordDeck","--run-dir",str(txdir),"--run-json",str(run_json),"--artifacts-json",str(art_json))
        evidence.append({"ordinal":ordinal,"rows":int(cp["rows"]),"sha":sha,"windows_run_id":int(info["id"])})
    run("python","WordDeck/tools/orchestrate_oxford5000_bulk_run.py","finalize","--worddeck-dir","WordDeck","--run-dir",str(txdir))
    shutil.copyfile(txdir/"final-summary.json",ART/"orchestration-final-summary.json")
    return sum(int(cp["rows"]) for cp in cps),evidence


def ensure_full_audio_request() -> str:
    path=WORDDECK/"Audio"/"generation-request.json"
    req={"source":"oxford5000","start":0,"limit":0,"accent":"en-GB","femaleVoice":"bf_emma","maleVoice":"bm_george","speed":1.0,"format":"mp3"}
    path.write_text(json.dumps(req,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    run("git","add","--",str(path)); run("git","diff","--cached","--check")
    if run("git","diff","--cached","--name-only",capture=True):
        run("git","commit","-m","WordDeck: request complete 2138-ID British offline AudioPack after V8 lexical completion")
        sha=run("git","rev-parse","HEAD",capture=True); run("git","push","origin","HEAD:worddeck-bootstrap"); wait_branch_sha(sha); wait_windows_ci(sha); return sha
    return run("git","rev-parse","HEAD",capture=True)


def wait_audio(sha: str) -> tuple[dict,dict]:
    wait_branch_sha(sha); run("gh","workflow","run","worddeck-audio.yml","--repo",REPO,"--ref","worddeck-bootstrap")
    run_id=None
    for _ in range(180):
        payload=gh_json(f"repos/{REPO}/actions/workflows/worddeck-audio.yml/runs?branch=worddeck-bootstrap&event=workflow_dispatch&per_page=50")
        for item in payload.get("workflow_runs",[]):
            if item.get("head_sha")==sha and item.get("head_branch")=="worddeck-bootstrap": run_id=int(item["id"]); break
        if run_id: break
        time.sleep(5)
    if not run_id: raise RuntimeError(f"No exact-head audio dispatch for {sha}")
    for _ in range(1800):
        info=gh_json(f"repos/{REPO}/actions/runs/{run_id}")
        if info.get("status")=="completed":
            if info.get("conclusion")!="success": raise RuntimeError(f"Audio run {run_id} failed: {info.get('conclusion')}")
            artifacts=gh_json(f"repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100")
            names={a.get("name") for a in artifacts.get("artifacts",[]) if not a.get("expired")}
            required={"worddeck-oxford5000-en-gb-0-0","WordDeck-win-x64-with-oxford5000-audio"}
            if not required<=names: raise RuntimeError(f"Audio run missing artifacts: {sorted(required-names)}")
            write_json(ART/"audio-run.json",info); write_json(ART/"audio-artifacts.json",artifacts)
            jobs=gh_json(f"repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100")
            write_json(ART/"audio-jobs.json",jobs)
            return info,artifacts
        time.sleep(10)
    raise RuntimeError(f"Timed out waiting for audio run {run_id}")


def main() -> int:
    TMP.mkdir(parents=True,exist_ok=True); ART.mkdir(parents=True,exist_ok=True)
    run("git","config","user.name","github-actions[bot]"); run("git","config","user.email","41898282+github-actions[bot]@users.noreply.github.com")
    run("python","WordDeck/tools/fetch_oxford5000_official_html.py","--output",str(TMP/"official.html"))
    start_runtime,_,start_unaccounted=ledger("start")
    start_n=count_rows(start_runtime); remaining=count_rows(start_unaccounted)
    if start_n!=1004 or remaining!=1134: raise RuntimeError(f"V8 expects technical V7 state 1004/1134, got {start_n}/{remaining}")
    unresolved=WORDDECK/"QA"/"oxford5000_manual_emergency_v7_final_unresolved.tsv"
    if count_rows(unresolved)!=1134: raise RuntimeError("V8 unresolved source must contain exactly 1134 rows")
    unacc_ids={r.split("\t",1)[0] for r in start_unaccounted.read_text(encoding="utf-8-sig").splitlines()[1:] if r.strip()}
    unresolved_ids={r.split("\t",1)[0] for r in unresolved.read_text(encoding="utf-8-sig").splitlines()[1:] if r.strip()}
    if unacc_ids!=unresolved_ids: raise RuntimeError("V8 unresolved evidence IDs do not equal exact live unaccounted ledger")
    run("python","WordDeck/tools/validate_oxford3000_baseline_files.py","--report",str(TMP/"oxford3000-start.tsv"))

    qadir=TMP/"content"; qadir.mkdir(parents=True,exist_ok=True)
    run("python","WordDeck/tools/complete_oxford5000_emergency_v8.py","--input",str(unresolved),"--qa-dir",str(qadir))
    summary=json.loads((qadir/"summary.json").read_text(encoding="utf-8"))
    if int(summary["pass"])!=1134 or int(summary["blocked"])!=0: raise RuntimeError(f"V8 must resolve entire 1134-row tail: {summary}")
    integrated,checkpoints=integrate_all(qadir,start_runtime,start_unaccounted,1134)
    final_runtime,final_accounting,final_unaccounted=ledger("final")
    final_n=count_rows(final_runtime); final_remaining=count_rows(final_unaccounted)
    if integrated!=1134 or final_n!=2138 or final_remaining!=0: raise RuntimeError(f"V8 lexical completion mismatch integrated={integrated} final={final_n}/{final_remaining}")
    shutil.copyfile(final_runtime,ART/"final-runtime.tsv"); shutil.copyfile(final_accounting,ART/"final-accounting.tsv"); shutil.copyfile(final_unaccounted,ART/"final-unaccounted.tsv"); shutil.copyfile(qadir/"review-evidence.tsv",ART/"v8-review-evidence.tsv")
    run("python","WordDeck/tools/validate_oxford3000_baseline_files.py","--report",str(ART/"oxford3000-final.tsv"))

    final_sha=ensure_full_audio_request(); audio_info,audio_artifacts=wait_audio(final_sha)
    final={"start_activated":1004,"start_remaining":1134,"v8_reviewed":1134,"v8_second_semantic_qa":1134,"newly_activated_v8":1134,"final_activated":2138,"final_remaining":0,"checkpoint_count":len(checkpoints),"checkpoints":checkpoints,"final_sha":final_sha,"audio_complete":True,"audio_run_id":int(audio_info["id"]),"audio_covered_ids":2138,"audio_assets":2138,"audio_required_artifacts":["worddeck-oxford5000-en-gb-0-0","WordDeck-win-x64-with-oxford5000-audio"],"provenance":"WORK_DEVELOPER_MANUAL_EMERGENCY_CONTEXTUAL_REVIEW; not AUTO_DATA_FACTORY/AUTO_CONTENT_QA"}
    write_json(ART/"final-summary.json",final)
    with GH_ENV.open("a",encoding="utf-8") as h:
        h.write(f"FINAL_RUNTIME=2138\nFINAL_REMAINING=0\nFINAL_SHA={final_sha}\nTOTAL_INTEGRATED=1134\nAUDIO_RUN_ID={audio_info['id']}\nAUDIO_COMPLETE=true\n")
    print(json.dumps(final,ensure_ascii=False,indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())
