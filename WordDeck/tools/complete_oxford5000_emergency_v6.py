#!/usr/bin/env python3
"""V6 candidate-specific lexical evidence and Unicode-safe Oxford5000 reviewer."""
from __future__ import annotations

import re
import sys
import time
import unicodedata
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import requests

import complete_oxford5000_emergency as base
import complete_oxford5000_emergency_v4 as v4
import complete_oxford5000_emergency_v5 as v5
import complete_oxford5000_emergency_v5_strict as strict

VERSION = "V6"
UA_API = "https://uk.wiktionary.org/w/api.php"
UA_PAGE = "https://uk.wiktionary.org/wiki/"
EN_TERM_RE = re.compile(r"\{\{(?:t\+?|t-check|tt\+?|переклад)\|en\|([^|}\n]+)", re.I)
EN_LINK_RE = re.compile(r"(?:англ\.|English)\s*:?\s*\[\[([^]|#]+)", re.I)
DEF_LINE_RE = re.compile(r"^#(?![:*])\s*(.+)$", re.M)
FEMALE_SOURCE_RE = re.compile(r"\b(?:woman|women|female|girl|wife|mother|sister|daughter|actress|waitress|businesswoman|policewoman)\b", re.I)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "WordDeck-V6/1.0 lexical QA; https://github.com/Oleksii-debug/Accessible-Chess"})

_original_fetch_definitions = base.fetch_definitions
_original_candidate_options = v5.candidate_options
_original_gate = v5.gate
_definition_cache: dict[str, str] = {}


def strip_stress(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text or "")
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", stripped)


def analysis_tokens(text: str) -> list[str]:
    normalized = strip_stress(unicodedata.normalize("NFKC", text or ""))
    return re.findall(r"[А-Яа-яІіЇїЄєҐґ'-]+", normalized)


def clean_term(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).strip(" ;:,.")


def clean_wiki_text(value: str) -> str:
    value = re.sub(r"\{\{[^{}]*\}\}", " ", value or "")
    value = re.sub(r"\[\[([^]|]+)\|([^]]+)\]\]", r"\2", value)
    value = re.sub(r"\[\[([^]]+)\]\]", r"\1", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"'{2,}", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" ;:,-")


def fetch_definitions_record(rows):
    result = _original_fetch_definitions(rows)
    _definition_cache.clear()
    for row in rows:
        _definition_cache[row["entry_id"]] = result.get(row["entry_id"], ("", ""))[0]
    return result


@lru_cache(maxsize=4096)
def fetch_uk_wiktionary(term: str) -> tuple[str, str]:
    lookup = strip_stress(term).strip()
    if not lookup:
        return "", "blank candidate"
    params = {"action": "parse", "page": lookup, "prop": "wikitext", "format": "json", "formatversion": "2", "redirects": "1"}
    last_error = ""
    for attempt in range(4):
        try:
            response = SESSION.get(UA_API, params=params, timeout=25)
            if response.status_code == 429:
                time.sleep(min(8, 1 + attempt * 2))
                continue
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                return "", f"uk.wiktionary error={payload['error'].get('code', 'unknown')}"
            return payload.get("parse", {}).get("wikitext", "") or "", ""
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(min(6, 1 + attempt))
    return "", last_error or "uk.wiktionary unavailable"


def ukrainian_section(page: str) -> str:
    if not page:
        return ""
    patterns = [
        re.compile(r"^==\s*Українська\s*==\s*$", re.M | re.I),
        re.compile(r"^==\s*\{\{(?:мова|lang)\|uk[^}]*\}\}\s*==\s*$", re.M | re.I),
        re.compile(r"^==\s*\{\{uk\}\}\s*==\s*$", re.M | re.I),
    ]
    for pattern in patterns:
        match = pattern.search(page)
        if not match:
            continue
        tail = page[match.end():]
        nxt = re.search(r"^==[^=].*?==\s*$", tail, re.M)
        return tail[:nxt.start()] if nxt else tail
    return page


def candidate_lexical_evidence(term: str, source: str) -> dict[str, object]:
    lookup = strip_stress(term).strip()
    page, error = fetch_uk_wiktionary(lookup)
    section = ukrainian_section(page)
    definitions = [clean_wiki_text(x) for x in DEF_LINE_RE.findall(section)]
    definitions = [x for x in definitions if x][:8]
    english_terms = [clean_term(x) for x in EN_TERM_RE.findall(section)]
    english_terms += [clean_term(x) for x in EN_LINK_RE.findall(section)]
    english_terms = sorted({x.casefold(): x for x in english_terms if x}.values(), key=str.casefold)
    source_surface = base.surface(source).casefold()
    exact_english = any(base.surface(x).casefold() == source_surface for x in english_terms)
    return {
        "candidate_evidence_source": UA_PAGE + quote(lookup.replace(" ", "_")),
        "candidate_evidence_lookup": lookup,
        "candidate_evidence_definitions": definitions,
        "candidate_evidence_english_terms": english_terms,
        "candidate_evidence_exact_english": exact_english,
        "candidate_evidence_error": error,
        "candidate_evidence_ok": bool(section and definitions and exact_english),
        "candidate_evidence_policy": "candidate Ukrainian lexical page + own definition + exact English lexical mapping",
    }


