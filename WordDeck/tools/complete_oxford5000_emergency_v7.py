#!/usr/bin/env python3
"""V7 same-sense Ukrainian lexical evidence gate for Oxford 5000 completion.

V7 preserves V6 Unicode/morphology/gender corrections but replaces page-wide
candidate evidence with a structurally parsed sense model. Automatic PASS needs
an actual Ukrainian semantic definition, a same-sense bilingual chain, and a
positive alignment to the exact Oxford definition. Structural headings and
cross-sense page-wide mappings fail closed.
"""
from __future__ import annotations

import re
import sys
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import requests

import complete_oxford5000_emergency as base
import complete_oxford5000_emergency_v4 as v4
import complete_oxford5000_emergency_v5 as v5
import complete_oxford5000_emergency_v6 as v6

VERSION = "V7"
UA_API = "https://uk.wiktionary.org/w/api.php"
UA_PAGE = "https://uk.wiktionary.org/wiki/"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "WordDeck-V7/1.0 same-sense lexical QA; https://github.com/Oleksii-debug/Accessible-Chess"})

_V6_GATE = v6.gate_v6
_ORIGINAL_OPTIONS = v6._original_candidate_options
_RELATION_WORDS = {
    "синоніми", "антоніми", "гіпероніми", "гіпоніми", "мероніми", "холоніми",
    "споріднені слова", "похідні слова", "етимологія", "фразеологізми",
    "усталені словосполучення", "термінологічні словосполучення", "переклад",
    "переклади", "приклади", "примітки", "джерела", "див. також", "категорії",
}
_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "with", "by",
    "that", "which", "who", "is", "are", "be", "being", "as", "from", "something",
    "someone", "somebody", "thing", "person", "state", "act", "process", "one", "used",
}


def _normalize_heading(text: str) -> str:
    value = v6.clean_wiki_text(text).strip().strip("=:-—– ")
    return re.sub(r"\s+", " ", value).casefold()


def _semantic_definition(raw: str) -> str:
    if not raw:
        return ""
    stripped = raw.strip()
    if re.fullmatch(r"=+.*=+", stripped):
        return ""
    if re.fullmatch(r"\{\{[^{}]+\}\}", stripped):
        return ""
    cleaned = v6.clean_wiki_text(stripped)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" #;:,.—–-\t")
    if not cleaned:
        return ""
    heading = _normalize_heading(stripped)
    if heading in _RELATION_WORDS or any(heading.startswith(word + " ") for word in _RELATION_WORDS):
        return ""
    if "====" in stripped or "===" in stripped:
        return ""
    if len(re.findall(r"[А-Яа-яІіЇїЄєҐґ]", cleaned)) < 4:
        return ""
    if cleaned in {"—", "–", "-", "…", "..."}:
        return ""
    return cleaned


def parse_ukrainian_senses(section: str) -> list[dict[str, object]]:
    """Parse only top-level numbered sense lines and keep mapping inside that sense block."""
    lines = section.splitlines()
    senses: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for line in lines:
        if re.match(r"^\s*=+[^=].*=+\s*$", line):
            current = None
            continue
        match = re.match(r"^#(?![#*:])\s*(.+?)\s*$", line)
        if match:
            definition = _semantic_definition(match.group(1))
            if not definition:
                current = None
                continue
            current = {
                "sense_index": len(senses) + 1,
                "definition": definition,
                "raw_block": line,
                "english_terms": [],
            }
            senses.append(current)
            continue
        if current is not None and re.match(r"^#[:*]", line):
            current["raw_block"] = str(current["raw_block"]) + "\n" + line
    for sense in senses:
        block = str(sense["raw_block"])
        terms = [v6.clean_term(x) for x in v6.EN_TERM_RE.findall(block)]
        terms += [v6.clean_term(x) for x in v6.EN_LINK_RE.findall(block)]
        sense["english_terms"] = sorted({x.casefold(): x for x in terms if x}.values(), key=str.casefold)
    return senses


