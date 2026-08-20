#!/usr/bin/env python3
"""Sense-bound MANUAL_EMERGENCY_WORK V5 reviewer for the Oxford 5000 tail.

V5 is fail-closed. Surface MT is candidate generation only and can never
authorize PASS by itself. Automatic PASS requires a Ukrainian lexical value
that is:
- concise and learner-facing;
- in canonical Ukrainian dictionary form;
- tied to a sense-specific bilingual translation block;
- aligned to the exact Oxford definition;
- compatible with the Oxford POS and semantic role.

Wiktionary translations are accepted as confirmation only when they occur
inside a structurally sense-labelled translation block (trans-top/gloss).
Quantitative metrics and reverse translation are supporting evidence only.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import complete_oxford5000_emergency as base
import complete_oxford5000_emergency_v4 as v4

VERSION = "V5"
STOP = {
    "a","an","the","to","of","in","on","at","for","from","with","and","or","that",
    "which","who","whose","is","are","be","being","been","as","by","it","its","this",
    "these","those","someone","somebody","something","person","thing","one","very"
}
SENSE_TOP_RE = re.compile(r"\{\{trans-top(?:-also)?\|([^{}]*)\}\}", re.I)
SENSE_BOTTOM_RE = re.compile(r"\{\{trans-bottom\}\}", re.I)
UK_TERM_RE = re.compile(r"\{\{(?:t\+?|t-check|tt\+?)\|uk\|([^|}\n]+)", re.I)
WIKI_LINK_RE = re.compile(r"\[\[([^]|]+)(?:\|([^]]+))?\]\]")
TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
HOLD_FIELDS = [
    "entry_id","source","part_of_speech","level","official_source","definition_path",
    "exact_definition","selected_candidate","selected_candidate_method","sense_source",
    "sense_gloss","sense_alignment","morphology_evidence","candidate_history","reason"
]

def clean_gloss(value: str) -> str:
    value = WIKI_LINK_RE.sub(lambda m: m.group(2) or m.group(1), value or "")
    value = TEMPLATE_RE.sub(" ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ;:,-")

def content_tokens(value: str) -> set[str]:
    return {x for x in re.findall(r"[a-z]+", (value or "").casefold()) if len(x) > 2 and x not in STOP}

def lexical_overlap(gloss: str, definition: str) -> int:
    return len(content_tokens(gloss) & content_tokens(definition))

def extract_sense_bound_terms(page_text: str, pos: str) -> list[dict[str, str]]:
    section = base.pos_section(page_text, pos)
    if not section:
        return []
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    starts = list(SENSE_TOP_RE.finditer(section))
    for start in starts:
        bottom = SENSE_BOTTOM_RE.search(section, start.end())
        if not bottom:
            continue
        next_top = SENSE_TOP_RE.search(section, start.end())
        end = bottom.start()
        if next_top and next_top.start() < end:
            end = next_top.start()
        gloss = clean_gloss(start.group(1))
        if not gloss:
            continue
        block = section[start.end():end]
        for match in UK_TERM_RE.finditer(block):
            term = base.clean(match.group(1))
            key = (term.casefold(), gloss.casefold())
            if term and key not in seen:
                seen.add(key)
                out.append({
                    "text": term,
                    "method": "en_wiktionary_sense_bound_uk_translation",
                    "sense_source": "English Wiktionary",
                    "sense_gloss": gloss,
                })
    return out

class UkrainianMorphology:
    def __init__(self) -> None:
        from pymorphy3 import MorphAnalyzer
        self.morph = MorphAnalyzer(lang="uk")

    @staticmethod
    def _expected(pos: str) -> set[str]:
        kind = pos.casefold()
        if kind == "noun": return {"NOUN","NPRO"}
        if kind in {"verb","modal verb"}: return {"INFN","VERB"}
        if kind == "adjective": return {"ADJF"}
        if kind == "adverb": return {"ADVB"}
        if kind == "preposition": return {"PREP"}
        if kind == "conjunction": return {"CONJ"}
        if kind == "pronoun": return {"NPRO"}
        if kind == "number": return {"NUMR"}
        if kind == "exclamation": return {"INTJ"}
        if kind == "determiner": return {"ADJF","NPRO"}
        return set()

    def canonicalize(self, candidate: str, pos: str) -> tuple[str, str]:
        value = candidate.strip()
        words = re.findall(r"[А-Яа-яІіЇїЄєҐґ'-]+", value)
        if len(words) != 1:
            return value, "multiword value retained; no silent token-level lemma rewrite"
        parses = self.morph.parse(words[0])
        expected = self._expected(pos)
        matching = [p for p in parses if not expected or str(p.tag.POS) in expected]
        if not matching:
            return value, "no Ukrainian morphology parse matching requested POS"
        best = matching[0]
        normal = str(best.normal_form or words[0]).strip()
        if normal and normal.casefold() != words[0].casefold():
            return normal, f"pymorphy3 uk normalized {words[0]!r}->{normal!r}; tag={best.tag}; score={best.score:.4f}"
        return value, f"pymorphy3 uk canonical form retained; tag={best.tag}; score={best.score:.4f}"

    def validate(self, candidate: str, pos: str) -> tuple[bool, str]:
        value = candidate.strip()
        words = re.findall(r"[А-Яа-яІіЇїЄєҐґ'-]+", value)
        if not words:
            return False, "no Ukrainian lexical token"
        if len(words) > 1:
            ok, why = v4.lexical_form_ok(value, pos)
            return (ok, "multiword lexical phrase; V4 lexical/POS form accepted" if ok else why)
        token = words[0]
        parses = self.morph.parse(token)
        expected = self._expected(pos)
        matches = [p for p in parses if not expected or str(p.tag.POS) in expected]
        if not matches:
            return False, f"pymorphy3 uk has no requested-POS parse for {token!r}"
        canonical = [p for p in matches if str(p.normal_form or "").casefold() == token.casefold()]
        if not canonical:
            normals = sorted({str(p.normal_form) for p in matches if p.normal_form})
            return False, f"not canonical Ukrainian lemma; normal forms={normals[:6]}"
        best = canonical[0]
        tag = best.tag
        kind = pos.casefold()
        if kind == "adjective":
            if str(tag.POS) != "ADJF":
                return False, f"adjective is not ADJF: {tag}"
            gender = getattr(tag, "gender", None)
            case = getattr(tag, "case", None)
            number = getattr(tag, "number", None)
            if gender not in {None, "masc"} or case not in {None, "nomn"} or number not in {None, "sing"}:
                return False, f"adjective is not canonical nominative masculine singular: {tag}"
        if kind == "noun":
            case = getattr(tag, "case", None)
            if case not in {None, "nomn"}:
                return False, f"noun is not nominative lemma form: {tag}"
        if kind in {"verb","modal verb"}:
            if str(tag.POS) not in {"INFN","VERB"}:
                return False, f"verb is not infinitive/lexical verb form: {tag}"
            if not re.search(r"(ти|тися|ться)$", token.casefold()):
                return False, f"verb is not learner-facing infinitive form: {token!r}"
        return True, f"pymorphy3 uk canonical lemma PASS; tag={tag}; score={best.score:.4f}"

def candidate_options(
    row: dict[str, str],
    surface_mt: str,
    wiki_text: str,
    overrides: dict[str, tuple[str, str]],
    morphology: UkrainianMorphology,
) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    eid = row["entry_id"]
    if eid in overrides:
        value, reason = overrides[eid]
        canonical, morph_note = morphology.canonicalize(value, row["part_of_speech"])
        options.append({
            "text": canonical,
            "method": "explicit_work_developer_override:" + reason,
            "sense_source": "explicit reviewed override",
            "sense_gloss": reason,
            "morph_normalization": morph_note,
        })
    for item in extract_sense_bound_terms(wiki_text, row["part_of_speech"]):
        canonical, morph_note = morphology.canonicalize(item["text"], row["part_of_speech"])
        options.append({**item, "text": canonical, "morph_normalization": morph_note})
    if surface_mt.strip():
        canonical, morph_note = morphology.canonicalize(surface_mt, row["part_of_speech"])
        options.append({
            "text": canonical,
            "method": base.EN_UK_MODEL + "_surface_candidate",
            "sense_source": "",
            "sense_gloss": "",
            "morph_normalization": morph_note,
        })
    dedup: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in options:
        key = (item["text"].casefold(), item["method"], item.get("sense_gloss","").casefold())
        if item["text"] and key not in seen:
            seen.add(key)
            dedup.append(item)
    if not dedup:
        dedup.append({
            "text": "",
            "method": "no_auxiliary_candidate_available",
            "sense_source": "",
            "sense_gloss": "",
            "morph_normalization": "",
        })
    return dedup

def build_wiki_confirmation(
    options: list[dict[str, str]],
    gloss_scores: dict[int, float],
    definition: str,
) -> dict[str, list[dict[str, object]]]:
    confirmed: dict[str, list[dict[str, object]]] = {}
    for idx, item in enumerate(options):
        if item["method"] != "en_wiktionary_sense_bound_uk_translation":
            continue
        gloss = item.get("sense_gloss","")
        score = gloss_scores.get(idx, 0.0)
        overlap = lexical_overlap(gloss, definition)
        aligned = bool(gloss and (overlap >= 1 or score >= 0.62))
        if aligned:
            confirmed.setdefault(item["text"].casefold(), []).append({
                "gloss": gloss,
                "score": score,
                "overlap": overlap,
                "source": item.get("sense_source","English Wiktionary"),
            })
    return confirmed

def gate(
    row: dict[str, str],
    candidate: dict[str, str],
    reverse: str,
    definition: str,
    cand_def_similarity: float,
    rev_def_similarity: float,
    gloss_similarity: float,
    confirmations: dict[str, list[dict[str, object]]],
    morphology: UkrainianMorphology,
) -> tuple[bool, str, float]:
    text = candidate["text"]
    method = candidate["method"]
    ok, why = v4.lexical_form_ok(text, row["part_of_speech"])
    if not ok:
        return False, why, base.lexical_score(row["source"], reverse)
    if not definition:
        return False, "exact Oxford definition unavailable", base.lexical_score(row["source"], reverse)
    ok, morph = morphology.validate(text, row["part_of_speech"])
    if not ok:
        return False, morph, base.lexical_score(row["source"], reverse)
    ok, why = v4.role_ok(definition, reverse, row["source"])
    if not ok:
        return False, why, base.lexical_score(row["source"], reverse)
    lex = base.lexical_score(row["source"], reverse)
    key = text.casefold()
    explicit = method.startswith("explicit_work_developer_override:")
    wiki = method == "en_wiktionary_sense_bound_uk_translation"
    surface = method.endswith("_surface_candidate")
    if wiki:
        gloss = candidate.get("sense_gloss","")
        overlap = lexical_overlap(gloss, definition)
        if not gloss:
            return False, "Wiktionary candidate is not bound to a labelled sense/gloss", lex
        if not (overlap >= 1 or gloss_similarity >= 0.62):
            return False, f"sense-specific Wiktionary gloss does not align with exact Oxford definition; gloss_similarity={gloss_similarity:.3f}; lexical_overlap={overlap}", lex
        if key not in confirmations:
            return False, "sense-bound bilingual confirmation did not survive alignment gate", lex
        if min(cand_def_similarity, rev_def_similarity) < 0.30:
            return False, "candidate has contradictory definition support despite sense-bound source", lex
        return True, f"V5 PASS: sense-bound Wiktionary bilingual confirmation + exact Oxford definition + canonical Ukrainian lemma; gloss_similarity={gloss_similarity:.3f}; overlap={overlap}; {morph}", lex
    if surface:
        if key not in confirmations:
            return False, "surface MT is candidate generation only; no independent sense-specific bilingual confirmation for this lexical value", lex
        return True, f"V5 PASS: surface candidate independently confirmed by aligned sense-bound Wiktionary translation + canonical Ukrainian lemma; {morph}", lex
    if explicit:
        reason = method.split(":",1)[1]
        if "sense_source=" not in reason or "sense_gloss=" not in reason or "evidence=" not in reason:
            return False, "reviewed override lacks explicit sense_source/sense_gloss/evidence fields", lex
        if min(cand_def_similarity, rev_def_similarity) < 0.30:
            return False, "reviewed override contradicts exact Oxford definition", lex
        return True, f"V5 PASS: documented explicit reviewed override with sense-specific source + canonical Ukrainian lemma; {morph}", lex
    return False, f"unsupported evidence provenance for V5 PASS: {method}", lex

def self_test() -> None:
    morphology = UkrainianMorphology()
    wiki = """==English==