class UkrainianMorphologyV6(v5.UkrainianMorphology):
    def canonicalize(self, candidate: str, pos: str) -> tuple[str, str]:
        value = unicodedata.normalize("NFKC", candidate or "").strip()
        analysis = strip_stress(value)
        words = analysis_tokens(analysis)
        if len(words) != 1:
            return analysis, "V6 genuine multiword value retained; stress marks removed before tokenization"
        parses = self.morph.parse(words[0])
        expected = self._expected(pos)
        matching = [p for p in parses if not expected or str(p.tag.POS) in expected]
        if not matching:
            return analysis, f"V6 no Ukrainian morphology parse matching requested POS for {words[0]!r}"
        best = matching[0]
        normal = strip_stress(str(best.normal_form or words[0])).strip()
        return normal or analysis, f"V6 Unicode/stress-normalized dictionary lemma {value!r}->{normal!r}; tag={best.tag}; score={best.score:.4f}"

    def validate(self, candidate: str, pos: str) -> tuple[bool, str]:
        value = unicodedata.normalize("NFKC", candidate or "").strip()
        analysis = strip_stress(value)
        words = analysis_tokens(analysis)
        if not words:
            return False, "V6 no Ukrainian lexical token after Unicode/stress normalization"
        if len(words) > 1:
            ok, why = v4.lexical_form_ok(analysis, pos)
            return ok, "V6 genuine multiword lexical phrase; Unicode-normalized V4 lexical/POS form accepted" if ok else why
        token = words[0]
        parses = self.morph.parse(token)
        expected = self._expected(pos)
        matches = [p for p in parses if not expected or str(p.tag.POS) in expected]
        if not matches:
            return False, f"V6 pymorphy3 uk has no requested-POS parse for {token!r}"
        canonical = [p for p in matches if strip_stress(str(p.normal_form or "")).casefold() == token.casefold()]
        if not canonical:
            normals = sorted({strip_stress(str(p.normal_form)) for p in matches if p.normal_form})
            return False, f"V6 not canonical Ukrainian lemma after stress normalization; normal forms={normals[:6]}"
        best = canonical[0]
        tag = best.tag
        kind = pos.casefold()
        if kind == "adjective":
            if str(tag.POS) != "ADJF":
                return False, f"V6 adjective is not ADJF: {tag}"
            if getattr(tag, "gender", None) not in {None, "masc"} or getattr(tag, "case", None) not in {None, "nomn"} or getattr(tag, "number", None) not in {None, "sing"}:
                return False, f"V6 adjective is not canonical nominative masculine singular: {tag}"
        if kind == "noun" and getattr(tag, "case", None) not in {None, "nomn"}:
            return False, f"V6 noun is not nominative lemma form: {tag}"
        if kind in {"verb", "modal verb"}:
            if str(tag.POS) not in {"INFN", "VERB"} or not re.search(r"(?:ти|тися|ться)$", token.casefold()):
                return False, f"V6 verb is not learner-facing infinitive: {token!r}; tag={tag}"
        return True, f"V6 pymorphy3 uk canonical lemma PASS after Unicode/stress normalization; tag={tag}; score={best.score:.4f}"


def feminine_only_person_noun(candidate: str, morphology: UkrainianMorphologyV6) -> tuple[bool, str]:
    tokens = analysis_tokens(candidate)
    if len(tokens) != 1:
        return False, ""
    parses = [p for p in morphology.morph.parse(tokens[0]) if str(p.tag.POS) == "NOUN"]
    if not parses:
        return False, ""
    genders = {getattr(p.tag, "gender", None) for p in parses}
    return genders == {"femn"}, f"V6 noun gender parses={sorted(str(x) for x in genders)}"


def candidate_options_v6(row, surface_mt, wiki_text, overrides, morphology):
    options = _original_candidate_options(row, surface_mt, wiki_text, overrides, morphology)
    by_lexeme: dict[str, dict[str, object]] = {}
    for item in options:
        text = strip_stress(item.get("text", "")).strip()
        item["text"] = text
        if not text:
            continue
        key = text.casefold()
        if item.get("method") == "en_wiktionary_sense_bound_uk_translation":
            evidence = by_lexeme.get(key)
            if evidence is None:
                evidence = candidate_lexical_evidence(text, row["source"])
                by_lexeme[key] = evidence
            item.update(evidence)
    for item in options:
        key = strip_stress(item.get("text", "")).casefold()
        if key in by_lexeme and item.get("method", "").endswith("_surface_candidate"):
            item.update(by_lexeme[key])
    return options