@lru_cache(maxsize=8192)
def fetch_uk_wiktionary_v7(term: str) -> tuple[str, str]:
    lookup = v6.strip_stress(term).strip()
    if not lookup:
        return "", "blank candidate"
    params = {"action": "parse", "page": lookup, "prop": "wikitext", "format": "json", "formatversion": "2", "redirects": "1"}
    last = ""
    for attempt in range(6):
        try:
            response = SESSION.get(UA_API, params=params, timeout=30)
            if response.status_code == 429:
                retry = response.headers.get("Retry-After", "")
                try:
                    delay = float(retry)
                except ValueError:
                    delay = 1.5 * (2 ** attempt)
                if attempt + 1 < 6:
                    time.sleep(min(30.0, max(1.0, delay)))
                    continue
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                return "", f"uk.wiktionary error={payload['error'].get('code', 'unknown')}"
            time.sleep(0.08)
            return payload.get("parse", {}).get("wikitext", "") or "", ""
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            if attempt + 1 < 6:
                time.sleep(min(20.0, 1.25 * (2 ** attempt)))
    return "", last or "uk.wiktionary unavailable"


class SenseAligner:
    def __init__(self) -> None:
        self.mt = base.Marian(base.UK_EN_MODEL)
        self.sem = base.Semantic()

    @staticmethod
    def content_words(text: str) -> set[str]:
        return {w for w in re.findall(r"[a-z]+", text.casefold()) if len(w) >= 3 and w not in _STOPWORDS}

    def align(self, definitions: list[str], oxford: str) -> list[dict[str, object]]:
        if not definitions:
            return []
        translations = self.mt.run(definitions, batch=16)
        scores = self.sem.pair_scores(translations, [oxford] * len(translations))
        target_words = self.content_words(oxford)
        result: list[dict[str, object]] = []
        for definition, translated, score in zip(definitions, translations, scores, strict=True):
            overlap = len(self.content_words(translated) & target_words)
            result.append({
                "uk_definition": definition,
                "uk_definition_en": translated,
                "semantic_similarity": float(score),
                "content_overlap": overlap,
            })
        return result


_ALIGNER: SenseAligner | None = None


def _aligner() -> SenseAligner:
    global _ALIGNER
    if _ALIGNER is None:
        _ALIGNER = SenseAligner()
    return _ALIGNER


def select_same_sense(records: list[dict[str, object]], source: str, oxford_definition: str,
                      method: str, source_gloss: str) -> dict[str, object]:
    if not records or not oxford_definition:
        return {"ok": False, "reason": "no usable Ukrainian semantic sense or exact Oxford definition"}
    source_surface = base.surface(source).casefold()
    aligned = _aligner().align([str(r["definition"]) for r in records], oxford_definition)
    scored: list[dict[str, object]] = []
    for record, evidence in zip(records, aligned, strict=True):
        terms = [base.surface(str(x)).casefold() for x in record.get("english_terms", [])]
        local_exact = source_surface in terms
        score = float(evidence["semantic_similarity"])
        overlap = int(evidence["content_overlap"])
        semantic_ok = (local_exact and score >= 0.58) or (score >= 0.66 and overlap >= 1)
        scored.append({**record, **evidence, "same_sense_exact_english": local_exact, "semantic_ok": semantic_ok})
    viable = [r for r in scored if r["semantic_ok"]]
    if not viable:
        return {"ok": False, "reason": "no Ukrainian sense positively aligns to exact Oxford definition", "senses": scored}
    viable.sort(key=lambda r: (bool(r["same_sense_exact_english"]), float(r["semantic_similarity"]), int(r["content_overlap"])), reverse=True)
    best = viable[0]
    same_local = [r for r in viable if r["same_sense_exact_english"]]
    if len(same_local) > 1:
        return {"ok": False, "reason": "multiple Ukrainian senses carry the exact English mapping; sense remains ambiguous", "senses": scored}
    origin_bound = method == "en_wiktionary_sense_bound_uk_translation" and bool(source_gloss.strip())
    if best["same_sense_exact_english"]:
        mapping = "uk_wiktionary_same_sense_exact_english"
    elif origin_bound:
        if len(viable) > 1:
            second = viable[1]
            margin = float(best["semantic_similarity"]) - float(second["semantic_similarity"])
            if margin < 0.07:
                return {"ok": False, "reason": f"polysemous Ukrainian senses are not contrastively separated; margin={margin:.3f}", "senses": scored}
        mapping = "english_wiktionary_exact_sense_candidate_plus_unique_uk_semantic_sense"
    else:
        return {"ok": False, "reason": "same-sense bilingual mapping is not established", "senses": scored}
    return {"ok": True, "mapping": mapping, "selected": best, "senses": scored}


