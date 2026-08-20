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
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


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
        if oc["status"] == "RECOVERY_REQUIRED":
            if bc["status"] != "APPLIED":
                raise ValueError("RECOVERY_REQUIRED checkpoint does not match an APPLIED bulk checkpoint")
            applied = [int(x["index"]) for x in bp["checkpoints"] if x["status"] == "APPLIED"]
            if int(bc["index"]) != max(applied): raise ValueError("RECOVERY_REQUIRED checkpoint is not LIFO")
            try:
                bulk.rollback_last(worddeck, paths(run)["tx"])
            except Exception as exc:
                raise ValueError(f"Checkpoint {oc['index']} remains RECOVERY_REQUIRED; rollback retry failed") from exc
            oc["status"] = "PENDING"; state["status"] = "ACTIVE"
            state["recoveries"].append({"checkpoint": bc["index"], "action": "RECOVERY_REQUIRED_TO_PENDING"})
            save_json(paths(run)["journal"], state); return state
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
        if a.get("expired") is not False or not isinstance(wr, dict) or int(wr.get("id")) != rid or str(wr.get("head_sha") or "").lower() != sha: raise ValueError(f"Artifact {name} is not bound to exact run/HEAD")
        dg = str(a.get("digest") or "").lower()
        if not DIGEST_RE.fullmatch(dg): raise ValueError(f"Artifact {name} lacks valid SHA-256 digest")
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
    """Exercise the real orchestration state machine in isolated synthetic Git repos."""
    transition.run_self_test(); transition_evidence.run_self_test()

    def expect_error(label: str, action: Any, needle: str) -> str:
        try:
            action()
        except ValueError as exc:
            text = str(exc)
            if needle not in text:
                raise AssertionError(f"{label}: expected {needle!r}, got {text!r}") from exc
            return text
        raise AssertionError(f"{label}: expected ValueError")

    def git(repo: Path, *args: str) -> str:
        proc = subprocess.run(["git", "-C", str(repo), *args], check=False, capture_output=True, text=True)
        if proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}")
        return proc.stdout.strip()

    def commit(repo: Path, message: str) -> str:
        git(repo, "add", "-A"); git(repo, "commit", "-m", message)
        sha = git(repo, "rev-parse", "HEAD").lower()
        if not SHA_RE.fullmatch(sha): raise AssertionError("Synthetic Git commit did not produce a valid SHA")
        return sha

    def write_official(path: Path, identities: list[tuple[str, str, str]]) -> None:
        lines = ["<html><body><div id=\"wordlistsContentPanel\"><ul>"]
        for source, pos, level in identities:
            lines.append(
                f'<li data-hw="{source}" data-ox5000="{level.lower()}">'
                f'<a href="/definition/english/{source}">{source}</a>'
                f'<span class="pos">{pos}</span></li>'
            )
        lines.append("</ul></div></body></html>")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def make_fixture(base: Path, pass_count: int) -> dict[str, Path]:
        repo, worddeck, inputs, run_dir = base/"repo", base/"repo"/"WordDeck", base/"inputs", base/"run"
        qa_dir = worddeck/"QA"; qa_dir.mkdir(parents=True, exist_ok=True); inputs.mkdir(parents=True, exist_ok=True)
        initial = [("seed-alpha", "noun", "B2"), ("seed-beta", "verb", "C1")]
        candidates = [
            (f"fixture-word-{i:04d}", "noun" if i % 2 else "verb", "C1" if i % 3 == 0 else "B2")
            for i in range(1, pass_count + 1)
        ]
        official = inputs/"official.html"; write_official(official, initial + candidates)
        initial_name = "oxford5000_source_after_selftest_initial.tsv"
        initial_rows = [{"entry_id":handoff.lexical_entry_id(s,p,l), "source":s, "part_of_speech":p,
                         "level":l, "status":"verified", "ukrainian":f"початковий-{n}"}
                        for n,(s,p,l) in enumerate(initial, 1)]
        handoff.write_tsv(initial_rows, qa_dir/initial_name,
                          ["entry_id","source","part_of_speech","level","status","ukrainian"])
        (worddeck/"ReviewedOxford5000Bootstrap.cs").write_text(
            "internal static class Fixture {\n"
            " public const int ExpectedCanonicalRows = 2;\n"
            " void Build() {\n"
            f"  AppendVerifiedSlice(result, \"{initial_name}\", 2, 100);\n"
            " }\n}\n", encoding="utf-8")
        (worddeck/"WordDeck.csproj").write_text(
            f'<Project><ItemGroup>\n <EmbeddedResource Include="QA\\{initial_name}" />\n</ItemGroup></Project>\n',
            encoding="utf-8")
        data_rows, qa_rows = [], []
        for i, (source, pos, level) in enumerate(candidates, 1):
            eid = handoff.lexical_entry_id(source, pos, level)
            data_rows.append({"data_factory_run_id":"df-e2e", "entry_id":eid, "source":source,
                              "part_of_speech":pos, "level":level, "official_source":"synthetic-official",
                              "source_check":f"checked-{i}", "ukrainian_candidate":f"кандидат-{i}"})
            qa_rows.append({"content_qa_run_id":"qa-e2e", "data_factory_run_id":"df-e2e",
                            "entry_id":eid, "source":source, "part_of_speech":pos, "level":level,
                            "decision":"PASS", "ukrainian":f"переклад-{i}", "qa_reason":"synthetic pass"})
        data, qa = inputs/"data-factory.tsv", inputs/"content-qa.tsv"
        handoff.write_tsv(data_rows, data, sorted(handoff.DATA_FACTORY_REQUIRED))
        handoff.write_tsv(qa_rows, qa, sorted(handoff.CONTENT_QA_REQUIRED))
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
        git(repo, "config", "user.email", "worddeck-selftest@example.invalid")
        git(repo, "config", "user.name", "WordDeck Self-Test")
        git(repo, "checkout", "-b", "worddeck-bootstrap")
        commit(repo, "selftest fixture baseline")
        pre_runtime, pre_unaccounted = inputs/"pre-runtime.tsv", inputs/"pre-unaccounted.tsv"
        rc, rem = generate(worddeck, official, pre_runtime, pre_unaccounted, inputs/"pre-accounting.tsv")
        if rc != 2 or rem != pass_count: raise AssertionError(f"Synthetic starting ledger mismatch: {rc}/{rem}")
        return {"repo":repo, "worddeck":worddeck, "inputs":inputs, "run":run_dir, "official":official,
                "pre_runtime":pre_runtime, "pre_unaccounted":pre_unaccounted, "data":data, "qa":qa}

    def ci_payload(root: Path, sha: str, run_id: int, run_number: int,
                   run_change: tuple[str, Any] | None = None,
                   artifact_change: tuple[int, str, Any] | None = None,
                   remove_artifact: str | None = None) -> tuple[Path, Path]:
        meta: dict[str, Any] = {"id":run_id, "name":"WordDeck Windows build", "head_branch":"worddeck-bootstrap",
                                "head_sha":sha, "status":"completed", "conclusion":"success", "run_number":run_number}
        arts = {"artifacts":[{"id":i+1, "name":name, "size_in_bytes":100+i, "expired":False,
                              "digest":"sha256:"+f"{i+1:064x}",
                              "workflow_run":{"id":run_id, "head_sha":sha}}
                             for i,name in enumerate(sorted(EXPECTED_ARTIFACTS))]}
        if run_change is not None: meta[run_change[0]] = run_change[1]
        if remove_artifact is not None:
            arts["artifacts"] = [a for a in arts["artifacts"] if a["name"] != remove_artifact]
        if artifact_change is not None:
            index, key, value = artifact_change
            if key.startswith("workflow_run."):
                arts["artifacts"][index]["workflow_run"][key.split(".",1)[1]] = value
            else:
                arts["artifacts"][index][key] = value
        r, a = root/"run.json", root/"artifacts.json"
        r.parent.mkdir(parents=True, exist_ok=True); r.write_text(json.dumps(meta), encoding="utf-8"); a.write_text(json.dumps(arts), encoding="utf-8")
        return r, a

    original_legacy = ledger.legacy.canonicalize
    ledger.legacy.canonicalize = lambda _qa_dir: []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); f = make_fixture(root/"main", 245)
            worddeck, run_dir, repo = f["worddeck"], f["run"], f["repo"]
            state = start(worddeck, run_dir, f["official"], f["pre_runtime"], f["pre_unaccounted"], f["data"], f["qa"], 120)
            if [c["rows"] for c in state["checkpoints"]] != [120,120,5]: raise AssertionError("START did not produce [120,120,5]")
            if (state["starting_runtime"], state["projected_runtime"], state["starting_remaining"], state["projected_remaining"]) != (2,247,245,0):
                raise AssertionError("START projected counts are wrong")
            for key, captured in state["immutable_input"].items():
                if fp(immutable(run_dir)[key]) != captured: raise AssertionError(f"Immutable {key} capture mismatch")
            if load_json(paths(run_dir)["journal"])["transaction_id"] != state["transaction_id"]: raise AssertionError("START journal did not persist")
            print("ORCH-E2E START PASS: real start(), immutable inputs, checkpoints=[120,120,5], projected 2->247.")

            state = apply_next(worddeck, run_dir); cp1 = state["checkpoints"][0]
            if cp1["status"] != "LOCAL_VALIDATED": raise AssertionError("Checkpoint 1 did not become LOCAL_VALIDATED")
            ev1 = Path(cp1["evidence_dir"])
            required = ["pre-runtime.tsv","pre-unaccounted.tsv","data-factory.tsv","content-qa.tsv","ready.tsv",
                        "provenance.tsv","post-runtime.tsv","post-unaccounted.tsv","transition.tsv","transition-evidence.tsv"]
            if any(not (ev1/name).is_file() for name in required): raise AssertionError("Checkpoint 1 real evidence set is incomplete")
            pre_rows = transition.read_tsv(ev1/"pre-runtime.tsv", transition.RUNTIME_REQUIRED, "selftest pre runtime")
            post_rows = transition.read_tsv(ev1/"post-runtime.tsv", transition.RUNTIME_REQUIRED, "selftest post runtime")
            pre_tail = transition.read_tsv(ev1/"pre-unaccounted.tsv", transition.UNACCOUNTED_REQUIRED, "selftest pre tail")
            post_tail = transition.read_tsv(ev1/"post-unaccounted.tsv", transition.UNACCOUNTED_REQUIRED, "selftest post tail")
            if len(post_rows)-len(pre_rows) != 120 or len(pre_tail)-len(post_tail) != 120: raise AssertionError("Checkpoint 1 real delta is not 120")
            if len(handoff.read_tsv(ev1/"data-factory.tsv", handoff.DATA_FACTORY_REQUIRED, "cp1 df")) != 120: raise AssertionError("Checkpoint 1 Data Factory subset is not 120")
            if len(handoff.read_tsv(ev1/"content-qa.tsv", handoff.CONTENT_QA_REQUIRED, "cp1 qa")) != 120: raise AssertionError("Checkpoint 1 Content QA subset is not 120")
            expect_error("later checkpoint before CI", lambda: apply_next(worddeck, run_dir), "requires authoritative CI_GREEN")
            print("ORCH-E2E APPLY-NEXT PASS: cp1 LOCAL_VALIDATED, exact +120/-120 evidence, later checkpoint blocked before CI_GREEN.")

            head1 = commit(repo, "selftest checkpoint 1")
            ci_root = root/"ci-cases"
            r,a = ci_payload(ci_root, head1, 1001, 1, run_change=("name","Wrong workflow"))
            expect_error("wrong workflow", lambda: mark_ci(worddeck, run_dir, r, a), "metadata is not exact")
            r,a = ci_payload(ci_root, head1, 1001, 1, run_change=("head_branch","wrong-branch"))
            expect_error("wrong branch", lambda: mark_ci(worddeck, run_dir, r, a), "metadata is not exact")
            r,a = ci_payload(ci_root, "x"*40, 1001, 1)
            expect_error("invalid run HEAD", lambda: mark_ci(worddeck, run_dir, r, a), "metadata is not exact")
            missing_name = sorted(EXPECTED_ARTIFACTS)[0]
            r,a = ci_payload(ci_root, head1, 1001, 1, remove_artifact=missing_name)
            expect_error("missing artifact", lambda: mark_ci(worddeck, run_dir, r, a), "Missing authoritative artifacts")
            r,a = ci_payload(ci_root, head1, 1001, 1, artifact_change=(0,"expired",True))
            expect_error("expired artifact", lambda: mark_ci(worddeck, run_dir, r, a), "not bound to exact run/HEAD")
            r,a = ci_payload(ci_root, head1, 1001, 1, artifact_change=(0,"digest","sha256:"+"g"*64))
            expect_error("invalid digest", lambda: mark_ci(worddeck, run_dir, r, a), "valid SHA-256 digest")
            r,a = ci_payload(ci_root, head1, 1001, 1, artifact_change=(0,"workflow_run.id",9999))
            expect_error("artifact wrong run", lambda: mark_ci(worddeck, run_dir, r, a), "not bound to exact run/HEAD")
            r,a = ci_payload(ci_root, "b"*40, 1001, 1)
            expect_error("local Git HEAD mismatch", lambda: mark_ci(worddeck, run_dir, r, a), "Local Git HEAD differs")
            bootstrap = worddeck/"ReviewedOxford5000Bootstrap.cs"; original_bytes = bootstrap.read_bytes(); bootstrap.write_bytes(original_bytes+b"// drift\n")
            r,a = ci_payload(ci_root, head1, 1001, 1)
            expect_error("repository bytes drift", lambda: mark_ci(worddeck, run_dir, r, a), "Repository bytes drifted")
            bulk.atomic(bootstrap, original_bytes)
            r,a = ci_payload(ci_root, head1, 1001, 1); state = mark_ci(worddeck, run_dir, r, a)
            if state["checkpoints"][0]["status"] != "CI_GREEN": raise AssertionError("Checkpoint 1 did not become CI_GREEN")
            print("ORCH-E2E MARK-CI PASS: wrong workflow/branch/head, missing/expired/bad-digest/misbound artifact, local-head and repo-drift rejection; exact metadata accepted.")

            expect_error("early finalize", lambda: finalize(worddeck, run_dir), "Every prepared checkpoint must be CI_GREEN")
            state = apply_next(worddeck, run_dir)
            if state["checkpoints"][1]["status"] != "LOCAL_VALIDATED": raise AssertionError("Checkpoint 2 did not progress after cp1 CI_GREEN")
            head2 = commit(repo, "selftest checkpoint 2"); r,a = ci_payload(ci_root, head2, 1002, 2); state = mark_ci(worddeck, run_dir, r, a)
            if state["checkpoints"][1]["status"] != "CI_GREEN": raise AssertionError("Checkpoint 2 did not become CI_GREEN")
            print("ORCH-E2E SEQUENCE PASS: cp1 CI_GREEN permitted cp2; cp2 LOCAL_VALIDATED->CI_GREEN; FINALIZE blocked early.")

            bp = bulk_plan(run_dir); bc3 = bp["checkpoints"][2]; txp = bulk.tx_paths(paths(run_dir)["tx"])
            bdir = txp["backups"]/"cp0003"; bdir.mkdir(parents=True, exist_ok=True)
            (bdir/"ReviewedOxford5000Bootstrap.cs").write_bytes((worddeck/"ReviewedOxford5000Bootstrap.cs").read_bytes())
            (bdir/"WordDeck.csproj").write_bytes((worddeck/"WordDeck.csproj").read_bytes())
            bc3["status"] = "APPLYING"; bc3["before_repo"] = bp["repo_current"]
            target3 = worddeck/"QA"/bc3["file_name"]; target3.write_text("partial", encoding="utf-8")
            bulk.write_json(txp["journal"], bp); recover(worddeck, run_dir); bp = bulk_plan(run_dir)
            if bp["checkpoints"][2]["status"] != "PENDING" or target3.exists(): raise AssertionError("APPLYING recovery failed")
            if load(run_dir)["recoveries"][-1]["action"] != "APPLYING_TO_PENDING": raise AssertionError("APPLYING recovery was not journaled")

            bp = bulk.apply_next(worddeck, paths(run_dir)["tx"])
            if bp["checkpoints"][2]["status"] != "APPLIED": raise AssertionError("Direct unmatched bulk apply failed")
            recover(worddeck, run_dir); bp = bulk_plan(run_dir)
            if bp["checkpoints"][2]["status"] != "PENDING" or (worddeck/"QA"/bc3["file_name"]).exists(): raise AssertionError("Unmatched APPLIED recovery failed")
            if load(run_dir)["recoveries"][-1]["action"] != "ROLLED_BACK_UNVALIDATED_APPLY": raise AssertionError("Unmatched APPLIED rollback was not journaled")

            bp_path = txp["journal"]; good_bp = load_json(bp_path); bad_bp = json.loads(json.dumps(good_bp)); bad_bp["checkpoints"][1]["status"] = "PENDING"; bulk.write_json(bp_path, bad_bp)
            expect_error("journal disagreement", lambda: recover(worddeck, run_dir), "journals disagree"); bulk.write_json(bp_path, good_bp)
            print("ORCH-E2E RECOVER PASS: APPLYING->PENDING, unmatched APPLIED rollback, journal disagreement fail-closed.")

            original_transition_execute = transition.execute
            def forced_transition_failure(_args: argparse.Namespace) -> dict[str, str]:
                raise ValueError("forced post-mutation transition failure")
            transition.execute = forced_transition_failure
            try:
                expect_error("post-mutation validation failure", lambda: apply_next(worddeck, run_dir), "forced post-mutation")
            finally:
                transition.execute = original_transition_execute
            state = load(run_dir); cp3 = state["checkpoints"][2]
            if cp3["status"] != "PENDING" or cp3["attempts"][-1]["status"] != "FAILED_ROLLED_BACK": raise AssertionError("Validation-failure rollback did not return cp3 to PENDING")
            if bulk_plan(run_dir)["checkpoints"][2]["status"] != "PENDING": raise AssertionError("Bulk rollback after validation failure did not persist")
            print("ORCH-E2E ROLLBACK PASS: forced post-mutation validation failure automatically rolled back and persisted failed attempt.")

            state = apply_next(worddeck, run_dir)
            if state["checkpoints"][2]["status"] != "LOCAL_VALIDATED": raise AssertionError("Checkpoint 3 did not become LOCAL_VALIDATED")
            head3 = commit(repo, "selftest checkpoint 3"); r,a = ci_payload(ci_root, head3, 1003, 3); state = mark_ci(worddeck, run_dir, r, a)
            if [c["status"] for c in state["checkpoints"]] != ["CI_GREEN"]*3: raise AssertionError("Not all checkpoints became CI_GREEN")
            state = finalize(worddeck, run_dir)
            persisted = load_json(paths(run_dir)["journal"]); final_summary = load_json(paths(run_dir)["final"])
            if state["status"] != "COMPLETE" or persisted["status"] != "COMPLETE": raise AssertionError("FINALIZE status did not persist")
            expected_summary = {"start_runtime":2,"final_runtime":247,"start_remaining":245,"final_remaining":0,"lexical_delta":245,"checkpoint_sizes":[120,120,5],"run_ids":[1001,1002,1003],"final_head":head3}
            for key,value in expected_summary.items():
                if final_summary.get(key) != value: raise AssertionError(f"Final summary {key} mismatch: {final_summary.get(key)!r}")
            if fp(paths(run_dir)["final"]) != persisted["final_summary"]: raise AssertionError("Persisted final-summary fingerprint mismatch")
            print("ORCH-E2E FINALIZE PASS: all three checkpoints CI_GREEN; persisted final summary proves +245 rows and exact run/head sequence.")

            ff = make_fixture(root/"rollback-failure", 5); fw, fr = ff["worddeck"], ff["run"]
            start(fw, fr, ff["official"], ff["pre_runtime"], ff["pre_unaccounted"], ff["data"], ff["qa"], 5)
            original_transition_execute = transition.execute; original_rollback = bulk.rollback_last
            transition.execute = forced_transition_failure
            def forced_rollback_failure(_worddeck: Path, _tx: Path) -> dict[str, Any]:
                raise ValueError("forced rollback failure")
            bulk.rollback_last = forced_rollback_failure
            try:
                expect_error("rollback failure trigger", lambda: apply_next(fw, fr), "forced post-mutation")
                blocked = load(fr)
                if blocked["status"] != "RECOVERY_REQUIRED" or blocked["checkpoints"][0]["status"] != "RECOVERY_REQUIRED": raise AssertionError("Rollback failure did not set RECOVERY_REQUIRED")
                expect_error("RECOVERY_REQUIRED blocks progress", lambda: apply_next(fw, fr), "RECOVERY_REQUIRED")
            finally:
                transition.execute = original_transition_execute; bulk.rollback_last = original_rollback
            repaired = recover(fw, fr)
            if repaired["status"] != "ACTIVE" or repaired["checkpoints"][0]["status"] != "PENDING": raise AssertionError("Explicit recovery retry did not restore PENDING")
            if repaired["recoveries"][-1]["action"] != "RECOVERY_REQUIRED_TO_PENDING": raise AssertionError("RECOVERY_REQUIRED recovery was not journaled")
            print("ORCH-E2E RECOVERY_REQUIRED PASS: rollback failure blocks progress; explicit recover() retry restores PENDING after repair.")
    finally:
        ledger.legacy.canonicalize = original_legacy

    print("Oxford 5000 bulk orchestration end-to-end self-test passed: START, APPLY-NEXT, RECOVER, MARK-CI-GREEN and FINALIZE exercised with real bulk/provenance/transition modules.")


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