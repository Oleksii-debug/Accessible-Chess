# WordDeck reuse-first architecture audit — 2026-08-18

Purpose: avoid custom implementations when a mature, maintained, legally usable component already solves the problem. This is an engineering decision record, not a shipped-dependency list. A candidate is not added to the runtime until the feature that needs it is implemented and the exact package/version/license is verified.

## Current architecture baseline

WordDeck remains a self-contained Windows .NET 8 WinForms application. Runtime logic stays deterministic/offline by default. `Microsoft.Data.Sqlite 8.0.29` remains the only current NuGet runtime dependency and is already justified for large SentencePack storage/query. British pronunciation generation remains a development/build-time Kokoro/Misaki pipeline; shipped runtime only plays MP3. Tatoeba corpus ingestion remains development/build-time and preserves provenance/license/attribution.

The emergency delivery priority remains: full verified Oxford 5000 data, British audio for every included entry, independent Recall study scopes `All Oxford 5000`, `A1`, `A2`, `B1`, `B2`, `C1`, and a truthful/rebindable hotkey/help system. The research below must accelerate that work, not block it.

## Decision 1 — automated Windows accessibility/UI testing: adopt FlaUI for tests

Upstream: https://github.com/FlaUI/FlaUI
License: MIT.
Role: development/test dependency only, not required by the shipped WordDeck executable.

FlaUI is specifically a .NET wrapper around Microsoft UI Automation for Win32, WinForms, WPF and related Windows applications. It can launch/attach to WordDeck, inspect accessible names/roles, focus controls, invoke controls and exercise keyboard-driven workflows. This is the strongest reuse candidate for closing the gap between unit/self-tests and real NVDA acceptance testing.

Integration plan: create a separate WordDeck UI/accessibility test project after the emergency Oxford scope vertical slice is stable. Prefer UIA2 as the first WinForms automation backend because FlaUI itself documents that UIA3 can expose WinForms-specific bugs that are absent in UIA2; add selected UIA3 coverage later. Tests should verify startup focus, Tab order, scope selector, current-card field, translation reveal, Spelling answer field, F1 help, shortcut-settings accessibility, scope/deck switching and persistence across restart. Real NVDA testing still remains required; FlaUI is regression coverage, not a claim of NVDA certification.

Decision: APPROVED FOR DEVELOPMENT TESTING. Do not add to production runtime.

## Decision 2 — installer, portable packages and updates: adopt Velopack for release engineering

Upstream: https://github.com/velopack/velopack
License: MIT.
Role: release/packaging dependency, not vocabulary/training logic.

Velopack already provides installer creation, portable packages, updates and delta packages for C# desktop applications. Writing our own updater/installer would waste time and create security/rollback problems.

Integration plan: keep the current self-contained ZIP beta path while Oxford 5000 is changing quickly. Once the first stable release candidate exists, prototype Velopack around the already-published WordDeck output. AudioPack should remain separable/optional where practical so application updates do not repeatedly redownload the entire audio library. The updater must never overwrite user state under LocalAppData.

Decision: APPROVED FOR RELEASE ENGINEERING AFTER THE EMERGENCY BETA.

## Decision 3 — EPUB Reading Mode: use VersOne.Epub, do not write an EPUB parser

Upstream: https://github.com/vers-one/EpubReader
NuGet: `VersOne.Epub`
License: public-domain dedication / Unlicense text in upstream repository.
Role: future Reading Mode importer.

The library supports EPUB 2 and EPUB 3 through 3.3 and exposes book text/content on modern .NET. It is a direct fit for importing user-owned EPUB books. WordDeck-specific code should only normalize extracted text, split chapters/sentences, index vocabulary and map tokens to WordDeck stable entry IDs.

Decision: APPROVED CANDIDATE FOR READING MODE WHEN THAT MODULE IS authorized. Do not create a custom EPUB parser.

## Decision 4 — PDF Reading Mode: use PdfPig for text PDFs, no OCR by default

Upstream: https://github.com/UglyToad/PdfPig
NuGet: `PdfPig`
License: Apache-2.0.
Role: future Reading Mode importer for text-based PDFs.

PdfPig already extracts text/words and includes document layout / reading-order tools. This is preferable to implementing PDF parsing. Its public API is still pre-1.0, so the integration must be isolated behind a WordDeck importer interface. Scanned/image-only PDFs are a separate OCR problem and should not be pulled into WordDeck merely to support PDFs.

Decision: APPROVED CANDIDATE FOR TEXT-PDF IMPORT. Keep OCR optional/separate.

## Decision 5 — HTML/article import: use AngleSharp

Upstream: https://github.com/AngleSharp/AngleSharp
NuGet: `AngleSharp`
License: MIT.
Role: future Reading Mode HTML cleanup/parser.

AngleSharp provides a standards-oriented HTML5 DOM and querySelector/querySelectorAll on modern .NET including net8.0. It is a much better base than regular expressions or a home-grown HTML parser.

Decision: APPROVED CANDIDATE FOR HTML IMPORT/CLEANUP.

## Decision 6 — deterministic Grammar/Story template rendering: use Scriban when the module is approved

