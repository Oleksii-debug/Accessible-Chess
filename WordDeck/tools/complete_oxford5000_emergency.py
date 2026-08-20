#!/usr/bin/env python3
"""Fail-closed MANUAL_EMERGENCY_WORK completion for the Oxford 5000 tail.

Oxford stable ID/source/POS/CEFR/definition path are immutable source truth.
Wiktionary and MT are candidate sources only. PASS is emitted only when
Ukrainian language/POS checks plus source-grounded semantic evidence succeed.
Uncertain rows are BLOCKED and are never activated.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import html
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

import requests

EXPECTED_TAIL = 1156
EN_UK_MODEL = "Helsinki-NLP/opus-mt-en-uk"
UK_EN_MODEL = "Helsinki-NLP/opus-mt-uk-en"
SEM_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

FIRST_FIELDS = ["data_factory_run_id", "entry_id", "source", "part_of_speech", "level", "official_source", "source_check", "ukrainian_candidate"]
SECOND_FIELDS = ["content_qa_run_id", "data_factory_run_id", "entry_id", "source", "part_of_speech", "level", "decision", "ukrainian", "qa_reason"]
FINAL_FIELDS = ["entry_id", "source", "part_of_speech", "level", "ukrainian", "status", "manual_emergency_first_pass_run_id", "manual_emergency_second_pass_run_id", "source_check", "qa_reason"]
HOLD_FIELDS = ["entry_id", "source", "part_of_speech", "level", "official_source", "definition_path", "exact_definition", "selected_candidate", "selected_candidate_method", "candidate_history", "reason"]
POS_HEADERS = {"noun": ("Noun", "Proper noun"), "verb": ("Verb",), "adjective": ("Adjective",), "adverb": ("Adverb",), "preposition": ("Preposition",), "conjunction": ("Conjunction",), "pronoun": ("Pronoun",), "determiner": ("Determiner",), "exclamation": ("Interjection",), "modal verb": ("Verb",), "number": ("Numeral", "Number")}


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle, delimiter="\t")]


def write_tsv(path: Path, rows: Iterable[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def stable_id(source: str, pos: str, level: str) -> str:
    identity = "\x1f".join((source.strip().casefold(), pos.strip().casefold(), level.strip().casefold()))
    return "ox5000-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]


def surface(value: str) -> str:
    return re.sub(r"(?<=\D)[12]$", "", value.strip())


def clean(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"\{\{(?:l|link)\|uk\|([^|}]+).*?\}\}", r"\1", value)
    value = re.sub(r"\[\[([^]|]+)(?:\|([^]]+))?\]\]", lambda match: match.group(2) or match.group(1), value)
    value = re.sub(r"<[^>]+>", "", value); value = re.sub(r"''+", "", value)
    return value.strip(" \t,;:")


def english_section(text: str) -> str:
    match = re.search(r"(?ms)^==English==\s*$", text)
    if not match: return ""
    rest = text[match.end():]; nxt = re.search(r"(?m)^==[^=].*?==\s*$", rest)
    return rest[:nxt.start()] if nxt else rest


def pos_section(text: str, pos: str) -> str:
    section = english_section(text)
    for header in POS_HEADERS.get(pos.casefold(), ()):
        match = re.compile(rf"(?m)^===+{re.escape(header)}===+\s*$").search(section)
        if not match: continue
        rest = section[match.end():]; nxt = re.search(r"(?m)^===[^=].*?===\s*$", rest)
        return rest[:nxt.start()] if nxt else rest
    return ""


def wiki_terms(text: str, pos: str) -> list[str]:
    section = pos_section(text, pos); out: list[str] = []
    for match in re.finditer(r"\{\{(?:t\+?|t-check|tt\+?)\|uk\|([^|}\n]+)", section, re.I):
        term = clean(match.group(1))
        if term and term.casefold() not in {item.casefold() for item in out}: out.append(term)
    return out[:4]


def _bounded_get(session: requests.Session, url: str, *, params: dict[str, str] | None = None, timeout: int = 40, attempts: int = 4) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(url, params=params, timeout=timeout)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "")
                try: delay = min(12.0, max(1.0, float(retry_after)))
                except ValueError: delay = min(12.0, 1.5 * (2 ** attempt))
                if attempt + 1 < attempts:
                    time.sleep(delay); continue
            response.raise_for_status(); return response
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts: time.sleep(min(10.0, 1.25 * (2 ** attempt)))
    assert last_error is not None
    raise last_error


def fetch_wiki(rows: list[dict[str, str]]) -> dict[str, str]:
    session = requests.Session(); session.headers["User-Agent"] = "WordDeck/1.0 (MANUAL_EMERGENCY_WORK; lexical QA; Oleksii-debug/Accessible-Chess)"
    titles = sorted({surface(row["source"]) for row in rows}, key=str.casefold); pages: dict[str, str] = {}; endpoint = "https://en.wiktionary.org/w/api.php"
    for start in range(0, len(titles), 25):
        batch = titles[start:start + 25]
        params = {"action": "query", "format": "json", "formatversion": "2", "prop": "revisions", "rvprop": "content", "rvslots": "main", "redirects": "1", "titles": "|".join(batch)}
        try:
            response = _bounded_get(session, endpoint, params=params, timeout=45)
            for page in response.json().get("query", {}).get("pages", []):
                revisions = page.get("revisions") or []; content = revisions[0].get("slots", {}).get("main", {}).get("content", "") if revisions else ""; title = page.get("title") or ""
                if title and content: pages[title.casefold()] = content
        except Exception as exc:
            print(f"WIKTIONARY_BATCH_WARNING start={start}: {type(exc).__name__}: {exc}", file=sys.stderr)
        time.sleep(0.35)
    return pages


def extract_definition(raw: str) -> str:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw, "html.parser")
    for selector in ("span.def", "li.sense span.def", "div.sense span.def"):
        node = soup.select_one(selector)
        if node:
            text = " ".join(node.stripped_strings)
            if len(text) > 8: return text
    for node in soup.find_all(["span", "div", "li"]):
        classes = " ".join(node.get("class") or [])
        if "def" in classes.casefold():
            text = " ".join(node.stripped_strings)
            if len(text) > 8: return text
    return ""


def fetch_one_definition(row: dict[str, str]) -> tuple[str, str, str]:
    session = requests.Session(); session.headers["User-Agent"] = "Mozilla/5.0 WordDeck MANUAL_EMERGENCY_WORK source-grounded QA"
    try:
        response = _bounded_get(session, row["source_url"], timeout=40, attempts=4); definition = extract_definition(response.text)
        if definition: return row["entry_id"], definition, ""
        return row["entry_id"], "", "Oxford definition text not found at exact definition path"
    except Exception as exc:
        return row["entry_id"], "", f"Oxford definition fetch failed after bounded retry: {type(exc).__name__}: {exc}"


def fetch_definitions(rows: list[dict[str, str]]) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(fetch_one_definition, row) for row in rows]
        for future in as_completed(futures):
            entry_id, definition, error = future.result(); out[entry_id] = (definition, error)
    return out


class Marian:
    def __init__(self, model_name: str):
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        self.tokenizer = AutoTokenizer.from_pretrained(model_name); self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name); self.model.eval()
    def run(self, texts: list[str], batch: int = 48) -> list[str]:
        import torch
        out: list[str] = []
        for start in range(0, len(texts), batch):
            current = texts[start:start + batch]; encoded = self.tokenizer(current, return_tensors="pt", padding=True, truncation=True, max_length=192)
            with torch.no_grad(): generated = self.model.generate(**encoded, max_new_tokens=72, num_beams=4)
            out.extend(self.tokenizer.batch_decode(generated, skip_special_tokens=True))
        return [text.strip() for text in out]


class Semantic:
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(SEM_MODEL)
    def pair_scores(self, left: list[str], right: list[str]) -> list[float]:
        import numpy as np
        if len(left) != len(right): raise ValueError("Semantic pair lists have different lengths")
        if not left: return []
        a = self.model.encode(left, batch_size=96, normalize_embeddings=True, show_progress_bar=False); b = self.model.encode(right, batch_size=96, normalize_embeddings=True, show_progress_bar=False)
        return [float(x) for x in np.sum(a * b, axis=1)]


def words(text: str) -> list[str]: return re.findall(r"[a-z]+", surface(text).casefold().replace("-", " "))

def lexical_score(source: str, reverse: str) -> float:
    a = " ".join(words(source)); b = " ".join(words(reverse))
    if not a or not b: return 0.0
    if a == b or a in b or b in a: return 1.0
    aa, bb = set(a.split()), set(b.split()); overlap = len(aa & bb) / max(1, len(aa | bb))
    return max(overlap, difflib.SequenceMatcher(a=a, b=b).ratio())


def language_ok(text: str) -> tuple[bool, str]:
    if not text.strip(): return False, "blank Ukrainian candidate"
    if re.search(r"\b(successful|message|user|action|area|unit|invalid|applications|support|reserve|animation|custom|float|bar|pixer|failer|security|fall|trunk|break|process)\b", text, re.I): return False, "English/source-language residue or model artifact"
    letters = re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґ]", text)
    if not letters: return False, "candidate has no alphabetic text"
    cyrillic = sum(bool(re.match(r"[А-Яа-яІіЇїЄєҐґ]", char)) for char in letters)
    if cyrillic / len(letters) < 0.72: return False, "candidate is not predominantly Ukrainian"
    if re.search(r"[A-Za-z]{3,}", text): return False, "Latin-language residue remains"
    if re.search(r"\b(azerbaijan|kgm)\b", text, re.I): return False, "malformed model artifact"
    return True, ""


def pos_ok(text: str, pos: str) -> tuple[bool, str]:
    value = text.strip().casefold(); kind = pos.casefold(); tokens = [item for item in re.split(r"[;,/]\s*", value) if item]
    if kind in {"verb", "modal verb"}:
        if not any(re.search(r"(ти|ться|тися)$", item.split()[0]) for item in tokens if item.split()): return False, "verb candidate is not an appropriate Ukrainian infinitive/verb phrase"
    if kind == "adjective":
        if not any(re.search(r"(ий|ій|а|я|е|є|і)$", item.split()[0]) for item in tokens if item.split()): return False, "adjective candidate has no plausible Ukrainian adjective morphology"
    if kind == "noun":
        if any(re.search(r"(ти|ться|тися)$", item.split()[0]) for item in tokens if item.split()): return False, "noun candidate is an infinitive/verb form"
    return True, ""


def gate(source: str, pos: str, candidate: str, reverse: str, definition: str, candidate_definition_similarity: float, reverse_definition_similarity: float) -> tuple[bool, str, float, float]:
    ok, reason = language_ok(candidate)
    if not ok: return False, reason, 0.0, 0.0
    ok, reason = pos_ok(candidate, pos)
    if not ok: return False, reason, 0.0, 0.0
    if not definition: return False, "exact Oxford definition unavailable", 0.0, 0.0
    lex = lexical_score(source, reverse); semantic = max(candidate_definition_similarity, reverse_definition_similarity)
    if lex < 0.28: return False, f"low reverse lexical agreement {lex:.3f}", lex, semantic
    if semantic < 0.38: return False, f"candidate/reverse meaning does not align with exact Oxford definition ({semantic:.3f})", lex, semantic
    return True, "positive source-grounded semantic/POS/language review", lex, semantic


def load_overrides(path: Path | None, known: set[str]) -> dict[str, tuple[str, str]]:
    if path is None or not path.exists(): return {}
    out: dict[str, tuple[str, str]] = {}
    for number, row in enumerate(read_tsv(path), 1):
        entry_id, ukrainian, reason = row.get("entry_id", ""), row.get("ukrainian", ""), row.get("reason", "")
        if not entry_id or not ukrainian or not reason: raise RuntimeError(f"Override row {number} requires entry_id, ukrainian, reason")
        if entry_id not in known: raise RuntimeError(f"Override outside exact tail: {entry_id}")
        if entry_id in out: raise RuntimeError(f"Duplicate override: {entry_id}")
        out[entry_id] = (ukrainian, reason)
    return out


def add_candidate(options: list[dict[str, str]], text: str, method: str) -> None:
    text = (text or "").strip()
    if not text: return
    if any(item["text"].casefold() == text.casefold() for item in options): return
    options.append({"text": text, "method": method})


def build_candidate_options(row: dict[str, str], contextual_mt: str, surface_mt: str, wiki_text: str, overrides: dict[str, tuple[str, str]]) -> list[dict[str, str]]:
    """Actual candidate-building path. Every candidate owns explicit provenance."""
    entry_id = row["entry_id"]; options: list[dict[str, str]] = []
    if entry_id in overrides:
        ukrainian, reason = overrides[entry_id]; add_candidate(options, ukrainian, "explicit_work_developer_override:" + reason)
    for term in wiki_terms(wiki_text, row["part_of_speech"]): add_candidate(options, term, "en_wiktionary_matching_pos_uk_translation")
    add_candidate(options, contextual_mt, EN_UK_MODEL + "_contextual_definition_candidate")
    add_candidate(options, surface_mt, EN_UK_MODEL + "_surface_candidate")
    if not options: options.append({"text": "", "method": "no_auxiliary_candidate_available"})
    for item in options:
        if not item.get("method"): raise RuntimeError(f"Candidate provenance missing for {entry_id}: {item!r}")
    return options


def self_test() -> None:
    base = {"entry_id": "ox5000-test", "source": "test", "part_of_speech": "noun", "level": "C1"}
    wiki = "==English==\n===Noun===\n# test\n====Translations====\n{{t|uk|перевірка}}\n"
    both = build_candidate_options(base, "контекст", "поверхня", wiki, {})
    assert {item["method"] for item in both} >= {"en_wiktionary_matching_pos_uk_translation", EN_UK_MODEL + "_contextual_definition_candidate", EN_UK_MODEL + "_surface_candidate"}
    contextual_only = build_candidate_options(base, "контекст", "", "", {}); assert contextual_only[0]["method"].endswith("_contextual_definition_candidate")
    surface_only = build_candidate_options(base, "", "перевірка", "", {}); assert surface_only[0]["method"].endswith("_surface_candidate")
    override = build_candidate_options(base, "", "", "", {"ox5000-test": ("перевірка", "reviewed exact sense")}); assert override[0]["method"].startswith("explicit_work_developer_override:")
    none = build_candidate_options(base, "", "", "", {}); assert none == [{"text": "", "method": "no_auxiliary_candidate_available"}]
    for group in (both, contextual_only, surface_only, override, none): assert all("method" in item and item["method"] for item in group)
    bad = [("chop", "verb", "bar"), ("peer", "noun", "Вузол"), ("rebel", "noun", "animation"), ("shrink", "verb", "pixer"), ("tendency", "noun", "custom"), ("trustee", "noun", "трапеза"), ("utilize", "verb", "applications"), ("workout", "noun", "successful message after an user action"), ("boost", "verb", "Підсилення"), ("cheer", "verb", "веселий")]
    for source_word, pos, candidate in bad:
        passed, *_ = gate(source_word, pos, candidate, source_word, "unrelated exact Oxford sense fixture", 0.10, 0.10)
        if passed: raise AssertionError(f"known-bad fixture escaped fail-closed gate: {source_word}")
    passed, *_ = gate("boost", "verb", "підсилювати", "boost", "to make something increase or become better or more successful", 0.80, 0.80); assert passed
    passed, *_ = gate("peer", "noun", "ровесник", "peer", "a person who is the same age or who has the same social status as you", 0.80, 0.80); assert passed
    print("Corrective emergency semantic QA self-test passed: actual candidate provenance paths are total, and language/POS/source-grounded failures remain fail closed.")


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--unaccounted", type=Path); parser.add_argument("--qa-dir", type=Path); parser.add_argument("--bootstrap", type=Path); parser.add_argument("--csproj", type=Path); parser.add_argument("--overrides", type=Path); parser.add_argument("--expected-tail", type=int, default=EXPECTED_TAIL); parser.add_argument("--round-id", default="round01"); parser.add_argument("--self-test", action="store_true"); args = parser.parse_args()
    if args.self_test: self_test(); return 0
    if not all((args.unaccounted, args.qa_dir, args.bootstrap, args.csproj)): parser.error("normal run requires --unaccounted --qa-dir --bootstrap --csproj")
    rows = read_tsv(args.unaccounted)
    if len(rows) != args.expected_tail: raise RuntimeError(f"exact tail required {args.expected_tail}, got {len(rows)}")
    seen: set[str] = set()
    for number, row in enumerate(rows, 1):
        for field in ("entry_id", "source", "part_of_speech", "level", "source_index", "source_url", "definition_path"):
            if not row.get(field): raise RuntimeError(f"unaccounted row {number} blank {field}")
        if row["level"].upper() not in {"B2", "C1"}: raise RuntimeError(f"invalid CEFR row {number}")
        if stable_id(row["source"], row["part_of_speech"], row["level"]) != row["entry_id"]: raise RuntimeError(f"stable ID mismatch row {number}")
        if row["entry_id"] in seen: raise RuntimeError(f"duplicate stable ID {row['entry_id']}")
        seen.add(row["entry_id"])
    round_token = re.sub(r"[^A-Za-z0-9_-]+", "-", args.round_id).strip("-") or "round"
    first_run_id = f"MANUAL_EMERGENCY_WORK_20260820_FIRST_PASS_V3_{round_token}"; second_run_id = f"MANUAL_EMERGENCY_WORK_20260820_SECOND_PASS_V3_{round_token}"
    overrides = load_overrides(args.overrides, seen); print(f"MANUAL_EMERGENCY_WORK V3 exact source reconciliation PASS: {len(rows)} round={round_token}")
    definitions = fetch_definitions(rows); wiki_pages = fetch_wiki(rows)
    contextual_inputs = [f"{surface(row['source'])} ({row['part_of_speech']}): {definitions[row['entry_id']][0]}" for row in rows]; surface_inputs = [surface(row["source"]) for row in rows]
    mt = Marian(EN_UK_MODEL); translations = mt.run(contextual_inputs + surface_inputs); del mt
    contextual = translations[:len(rows)]; surface_translations = translations[len(rows):]
    options: dict[str, list[dict[str, str]]] = {}
    for row, contextual_mt, surface_mt in zip(rows, contextual, surface_translations, strict=True):
        entry_id = row["entry_id"]; options[entry_id] = build_candidate_options(row, contextual_mt, surface_mt, wiki_pages.get(surface(row["source"]).casefold(), ""), overrides)
    flat_candidates: list[str] = []; flat_keys: list[tuple[str, int]] = []; flat_definitions: list[str] = []
    for row in rows:
        entry_id = row["entry_id"]; definition = definitions[entry_id][0]
        for index, item in enumerate(options[entry_id]): flat_candidates.append(item["text"]); flat_keys.append((entry_id, index)); flat_definitions.append(definition)
    reverse_values = Marian(UK_EN_MODEL).run(flat_candidates); reverse = {key: value for key, value in zip(flat_keys, reverse_values, strict=True)}
    semantic = Semantic(); candidate_semantic = semantic.pair_scores(flat_definitions, flat_candidates); reverse_semantic = semantic.pair_scores(flat_definitions, reverse_values); del semantic
    semantic_by_key = {key: (cand_sim, rev_sim) for key, cand_sim, rev_sim in zip(flat_keys, candidate_semantic, reverse_semantic, strict=True)}
    first_rows: list[dict[str, str]] = []; second_rows: list[dict[str, str]] = []; final_rows: list[dict[str, str]] = []; holds: list[dict[str, str]] = []
    for row in rows:
        entry_id = row["entry_id"]; definition, definition_error = definitions[entry_id]; evaluated = []; history_parts = []
        for index, item in enumerate(options[entry_id]):
            candidate = item["text"]; method = item["method"]; reverse_text = reverse[(entry_id, index)]; cand_sim, rev_sim = semantic_by_key[(entry_id, index)]
            passed, reason, lex, semantic_score = gate(row["source"], row["part_of_speech"], candidate, reverse_text, definition, cand_sim, rev_sim)
            evaluated.append((passed, semantic_score, lex, candidate, reverse_text, reason, method, cand_sim, rev_sim)); history_parts.append(f"{method}=>{candidate!r};reverse={reverse_text!r};lex={lex:.3f};candDef={cand_sim:.3f};revDef={rev_sim:.3f};decision={'PASS' if passed else 'BLOCKED'}:{reason}")
        evaluated.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        passed, semantic_score, lex, candidate, reverse_text, reason, method, cand_sim, rev_sim = evaluated[0]
        source_check = f"MANUAL_EMERGENCY_WORK V3 exact Oxford identity; source_index={row['source_index']}; definition_path={row['definition_path']}; stable_id=PASS; exact_definition={definition!r}; selected_candidate_method={method}"
        first_rows.append({"data_factory_run_id": first_run_id, "entry_id": entry_id, "source": row["source"], "part_of_speech": row["part_of_speech"], "level": row["level"].upper(), "official_source": row["source_url"], "source_check": source_check, "ukrainian_candidate": candidate})
        if passed:
            qa_reason = f"PASS: source-grounded second pass; method={method}; exact Oxford definition={definition!r}; candidate={candidate!r}; reverse={reverse_text!r}; lexical={lex:.3f}; candidate_definition_similarity={cand_sim:.3f}; reverse_definition_similarity={rev_sim:.3f}; semantic={semantic_score:.3f}; POS/language checks PASS."
            decision = "PASS"; ukrainian = candidate
            final_rows.append({"entry_id": entry_id, "source": row["source"], "part_of_speech": row["part_of_speech"], "level": row["level"].upper(), "ukrainian": candidate, "status": "verified", "manual_emergency_first_pass_run_id": first_run_id, "manual_emergency_second_pass_run_id": second_run_id, "source_check": source_check, "qa_reason": qa_reason})
        else:
            qa_reason = f"BLOCKED: {definition_error or reason}; method={method}; exact Oxford definition={definition!r}; candidate={candidate!r}; reverse={reverse_text!r}; lexical={lex:.3f}; candidate_definition_similarity={cand_sim:.3f}; reverse_definition_similarity={rev_sim:.3f}; semantic={semantic_score:.3f}."
            decision = "BLOCKED"; ukrainian = ""
            holds.append({"entry_id": entry_id, "source": row["source"], "part_of_speech": row["part_of_speech"], "level": row["level"].upper(), "official_source": row["source_url"], "definition_path": row["definition_path"], "exact_definition": definition, "selected_candidate": candidate, "selected_candidate_method": method, "candidate_history": " || ".join(history_parts), "reason": qa_reason})
        second_rows.append({"content_qa_run_id": second_run_id, "data_factory_run_id": first_run_id, "entry_id": entry_id, "source": row["source"], "part_of_speech": row["part_of_speech"], "level": row["level"].upper(), "decision": decision, "ukrainian": ukrainian, "qa_reason": qa_reason})
    qa_dir = args.qa_dir
    write_tsv(qa_dir / "oxford5000_manual_emergency_first_pass_20260820.tsv", first_rows, FIRST_FIELDS); write_tsv(qa_dir / "oxford5000_manual_emergency_second_pass_20260820.tsv", second_rows, SECOND_FIELDS); write_tsv(qa_dir / "oxford5000_manual_emergency_full_verified_tail_20260820.tsv", final_rows, FINAL_FIELDS); write_tsv(qa_dir / "oxford5000_manual_emergency_holds_20260820.tsv", holds, HOLD_FIELDS)
    summary = {"round_id": round_token, "total": len(rows), "pass": len(final_rows), "blocked": len(holds), "first_pass_run_id": first_run_id, "second_pass_run_id": second_run_id}
    (qa_dir / "semantic-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"MANUAL_EMERGENCY_WORK V3 COMPLETE: total={len(rows)} PASS={len(final_rows)} BLOCKED={len(holds)}; PASS+BLOCKED={len(final_rows)+len(holds)}. No BLOCKED row is verified.")
    return 0


if __name__ == "__main__": raise SystemExit(main())
