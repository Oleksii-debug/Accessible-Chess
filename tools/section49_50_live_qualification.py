"""Section 49/50 evidence runner: authenticated live calls only when explicitly enabled.

Never treats mocks, offline video, or a YouTube URL as a live model or as
verified chess analysis. Keys stay in environment, not in repo/logs/reports.
No signup, paid-tier selection, or account management is performed.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from acs.agent_cloud_provider import CloudChatProvider, provider_availability
from acs.agent_model_contracts import (
    ModelGatewayError, ModelMessage, ModelRequest, PrivacyClass,
    ProviderKind,
)
from acs.agent_model_gateway import ModelGateway

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
DEMO_PGN = '[Event "Section 49/50 lawfully authored fixture"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 *'
SCHEMA_VERSION = "section49-50-evidence-v1"


def _sha() -> str | None:
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "--verify", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode("ascii").strip()
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    return value if len(value) == 40 and all(x in "0123456789abcdef" for x in value) else None


def _sha256_file(path: Path, *, max_bytes: int = 1024**3) -> tuple[str, int]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("video is missing or is a symbolic link")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while chunk := f.read(1024**2):
            size += len(chunk)
            if size > max_bytes:
                raise ValueError("video exceeds test evidence size limit")
            digest.update(chunk)
    return digest.hexdigest(), size


def classify_evidence(item: object) -> str:
    """Do not promote transport-level replies to semantic/video qualification."""
    if type(item) is not dict or item.get("schema") != SCHEMA_VERSION:
        return "INVALID"
    if item.get("evidence_class") == "LIVE_MODEL":
        if item.get("status") == "LIVE_RESPONSE_RECEIVED" and item.get("source_sha"):
            return "MODEL_TRANSPORT_ONLY"
        return "BLOCKED_OR_FAILED"
    if item.get("evidence_class") == "OFFLINE_VIDEO":
        return "SOURCE_BYTES_ONLY" if item.get("sha256") and item.get("bytes", 0) > 0 else "BLOCKED_OR_FAILED"
    if item.get("evidence_class") == "YOUTUBE_EMBED":
        return "NOT_QUALIFIED"
    return "NOT_QUALIFIED"


async def _probe(name: str, model: str, source_sha: str | None) -> dict:
    item = {
        "schema": SCHEMA_VERSION, "evidence_class": "LIVE_MODEL",
        "provider": name, "model": model, "source_sha": source_sha,
        "status": "BLOCKED", "model_catalog_authenticated": False,
        "latency_ms": None, "tokens": None,
        "fen_fixture": START_FEN, "pgn_fixture": "local authored fixture",
        "chess_semantics": "NOT_INDEPENDENTLY_VERIFIED",
        "media_chain": "NOT_TESTED",
    }
    try:
        provider = CloudChatProvider(provider_id=name, default_model=model, allow_live_requests=True)
    except (TypeError, ValueError):
        item["reason"] = "INVALID_ROUTE_CONFIGURATION"
        return item
    if not provider.configured():
        item["reason"] = "NOT_CONFIGURED"
        return item
    try:
        catalog = await provider.list_models()
        item["model_catalog_authenticated"] = True
        if model not in catalog:
            item["reason"] = "MODEL_NOT_LISTED"
            return item
        gateway = ModelGateway()
        gateway.register(provider, default=True)
        req = ModelRequest(
            request_id="s49-" + name, provider_id=name,
            provider_kind=ProviderKind.CLOUD, privacy=PrivacyClass.PUBLIC,
            model=model, timeout_seconds=30,
            messages=(
                ModelMessage("system", "You are a chess explainer. Do not invent positions. Reply only with text."),
                ModelMessage("user", "Explain this FEN in 1-2 short sentences: " + START_FEN),
                ModelMessage("user", "Summarize the following PGN opening without guessing future moves: " + DEMO_PGN),
            ),
        )
        result = await gateway.complete(req)
        if not result.text.strip():
            item["reason"] = "EMPTY_RESPONSE"
            item["status"] = "FAIL"
        else:
            item["status"] = "LIVE_RESPONSE_RECEIVED"
            item["latency_ms"] = round(result.latency_ms or 0, 1)
            item["tokens"] = {
                "in": result.usage.input_tokens,
                "out": result.usage.output_tokens,
                "total": result.usage.total_tokens,
            }
            item["response_chars"] = len(result.text)
            item["reason"] = "LIVE_TRANSPORT_ONLY_NOT_CHESS_PASS"
    except ModelGatewayError as exc:
        item["status"] = "FAIL"
        item["reason"] = exc.code.value
    except Exception:
        # Never persist exception bodies: HTTP and provider exceptions can
        # include response headers or secret-bearing URLs.
        item["status"] = "FAIL"
        item["reason"] = "SAFE_UNCLASSIFIED_EXCEPTION"
    return item


async def _main(args) -> dict:
    source_sha = _sha()
    report = {
        "schema": SCHEMA_VERSION,
        "source_sha": source_sha,
        "run_mode": "LIVE_OPT_IN" if args.execute_live else "OFFLINE_ONLY",
        "routes": [],
        "providers": [{"name": p.provider_id, "state": p.mode}
                      for p in provider_availability()],
        "video": None,
        "youtube": {"schema": SCHEMA_VERSION, "evidence_class": "YOUTUBE_EMBED",
                    "status": "NOT_TESTED", "reason": "BROWSER_EMBED_NOT_RUN"},
        "section49_done": False, "section50_done": False,
    }
    if args.video:
        p = Path(args.video)
        try:
            digest, size = _sha256_file(p)
            report["video"] = {
                "schema": SCHEMA_VERSION, "evidence_class": "OFFLINE_VIDEO",
                "sha256": digest, "bytes": size,
                "status": "SOURCE_BYTES_ONLY",
                "board_fen_extraction": "NOT_TESTED",
                "stockfish": "NOT_TESTED",
                "book_library": "NOT_TESTED",
                "agent_restart_recovery": "NOT_TESTED",
                "reason": "FILE_INTEGRITY_IS_NOT_END_TO_END_VIDEO_QUALIFICATION",
            }
        except (OSError, ValueError):
            report["video"] = {
                "schema": SCHEMA_VERSION, "evidence_class": "OFFLINE_VIDEO",
                "status": "BLOCKED", "reason": "SOURCE_VIDEO_UNAVAILABLE_OR_INVALID",
            }
    if args.execute_live and args.free_tier_confirmed:
        for route in args.route:
            if ":" not in route:
                report["routes"].append({"status": "BLOCKED",
                                         "reason": "INVALID_ROUTE_FORMAT"})
                continue
            name, model = route.split(":", 1)
            report["routes"].append(await _probe(name, model, source_sha))
    else:
        for route in args.route:
            report["routes"].append({
                "schema": SCHEMA_VERSION, "evidence_class": "LIVE_MODEL",
                "route": route, "source_sha": source_sha, "status": "BLOCKED",
                "reason": "LIVE_NOT_AUTHORIZED_OR_FREE_TIER_NOT_CONFIRMED",
            })
    report["independent_live_routes"] = len({
        item.get("provider") for item in report["routes"]
        if classify_evidence(item) == "MODEL_TRANSPORT_ONLY"
    })
    report["integrated_semantic_qualification"] = "NOT_TESTED"
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", action="append", default=[],
                        help="provider:model; may be passed multiple times, Mistral first")
    parser.add_argument("--video", help="approved local MP4/WebM file (hash only)")
    parser.add_argument("--execute-live", action="store_true",
                        help="explicit opt-in to authenticated cloud inference")
    parser.add_argument("--free-tier-confirmed", action="store_true",
                        help="operator has confirmed remaining no-cost allowance")
    parser.add_argument("--output", default="section49-50-evidence.json")
    args = parser.parse_args(argv)
    if args.execute_live and not args.free_tier_confirmed:
        parser.error("live calls require --free-tier-confirmed")
    report = asyncio.run(_main(args))
    dest = Path(args.output)
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    print("EVIDENCE_WRITTEN=" + str(dest))
    print("LIVE_ROUTES=" + str(report["independent_live_routes"]))
    print("SECTION_49_DONE=NO; SECTION_50_DONE=NO; SEMANTIC_PASS_NOT_SELF_ISSUED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
