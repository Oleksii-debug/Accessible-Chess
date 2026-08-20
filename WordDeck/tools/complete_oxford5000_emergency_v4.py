#!/usr/bin/env python3
"""Strict MANUAL_EMERGENCY_WORK V4 lexical reviewer for Oxford 5000.

V4 deliberately never stores contextual translated definitions as flashcard values.
Only concise lexical candidates from explicit reviewed overrides, matching-POS
Wiktionary translations, or surface-only MT can be considered. Exact Oxford identity,
POS, CEFR and definition remain immutable source truth. Quantitative similarity is
supporting evidence only; lexical form, source relation, POS and semantic-role checks
are mandatory and fail closed.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import complete_oxford5000_emergency as base

VERSION = "V4"
SYNTHETIC_LABEL_RE = re.compile(r"\b(?:нун|нуун|ніун|ніуун|ноун|немає|noun|verb|adjective|adverb|adj|adv)\b", re.IGNORECASE)
PERSON_DEF_RE = re.compile(r"\b(?:a|the)\s+person\b|\bsomeone\b|\bsomebody\b|\bpeople who\b|\bperson who\b|\bperson whose\b", re.IGNORECASE)
PROCESS_DEF_RE = re.compile(r"\b(?:the|an?)\s+(?:act|action|process)\b|\bact of\b|\bprocess of\b|\baction of\b", re.IGNORECASE)
STATE_DEF_RE = re.compile(r"\b(?:the|a)\s+(?:state|condition|quality|feeling)\b", re.IGNORECASE)
PLACE_DEF_RE = re.compile(r"\b(?:a|the)\s+(?:place|area|building|room|site|country)\b", re.IGNORECASE)
EVENT_DEF_RE = re.compile(r"\b(?:an?|the)\s+(?:event|occasion|ceremony)\b", re.IGNORECASE)
OBJECT_DEF_RE = re.compile(r"\b(?:an?|the)\s+(?:object|thing|substance|material|device|tool|piece of)\b", re.IGNORECASE)


def normalize_english(text: str) -> str:
    return " ".join(re.findall(r"[a-z]+", text.casefold().replace("-", " ")))


def reverse_contains_source(source: str, reverse: str) -> bool:
    src = normalize_english(base.surface(source)); rev = normalize_english(reverse)
    return bool(src and rev and f" {src} " in f" {rev} ")


def definition_role(definition: str) -> str:
    if PERSON_DEF_RE.search(definition): return "person"
    if PROCESS_DEF_RE.search(definition): return "process"
    if STATE_DEF_RE.search(definition): return "state"
    if PLACE_DEF_RE.search(definition): return "place"
    if EVENT_DEF_RE.search(definition): return "event"
    if OBJECT_DEF_RE.search(definition): return "object"
    return "generic"


def reverse_role(reverse: str) -> str:
    value = normalize_english(reverse); tokens = value.split()
    if not tokens: return "unknown"
    first = tokens[0]
    if re.search(r"(?:er|or|ist|ian)$", first) or re.search(r"\b(?:person|worker|official|member|owner|employee|teacher|writer|artist|driver|manager|speaker|presenter)\b", value): return "person"
    if re.search(r"(?:tion|sion|ment|ing)$", first) or re.search(r"\b(?:act|action|process)\b", value): return "process"
    if re.search(r"(?:ness|ity|cy|hood)$", first) or re.search(r"\b(?:state|condition|quality|feeling)\b", value): return "state"
    if re.search(r"\b(?:place|area|building|room|site|country)\b", value): return "place"
    if re.search(r"\b(?:event|occasion|ceremony)\b", value): return "event"
    if re.search(r"\b(?:object|thing|substance|material|device|tool)\b", value): return "object"
    return "generic"


def lexical_form_ok(candidate: str, pos: str) -> tuple[bool, str]:
    value = candidate.strip()
    if not value: return False, "blank lexical value"
    ok, why = base.language_ok(value)
    if not ok: return False, why
    if SYNTHETIC_LABEL_RE.search(value): return False, "synthetic POS/model label in lexical value"
    if ":" in value: return False, "definition/gloss contamination: colon is forbidden in ordinary lexical value"
    if any(ch in value for ch in "()[]"): return False, "parenthetical/model annotation contamination"
    if any(ch in value for ch in "\n\r\t"): return False, "control/newline contamination"
    if re.search(r"[.!?]", value): return False, "sentence-like punctuation in lexical value"
    words = re.findall(r"[А-Яа-яІіЇїЄєҐґ'-]+", value)
    if len(words) > 5 or len(value) > 64: return False, "lexical value is definition-like or sentence-length"
    segments = [seg.strip() for seg in re.split(r"[;,/]", value) if seg.strip()]
    if len(segments) > 3: return False, "too many gloss alternatives for a flashcard value"
    ok, why = base.pos_ok(value, pos)
    if not ok: return False, why
    kind = pos.casefold(); first = words[0].casefold() if words else ""
    if kind == "adverb" and len(words) > 1 and first not in {"на","у","в","по","до","без","з","із","за","під","для","через"}: return False, "multiword adverb candidate is not an adverbial phrase"
    if kind == "noun" and re.search(r"(?:ти|тися|ться)$", first): return False, "noun candidate is verbal"
    return True, ""


def role_ok(definition: str, reverse: str, source: str) -> tuple[bool, str]:
    required = definition_role(definition)
    if required == "generic": return True, ""
    if reverse_contains_source(source, reverse):
        src = normalize_english(base.surface(source)).split()[0]
        if required == "person" and not (re.search(r"(?:er|or|ist|ian)$", src) or src in {"adult","child","teenager","peer","victim","witness","trustee","candidate"}):
            return False, f"Oxford definition requires person role but source/reverse role is not independently person-like ({src})"
        return True, ""
    observed = reverse_role(reverse)
    if observed != required: return False, f"semantic role mismatch: Oxford definition requires {required}, reverse candidate looks {observed}"
    return True, ""


def gate(source: str, pos: str, candidate: str, method: str, reverse: str, definition: str, candidate_definition_similarity: float, reverse_definition_similarity: float) -> tuple[bool, str, float]:
    ok, why = lexical_form_ok(candidate, pos)
    if not ok: return False, why, base.lexical_score(source, reverse)
    if not definition: return False, "exact Oxford definition unavailable", base.lexical_score(source, reverse)
    if "_contextual_definition_candidate" in method: return False, "contextual translated definition can never be the stored flashcard value", base.lexical_score(source, reverse)
    if method == "no_auxiliary_candidate_available": return False, "no lexical candidate evidence", 0.0
    ok, why = role_ok(definition, reverse, source)
    if not ok: return False, why, base.lexical_score(source, reverse)
    lex = base.lexical_score(source, reverse); exact_back = reverse_contains_source(source, reverse)
    explicit = method.startswith("explicit_work_developer_override:"); wiktionary = method == "en_wiktionary_matching_pos_uk_translation"; surface_mt = method.endswith("_surface_candidate")
    if explicit:
        if candidate_definition_similarity < 0.40 or reverse_definition_similarity < 0.40: return False, "reviewed override lacks sufficient independent definition alignment", lex
    elif wiktionary:
        if not exact_back: return False, "Wiktionary candidate does not back-translate to the exact English lexical identity", lex
        if candidate_definition_similarity < 0.38 or reverse_definition_similarity < 0.38: return False, "Wiktionary lexical candidate lacks two-sided exact-definition support", lex
    elif surface_mt:
        if not exact_back: return False, "surface MT candidate does not back-translate to the exact English lexical identity", lex
        if candidate_definition_similarity < 0.42 or reverse_definition_similarity < 0.42: return False, "surface MT candidate lacks two-sided exact-definition support", lex
    else: return False, f"unsupported candidate provenance for PASS: {method}", lex
    return True, "concise lexical form, POS, semantic role, provenance and exact-definition evidence PASS", lex


def candidate_options(row: dict[str, str], surface_mt: str, wiki_text: str, overrides: dict[str, tuple[str, str]]) -> list[dict[str, str]]:
    options = base.build_candidate_options(row, "", surface_mt, wiki_text, overrides)
    return [item for item in options if "_contextual_definition_candidate" not in item["method"]]


def self_test() -> None:
    bad_form=[("bold","adjective","жирний (підприємець): сміливий і впевнений","fat"),("brick","noun","Цегла (нун): будівельний матеріал","brick"),("candle","noun","свічка (ноун): предмет для освітлення","candle"),("certainty","noun","певність (ніуун): стан певності","certainty"),("completion","noun","завершення (немає): дія завершення","completion")]
    for src,pos,cand,rev in bad_form:
        passed,*_=gate(src,pos,cand,"en_wiktionary_matching_pos_uk_translation",rev,"exact Oxford definition fixture",0.9,0.9); assert not passed,(src,cand)
    passed,*_=gate("broadcaster","noun","трансляція","en_wiktionary_matching_pos_uk_translation","broadcast","a person whose job is presenting or talking on radio or television",0.9,0.9); assert not passed
    passed,*_=gate("briefly","adverb","короткий час","en_wiktionary_matching_pos_uk_translation","briefly","for a short time",0.9,0.9); assert not passed
    good=[("broadcaster","noun","телерадіоведучий","broadcaster","a person whose job is presenting or talking on radio or television"),("briefly","adverb","коротко","briefly","for a short time"),("brick","noun","цегла","brick","a rectangular block of baked clay used for building walls"),("boost","verb","підсилювати","boost","to make something increase or become better or more successful")]
    for src,pos,cand,rev,definition in good:
        passed,why,_=gate(src,pos,cand,"en_wiktionary_matching_pos_uk_translation",rev,definition,0.80,0.80); assert passed,(src,why)
    print("V4 lexical acceptance self-test passed: concise lexical form, entity/POS role and exact-source sense rules reject V3 failure classes.")


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--unaccounted",type=Path); parser.add_argument("--qa-dir",type=Path); parser.add_argument("--overrides",type=Path); parser.add_argument("--expected-tail",type=int); parser.add_argument("--round-id",default="round01"); parser.add_argument("--self-test",action="store_true"); args=parser.parse_args()
    if args.self_test: self_test(); return 0
    if not args.unaccounted or not args.qa_dir or args.expected_tail is None: parser.error("normal run requires --unaccounted --qa-dir --expected-tail")
    rows=base.read_tsv(args.unaccounted)
    if len(rows)!=args.expected_tail: raise RuntimeError(f"exact tail required {args.expected_tail}, got {len(rows)}")
    seen=set()
    for n,row in enumerate(rows,1):
        for field in ("entry_id","source","part_of_speech","level","source_index","source_url","definition_path"):
            if not row.get(field): raise RuntimeError(f"unaccounted row {n} blank {field}")
        if base.stable_id(row["source"],row["part_of_speech"],row["level"])!=row["entry_id"]: raise RuntimeError(f"stable ID mismatch row {n}")
        if row["entry_id"] in seen: raise RuntimeError(f"duplicate stable ID {row['entry_id']}")
        seen.add(row["entry_id"])
    round_token=re.sub(r"[^A-Za-z0-9_-]+","-",args.round_id).strip("-") or "round"; first_run_id=f"MANUAL_EMERGENCY_WORK_20260820_FIRST_PASS_V4_{round_token}"; second_run_id=f"MANUAL_EMERGENCY_WORK_20260820_SECOND_PASS_V4_{round_token}"
    overrides=base.load_overrides(args.overrides,seen); definitions=base.fetch_definitions(rows); wiki_pages=base.fetch_wiki(rows)
    mt=base.Marian(base.EN_UK_MODEL); surface_translations=mt.run([base.surface(row["source"]) for row in rows]); del mt
    options={}
    for row,surface_mt in zip(rows,surface_translations,strict=True): options[row["entry_id"]]=candidate_options(row,surface_mt,wiki_pages.get(base.surface(row["source"]).casefold(),""),overrides)
    flat_candidates=[]; flat_keys=[]; flat_definitions=[]
    for row in rows:
        eid=row["entry_id"]; definition=definitions[eid][0]
        for idx,item in enumerate(options[eid]): flat_candidates.append(item["text"]); flat_keys.append((eid,idx)); flat_definitions.append(definition)
    reverse_values=base.Marian(base.UK_EN_MODEL).run(flat_candidates); reverse={key:value for key,value in zip(flat_keys,reverse_values,strict=True)}; semantic=base.Semantic(); cand_scores=semantic.pair_scores(flat_definitions,flat_candidates); rev_scores=semantic.pair_scores(flat_definitions,reverse_values); del semantic; scores={key:(c,r) for key,c,r in zip(flat_keys,cand_scores,rev_scores,strict=True)}
    first_rows=[]; second_rows=[]; final_rows=[]; holds=[]
    for row in rows:
        eid=row["entry_id"]; definition,definition_error=definitions[eid]; evaluated=[]; history=[]
        for idx,item in enumerate(options[eid]):
            cand=item["text"]; method=item["method"]; rev=reverse[(eid,idx)]; cand_sim,rev_sim=scores[(eid,idx)]; passed,reason,lex=gate(row["source"],row["part_of_speech"],cand,method,rev,definition,cand_sim,rev_sim); priority=3 if method.startswith("explicit_work_developer_override:") else 2 if method=="en_wiktionary_matching_pos_uk_translation" else 1; evaluated.append((passed,priority,min(cand_sim,rev_sim),lex,cand,method,rev,reason,cand_sim,rev_sim)); history.append(f"{method}=>{cand!r};reverse={rev!r};lex={lex:.3f};candDef={cand_sim:.3f};revDef={rev_sim:.3f};decision={'PASS' if passed else 'BLOCKED'}:{reason}")
        evaluated.sort(key=lambda x:(x[0],x[1],x[2],x[3]),reverse=True); passed,_,_,lex,cand,method,rev,reason,cand_sim,rev_sim=evaluated[0]
        source_check=f"MANUAL_EMERGENCY_WORK V4 exact Oxford identity; source_index={row['source_index']}; definition_path={row['definition_path']}; stable_id=PASS; exact_definition={definition!r}; selected_candidate_method={method}; contextual_definition_candidate_forbidden_as_final=PASS"
        first_rows.append({"data_factory_run_id":first_run_id,"entry_id":eid,"source":row["source"],"part_of_speech":row["part_of_speech"],"level":row["level"].upper(),"official_source":row["source_url"],"source_check":source_check,"ukrainian_candidate":cand})
        if passed:
            qa_reason=f"PASS V4: concise lexical equivalent; method={method}; exact Oxford definition={definition!r}; candidate={cand!r}; reverse={rev!r}; lexical={lex:.3f}; candidate_definition_similarity={cand_sim:.3f}; reverse_definition_similarity={rev_sim:.3f}; lexical-form/POS/role/source-grounded checks PASS."; decision="PASS"; ukrainian=cand; final_rows.append({"entry_id":eid,"source":row["source"],"part_of_speech":row["part_of_speech"],"level":row["level"].upper(),"ukrainian":cand,"status":"verified","manual_emergency_first_pass_run_id":first_run_id,"manual_emergency_second_pass_run_id":second_run_id,"source_check":source_check,"qa_reason":qa_reason})
        else:
            qa_reason=f"BLOCKED V4: {definition_error or reason}; method={method}; exact Oxford definition={definition!r}; candidate={cand!r}; reverse={rev!r}; lexical={lex:.3f}; candidate_definition_similarity={cand_sim:.3f}; reverse_definition_similarity={rev_sim:.3f}."; decision="BLOCKED"; ukrainian=""; holds.append({"entry_id":eid,"source":row["source"],"part_of_speech":row["part_of_speech"],"level":row["level"].upper(),"official_source":row["source_url"],"definition_path":row["definition_path"],"exact_definition":definition,"selected_candidate":cand,"selected_candidate_method":method,"candidate_history":" || ".join(history),"reason":qa_reason})
        second_rows.append({"content_qa_run_id":second_run_id,"data_factory_run_id":first_run_id,"entry_id":eid,"source":row["source"],"part_of_speech":row["part_of_speech"],"level":row["level"].upper(),"decision":decision,"ukrainian":ukrainian,"qa_reason":qa_reason})
    qd=args.qa_dir; base.write_tsv(qd/"first-pass.tsv",first_rows,base.FIRST_FIELDS); base.write_tsv(qd/"second-pass.tsv",second_rows,base.SECOND_FIELDS); base.write_tsv(qd/"verified.tsv",final_rows,base.FINAL_FIELDS); base.write_tsv(qd/"holds.tsv",holds,base.HOLD_FIELDS); summary={"version":VERSION,"round_id":round_token,"total":len(rows),"pass":len(final_rows),"blocked":len(holds),"first_pass_run_id":first_run_id,"second_pass_run_id":second_run_id}; (qd/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); print(f"MANUAL_EMERGENCY_WORK V4 COMPLETE: total={len(rows)} PASS={len(final_rows)} BLOCKED={len(holds)}"); return 0

if __name__=="__main__": raise SystemExit(main())