def candidate_lexical_evidence_v7(term: str, source: str, oxford_definition: str,
                                  method: str, source_gloss: str) -> dict[str, object]:
    lookup = v6.strip_stress(term).strip()
    page, error = fetch_uk_wiktionary_v7(lookup)
    section = v6.ukrainian_section(page)
    senses = parse_ukrainian_senses(section)
    if not section or not senses:
        return {
            "candidate_evidence_version": VERSION,
            "candidate_evidence_source": UA_PAGE + quote(lookup.replace(" ", "_")),
            "candidate_evidence_lookup": lookup,
            "candidate_evidence_ok": False,
            "candidate_evidence_error": error or "no actual Ukrainian semantic definition",
            "candidate_evidence_senses": senses,
            "candidate_evidence_policy": "same-sense structural Ukrainian definition + bilingual binding + Oxford alignment",
        }
    selected = select_same_sense(senses, source, oxford_definition, method, source_gloss)
    result: dict[str, object] = {
        "candidate_evidence_version": VERSION,
        "candidate_evidence_source": UA_PAGE + quote(lookup.replace(" ", "_")),
        "candidate_evidence_lookup": lookup,
        "candidate_evidence_error": error,
        "candidate_evidence_senses": selected.get("senses", senses),
        "candidate_evidence_ok": bool(selected.get("ok")),
        "candidate_evidence_policy": "same-sense structural Ukrainian definition + bilingual binding + Oxford alignment",
        "candidate_evidence_reason": selected.get("reason", ""),
    }
    if selected.get("ok"):
        best = dict(selected["selected"])
        result.update({
            "candidate_same_sense_mapping": selected["mapping"],
            "candidate_sense_index": best["sense_index"],
            "candidate_definition": best["definition"],
            "candidate_definition_en": best["uk_definition_en"],
            "candidate_definition_similarity": best["semantic_similarity"],
            "candidate_definition_overlap": best["content_overlap"],
            "candidate_same_sense_english_terms": best.get("english_terms", []),
        })
    return result


def candidate_options_v7(row, surface_mt, wiki_text, overrides, morphology):
    options = _ORIGINAL_OPTIONS(row, surface_mt, wiki_text, overrides, morphology)
    definition = v6._definition_cache.get(row["entry_id"], "")
    by_lexeme: dict[str, dict[str, object]] = {}
    for item in options:
        text = v6.strip_stress(item.get("text", "")).strip()
        item["text"] = text
        if not text:
            continue
        method = item.get("method", "")
        eligible = method == "en_wiktionary_sense_bound_uk_translation" or method.startswith("explicit_work_developer_override:")
        if eligible:
            key = text.casefold()
            evidence = by_lexeme.get(key)
            if evidence is None:
                evidence = candidate_lexical_evidence_v7(text, row["source"], definition, method, item.get("sense_gloss", ""))
                by_lexeme[key] = evidence
            item.update(evidence)
    for item in options:
        key = v6.strip_stress(item.get("text", "")).casefold()
        if key in by_lexeme and item.get("method", "").endswith("_surface_candidate"):
            item.update(by_lexeme[key])
    return options


