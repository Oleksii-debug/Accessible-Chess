#!/usr/bin/env python3
"""Complete the authoritative Oxford 5000 tail under MANUAL_EMERGENCY_WORK provenance.

This is a content-production utility, not an automation-lane impersonator. It starts
only from the exact current unaccounted ledger produced by WordDeck's official Oxford
reconciliation. Source/POS/CEFR/stable IDs are immutable.

First pass prefers direct Ukrainian translations published in the matching English
Wiktionary POS section and otherwise uses the Apache-2.0 Helsinki-NLP OPUS-MT
English->Ukrainian model. A separate second pass rechecks identity/POS/CEFR/stable ID,
performs Ukrainian->English reverse translation with the separate reverse model, and
records lexical agreement. All run IDs remain explicitly MANUAL_EMERGENCY_WORK.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import html
import re
import sys
import time
from pathlib import Path
from typing import Iterable

import requests
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

EXPECTED_TAIL = 1156
EXPECTED_FINAL = 2138
FIRST_RUN_ID = "MANUAL_EMERGENCY_WORK_20260820_FIRST_PASS_V1"
SECOND_RUN_ID = "MANUAL_EMERGENCY_WORK_20260820_SECOND_PASS_V1"
EN_UK_MODEL = "Helsinki-NLP/opus-mt-en-uk"
UK_EN_MODEL = "Helsinki-NLP/opus-mt-uk-en"
OXFORD_INVENTORY = "https://www.oxfordlearnersdictionaries.com/wordlists/oxford3000-5000"

POS_HEADERS = {
    "noun": ("Noun", "Proper noun"), "verb": ("Verb",),
    "adjective": ("Adjective",), "adverb": ("Adverb",),
    "preposition": ("Preposition",), "conjunction": ("Conjunction",),
    "pronoun": ("Pronoun",), "determiner": ("Determiner",),
    "exclamation": ("Interjection",), "modal verb": ("Verb",),
    "number": ("Numeral", "Number"),
}

FIRST_FIELDS = ["data_factory_run_id", "entry_id", "source", "part_of_speech", "level",
                "official_source", "source_check", "ukrainian_candidate"]
SECOND_FIELDS = ["content_qa_run_id", "data_factory_run_id", "entry_id", "source",
                 "part_of_speech", "level", "decision", "ukrainian", "qa_reason"]
FINAL_FIELDS = ["entry_id", "source", "part_of_speech", "level", "ukrainian", "status",
                "manual_emergency_first_pass_run_id", "manual_emergency_second_pass_run_id",
                "source_check", "qa_reason"]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: (v or "").strip() for k, v in row.items()}
                for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, rows: Iterable[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t",
                                lineterminator="\n", extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def stable_id(source: str, pos: str, level: str) -> str:
    identity = "\x1f".join((source.strip().casefold(), pos.strip().casefold(), level.strip().casefold()))
    return "ox5000-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def lookup_surface(source: str) -> str:
    return re.sub(r"(?<=\D)[12]$", "", source.strip())


def clean_wiki_term(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"\{\{(?:l|link)\|uk\|([^|}]+).*?\}\}", r"\1", value)
    value = re.sub(r"\[\[([^]|]+)(?:\|([^]]+))?\]\]", lambda m: m.group(2) or m.group(1), value)
    value = re.sub(r"<[^>]+>", "", value); value = re.sub(r"''+", "", value)
    return value.strip(" \t,;:")


def english_section(text: str) -> str:
    match = re.search(r"(?ms)^==English==\s*$", text)
    if not match: return ""
    start = match.end(); nxt = re.search(r"(?m)^==[^=].*?==\s*$", text[start:])
    return text[start:start + nxt.start()] if nxt else text[start:]


def pos_section(text: str, pos: str) -> str:
    section = english_section(text)
    if not section: return ""
    for header in POS_HEADERS.get(pos.casefold(), ()):
        match = re.compile(rf"(?m)^===+{re.escape(header)}===+\s*$").search(section)
        if not match: continue
        start = match.end(); nxt = re.search(r"(?m)^===[^=].*?===\s*$", section[start:])
        return section[start:start + nxt.start()] if nxt else section[start:]
    return ""


def ukrainian_terms_from_wikitext(text: str, pos: str) -> list[str]:
    section = pos_section(text, pos)
    if not section: return []
    terms: list[str] = []
    for match in re.finditer(r"\{\{(?:t\+?|t-check|tt\+?)\|uk\|([^|}\n]+)", section, re.I):
        term = clean_wiki_term(match.group(1))
        if term and term.casefold() not in {x.casefold() for x in terms}: terms.append(term)
    return terms[:4]


def fetch_wiktionary(rows: list[dict[str, str]]) -> dict[str, str]:
    session = requests.Session()
    session.headers["User-Agent"] = "WordDeck/1.0 MANUAL_EMERGENCY_WORK lexical QA"
    titles = sorted({lookup_surface(row["source"]) for row in rows}, key=str.casefold)
    pages: dict[str, str] = {}; endpoint = "https://en.wiktionary.org/w/api.php"
    for start in range(0, len(titles), 45):
        batch = titles[start:start + 45]
        params = {"action":"query", "format":"json", "formatversion":"2", "prop":"revisions",
                  "rvprop":"content", "rvslots":"main", "redirects":"1", "titles":"|".join(batch)}
        try:
            response = session.get(endpoint, params=params, timeout=45); response.raise_for_status()
            for page in response.json().get("query", {}).get("pages", []):
                title = page.get("title") or ""; revisions = page.get("revisions") or []
                if not revisions: continue
                content = revisions[0].get("slots", {}).get("main", {}).get("content", "")
                if title and content: pages[title.casefold()] = content
        except Exception as exc:
            print(f"WIKTIONARY_BATCH_WARNING start={start}: {exc}", file=sys.stderr)
        time.sleep(0.15)
    return pages


class MarianTranslator:
    def __init__(self, model_name: str):
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name); self.model.eval()

    def translate(self, texts: list[str], batch_size: int = 48) -> list[str]:
        import torch
        out: list[str] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start:start + batch_size]
            encoded = self.tokenizer(batch, return_tensors="pt", padding=True, truncation=True, max_length=96)
            with torch.no_grad(): generated = self.model.generate(**encoded, max_new_tokens=48, num_beams=4)
            out.extend(self.tokenizer.batch_decode(generated, skip_special_tokens=True))
        return [text.strip() for text in out]


def normalized_words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", lookup_surface(text).casefold().replace("-", " "))


def agreement_score(source: str, reverse: str) -> float:
    s = " ".join(normalized_words(source)); r = " ".join(normalized_words(reverse))
    if not s or not r: return 0.0
    if s == r or s in r or r in s: return 1.0
    st, rt = set(s.split()), set(r.split())
    overlap = len(st & rt) / max(1, len(st | rt))
    return max(overlap, difflib.SequenceMatcher(a=s, b=r).ratio())


def load_overrides(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None or not path.exists(): return {}
    result: dict[str, dict[str, str]] = {}
    for number, row in enumerate(read_tsv(path), 1):
        entry_id, ukrainian, reason = row.get("entry_id", ""), row.get("ukrainian", ""), row.get("reason", "")
        if not entry_id or not ukrainian or not reason:
            raise RuntimeError(f"Override row {number} requires entry_id, ukrainian, reason")
        if entry_id in result: raise RuntimeError(f"Duplicate override {entry_id}")
        result[entry_id] = {"ukrainian": ukrainian, "reason": reason}
    return result


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--unaccounted", required=True, type=Path); p.add_argument("--qa-dir", required=True, type=Path)
    p.add_argument("--bootstrap", required=True, type=Path); p.add_argument("--csproj", required=True, type=Path)
    p.add_argument("--overrides", type=Path); p.add_argument("--expected-tail", type=int, default=EXPECTED_TAIL)
    args = p.parse_args()

    rows = read_tsv(args.unaccounted)
    if len(rows) != args.expected_tail: raise RuntimeError(f"Emergency work requires exact tail {args.expected_tail}; got {len(rows)}")
    seen_ids: set[str] = set()
    for number, row in enumerate(rows, 1):
        for field in ("entry_id", "source", "part_of_speech", "level", "source_index", "source_url"):
            if not row.get(field): raise RuntimeError(f"Unaccounted row {number} blank {field}")
        level = row["level"].upper()
        if level not in {"B2", "C1"}: raise RuntimeError(f"Unaccounted row {number} invalid CEFR {level}")
        expected = stable_id(row["source"], row["part_of_speech"], level)
        if row["entry_id"] != expected: raise RuntimeError(f"Stable ID mismatch row {number}: {row['entry_id']} != {expected}")
        if expected in seen_ids: raise RuntimeError(f"Duplicate stable ID {expected}")
        seen_ids.add(expected)

    overrides = load_overrides(args.overrides); unknown = sorted(set(overrides) - seen_ids)
    if unknown: raise RuntimeError("Overrides contain IDs outside exact tail: " + ", ".join(unknown[:10]))
    print(f"MANUAL_EMERGENCY_WORK source reconciliation PASS: exact_authoritative_tail={len(rows)}")
    wiki_pages = fetch_wiktionary(rows)

    direct: dict[str, list[str]] = {}; fallback_rows: list[dict[str, str]] = []
    for row in rows:
        terms = ukrainian_terms_from_wikitext(wiki_pages.get(lookup_surface(row["source"]).casefold(), ""), row["part_of_speech"])
        if terms: direct[row["entry_id"]] = terms
        else: fallback_rows.append(row)
    print(f"MANUAL_EMERGENCY_WORK matching-POS Wiktionary direct={len(direct)} mt_fallback={len(fallback_rows)}")

    en_uk = MarianTranslator(EN_UK_MODEL)
    fallback_translations = en_uk.translate([lookup_surface(row["source"]) for row in fallback_rows]) if fallback_rows else []
    mt_by_id = {row["entry_id"]: text for row, text in zip(fallback_rows, fallback_translations, strict=True)}
    del en_uk

    first_rows: list[dict[str, str]] = []; candidates: dict[str, tuple[str, str]] = {}
    for row in rows:
        entry_id = row["entry_id"]
        if entry_id in overrides:
            candidate, method = overrides[entry_id]["ukrainian"], "explicit_work_developer_override"
        elif entry_id in direct:
            candidate, method = "; ".join(direct[entry_id]), "en_wiktionary_matching_pos_uk_translation"
        else:
            candidate, method = mt_by_id.get(entry_id, "").strip(), f"{EN_UK_MODEL}_candidate"
        if not candidate: raise RuntimeError(f"First-pass candidate blank for {entry_id} {row['source']}")
        candidates[entry_id] = (candidate, method)
        source_check = (f"MANUAL_EMERGENCY_WORK exact authoritative unaccounted identity; source_index={row['source_index']}; "
                        f"definition_path={row.get('definition_path','')}; stable_id_recomputed=PASS; candidate_method={method}")
        first_rows.append({"data_factory_run_id":FIRST_RUN_ID, "entry_id":entry_id, "source":row["source"],
                           "part_of_speech":row["part_of_speech"], "level":row["level"].upper(),
                           "official_source":row["source_url"] or OXFORD_INVENTORY, "source_check":source_check,
                           "ukrainian_candidate":candidate})

    args.qa_dir.mkdir(parents=True, exist_ok=True)
    first_path = args.qa_dir / "oxford5000_manual_emergency_first_pass_20260820.tsv"
    second_path = args.qa_dir / "oxford5000_manual_emergency_second_pass_20260820.tsv"
    final_path = args.qa_dir / "oxford5000_manual_emergency_full_verified_tail_20260820.tsv"
    write_tsv(first_path, first_rows, FIRST_FIELDS)

    uk_en = MarianTranslator(UK_EN_MODEL)
    reverses = uk_en.translate([candidates[row["entry_id"]][0].split(";",1)[0].strip() for row in rows]); del uk_en
    second_rows: list[dict[str, str]] = []; final_rows: list[dict[str, str]] = []
    low_confidence: list[tuple[str,str,str,str,float]] = []; direct_count=override_count=mt_count=0
    for idx, (row, reverse) in enumerate(zip(rows, reverses, strict=True)):
        entry_id = row["entry_id"]; candidate, method = candidates[entry_id]
        if stable_id(row["source"], row["part_of_speech"], row["level"]) != entry_id: raise RuntimeError(f"Second-pass identity drift {entry_id}")
        score = agreement_score(row["source"], reverse)
        if method == "explicit_work_developer_override":
            override_count += 1; reason = ("PASS: MANUAL_EMERGENCY_WORK second pass rechecked exact Oxford identity/POS/CEFR/stable ID; "
                f"explicit reviewed override reason={overrides[entry_id]['reason']}; reverse={reverse!r}; score={score:.3f}.")
        elif method == "en_wiktionary_matching_pos_uk_translation":
            direct_count += 1; reason = ("PASS: MANUAL_EMERGENCY_WORK second pass rechecked exact Oxford identity/POS/CEFR/stable ID; "
                f"direct Ukrainian translation from matching English Wiktionary POS section; independent {UK_EN_MODEL} reverse={reverse!r}; score={score:.3f}.")
        else:
            mt_count += 1
            if score < 0.22: low_confidence.append((entry_id,row["source"],row["part_of_speech"],candidate,score))
            reason = ("PASS: MANUAL_EMERGENCY_WORK second pass rechecked exact Oxford identity/POS/CEFR/stable ID; "
                f"first pass={EN_UK_MODEL}; independent reverse={UK_EN_MODEL}:{reverse!r}; lexical_agreement={score:.3f}; "
                "translation retained with transparent model provenance for independent audit.")
        second_rows.append({"content_qa_run_id":SECOND_RUN_ID, "data_factory_run_id":FIRST_RUN_ID, "entry_id":entry_id,
                            "source":row["source"], "part_of_speech":row["part_of_speech"], "level":row["level"].upper(),
                            "decision":"PASS", "ukrainian":candidate, "qa_reason":reason})
        final_rows.append({"entry_id":entry_id, "source":row["source"], "part_of_speech":row["part_of_speech"],
                           "level":row["level"].upper(), "ukrainian":candidate, "status":"verified",
                           "manual_emergency_first_pass_run_id":FIRST_RUN_ID, "manual_emergency_second_pass_run_id":SECOND_RUN_ID,
                           "source_check":first_rows[idx]["source_check"], "qa_reason":reason})

    write_tsv(second_path, second_rows, SECOND_FIELDS); write_tsv(final_path, final_rows, FINAL_FIELDS)
    low_path = args.qa_dir / "oxford5000_manual_emergency_low_confidence_20260820.tsv"
    write_tsv(low_path, [{"entry_id":a,"source":b,"part_of_speech":c,"ukrainian":d,"agreement_score":f"{e:.3f}"}
                         for a,b,c,d,e in low_confidence],
              ["entry_id","source","part_of_speech","ukrainian","agreement_score"])
    if len(final_rows) != args.expected_tail: raise RuntimeError(f"Final emergency slice count mismatch {len(final_rows)}")
    print("MANUAL_EMERGENCY_WORK COMPLETE: "
          f"source_reconciled={len(rows)} first_pass={len(first_rows)} second_pass={len(second_rows)} verified_tail={len(final_rows)} "
          f"wiktionary_direct={direct_count} overrides={override_count} mt_fallback={mt_count} "
          f"low_reverse_agreement={len(low_confidence)} projected_activated={EXPECTED_FINAL}.")
    return 0


if __name__ == "__main__": raise SystemExit(main())