Upstream: https://github.com/scriban/scriban
NuGet: `Scriban`
License: BSD 2-Clause style upstream license.
Role: future deterministic grammar exercise/story template renderer.

Scriban is a fast, lightweight .NET templating/scripting engine with a controllable sandbox and net8 support. It can replace a large amount of fragile string-concatenation/template parsing code for deterministic exercise generation. WordDeck should keep grammatical rules, lexical slots, difficulty constraints and validation in its own data/model; Scriban should only render controlled templates.

Decision: APPROVED CANDIDATE FOR FUTURE GRAMMAR/STORY TEMPLATE RENDERING. Do not implement Grammar/Story until user approval.

## Decision 7 — Markdown: Markdig only if Reading/help import needs Markdown

Upstream: https://github.com/xoofx/markdig
NuGet: `Markdig`
Role: future Markdown ingestion/rendering.

Markdig is CommonMark-compliant, fast, extensible and heavily tested. It solves Markdown parsing if WordDeck later imports Markdown notes/books. Current F1/help is plain accessible text and does not need Markdig.

Decision: APPROVED CONDITIONAL CANDIDATE; no dependency now.

## Decision 8 — lexical relations / word families: use Open English WordNet as an attributed data layer

Upstream: https://github.com/globalwordnet/english-wordnet
Official data releases: https://en-word.net/
License: CC BY 4.0.
Role: future Word Families / synonyms / antonyms / hypernyms / sense-aware lexical relations.

Open English WordNet provides synsets and lexical relations and releases current data in LMF, JSON, RDF and WNDB forms. It is a better foundation than inventing a synonym/antonym/word-family graph. WordDeck must keep Oxford identity/CEFR/sense rows as the learning authority; WordNet is supplementary metadata and cannot silently overwrite Oxford senses/translations.

Integration plan: when Word Families is approved, build a development-time importer from the official release into a compact WordDeck SQLite companion database, retain required CC BY attribution, and link only high-confidence matches by lemma/POS/sense. Ambiguous matches remain unresolved instead of being guessed.

Decision: APPROVED FUTURE DATA SOURCE WITH ATTRIBUTION.

## Decision 9 — advanced NLP/lemmatization at build time: spaCy is a strong development tool, not a shipped dependency

Upstream: https://github.com/explosion/spaCy
License: MIT for spaCy core; every downloaded model/data package must be checked separately.
Role: development-time corpus QA, POS/lemma/dependency experiments, sentence-gap diagnosis and grammar pattern analysis.

spaCy supports tokenization, tagging, parsing and trained pipelines for many languages. It can save substantial development time for diagnostics. WordDeck should not require Python/spaCy on the user's Windows machine. Any result that affects shipped deterministic data must be serialized into validated WordDeck data and covered by tests/provenance.

Decision: APPROVED FOR DEVELOPMENT-TIME ANALYSIS ONLY, subject to model-license checks.

## Decision 10 — Grammar diagnostics: keep LanguageTool optional, do not make it core

Upstream: https://github.com/languagetool-org/languagetool
License: LGPL 2.1 or later for the core.
Role: possible future optional local grammar/error-diagnostic engine.

LanguageTool detects grammar/style errors beyond basic spelling and can run as a local HTTP server, but it is a large Java project; upstream documents Java/Maven requirements and a large source/build footprint. Bundling a Java runtime and LanguageTool into the core WordDeck app would increase installation size and maintenance significantly.

Use case if later justified: an optional provider behind `IGrammarDiagnosticProvider`, with deterministic WordDeck grammar exercises remaining usable without it. Never make Grammar Mode depend on a network service.

Decision: EVALUATE LATER AS OPTIONAL PROVIDER; DO NOT BUNDLE NOW.

## Decision 11 — sentence realization: use official SimpleNLG only as a reference/build-time candidate; do not adopt the stale C# port as core

Official upstream: https://github.com/simplenlg/simplenlg
Official license: MPL 2.0.
C# port reviewed: https://github.com/nickhodge/SharpSimpleNLG

The C# port explicitly states that it is behind the current original SimpleNLG project and documents incomplete/future work plus some failing tests. That makes it a poor foundation for a new core dependency. The Java original can still be useful as a reference or development-time experiment.

Decision: DO NOT ADOPT SharpSimpleNLG as core. Prefer corpus-first Sentence Coach plus controlled templates; revisit official SimpleNLG only for development-time generation if measured gaps justify it.

## Decision 12 — spelling suggestions: WeCantSpell.Hunspell is technically capable but not needed for answer acceptance

Upstream: https://github.com/aarondandy/WeCantSpell.Hunspell
Role: possible future typo suggestions only.

The library is a managed .NET Hunspell port that checks words and suggests corrections, but upstream explicitly describes its MPL/LGPL/GPL tri-license as complicated. More importantly, WordDeck Spelling must accept the exact target/explicit accepted variants rather than treating any dictionary word as correct.

Decision: DO NOT ADD TO CORE MATCHING. If later used, it may only produce explanatory typo suggestions after a wrong answer and requires a separate license/dictionary audit.