def gate_v7(row, candidate, reverse, definition, cand_def_similarity, rev_def_similarity,
            gloss_similarity, confirmations, morphology):
    passed, reason, lex = _V6_GATE(row, candidate, reverse, definition, cand_def_similarity,
                                   rev_def_similarity, gloss_similarity, confirmations, morphology)
    if not passed:
        return False, reason, lex
    if candidate.get("candidate_evidence_version") != VERSION or not candidate.get("candidate_evidence_ok"):
        return False, "V7 requires actual same-sense Ukrainian semantic evidence", lex
    if not candidate.get("candidate_definition") or not candidate.get("candidate_same_sense_mapping"):
        return False, "V7 candidate evidence lacks selected Ukrainian sense definition/mapping", lex
    score = float(candidate.get("candidate_definition_similarity") or 0.0)
    overlap = int(candidate.get("candidate_definition_overlap") or 0)
    if score < 0.58 or (overlap < 1 and candidate.get("candidate_same_sense_mapping") != "uk_wiktionary_same_sense_exact_english"):
        return False, "V7 selected Ukrainian sense is not positively aligned to exact Oxford definition", lex
    return True, (
        "V7 PASS: exact Oxford sense -> sense-bound English bilingual candidate -> actual Ukrainian semantic sense -> "
        f"same-sense bilingual binding={candidate.get('candidate_same_sense_mapping')}; "
        f"uk_sense={candidate.get('candidate_sense_index')}; uk_definition={candidate.get('candidate_definition')!r}; "
        f"uk_definition_en={candidate.get('candidate_definition_en')!r}; similarity={score:.3f}; overlap={overlap}; {reason}"
    ), lex


def self_test() -> None:
    headings = "# ==== Мероніми ====\n# ===Усталені та термінологічні словосполучення===\n# —\n"
    assert parse_ukrainian_senses(headings) == [], "headings-only evidence must fail"
    mixed = "# перше реальне значення\n#: {{t|en|other}}\n# друге реальне значення\n#: {{t|en|literary}}\n"
    senses = parse_ukrainian_senses(mixed)
    assert len(senses) == 2
    assert senses[0]["english_terms"] == ["other"]
    assert senses[1]["english_terms"] == ["literary"], "page-wide mapping must not cross senses"
    assert v6.strip_stress("й ї літерату́рний") == "й ї літературний"
    morphology = v6.UkrainianMorphologyV6()
    ok, _ = morphology.validate("чарівна", "adjective")
    assert not ok, "accent/canonical morphology regression"
    row = {"source": "literary", "part_of_speech": "adjective"}
    confirmations = {"книжковий": [{"gloss": "connected with literature", "score": 0.9, "overlap": 2}]}
    bad = {"text": "книжковий", "method": "en_wiktionary_sense_bound_uk_translation", "sense_gloss": "connected with literature", "candidate_evidence_ok": False, "candidate_evidence_version": VERSION}
    passed, _, _ = gate_v7(row, bad, "literary", "connected with literature", 0.8, 0.8, 0.9, confirmations, morphology)
    assert not passed, "literary->книжковий must fail without same-sense candidate evidence"
    miner = {"text": "мінер", "method": "en_wiktionary_sense_bound_uk_translation", "sense_gloss": "one who lays mines", "candidate_evidence_ok": False, "candidate_evidence_version": VERSION}
    passed, _, _ = gate_v7({"source": "miner", "part_of_speech": "noun"}, miner, "miner", "a person who works in a mine", 0.8, 0.8, 0.9, {"мінер": [{"gloss": "one who lays mines", "score": 0.9, "overlap": 1}]}, morphology)
    assert not passed, "miner explosives sense must not pass mine-worker Oxford sense"
    print("V7 self-test passed: headings fail, mappings stay sense-local, Unicode morphology preserved, literary/miner regressions fail closed.")


def install() -> None:
    v6.install()
    v5.UkrainianMorphology = v6.UkrainianMorphologyV6
    v5.candidate_options = candidate_options_v7
    v5.gate = gate_v7
    v5.VERSION = VERSION


def relabel_outputs() -> None:
    if "--qa-dir" not in sys.argv:
        return
    qadir = Path(sys.argv[sys.argv.index("--qa-dir") + 1])
    for name in ("first-pass.tsv", "second-pass.tsv", "verified.tsv", "holds.tsv", "summary.json"):
        path = qadir / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        text = text.replace("_V5_", "_V7_").replace("PASS V5", "PASS V7").replace("BLOCKED V5", "BLOCKED V7")
        text = text.replace(" V5 exact Oxford identity", " V7 exact Oxford identity")
        text = text.replace('"version": "V5"', '"version": "V7"')
        path.write_text(text, encoding="utf-8")


def main() -> int:
    install()
    result = v5.main()
    relabel_outputs()
    return result


if __name__ == "__main__":
    install()
    if "--self-test" in sys.argv:
        self_test()
        raise SystemExit(0)
    raise SystemExit(main())
