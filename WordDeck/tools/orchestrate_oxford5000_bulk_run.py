#!/usr/bin/env python3
"""Resumable end-to-end orchestration for real Oxford 5000 bulk checkpoints.

Development-time only. No harvesting or linguistic judgement is performed. The tool
binds strict provenance -> transactional APPLY-NEXT -> exact pre/post corpus evidence ->
transition/evidence gates -> authoritative Windows CI evidence before a later checkpoint
may proceed. Run state and evidence must stay outside the repository root.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import prepare_oxford5000_bulk_integration as bulk
import validate_oxford5000_automation_handoff as handoff
import validate_oxford5000_handoff_provenance as provenance
import validate_oxford5000_integration_transition as transition
import validate_oxford5000_runtime_ledger as ledger
import validate_oxford5000_transition_evidence as transition_evidence

VERSION = 1
EXPECTED_ARTIFACTS = {
    "WordDeck-win-x64", "WordDeck-oxford3000-baseline-integrity",
    "WordDeck-oxford5000-official-inventory", "WordDeck-oxford5000-canonical-runtime",
    "WordDeck-oxford5000-runtime-accounting", "WordDeck-oxford5000-unaccounted",
    "WordDeck-sentence-coverage-gap-records", "WordDeck-pronunciation-regeneration-request",
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def paths(run: Path) -> dict[str, Path]:
    return {"journal": run / "orchestration.json", "input": run / "immutable-input",
            "tx": run / "transaction", "evidence": run / "checkpoint-evidence",
            "final": run / "final-summary.json"}


def load_json(path: Path) -> dict[str, Any]:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict): raise ValueError(f"Expected JSON object in {path.name}")
    return obj


def save_json(path: Path, obj: dict[str, Any]) -> None:
    bulk.atomic(path, (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())


def fp(path: Path) -> dict[str, str]: return bulk.state(path)


def copy_exact(src: Path, dst: Path) -> dict[str, str]:
    data = src.read_bytes()
    if dst.exists() and dst.read_bytes() != data: raise ValueError(f"Immutable input drifted: {dst.name}")
    if not dst.exists(): bulk.atomic(dst, data)
    return fp(dst)


def git_checkpoint(worddeck: Path) -> str:
    repo = worddeck.resolve().parent
    try:
        sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip().lower()
        branch = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("Could not verify local Git checkpoint") from exc
    if not SHA_RE.fullmatch(sha) or branch != "worddeck-bootstrap":
        raise ValueError(f"Expected worddeck-bootstrap at a valid Git HEAD, got {branch!r}/{sha!r}")
    return sha


def immutable(run: Path) -> dict[str, Path]:
    root = paths(run)["input"]
    return {"official": root / "official.html", "pre_runtime": root / "starting-runtime.tsv",
            "pre_unaccounted": root / "starting-unaccounted.tsv", "data": root / "data-factory.tsv",
            "qa": root / "content-qa.tsv"}


def generate(worddeck: Path, official: Path, runtime: Path, unaccounted: Path, report: Path) -> tuple[int, int]:
    rows, staged_counts, staged_rows, staged_files = ledger.build_runtime_ledger(worddeck)
    remaining, stats = ledger.reconcile_official(rows, staged_rows, official)
    ledger.write_ledger(rows, runtime); ledger.write_unaccounted(remaining, unaccounted)
    ledger.write_report(rows, staged_counts, staged_files, report, stats)
    return len(rows), len(remaining)


def start(worddeck: Path, run: Path, official: Path, pre_runtime: Path, pre_unaccounted: Path,
          data: Path, qa: Path, chunk: int) -> dict[str, Any]:
    worddeck, run = worddeck.resolve(), run.resolve(); bulk.ensure_tx_outside_repo(worddeck, run)
    start_head = git_checkpoint(worddeck); p = paths(run); p["input"].mkdir(parents=True, exist_ok=True); p["evidence"].mkdir(parents=True, exist_ok=True)
    inp = immutable(run); sources = {"official": official, "pre_runtime": pre_runtime,
        "pre_unaccounted": pre_unaccounted, "data": data, "qa": qa}
    states = {k: copy_exact(Path(v), inp[k]) for k, v in sources.items()}
    if p["journal"].exists():
        old = load_json(p["journal"])
        if old.get("immutable_input") != states or Path(old["worddeck_dir"]).resolve() != worddeck:
            raise ValueError("Existing orchestration journal disagrees with this run")
        return old
    current = run / "starting-reconciliation"; rc, rem = generate(worddeck, inp["official"], current/"runtime.tsv", current/"unaccounted.tsv", current/"accounting.tsv")
    if fp(current/"runtime.tsv") != states["pre_runtime"] or fp(current/"unaccounted.tsv") != states["pre_unaccounted"]:
        raise ValueError("Starting authoritative artifacts do not match the current repository")
    plan = bulk.prepare(worddeck, inp["pre_unaccounted"], inp["data"], inp["qa"], p["tx"], chunk)
    if int(plan["start_count"]) != rc: raise ValueError("Bulk start count disagrees with runtime ledger")
    state = {"version": VERSION, "status": "ACTIVE", "worddeck_dir": str(worddeck), "starting_git_head": start_head,
        "transaction_id": plan["transaction_id"], "immutable_input": states, "starting_runtime": rc,
        "starting_remaining": rem, "qualified_pass": int(plan["qualified_pass_rows"]), "fail_closed": int(plan["fail_closed_rows"]),
        "projected_runtime": int(plan["projected_final_count"]), "projected_remaining": rem-int(plan["qualified_pass_rows"]),
        "checkpoints": [{"index": int(c["index"]), "rows": int(c["expected_rows"]), "file": c["file_name"],
            "before": int(c["count_before"]), "after": int(c["count_after"]), "status": "PENDING", "attempts": []}
            for c in plan["checkpoints"]], "recoveries": []}
    save_json(p["journal"], state); return state


def load(run: Path) -> dict[str, Any]:
    j = paths(run.resolve())["journal"]
    if not j.is_file(): raise FileNotFoundError("Run start has not been recorded")
    return load_json(j)


def bulk_plan(run: Path) -> dict[str, Any]: return load_json(bulk.tx_paths(paths(run.resolve())["tx"])["journal"])


def recover(worddeck: Path, run: Path) -> dict[str, Any]:
    worddeck, run = worddeck.resolve(), run.resolve(); bulk.ensure_tx_outside_repo(worddeck, run); state = load(run)
    if Path(state["worddeck_dir"]).resolve() != worddeck: raise ValueError("Orchestration journal targets a different WordDeck directory")
    bp = bulk_plan(run)
    applying = next((c for c in bp["checkpoints"] if c["status"] == "APPLYING"), None)
    if applying:
        bulk.recover_applying(worddeck, paths(run)["tx"], bp); state["recoveries"].append({"checkpoint": applying["index"], "action": "APPLYING_TO_PENDING"}); save_json(paths(run)["journal"], state); bp = bulk_plan(run)
    for oc, bc in zip(state["checkpoints"], bp["checkpoints"], strict=True):
        if oc["status"] == "PENDING" and bc["status"] == "APPLIED":
            applied = [int(x["index"]) for x in bp["checkpoints"] if x["status"] == "APPLIED"]
            if int(bc["index"]) != max(applied): raise ValueError("Unvalidated APPLIED checkpoint is not LIFO")
            bulk.rollback_last(worddeck, paths(run)["tx"]); state["recoveries"].append({"checkpoint": bc["index"], "action": "ROLLED_BACK_UNVALIDATED_APPLY"}); save_json(paths(run)["journal"], state); break
        if oc["status"] in {"LOCAL_VALIDATED", "CI_GREEN"} and bc["status"] != "APPLIED": raise ValueError("Orchestration and bulk journals disagree")
    return state


def prepared_ids(run: Path, file: str) -> list[str]:
    src = bulk.tx_paths(paths(run.resolve())["tx"])["slices"] / file
    ids = [r["entry_id"] for r in handoff.read_tsv(src, {"entry_id","source","part_of_speech","level"}, "prepared checkpoint")]
    if len(ids) != len(set(ids)): raise ValueError("Prepared checkpoint has duplicate IDs")
    return ids


def subset_handoff(run: Path, ids: list[str], out: Path) -> tuple[Path, Path]:
    inp = immutable(run); d = handoff.read_tsv(inp["data"], handoff.DATA_FACTORY_REQUIRED, "full Data Factory handoff"); q = handoff.read_tsv(inp["qa"], handoff.CONTENT_QA_REQUIRED, "full Content QA handoff")
    bd, bq = {r["entry_id"]: r for r in d}, {r["entry_id"]: r for r in q}
    if any(i not in bd or i not in bq for i in ids): raise ValueError("Prepared ID is absent from immutable handoff")
    dr, qr = [bd[i] for i in ids], [bq[i] for i in ids]
    if any(r["decision"].strip().upper() != "PASS" for r in qr): raise ValueError("Prepared checkpoint contains non-PASS QA")
    df, cq = out/"data-factory.tsv", out/"content-qa.tsv"; handoff.write_tsv(dr, df, sorted(handoff.DATA_FACTORY_REQUIRED)); handoff.write_tsv(qr, cq, sorted(handoff.CONTENT_QA_REQUIRED)); return df, cq


def apply_next(worddeck: Path, run: Path) -> dict[str, Any]:
    worddeck, run = worddeck.resolve(), run.resolve(); recover(worddeck, run); state = load(run)
    waiting = next((c for c in state["checkpoints"] if c["status"] == "LOCAL_VALIDATED"), None)
    if waiting: raise ValueError(f"Checkpoint {waiting['index']} requires authoritative CI_GREEN before continuing")
    cp = next((c for c in state["checkpoints"] if c["status"] == "PENDING"), None)
    if not cp: return state
    for prev in state["checkpoints"]:
        if prev["index"] >= cp["index"]: break
        if prev["status"] != "CI_GREEN": raise ValueError(f"Checkpoint {prev['index']} is not CI_GREEN")
    attempt = len(cp["attempts"])+1; out = paths(run)["evidence"]/f"cp{cp['index']:04d}"/f"attempt{attempt:03d}"; out.mkdir(parents=True, exist_ok=True)
    cp["attempts"].append({"number": attempt, "status": "STARTED"}); save_json(paths(run)["journal"], state); mutated = False
    try:
        inp = immutable(run); pre_r, pre_u = out/"pre-runtime.tsv", out/"pre-unaccounted.tsv"
        before, rem = generate(worddeck, inp["official"], pre_r, pre_u, out/"pre-accounting.tsv")
        expected_rem = state["starting_remaining"]-sum(c["rows"] for c in state["checkpoints"] if c["status"] == "CI_GREEN")
        if before != cp["before"] or rem != expected_rem: raise ValueError("Pre-checkpoint runtime/unaccounted count drift")
        ids = prepared_ids(run, cp["file"])
        if len(ids) != cp["rows"]: raise ValueError("Prepared row count drift")
        df, cq = subset_handoff(run, ids, out); ready, unresolved, _ = provenance.execute_strict(pre_u, df, cq, out/"ready.tsv", out/"unresolved.tsv", out/"provenance.tsv")
        if unresolved or [r["entry_id"] for r in ready] != ids: raise ValueError("Checkpoint strict provenance does not equal prepared PASS identities")
        bp = bulk.apply_next(worddeck, paths(run)["tx"]); bc = next(c for c in bp["checkpoints"] if int(c["index"]) == cp["index"])
        if bc["status"] != "APPLIED": raise ValueError("Bulk checkpoint did not become APPLIED")
        mutated = True; post_r, post_u = out/"post-runtime.tsv", out/"post-unaccounted.tsv"; after, post_rem = generate(worddeck, inp["official"], post_r, post_u, out/"post-accounting.tsv")
        if after != cp["after"] or post_rem != rem-cp["rows"]: raise ValueError("Post-checkpoint corpus delta drift")
        ns = argparse.Namespace(pre_unaccounted=pre_u, data_factory=df, content_qa=cq, pre_runtime=pre_r, post_runtime=post_r, post_unaccounted=post_u, report=out/"transition.tsv")
        tr = transition.execute(ns); ens = argparse.Namespace(**vars(ns)); ens.report = out/"transition-evidence.tsv"; ev = transition_evidence.execute(ens)
        if any(int(r[k]) != cp["rows"] for r in (tr,ev) for k in ("runtime_delta","unaccounted_delta")): raise ValueError("Real transition evidence delta drift")
        state = load(run); cp = next(c for c in state["checkpoints"] if c["index"] == cp["index"]); cp["attempts"][-1]["status"] = "LOCAL_PASS"; cp["status"] = "LOCAL_VALIDATED"; cp["evidence_dir"] = str(out); cp["repo_after"] = bc["after_repo"]; save_json(paths(run)["journal"], state); return state
    except Exception as exc:
        rb = None
        if mutated:
            try: bulk.rollback_last(worddeck, paths(run)["tx"])
            except Exception as e: rb = str(e)
        state = load(run); cp = next(c for c in state["checkpoints"] if c["index"] == cp["index"]); cp["attempts"][-1].update({"status":"FAILED_ROLLED_BACK" if mutated and not rb else "FAILED", "error":str(exc)})
        cp["status"] = "PENDING" if not rb else "RECOVERY_REQUIRED"; state["status"] = "ACTIVE" if not rb else "RECOVERY_REQUIRED"
        if rb: cp["attempts"][-1]["rollback_error"] = rb
        save_json(paths(run)["journal"], state); raise


def unwrap(obj: dict[str, Any]) -> dict[str, Any]:
    while isinstance(obj.get("result"), dict): obj = obj["result"]
    return obj


def verify_ci(run_json: Path, artifacts_json: Path) -> dict[str, Any]:
    run, ao = unwrap(load_json(run_json)), unwrap(load_json(artifacts_json)); arts = ao.get("artifacts")
    if not isinstance(arts, list): raise ValueError("Artifacts JSON has no artifacts list")
    sha = str(run.get("head_sha") or "").lower()
    if not SHA_RE.fullmatch(sha) or run.get("name") != "WordDeck Windows build" or run.get("head_branch") != "worddeck-bootstrap" or run.get("status") != "completed" or run.get("conclusion") != "success": raise ValueError("Authoritative WordDeck Windows run metadata is not exact completed SUCCESS")
    rid = int(run["id"]); by = {a.get("name"): a for a in arts if isinstance(a, dict)}; missing = EXPECTED_ARTIFACTS-set(by)
    if missing: raise ValueError("Missing authoritative artifacts: "+", ".join(sorted(missing)))
    keep = {}
    for name in sorted(EXPECTED_ARTIFACTS):
        a = by[name]; wr = a.get("workflow_run")
        if a.get("expired") is True or not isinstance(wr, dict) or int(wr.get("id")) != rid or str(wr.get("head_sha") or "").lower() != sha: raise ValueError(f"Artifact {name} is not bound to exact run/HEAD")
        dg = str(a.get("digest") or "")
        if not dg.startswith("sha256:") or len(dg) != 71: raise ValueError(f"Artifact {name} lacks SHA-256 digest")
        keep[name] = {"id":int(a["id"]), "size":int(a["size_in_bytes"]), "digest":dg}
    return {"run_id":rid, "run_number":int(run["run_number"]), "head_sha":sha, "artifacts":keep}


def repo_after_state(worddeck: Path, file: str) -> dict[str, dict[str, str]]:
    target = worddeck / "QA" / file
    if not target.is_file(): raise ValueError("Applied checkpoint QA slice is missing")
    return {"bootstrap": fp(worddeck / "ReviewedOxford5000Bootstrap.cs"),
            "csproj": fp(worddeck / "WordDeck.csproj"), "slice": fp(target)}


def mark_ci(worddeck: Path, run: Path, run_json: Path, artifacts_json: Path) -> dict[str, Any]:
    worddeck, run = worddeck.resolve(), run.resolve(); recover(worddeck, run); state = load(run); cp = next((c for c in state["checkpoints"] if c["status"] == "LOCAL_VALIDATED"), None)
    if not cp: raise ValueError("No LOCAL_VALIDATED checkpoint awaits CI")
    if repo_after_state(worddeck, cp["file"]) != cp["repo_after"]: raise ValueError("Repository bytes drifted after local checkpoint validation")
    ci = verify_ci(run_json, artifacts_json)
    if git_checkpoint(worddeck) != ci["head_sha"]: raise ValueError("Local Git HEAD differs from authoritative run HEAD")
    cp["ci"] = ci; cp["status"] = "CI_GREEN"; save_json(paths(run)["journal"], state); return state


def finalize(worddeck: Path, run: Path) -> dict[str, Any]:
    worddeck, run = worddeck.resolve(), run.resolve(); recover(worddeck, run); state = load(run)
    if any(c["status"] != "CI_GREEN" for c in state["checkpoints"]): raise ValueError("Every prepared checkpoint must be CI_GREEN before finalize")
    summary = {"contract":"worddeck-oxford5000-bulk-orchestration-v1", "transaction_id":state["transaction_id"], "start_runtime":state["starting_runtime"], "final_runtime":state["projected_runtime"], "start_remaining":state["starting_remaining"], "final_remaining":state["projected_remaining"], "lexical_delta":state["qualified_pass"], "fail_closed":state["fail_closed"], "checkpoint_sizes":[c["rows"] for c in state["checkpoints"]], "run_ids":[c["ci"]["run_id"] for c in state["checkpoints"]], "final_head":state["checkpoints"][-1]["ci"]["head_sha"]}
    save_json(paths(run)["final"], summary); state["status"]="COMPLETE"; state["final_summary"]=fp(paths(run)["final"]); save_json(paths(run)["journal"], state); return state


def summary(state: dict[str, Any]) -> str:
    counts: dict[str,int]={}
    for c in state.get("checkpoints",[]): counts[c["status"]]=counts.get(c["status"],0)+1
    return f"transaction={state.get('transaction_id')}, status={state.get('status')}, ready={state.get('qualified_pass')}, checkpoints={counts}, projected_runtime={state.get('projected_runtime')}"


def self_test() -> None:
    transition.run_self_test(); transition_evidence.run_self_test()
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp); sha="a"*40; run={"id":123,"name":"WordDeck Windows build","head_branch":"worddeck-bootstrap","head_sha":sha,"status":"completed","conclusion":"success","run_number":9}
        arts={"artifacts":[{"id":i+1,"name":n,"size_in_bytes":100+i,"expired":False,"digest":"sha256:"+f"{i:064x}","workflow_run":{"id":123,"head_sha":sha}} for i,n in enumerate(sorted(EXPECTED_ARTIFACTS))]}
        r,a=root/"run.json",root/"artifacts.json"; r.write_text(json.dumps(run),encoding="utf-8"); a.write_text(json.dumps(arts),encoding="utf-8"); assert verify_ci(r,a)["head_sha"]==sha
        broken=json.loads(a.read_text()); broken["artifacts"][0]["workflow_run"]["head_sha"]="b"*40; a.write_text(json.dumps(broken),encoding="utf-8")
        try: verify_ci(r,a)
        except ValueError as e: assert "exact run/HEAD" in str(e)
        else: raise AssertionError("CI artifact HEAD mismatch was accepted")
    print("Oxford 5000 bulk orchestration self-test passed: transition evidence and authoritative CI/artifact binding are fail-closed.")


def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--self-test",action="store_true"); s=p.add_subparsers(dest="command")
    x=s.add_parser("start");
    for n in ("worddeck-dir","run-dir","official-html","pre-runtime","pre-unaccounted","data-factory","content-qa"): x.add_argument("--"+n,type=Path,required=True)
    x.add_argument("--checkpoint-size",type=int,default=bulk.DEFAULT_CHUNK)
    for name in ("apply-next","recover","finalize"):
        x=s.add_parser(name); x.add_argument("--worddeck-dir",type=Path,required=True); x.add_argument("--run-dir",type=Path,required=True)
    x=s.add_parser("mark-ci-green"); x.add_argument("--worddeck-dir",type=Path,required=True); x.add_argument("--run-dir",type=Path,required=True); x.add_argument("--run-json",type=Path,required=True); x.add_argument("--artifacts-json",type=Path,required=True)
    x=s.add_parser("status"); x.add_argument("--run-dir",type=Path,required=True); return p


def main() -> int:
    a=parser().parse_args()
    if a.self_test: self_test(); return 0
    if a.command=="start": st=start(a.worddeck_dir,a.run_dir,a.official_html,a.pre_runtime,a.pre_unaccounted,a.data_factory,a.content_qa,a.checkpoint_size)
    elif a.command=="apply-next": st=apply_next(a.worddeck_dir,a.run_dir)
    elif a.command=="recover": st=recover(a.worddeck_dir,a.run_dir)
    elif a.command=="mark-ci-green": st=mark_ci(a.worddeck_dir,a.run_dir,a.run_json,a.artifacts_json)
    elif a.command=="finalize": st=finalize(a.worddeck_dir,a.run_dir)
    elif a.command=="status": st=load(a.run_dir.resolve())
    else: raise SystemExit("choose a command or use --self-test")
    print("Oxford 5000 bulk orchestration: "+summary(st)); return 0


if __name__=="__main__": raise SystemExit(main())