===Noun===
# test
====Translations====
{{trans-top|a person who works in a mine}}
* Ukrainian: {{t|uk|шахтар}}
{{trans-bottom}}
{{trans-top|a person who lays explosive mines}}
* Ukrainian: {{t|uk|мінер}}
{{trans-bottom}}
"""
    terms = extract_sense_bound_terms(wiki, "noun")
    assert any(x["text"] == "шахтар" and "works in a mine" in x["sense_gloss"] for x in terms)
    assert any(x["text"] == "мінер" and "explosive" in x["sense_gloss"] for x in terms)
    ok, _ = morphology.validate("чарівна", "adjective")
    assert not ok, "feminine adjective form must fail canonical lemma validation"
    canonical, _ = morphology.canonicalize("чарівна", "adjective")
    assert canonical.casefold() == "чарівний"
    ok, _ = morphology.validate(canonical, "adjective")
    assert ok
    for src,pos,cand in [
        ("broadcaster","noun","трансляція"),
        ("briefly","adverb","короткий час"),
        ("bold","adjective","жирний (підприємець): сміливий"),
        ("brick","noun","цегла (нун): будівельний матеріал"),
    ]:
        ok, _ = v4.lexical_form_ok(cand, pos)
        if src in {"bold","brick"}:
            assert not ok
    print("V5 sense-bound self-test passed: labelled bilingual sense extraction, miner-sense separation and canonical Ukrainian lemma validation are fail-closed.")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unaccounted", type=Path)
    parser.add_argument("--qa-dir", type=Path)
    parser.add_argument("--overrides", type=Path)
    parser.add_argument("--expected-tail", type=int)
    parser.add_argument("--round-id", default="round01")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.unaccounted or not args.qa_dir or args.expected_tail is None:
        parser.error("normal run requires --unaccounted --qa-dir --expected-tail")
    rows = base.read_tsv(args.unaccounted)
    if len(rows) != args.expected_tail:
        raise RuntimeError(f"exact tail required {args.expected_tail}, got {len(rows)}")
    seen: set[str] = set()
    for number, row in enumerate(rows, 1):
        for field in ("entry_id","source","part_of_speech","level","source_index","source_url","definition_path"):
            if not row.get(field):
                raise RuntimeError(f"unaccounted row {number} blank {field}")
        if base.stable_id(row["source"], row["part_of_speech"], row["level"]) != row["entry_id"]:
            raise RuntimeError(f"stable ID mismatch row {number}")
        if row["entry_id"] in seen:
            raise RuntimeError(f"duplicate stable ID {row['entry_id']}")
        seen.add(row["entry_id"])
    round_token = re.sub(r"[^A-Za-z0-9_-]+","-",args.round_id).strip("-") or "round"
    first_run_id = f"MANUAL_EMERGENCY_WORK_20260820_FIRST_PASS_V5_{round_token}"
    second_run_id = f"MANUAL_EMERGENCY_WORK_20260820_SECOND_PASS_V5_{round_token}"
    overrides = base.load_overrides(args.overrides, seen)
    definitions = base.fetch_definitions(rows)
    wiki_pages = base.fetch_wiki(rows)
    morphology = UkrainianMorphology()
    mt = base.Marian(base.EN_UK_MODEL)
    surface_translations = mt.run([base.surface(row["source"]) for row in rows])
    del mt
    options: dict[str, list[dict[str,str]]] = {}
    for row, surface_mt in zip(rows, surface_translations, strict=True):
        page = wiki_pages.get(base.surface(row["source"]).casefold(), "")
        options[row["entry_id"]] = candidate_options(row, surface_mt, page, overrides, morphology)
    flat_candidates: list[str] = []
    flat_definitions: list[str] = []
    flat_glosses: list[str] = []
    flat_keys: list[tuple[str,int]] = []
    for row in rows:
        eid = row["entry_id"]
        definition = definitions[eid][0]
        for idx, item in enumerate(options[eid]):
            flat_keys.append((eid,idx))
            flat_candidates.append(item["text"])
            flat_definitions.append(definition)
            flat_glosses.append(item.get("sense_gloss","") or definition)
    reverse_values = base.Marian(base.UK_EN_MODEL).run(flat_candidates)
    semantic = base.Semantic()
    cand_scores = semantic.pair_scores(flat_definitions, flat_candidates)
    rev_scores = semantic.pair_scores(flat_definitions, reverse_values)
    gloss_scores = semantic.pair_scores(flat_definitions, flat_glosses)
    del semantic
    reverse = {key: value for key,value in zip(flat_keys, reverse_values, strict=True)}
    scores = {key: (cand, rev, gloss) for key,cand,rev,gloss in zip(flat_keys,cand_scores,rev_scores,gloss_scores,strict=True)}
    first_rows: list[dict[str,str]] = []
    second_rows: list[dict[str,str]] = []
    final_rows: list[dict[str,str]] = []
    holds: list[dict[str,str]] = []
    for row in rows:
        eid = row["entry_id"]
        definition, definition_error = definitions[eid]
        gloss_by_index = {idx: scores[(eid,idx)][2] for idx in range(len(options[eid]))}
        confirmations = build_wiki_confirmation(options[eid], gloss_by_index, definition)
        evaluated = []
        history = []
        for idx,item in enumerate(options[eid]):
            cand_sim, rev_sim, gloss_sim = scores[(eid,idx)]
            rev = reverse[(eid,idx)]
            passed, reason, lex = gate(row, item, rev, definition, cand_sim, rev_sim, gloss_sim, confirmations, morphology)
            priority = 3 if item["method"].startswith("explicit_work_developer_override:") else 2 if item["method"] == "en_wiktionary_sense_bound_uk_translation" else 1
            evaluated.append((passed,priority,gloss_sim,min(cand_sim,rev_sim),lex,item,rev,reason))
            history.append(f"{item['method']}=>{item['text']!r};sense_gloss={item.get('sense_gloss','')!r};reverse={rev!r};glossDef={gloss_sim:.3f};candDef={cand_sim:.3f};revDef={rev_sim:.3f};lex={lex:.3f};morph={item.get('morph_normalization','')};decision={'PASS' if passed else 'BLOCKED'}:{reason}")
        evaluated.sort(key=lambda x:(x[0],x[1],x[2],x[3],x[4]), reverse=True)
        passed,_,gloss_sim,_,lex,item,rev,reason = evaluated[0]
        cand = item["text"]
        method = item["method"]
        morph_ok, morph_evidence = morphology.validate(cand, row["part_of_speech"]) if cand else (False,"blank")
        source_check = f"MANUAL_EMERGENCY_WORK V5 exact Oxford identity; source_index={row['source_index']}; definition_path={row['definition_path']}; exact_definition={definition!r}; selected_candidate_method={method}; sense_source={item.get('sense_source','')!r}; sense_gloss={item.get('sense_gloss','')!r}; gloss_definition_similarity={gloss_sim:.3f}; morphology={morph_evidence!r}; surface_mt_never_sole_pass=PASS"
        first_rows.append({"data_factory_run_id":first_run_id,"entry_id":eid,"source":row["source"],"part_of_speech":row["part_of_speech"],"level":row["level"].upper(),"official_source":row["source_url"],"source_check":source_check,"ukrainian_candidate":cand})
        if passed:
            qa_reason = f"PASS V5: {reason}; exact Oxford definition={definition!r}; reverse={rev!r}; lexical_support={lex:.3f}."
            decision = "PASS"
            ukrainian = cand
            final_rows.append({"entry_id":eid,"source":row["source"],"part_of_speech":row["part_of_speech"],"level":row["level"].upper(),"ukrainian":cand,"status":"verified","manual_emergency_first_pass_run_id":first_run_id,"manual_emergency_second_pass_run_id":second_run_id,"source_check":source_check,"qa_reason":qa_reason})
        else:
            qa_reason = f"BLOCKED V5: {definition_error or reason}; exact Oxford definition={definition!r}."
            decision = "BLOCKED"
            ukrainian = ""
            holds.append({"entry_id":eid,"source":row["source"],"part_of_speech":row["part_of_speech"],"level":row["level"].upper(),"official_source":row["source_url"],"definition_path":row["definition_path"],"exact_definition":definition,"selected_candidate":cand,"selected_candidate_method":method,"sense_source":item.get("sense_source",""),"sense_gloss":item.get("sense_gloss",""),"sense_alignment":f"gloss_definition_similarity={gloss_sim:.3f}; lexical_overlap={lexical_overlap(item.get('sense_gloss',''),definition)}","morphology_evidence":morph_evidence,"candidate_history":" || ".join(history),"reason":qa_reason})
        second_rows.append({"content_qa_run_id":second_run_id,"data_factory_run_id":first_run_id,"entry_id":eid,"source":row["source"],"part_of_speech":row["part_of_speech"],"level":row["level"].upper(),"decision":decision,"ukrainian":ukrainian,"qa_reason":qa_reason})
    qa = args.qa_dir
    base.write_tsv(qa/"first-pass.tsv", first_rows, base.FIRST_FIELDS)
    base.write_tsv(qa/"second-pass.tsv", second_rows, base.SECOND_FIELDS)
    base.write_tsv(qa/"verified.tsv", final_rows, base.FINAL_FIELDS)
    base.write_tsv(qa/"holds.tsv", holds, HOLD_FIELDS)
    summary = {"version":VERSION,"round_id":round_token,"total":len(rows),"pass":len(final_rows),"blocked":len(holds),"first_pass_run_id":first_run_id,"second_pass_run_id":second_run_id,"sense_bound_policy":"surface MT never sole PASS; Wiktionary trans-top gloss must align to Oxford sense; canonical Ukrainian lemma required"}
    (qa/"summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(f"MANUAL_EMERGENCY_WORK V5 COMPLETE: total={len(rows)} PASS={len(final_rows)} BLOCKED={len(holds)}.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
