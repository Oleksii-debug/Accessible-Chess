#!/usr/bin/env python3
"""Contrastive sense-binding hardening for WordDeck V5.

This wrapper keeps the V5 reviewer but replaces its sense-confirmation policy:
a labelled bilingual translation block is eligible only when its own English
sense/gloss is the uniquely best supported Wiktionary sense for the exact
Oxford definition. A shared topical word (for example `mine`) cannot establish
sense identity. Near-tied senses fail closed.
"""
from __future__ import annotations

import sys

import complete_oxford5000_emergency_v5 as v5

MIN_SENSE_SIMILARITY = 0.64
MIN_CONTRASTIVE_MARGIN = 0.08


def strict_build_wiki_confirmation(options, gloss_scores, definition):
    rows = []
    for idx, item in enumerate(options):
        if item.get("method") != "en_wiktionary_sense_bound_uk_translation":
            continue
        gloss = (item.get("sense_gloss") or "").strip()
        if not gloss:
            continue
        score = float(gloss_scores.get(idx, 0.0))
        overlap = v5.lexical_overlap(gloss, definition)
        rows.append((idx, item, gloss, score, overlap))
    if not rows:
        return {}

    # Rank distinct labelled senses, not candidate spellings. If several
    # Ukrainian translations occur in one translation block they share one
    # sense and can all remain candidates.
    best_by_gloss = {}
    for idx, item, gloss, score, overlap in rows:
        key = gloss.casefold()
        prior = best_by_gloss.get(key)
        if prior is None or score > prior[0]:
            best_by_gloss[key] = (score, overlap, gloss)
    ranked = sorted(best_by_gloss.values(), key=lambda x: x[0], reverse=True)
    best_score, best_overlap, best_gloss = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else None

    # Structural binding is mandatory, but it is not enough. Require a strong
    # semantic relation to the exact Oxford definition and lexical anchoring.
    if best_score < MIN_SENSE_SIMILARITY or best_overlap < 1:
        return {}
    if second_score is not None and best_score - second_score < MIN_CONTRASTIVE_MARGIN:
        return {}

    confirmed = {}
    for _idx, item, gloss, score, overlap in rows:
        if gloss.casefold() != best_gloss.casefold():
            continue
        if score < MIN_SENSE_SIMILARITY or overlap < 1:
            continue
        confirmed.setdefault(item["text"].casefold(), []).append({
            "gloss": gloss,
            "score": score,
            "overlap": overlap,
            "source": item.get("sense_source", "English Wiktionary"),
            "contrastive_margin": None if second_score is None else best_score - second_score,
            "policy": "uniquely best labelled sense aligned to exact Oxford definition",
        })
    return confirmed


def strict_self_test() -> None:
    definition = "a person who works in a mine taking out coal, gold, diamonds, etc."
    options = [
        {"text":"шахтар","method":"en_wiktionary_sense_bound_uk_translation","sense_gloss":"a person who works in a mine extracting coal, gold or diamonds","sense_source":"English Wiktionary"},
        {"text":"мінер","method":"en_wiktionary_sense_bound_uk_translation","sense_gloss":"a person who places explosive mines","sense_source":"English Wiktionary"},
    ]
    confirmed = strict_build_wiki_confirmation(options, {0:0.89,1:0.70}, definition)
    assert "шахтар" in confirmed
    assert "мінер" not in confirmed

    # A near tie is ambiguous even when both senses mention the same topical
    # word; neither is automatically certified.
    ambiguous = strict_build_wiki_confirmation(options, {0:0.79,1:0.75}, definition)
    assert not ambiguous

    # A single labelled sense still needs both strong semantic alignment and
    # lexical anchoring; a numerical similarity alone is not accepted.
    no_anchor = [{"text":"приклад","method":"en_wiktionary_sense_bound_uk_translation","sense_gloss":"a completely unrelated description","sense_source":"English Wiktionary"}]
    assert not strict_build_wiki_confirmation(no_anchor, {0:0.90}, definition)
    print("V5 contrastive sense-binding self-test passed: wrong/near-tied senses fail closed and miner mine-worker sense remains separable from explosive-miner sense.")


def main() -> int:
    v5.build_wiki_confirmation = strict_build_wiki_confirmation
    if "--self-test" in sys.argv:
        v5.self_test()
        strict_self_test()
        return 0
    return v5.main()


if __name__ == "__main__":
    raise SystemExit(main())