## Decision 13 — audio playback: keep current Windows playback until a real problem appears; do not replace working code with NAudio now

Upstream: https://github.com/naudio/NAudio
License: MIT.

NAudio is a mature .NET audio library, but current NAudio 3 targets net9.0 while WordDeck currently targets net8.0. The current small Windows MP3 playback layer has already worked in a real user beta. Replacing it now adds dependency and regression risk with no measured benefit.

Decision: REJECT FOR CURRENT RUNTIME. Reconsider a compatible NAudio line only if we need device selection, volume control, robust playback events, overlapping audio, recording or Dictation recording.

## Decision 14 — spaced repetition / FSRS: use official implementations/specification as the reference, not an unverified C# port

Authoritative ecosystem index: https://github.com/open-spaced-repetition/awesome-fsrs

The current curated FSRS implementation list contains maintained implementations for several languages, but no official/established C# implementation was identified in this audit. Replacing the current conservative WordDeck scheduler with a random C# port would not satisfy reuse-first.

Decision: keep the current explainable scheduler for now. When FSRS becomes a release priority, either use a maintained official implementation through a clean boundary or implement only the minimal C# port necessary, with parity fixtures generated by an official FSRS implementation. Never invent scheduling math from memory.

## Decision 15 — full-text search: do not add Lucene.Net yet

Upstream reviewed: https://github.com/apache/lucenenet

Lucene.Net is mature and powerful, but WordDeck already has SQLite in the shipped dependency graph. For our current corpus sizes and exact target/sentence lookup, indexed SQLite is sufficient. If future Reading Mode needs full-text search, evaluate SQLite FTS5 first. Adding Lucene now would duplicate storage/index infrastructure.

Decision: REJECT FOR NOW; prefer existing SQLite.

## Decision 16 — learner grammar corpora: use Universal Dependencies only as research/QA unless text redistribution is clearly licensed

Upstream EWT: https://github.com/UniversalDependencies/UD_English-EWT
Upstream ESL/TLE: https://github.com/UniversalDependencies/UD_English-ESL

UD English EWT provides a gold-standard dependency treebank, but its underlying texts have mixed source copyrights. UD English ESL/TLE is particularly interesting for learner-error research because each sentence has original/error-corrected annotation, but the repository deliberately omits the sentence text because the FCE text requires a separate license.

Decision: useful for development-time grammar structure/error-taxonomy research, not a source to bundle blindly into WordDeck. Do not redistribute restricted learner text.

## Decision 17 — optional local AI provider: do not add an SDK while raw Ollama HTTP remains trivial

Reviewed candidate: https://github.com/awaescher/OllamaSharp

OllamaSharp could reduce boilerplate if WordDeck later needs streaming, embeddings, tools or richer model APIs. The current planned optional local provider needs only a small `/api/chat` boundary and WordDeck already requires provider interchangeability. Adding a dependency now gives little benefit.

Decision: keep a tiny `ILlmProvider` / HTTP adapter when AI features are approved; reconsider OllamaSharp only if the provider surface becomes nontrivial.

## Architecture consequence

WordDeck should be a small core with replaceable adapters, not a monolith that embeds every researched library. Recommended boundaries are: `IDictionaryRepository`, `IStudyScopeStore`, `ISpellingScheduler`, `ISentenceCorpus`, `IAudioPlayer`, `ITextImporter`, `IGrammarDiagnosticProvider`, and `ILlmProvider`. The core owns stable IDs, deck/scope state, exact evaluation rules, persistence, accessibility behavior and deterministic training policy. Third-party components stay behind the narrow interface that needs them.

For the current emergency Oxford milestone, no new large runtime dependency is needed. The fastest route remains existing .NET/WinForms + SQLite + existing Kokoro build pipeline, while the new study-scope state model is WordDeck-specific business logic. FlaUI is the one newly approved dependency that directly reduces testing work without changing runtime behavior.

## Upstream source-archive policy

Do not commit entire upstream repositories or large source ZIPs into the WordDeck source branch merely because they were reviewed. That creates duplicated history, bloats clones/CI and makes license/update tracking worse. Prefer pinned NuGet packages for .NET runtime/test dependencies and official versioned data archives for datasets. Maintain this decision record and a source manifest. If an upstream project must be patched/vendorized later, preserve its complete license/notice and record the exact upstream revision.

A local research bundle may contain source snapshots/links for review, but it is not a shipped WordDeck package.

## Priority order after this audit

1. Finish Oxford 5000 data + independent All/A1/A2/B1/B2/C1 Recall scopes + British audio.
2. Add shared human-readable shortcut formatter and truth tests for F1/settings/runtime bindings.
3. Add FlaUI-based keyboard/UI Automation regression tests around the stable emergency beta.
4. Keep SQLite/Tatoeba Sentence Coach moving without adding Lucene or new NLP runtime dependencies.
5. After release candidate, add Velopack packaging/update prototype.
6. Only when user explicitly authorizes future modules: Reading Mode uses VersOne.Epub + PdfPig + AngleSharp; Grammar/Story may use Scriban; lexical relations use attributed Open English WordNet; optional build-time NLP may use spaCy; LanguageTool remains optional.
