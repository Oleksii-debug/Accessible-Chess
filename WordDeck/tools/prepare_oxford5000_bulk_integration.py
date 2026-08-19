#!/usr/bin/env python3
"""Prepare/apply resumable Oxford 5000 QA-PASS integration checkpoints.

Development-time only. No harvesting or linguistic judgement is performed. PREPARE runs
the existing strict Data Factory -> Content QA provenance gate and writes deterministic
<=120-row verified slices outside the repo. APPLY-NEXT activates exactly one slice by
updating the current runtime count/call and csproj resource. A journal, exact backups,
SHA-256 drift checks, resume recovery, and ROLLBACK-LAST make interrupted high-load runs
recoverable without duplicate activation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import validate_oxford5000_automation_handoff as handoff
import validate_oxford5000_handoff_provenance as provenance
import validate_oxford5000_runtime_ledger as ledger

VERSION = 1
DEFAULT_CHUNK = 120
MAX_CHUNK = 120
FIELDS = [
    "entry_id", "source", "part_of_speech", "level", "status", "ukrainian",
    "official_source", "source_check", "data_factory_run_id", "content_qa_run_id", "qa_reason",
]
COUNT_RE = re.compile(r"(public\s+const\s+int\s+ExpectedCanonicalRows\s*=\s*)(\d+)(\s*;)")
CALL_RE = re.compile(
    r'(?P<i>\s*)AppendVerifiedSlice\s*\(\s*result\s*,\s*"(?P<n>[^"]+)"\s*,\s*(?P<c>[^,\)]+)\s*,\s*(?P<m>[^\)]+)\);'
)
RES_RE = re.compile(
    r'(?P<i>\s*)<EmbeddedResource\s+Include="QA\\(?P<n>oxford5000_source_after_[^"]+\.tsv)"\s*/>'
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def state(path: Path) -> dict[str, str]:
    b = path.read_bytes()
    return {"sha256": digest(b), "bytes": str(len(b))}


def atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
        raise


def write_json(path: Path, obj: dict[str, Any]) -> None:
    atomic(path, (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())


def tx_paths(tx: Path) -> dict[str, Path]:
    return {
        "journal": tx / "transaction.json", "ready": tx / "ready.tsv",
        "unresolved": tx / "unresolved.tsv", "provenance": tx / "provenance.tsv",
        "slices": tx / "prepared-slices", "backups": tx / "backups",
    }


def ensure_tx_outside_repo(worddeck: Path, tx: Path) -> None:
    repo = worddeck.resolve().parent
    try: tx.resolve().relative_to(repo)
    except ValueError: return
    raise ValueError("transaction-dir must be outside the repository root")


def expected_count(text: str) -> int:
    m = list(COUNT_RE.finditer(text))
    if len(m) != 1:
        raise ValueError("Expected exactly one public const int ExpectedCanonicalRows assignment")
    return int(m[0].group(2))


def set_expected_count(text: str, old: int, new: int) -> str:
    if expected_count(text) != old:
        raise ValueError(f"ExpectedCanonicalRows drifted; expected {old}")
    return COUNT_RE.sub(lambda m: f"{m.group(1)}{new}{m.group(3)}", text, count=1)


def next_major(text: str) -> int:
    constants = ledger.parse_int_constants(text)
    calls = ledger.parse_runtime_slices(text)
    if not calls: raise ValueError("No active AppendVerifiedSlice calls found")
    return max(ledger.resolve_int(m, constants) for _, _, m in calls) + 1


def add_call(text: str, name: str, rows: int, major: int) -> str:
    calls = list(CALL_RE.finditer(text))
    if not calls: raise ValueError("No AppendVerifiedSlice insertion anchor found")
    if any(m.group("n") == name for m in calls): raise ValueError(f"Runtime already contains {name}")
    last = calls[-1]
    line = f'{last.group("i")}AppendVerifiedSlice(result, "{name}", {rows}, {major});'
    return text[:last.end()] + "\n" + line + text[last.end():]


def add_resource(text: str, name: str) -> str:
    matches = list(RES_RE.finditer(text))
    if not matches: raise ValueError("No Oxford source-after EmbeddedResource anchor found")
    if any(m.group("n") == name for m in matches): raise ValueError(f"csproj already embeds {name}")
    last = matches[-1]
    line = f'{last.group("i")}<EmbeddedResource Include="QA\\{name}" />'
    return text[:last.end()] + "\n" + line + text[last.end():]


def render(rows: list[dict[str, str]]) -> bytes:
    out = ["\t".join(FIELDS)]
    for nr, row in enumerate(rows, 1):
        vals = []
        for field in FIELDS:
            value = (row.get(field) or "").strip()
            if any(c in value for c in "\t\r\n"):
                raise ValueError(f"QA-PASS row {nr} field {field!r} contains TAB/newline")
            vals.append(value)
        out.append("\t".join(vals))
    return ("\n".join(out) + "\n").encode("utf-8")


def safe_token(value: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return (token or "qa")[:40]


def prepare(
    worddeck: Path, unaccounted: Path, data_factory: Path, content_qa: Path,
    tx: Path, chunk_size: int,
) -> dict[str, Any]:
    worddeck, tx = worddeck.resolve(), tx.resolve()
    ensure_tx_outside_repo(worddeck, tx)
    if not 1 <= chunk_size <= MAX_CHUNK:
        raise ValueError(f"checkpoint-size must be 1..{MAX_CHUNK}")
    p = tx_paths(tx); p["slices"].mkdir(parents=True, exist_ok=True); p["backups"].mkdir(parents=True, exist_ok=True)
    ready, unresolved, evidence = provenance.execute_strict(
        unaccounted, data_factory, content_qa, p["ready"], p["unresolved"], p["provenance"]
    )
    if not ready: raise ValueError("Qualified handoff has zero QA-PASS rows")

    bootstrap, csproj, qa = worddeck / "ReviewedOxford5000Bootstrap.cs", worddeck / "WordDeck.csproj", worddeck / "QA"
    if not bootstrap.is_file() or not csproj.is_file() or not qa.is_dir():
        raise FileNotFoundError("WordDeck runtime/bootstrap/project/QA paths are incomplete")
    bt, cp = bootstrap.read_text(encoding="utf-8"), csproj.read_text(encoding="utf-8")
    start_count, major0 = expected_count(bt), next_major(bt)
    chunks = [ready[i:i+chunk_size] for i in range(0, len(ready), chunk_size)]
    run = safe_token(evidence["content_qa_run_id"])
    material = "\n".join([
        str(VERSION), evidence["unaccounted_sha256"], evidence["data_factory_sha256"],
        evidence["content_qa_sha256"], str(chunk_size), *(r["entry_id"] for r in ready)
    ])
    txid = "ox5000-tx-" + hashlib.sha256(material.encode()).hexdigest()[:20]
    checkpoints, done = [], 0
    for i, chunk in enumerate(chunks, 1):
        name = f"oxford5000_source_after_auto_{run}_cp{i:04d}_rows_{len(chunk):04d}.tsv"
        if name in bt or name in cp or (qa / name).exists(): raise ValueError(f"Prepared filename collision: {name}")
        payload = render(chunk); atomic(p["slices"] / name, payload); done += len(chunk)
        checkpoints.append({
            "index": i, "status": "PENDING", "file_name": name, "expected_rows": len(chunk),
            "major_order": major0 + i - 1, "count_before": start_count + done - len(chunk),
            "count_after": start_count + done, "slice_sha256": digest(payload), "slice_bytes": len(payload),
            "first_entry_id": chunk[0]["entry_id"], "last_entry_id": chunk[-1]["entry_id"],
        })
    plan: dict[str, Any] = {
        "version": VERSION, "transaction_id": txid, "worddeck_dir": str(worddeck),
        "checkpoint_size": chunk_size, "qualified_pass_rows": len(ready), "fail_closed_rows": len(unresolved),
        "checkpoint_count": len(checkpoints), "start_count": start_count, "projected_final_count": start_count + len(ready),
        "data_factory_run_id": evidence["data_factory_run_id"], "content_qa_run_id": evidence["content_qa_run_id"],
        "repo_current": {"bootstrap": state(bootstrap), "csproj": state(csproj)},
        "input_sha256": {k: evidence[k] for k in ("unaccounted_sha256", "data_factory_sha256", "content_qa_sha256")},
        "checkpoints": checkpoints,
    }
    if p["journal"].exists():
        old = json.loads(p["journal"].read_text(encoding="utf-8"))
        if old.get("transaction_id") != txid: raise ValueError("transaction-dir already belongs to another transaction")
        if any(c.get("status") != "PENDING" for c in old.get("checkpoints", [])): return old
        if old != plan: raise ValueError("Deterministic re-prepare disagrees with existing journal")
        return old
    write_json(p["journal"], plan); return plan


def verify_repo(worddeck: Path, plan: dict[str, Any]) -> None:
    actual = {"bootstrap": state(worddeck / "ReviewedOxford5000Bootstrap.cs"), "csproj": state(worddeck / "WordDeck.csproj")}
    if actual != plan["repo_current"]:
        raise ValueError("WordDeck integration files changed outside this transaction")


def verify_backup(item: dict[str, Any], bootstrap_backup: Path, csproj_backup: Path) -> None:
    before = item.get("before_repo")
    if not isinstance(before, dict) or "bootstrap" not in before or "csproj" not in before:
        raise ValueError("Checkpoint journal has no exact before_repo evidence")
    if not bootstrap_backup.is_file() or not csproj_backup.is_file():
        raise ValueError("Checkpoint exact backup is incomplete")
    actual = {"bootstrap": state(bootstrap_backup), "csproj": state(csproj_backup)}
    if actual != before:
        raise ValueError("Checkpoint backup bytes do not match journal before_repo evidence")


def recover_applying(worddeck: Path, tx: Path, plan: dict[str, Any]) -> dict[str, Any]:
    p = tx_paths(tx)
    applying = next((c for c in plan["checkpoints"] if c["status"] == "APPLYING"), None)
    if not applying: return plan
    bdir = p["backups"] / f'cp{int(applying["index"]):04d}'
    b1, b2 = bdir / "ReviewedOxford5000Bootstrap.cs", bdir / "WordDeck.csproj"
    verify_backup(applying, b1, b2)
    atomic(worddeck / "ReviewedOxford5000Bootstrap.cs", b1.read_bytes())
    atomic(worddeck / "WordDeck.csproj", b2.read_bytes())
    target = worddeck / "QA" / applying["file_name"]
    if target.exists(): target.unlink()
    applying["status"] = "PENDING"; applying.pop("before_repo", None); applying.pop("after_repo", None)
    plan["repo_current"] = {"bootstrap": state(worddeck / "ReviewedOxford5000Bootstrap.cs"), "csproj": state(worddeck / "WordDeck.csproj")}
    write_json(p["journal"], plan); return plan


def apply_next(worddeck: Path, tx: Path) -> dict[str, Any]:
    worddeck, tx = worddeck.resolve(), tx.resolve(); ensure_tx_outside_repo(worddeck, tx); p = tx_paths(tx)
    plan = json.loads(p["journal"].read_text(encoding="utf-8"))
    if Path(plan["worddeck_dir"]).resolve() != worddeck: raise ValueError("Transaction targets a different WordDeck directory")
    plan = recover_applying(worddeck, tx, plan)
    item = next((c for c in plan["checkpoints"] if c["status"] == "PENDING"), None)
    if not item: return plan
    verify_repo(worddeck, plan)
    prepared = p["slices"] / item["file_name"]
    if digest(prepared.read_bytes()) != item["slice_sha256"] or prepared.stat().st_size != item["slice_bytes"]:
        raise ValueError("Prepared slice bytes drifted")
    target = worddeck / "QA" / item["file_name"]
    if target.exists(): raise ValueError("Target QA slice already exists")
    bootstrap, csproj = worddeck / "ReviewedOxford5000Bootstrap.cs", worddeck / "WordDeck.csproj"
    bt, cp = bootstrap.read_text(encoding="utf-8"), csproj.read_text(encoding="utf-8")
    bt2 = add_call(set_expected_count(bt, int(item["count_before"]), int(item["count_after"])), item["file_name"], int(item["expected_rows"]), int(item["major_order"]))
    cp2 = add_resource(cp, item["file_name"])
    bdir = p["backups"] / f'cp{int(item["index"]):04d}'; bdir.mkdir(parents=True, exist_ok=True)
    atomic(bdir / "ReviewedOxford5000Bootstrap.cs", bt.encode()); atomic(bdir / "WordDeck.csproj", cp.encode())
    item["status"] = "APPLYING"; item["before_repo"] = plan["repo_current"]; write_json(p["journal"], plan)
    try:
        atomic(target, prepared.read_bytes()); atomic(bootstrap, bt2.encode()); atomic(csproj, cp2.encode())
    except Exception:
        recover_applying(worddeck, tx, plan); raise
    item["status"] = "APPLIED"; item["after_repo"] = {"bootstrap": state(bootstrap), "csproj": state(csproj), "slice": state(target)}
    plan["repo_current"] = {"bootstrap": state(bootstrap), "csproj": state(csproj)}; write_json(p["journal"], plan); return plan


def rollback_last(worddeck: Path, tx: Path) -> dict[str, Any]:
    worddeck, tx = worddeck.resolve(), tx.resolve(); ensure_tx_outside_repo(worddeck, tx); p = tx_paths(tx)
    plan = recover_applying(worddeck, tx, json.loads(p["journal"].read_text(encoding="utf-8")))
    applied = [c for c in plan["checkpoints"] if c["status"] == "APPLIED"]
    if not applied: return plan
    item = applied[-1]; verify_repo(worddeck, plan)
    bdir = p["backups"] / f'cp{int(item["index"]):04d}'
    b1, b2 = bdir / "ReviewedOxford5000Bootstrap.cs", bdir / "WordDeck.csproj"
    verify_backup(item, b1, b2)
    atomic(worddeck / "ReviewedOxford5000Bootstrap.cs", b1.read_bytes())
    atomic(worddeck / "WordDeck.csproj", b2.read_bytes())
    target = worddeck / "QA" / item["file_name"]
    if target.exists(): target.unlink()
    item["status"] = "PENDING"; item.pop("before_repo", None); item.pop("after_repo", None)
    plan["repo_current"] = {"bootstrap": state(worddeck / "ReviewedOxford5000Bootstrap.cs"), "csproj": state(worddeck / "WordDeck.csproj")}
    write_json(p["journal"], plan); return plan


def summary(plan: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for c in plan["checkpoints"]: counts[c["status"]] = counts.get(c["status"], 0) + 1
    return f"transaction={plan['transaction_id']}, ready={plan['qualified_pass_rows']}, checkpoints={plan['checkpoint_count']}, statuses={counts}, projected_final={plan['projected_final_count']}"


def fixture(root: Path, n: int) -> tuple[Path, Path, Path]:
    u, d, q = root / "u.tsv", root / "d.tsv", root / "q.tsv"
    ur, dr, qr = [], [], []
    for i in range(1, n + 1):
        source, pos, level = f"word-{i:04d}", ("noun" if i % 2 else "verb"), ("C1" if i % 3 == 0 else "B2")
        eid = handoff.lexical_entry_id(source, pos, level)
        ur.append({"entry_id": eid, "source_index": str(i), "source": source, "part_of_speech": pos, "level": level})
        dr.append({"data_factory_run_id": "df-selftest", "entry_id": eid, "source": source, "part_of_speech": pos, "level": level, "official_source": "official", "source_check": f"checked-{i}", "ukrainian_candidate": f"кандидат-{i}"})
        qr.append({"content_qa_run_id": "qa-selftest", "data_factory_run_id": "df-selftest", "entry_id": eid, "source": source, "part_of_speech": pos, "level": level, "decision": "PASS", "ukrainian": f"переклад-{i}", "qa_reason": "passed"})
    handoff.write_tsv(ur, u, ["entry_id", "source_index", "source", "part_of_speech", "level"])
    handoff.write_tsv(dr, d, sorted(handoff.DATA_FACTORY_REQUIRED)); handoff.write_tsv(qr, q, sorted(handoff.CONTENT_QA_REQUIRED)); return u, d, q


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp); repo = root / "repo"; worddeck = repo / "WordDeck"; (worddeck / "QA").mkdir(parents=True)
        (worddeck / "ReviewedOxford5000Bootstrap.cs").write_text('''internal static class X {\n private const int StandardSliceRows = 29;\n public const int ExpectedCanonicalRows = 982;\n void B(){\n  AppendVerifiedSlice(result, "old-a.tsv", StandardSliceRows, 2021);\n  AppendVerifiedSlice(result, "old-b.tsv", StandardSliceRows, 9999);\n }\n}\n''', encoding="utf-8")
        (worddeck / "WordDeck.csproj").write_text('''<Project><ItemGroup>\n <EmbeddedResource Include="QA\\oxford5000_source_after_old-a.tsv" />\n <EmbeddedResource Include="QA\\oxford5000_source_after_old-b.tsv" />\n</ItemGroup></Project>\n''', encoding="utf-8")
        u, d, q = fixture(root, 245); tx = root / "tx"
        plan = prepare(worddeck, u, d, q, tx, 120)
        assert [c["expected_rows"] for c in plan["checkpoints"]] == [120, 120, 5]
        assert [c["major_order"] for c in plan["checkpoints"]] == [10000, 10001, 10002]
        assert plan["projected_final_count"] == 1227
        assert prepare(worddeck, u, d, q, tx, 120)["transaction_id"] == plan["transaction_id"]

        # Simulate a crash after the journal enters APPLYING and after a partial target write.
        first = plan["checkpoints"][0]
        bdir = tx_paths(tx)["backups"] / "cp0001"; bdir.mkdir(parents=True, exist_ok=True)
        b1, b2 = bdir / "ReviewedOxford5000Bootstrap.cs", bdir / "WordDeck.csproj"
        b1.write_bytes((worddeck / "ReviewedOxford5000Bootstrap.cs").read_bytes())
        b2.write_bytes((worddeck / "WordDeck.csproj").read_bytes())
        first["status"] = "APPLYING"; first["before_repo"] = plan["repo_current"]
        (worddeck / "QA" / first["file_name"]).write_text("partial-crash-output", encoding="utf-8")
        write_json(tx_paths(tx)["journal"], plan)

        # Corrupt backup bytes: recovery must fail closed before restoring anything.
        original_backup = b1.read_bytes(); b1.write_bytes(original_backup + b"corrupt")
        try: apply_next(worddeck, tx)
        except ValueError as e: assert "backup bytes" in str(e)
        else: raise AssertionError("Corrupted recovery backup was accepted")
        b1.write_bytes(original_backup)

        # A clean retry must roll back the interrupted state and apply checkpoint 1 once.
        plan = apply_next(worddeck, tx)
        assert first["file_name"] == plan["checkpoints"][0]["file_name"] and plan["checkpoints"][0]["status"] == "APPLIED"
        assert expected_count((worddeck / "ReviewedOxford5000Bootstrap.cs").read_text()) == 1102
        plan = apply_next(worddeck, tx); second = plan["checkpoints"][1]["file_name"]; assert expected_count((worddeck / "ReviewedOxford5000Bootstrap.cs").read_text()) == 1222
        plan = rollback_last(worddeck, tx); assert plan["checkpoints"][1]["status"] == "PENDING" and not (worddeck / "QA" / second).exists()
        plan = apply_next(worddeck, tx); plan = apply_next(worddeck, tx); assert [c["status"] for c in plan["checkpoints"]] == ["APPLIED"] * 3
        assert expected_count((worddeck / "ReviewedOxford5000Bootstrap.cs").read_text()) == 1227
        rollback_last(worddeck, tx); b = worddeck / "ReviewedOxford5000Bootstrap.cs"; b.write_text(b.read_text() + "// drift\n")
        try: apply_next(worddeck, tx)
        except ValueError as e: assert "changed outside" in str(e)
        else: raise AssertionError("Unjournaled drift was accepted")
    print("Oxford 5000 bulk integration transaction self-test passed: provenance, deterministic chunking, apply-next, resume, rollback and drift detection are fail-closed.")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("--self-test", action="store_true"); s = p.add_subparsers(dest="command")
    x = s.add_parser("prepare"); x.add_argument("--worddeck-dir", type=Path, required=True); x.add_argument("--unaccounted", type=Path, required=True); x.add_argument("--data-factory", type=Path, required=True); x.add_argument("--content-qa", type=Path, required=True); x.add_argument("--transaction-dir", type=Path, required=True); x.add_argument("--checkpoint-size", type=int, default=DEFAULT_CHUNK)
    for name in ("apply-next", "rollback-last", "status"):
        x = s.add_parser(name); x.add_argument("--worddeck-dir", type=Path, required=True); x.add_argument("--transaction-dir", type=Path, required=True)
    return p


def main() -> int:
    args = parser().parse_args()
    if args.self_test: self_test(); return 0
    if args.command == "prepare": plan = prepare(args.worddeck_dir, args.unaccounted, args.data_factory, args.content_qa, args.transaction_dir, args.checkpoint_size)
    elif args.command == "apply-next": plan = apply_next(args.worddeck_dir, args.transaction_dir)
    elif args.command == "rollback-last": plan = rollback_last(args.worddeck_dir, args.transaction_dir)
    elif args.command == "status": plan = json.loads(tx_paths(args.transaction_dir.resolve())["journal"].read_text(encoding="utf-8"))
    else: raise SystemExit("choose a command or use --self-test")
    print("Oxford 5000 bulk integration: " + summary(plan)); return 0


if __name__ == "__main__": raise SystemExit(main())