def gate_v6(row, candidate, reverse, definition, cand_def_similarity, rev_def_similarity, gloss_similarity, confirmations, morphology):
    passed, reason, lex = _original_gate(row, candidate, reverse, definition, cand_def_similarity, rev_def_similarity, gloss_similarity, confirmations, morphology)
    if not passed:
        return False, reason, lex
    method = candidate.get("method", "")
    if method.startswith("explicit_work_developer_override:"):
        detail = method.split(":", 1)[1]
        if "candidate_evidence=" not in detail:
            return False, "V6 reviewed override lacks candidate_evidence= field", lex
    elif not candidate.get("candidate_evidence_ok"):
        return False, "V6 candidate-specific Ukrainian lexical evidence missing/ambiguous or lacks exact English lexical mapping", lex
    if row["part_of_speech"].casefold() == "noun" and v4.definition_role(definition) == "person" and not FEMALE_SOURCE_RE.search(f"{row['source']} {definition}"):
        feminine, note = feminine_only_person_noun(candidate.get("text", ""), morphology)
        if feminine:
            return False, f"V6 neutral English person headword rejects feminine-only Ukrainian noun without female-specific evidence; {note}", lex
    return True, (
        "V6 PASS: V5 strict source-sense evidence + candidate-specific Ukrainian lexical evidence + Unicode/stress-safe canonical morphology + neutral-person gender policy; "
        f"candidate_source={candidate.get('candidate_evidence_source','')!r}; candidate_definitions={candidate.get('candidate_evidence_definitions',[])!r}; "
        f"candidate_english_terms={candidate.get('candidate_evidence_english_terms',[])!r}; {reason}"
    ), lex


def self_test() -> None:
    morphology = UkrainianMorphologyV6()
    for accented, pos in [("акціоне́рка", "noun"), ("чемпіона́т", "noun"), ("цивіліза́ція", "noun")]:
        tokens = analysis_tokens(accented)
        assert len(tokens) == 1, (accented, tokens)
        canonical, note = morphology.canonicalize(accented, pos)
        assert len(analysis_tokens(canonical)) == 1
        assert "multiword" not in note.casefold(), (accented, note)
    ok, why = morphology.validate("чарівна", "adjective")
    assert not ok, why
    row = {"source": "literary", "part_of_speech": "adjective"}
    confirmations = {"книжковий": [{"gloss": "connected with literature", "score": 0.9, "overlap": 2}]}
    bad = {"text": "книжковий", "method": "en_wiktionary_sense_bound_uk_translation", "sense_gloss": "connected with literature", "candidate_evidence_ok": False}
    passed, _, _ = gate_v6(row, bad, "literary", "connected with literature", 0.8, 0.8, 0.9, confirmations, morphology)
    assert not passed, "literary->книжковий must fail without candidate-side lexical evidence"
    good = {"text": "літературний", "method": "en_wiktionary_sense_bound_uk_translation", "sense_gloss": "connected with literature", "candidate_evidence_ok": True, "candidate_evidence_source": "fixture://literaturnyi", "candidate_evidence_definitions": ["пов'язаний з літературою"], "candidate_evidence_english_terms": ["literary"]}
    confirmations = {"літературний": [{"gloss": "connected with literature", "score": 0.9, "overlap": 2}]}
    passed, why, _ = gate_v6(row, good, "literary", "connected with literature", 0.8, 0.8, 0.9, confirmations, morphology)
    assert passed, why
    shareholder = {"source": "shareholder", "part_of_speech": "noun"}
    female = {"text": "акціонерка", "method": "en_wiktionary_sense_bound_uk_translation", "sense_gloss": "a person who owns shares", "candidate_evidence_ok": True, "candidate_evidence_source": "fixture://aktsionerka", "candidate_evidence_definitions": ["жінка-акціонер"], "candidate_evidence_english_terms": ["shareholder"]}
    confirmations = {"акціонерка": [{"gloss": "a person who owns shares", "score": 0.9, "overlap": 2}]}
    passed, _, _ = gate_v6(shareholder, female, "shareholder", "a person who owns shares in a company", 0.8, 0.8, 0.9, confirmations, morphology)
    assert not passed, "neutral shareholder must reject feminine-only акціонерка"
    strict.self_test()
    print("V6 self-test passed: candidate-side lexical evidence, Unicode stress morphology, gender policy and V5 strict sense binding are fail-closed.")


def install() -> None:
    base.fetch_definitions = fetch_definitions_record
    v5.UkrainianMorphology = UkrainianMorphologyV6
    v5.candidate_options = candidate_options_v6
    v5.build_wiki_confirmation = strict.strict_build_wiki_confirmation
    v5.gate = gate_v6
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
        text = text.replace("_V5_", "_V6_").replace("PASS V5", "PASS V6").replace("BLOCKED V5", "BLOCKED V6").replace(" V5 exact Oxford identity", " V6 exact Oxford identity")
        text = text.replace('"version": "V5"', '"version": "V6"')
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
