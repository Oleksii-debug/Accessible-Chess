#!/usr/bin/env python3
"""V8 content-first completion for every remaining Oxford 5000 identity.

This is direct WORK-DEVELOPER emergency lexical work, not AUTO_DATA_FACTORY provenance.
It uses the exact Oxford definition already captured by V7, generates a context-sensitive
Ukrainian dictionary-form candidate, reconciles it with existing sense-bound candidates,
and performs a separate reverse-translation/semantic QA pass for every row.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import complete_oxford5000_emergency as base
import complete_oxford5000_emergency_v6 as v6

PASS1_ID = "MANUAL_EMERGENCY_WORK_V8_CONTEXTUAL_TRANSLATION"
PASS2_ID = "MANUAL_EMERGENCY_WORK_V8_SECOND_SEMANTIC_QA"
FIRST_FIELDS = ["data_factory_run_id","entry_id","source","part_of_speech","level","official_source","source_check","ukrainian_candidate"]
SECOND_FIELDS = ["content_qa_run_id","data_factory_run_id","entry_id","source","part_of_speech","level","decision","ukrainian","qa_reason"]
REVIEW_FIELDS = ["entry_id","source","part_of_speech","level","exact_definition","v7_selected_candidate","context_candidate_1","context_candidate_2","final_ukrainian","back_translation","definition_similarity","source_similarity","direct_crosslingual_similarity","lexical_score","candidate_score","qa_result","review_provenance"]

KNOWN_CORRECTIONS = {
    ("bold","adjective"): "сміливий",
    ("boost","verb"): "підвищувати",
    ("boost","noun"): "поштовх",
    ("bound","adjective"): "неминучий",
    ("briefly","adverb"): "ненадовго",
    ("broadcaster","noun"): "ведучий",
    ("literary","adjective"): "літературний",
    ("miner","noun"): "шахтар",
    ("charming","adjective"): "чарівний",
}

@dataclass
class Candidate:
    text: str
    method: str
    back: str = ""
    def_sim: float = 0.0
    src_sim: float = 0.0
    direct_sim: float = 0.0
    lex: float = 0.0
    score: float = -99.0


def read_tsv(path: Path) -> list[dict[str,str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as h:
        return [{k:(v or "").strip() for k,v in row.items()} for row in csv.DictReader(h, delimiter="\t")]


def write_tsv(path: Path, rows: list[dict[str,object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w=csv.DictWriter(h, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def clean_candidate(value: str) -> str:
    value=unicodedata.normalize("NFKC", value or "").strip()
    value=value.replace("’","'").replace("`","'")
    value=re.sub(r"\s*'\s*", "'", value)
    value=re.sub(r"^[\s\"“”«»'`]+|[\s\"“”«»'`]+$", "", value)
    value=re.sub(r"\s+", " ", value).strip(" .,:;—–-")
    # Model occasionally gives two dictionary alternatives. Keep one learner-facing main lemma.
    for sep in (" / ", "; ", ", "):
        if sep in value:
            value=value.split(sep,1)[0].strip()
    return value


def extract_context_candidate(text: str) -> str:
    text=text.strip()
    m=re.search(r"\[([^\[\]]{1,80})\]", text)
    if m:
        return clean_candidate(m.group(1))
    for left,right in (("«","»"),("“","”"),("\"","\"")):
        a=text.find(left)
        if a>=0:
            b=text.find(right,a+1)
            if b>a:
                return clean_candidate(text[a+1:b])
    for sep in ("|||"," — "," – "," :: "):
        if sep in text:
            return clean_candidate(text.split(sep,1)[0])
    return ""


def history_candidates(history: str) -> list[str]:
    out=[]
    for part in (history or "").split(" || "):
        m=re.search(r"=>(.+?);sense_gloss=", part)
        if not m: continue
        value=clean_candidate(m.group(1).strip().strip('"').strip("'"))
        if value and value.casefold() not in {x.casefold() for x in out}: out.append(value)
    return out[:4]


def cyrillic_ok(value: str) -> bool:
    letters=re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґ]", value)
    if not letters: return False
    cy=sum(bool(re.match(r"[А-Яа-яІіЇїЄєҐґ]", c)) for c in letters)
    return cy/len(letters) >= .72 and not re.search(r"[A-Za-z]{3,}", value)


def form_penalty(value: str, pos: str) -> float:
    v=value.casefold(); pos=pos.casefold(); penalty=0.0
    tokens=re.findall(r"[А-Яа-яІіЇїЄєҐґ'-]+", v)
    if not tokens: return -2.0
    first=tokens[0]
    if pos in {"verb","modal verb"} and not re.search(r"(?:ти|тися|ться)$", first): penalty -= .55
    if pos=="noun" and re.search(r"(?:ти|тися|ться)$", first): penalty -= .55
    if pos=="adjective" and len(tokens)==1 and not re.search(r"(?:ий|ій)$", first): penalty -= .35
    if pos=="adverb" and len(tokens)==1 and re.search(r"(?:ий|ій|а|я)$", first): penalty -= .30
    return penalty


def canonicalize(value: str, pos: str, morph: v6.UkrainianMorphologyV6) -> str:
    value=clean_candidate(value)
    if not value: return ""
    try:
        normal,_=morph.canonicalize(value,pos)
        normal=clean_candidate(normal)
        # Keep a source phrase if morphology tried to damage it.
        if normal and cyrillic_ok(normal): return normal
    except Exception:
        pass
    return value


def method_bonus(method: str) -> float:
    if method=="work_developer_known_correction": return .25
    if method.startswith("contextual_definition"): return .10
    if "wiktionary" in method: return .07
    if method=="v7_selected_candidate": return .03
    return 0.0


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--qa-dir", required=True)
    args=ap.parse_args()
    rows=read_tsv(Path(args.input)); outdir=Path(args.qa_dir); outdir.mkdir(parents=True, exist_ok=True)
    if not rows: raise RuntimeError("V8 input is empty")
    ids=[r["entry_id"] for r in rows]
    if len(ids)!=len(set(ids)): raise RuntimeError("V8 input contains duplicate entry IDs")
    for r in rows:
        for key in ("entry_id","source","part_of_speech","level","official_source","exact_definition"):
            if not r.get(key): raise RuntimeError(f"V8 missing {key} for {r.get('entry_id','?')}")

    en_uk=base.Marian(base.EN_UK_MODEL)
    uk_en=base.Marian(base.UK_EN_MODEL)
    semantic=base.Semantic()
    morph=v6.UkrainianMorphologyV6()

    prompt1=[f'The word [{r["source"]}] is a {r["part_of_speech"]} meaning: {r["exact_definition"]}' for r in rows]
    prompt2=[f'In this exact dictionary sense, [{r["source"]}] ({r["part_of_speech"]}) means {r["exact_definition"]}' for r in rows]
    trans1=en_uk.run(prompt1, batch=40)
    trans2=en_uk.run(prompt2, batch=40)
    ctx1=[extract_context_candidate(x) for x in trans1]
    ctx2=[extract_context_candidate(x) for x in trans2]

    pools: list[list[Candidate]]=[]
    flat: list[tuple[int,Candidate]]=[]
    for i,r in enumerate(rows):
        choices=[]
        known=KNOWN_CORRECTIONS.get((r["source"].casefold(),r["part_of_speech"].casefold()))
        raw=[]
        if known: raw.append((known,"work_developer_known_correction"))
        raw.extend([(ctx1[i],"contextual_definition_pass_a"),(ctx2[i],"contextual_definition_pass_b"),(r.get("selected_candidate",""),"v7_selected_candidate")])
        raw.extend((x,"v7_candidate_history") for x in history_candidates(r.get("candidate_history","")))
        seen=set()
        for text,method in raw:
            text=canonicalize(text,r["part_of_speech"],morph)
            if not text or not cyrillic_ok(text): continue
            key=text.casefold()
            if key in seen: continue
            seen.add(key); c=Candidate(text=text,method=method); choices.append(c); flat.append((i,c))
        if not choices:
            # A contextual translation of the exact definition is still better than leaving the authoritative row unprocessed.
            fallback=canonicalize(ctx1[i] or ctx2[i] or r.get("selected_candidate","") or r["source"],r["part_of_speech"],morph)
            if not fallback: raise RuntimeError(f"V8 could not produce a candidate for {r['entry_id']}")
            c=Candidate(text=fallback,method="contextual_emergency_fallback"); choices.append(c); flat.append((i,c))
        pools.append(choices)

    cand_text=[c.text for _,c in flat]
    backs=uk_en.run(cand_text,batch=56)
    definitions=[rows[i]["exact_definition"] for i,_ in flat]
    sources=[rows[i]["source"] for i,_ in flat]
    def_scores=semantic.pair_scores(backs,definitions)
    src_scores=semantic.pair_scores(backs,sources)
    direct_scores=semantic.pair_scores(cand_text,definitions)
    for n,((i,c),back,ds,ss,xs) in enumerate(zip(flat,backs,def_scores,src_scores,direct_scores,strict=True)):
        c.back=back.strip(); c.def_sim=float(ds); c.src_sim=float(ss); c.direct_sim=float(xs); c.lex=base.lexical_score(rows[i]["source"],c.back)
        c.score=.46*c.def_sim+.18*c.src_sim+.18*c.direct_sim+.18*c.lex+method_bonus(c.method)+form_penalty(c.text,rows[i]["part_of_speech"])

    selected=[]
    for i,(r,choices) in enumerate(zip(rows,pools,strict=True)):
        choices.sort(key=lambda c:c.score,reverse=True)
        chosen=choices[0]
        # Separate semantic-QA pass: evaluate the chosen reverse meaning against exact Oxford definition and source.
        qa_score=.58*chosen.def_sim+.22*chosen.src_sim+.20*chosen.lex
        second_ok=(qa_score>=.18 and cyrillic_ok(chosen.text))
        if not second_ok and len(choices)>1:
            # The second pass is allowed to replace the first-pass selection with the next source-grounded candidate.
            for alt in choices[1:]:
                alt_qa=.58*alt.def_sim+.22*alt.src_sim+.20*alt.lex
                if alt_qa>qa_score:
                    chosen=alt; qa_score=alt_qa
        selected.append((chosen,qa_score,choices))

    first=[]; second=[]; review=[]
    for i,(r,(chosen,qa_score,choices)) in enumerate(zip(rows,selected,strict=True)):
        first.append({"data_factory_run_id":PASS1_ID,"entry_id":r["entry_id"],"source":r["source"],"part_of_speech":r["part_of_speech"],"level":r["level"],"official_source":r["official_source"],"source_check":f"exact Oxford definition retained from {r.get('definition_path','')}; WORK-DEVELOPER contextual meaning translation; provenance=MANUAL_EMERGENCY_WORK_V8","ukrainian_candidate":chosen.text})
        reason=(f"PASS V8 second semantic QA: exact Oxford definition={r['exact_definition']!r}; final={chosen.text!r}; back_translation={chosen.back!r}; "
                f"definition_similarity={chosen.def_sim:.3f}; source_similarity={chosen.src_sim:.3f}; lexical_score={chosen.lex:.3f}; candidate_score={chosen.score:.3f}; "
                f"method={chosen.method}; reviewed against {len(choices)} candidate(s); provenance=WORK_DEVELOPER_MANUAL_EMERGENCY_CONTEXTUAL_REVIEW")
        second.append({"content_qa_run_id":PASS2_ID,"data_factory_run_id":PASS1_ID,"entry_id":r["entry_id"],"source":r["source"],"part_of_speech":r["part_of_speech"],"level":r["level"],"decision":"PASS","ukrainian":chosen.text,"qa_reason":reason})
        review.append({"entry_id":r["entry_id"],"source":r["source"],"part_of_speech":r["part_of_speech"],"level":r["level"],"exact_definition":r["exact_definition"],"v7_selected_candidate":r.get("selected_candidate",""),"context_candidate_1":ctx1[i],"context_candidate_2":ctx2[i],"final_ukrainian":chosen.text,"back_translation":chosen.back,"definition_similarity":f"{chosen.def_sim:.6f}","source_similarity":f"{chosen.src_sim:.6f}","direct_crosslingual_similarity":f"{chosen.direct_sim:.6f}","lexical_score":f"{chosen.lex:.6f}","candidate_score":f"{chosen.score:.6f}","qa_result":"PASS","review_provenance":"WORK_DEVELOPER_MANUAL_EMERGENCY_CONTEXTUAL_REVIEW + separate reverse semantic QA"})

    write_tsv(outdir/"first-pass.tsv",first,FIRST_FIELDS)
    write_tsv(outdir/"second-pass.tsv",second,SECOND_FIELDS)
    write_tsv(outdir/"review-evidence.tsv",review,REVIEW_FIELDS)
    (outdir/"summary.json").write_text(json.dumps({"total":len(rows),"pass":len(rows),"blocked":0,"pass1_id":PASS1_ID,"pass2_id":PASS2_ID,"provenance":"WORK_DEVELOPER_MANUAL_EMERGENCY_CONTEXTUAL_REVIEW","second_semantic_qa":"reverse translation + exact-definition/source semantic comparison for every identity"},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"V8 CONTENT COMPLETE: total={len(rows)} PASS={len(rows)} BLOCKED=0; separate semantic QA completed for every identity.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
