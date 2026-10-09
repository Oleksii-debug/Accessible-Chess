# Accessible Chess — Canonical Product Vision Amendment — 2026-09-04

Status: binding user-authorized amendment to `docs/CANONICAL_PRODUCT_VISION_UA.md`.

## 1. What this amendment changes

The earlier canonical vision contains the statement:

`ПЛАТФОРМА ПРОДУКТУ: WINDOWS. Окремі версії для інших платформ не входять до Product Vision.`

The user explicitly changed this direction on 2026-09-04.

That older platform restriction is superseded.

The binding end-state direction is now:
- Accessible Chess keeps a full Windows/NVDA desktop edition;
- Accessible Chess also gains a real accessible Web edition as a first-class final product surface;
- Windows and Web must use one canonical chess/domain/application truth rather than independent implementations;
- the Web product is not a streamed picture of a Windows desktop as the normal architecture;
- current Windows development must continue and should not be delayed by building the entire Web product now;
- current architecture must remain Web-ready so a later Web edition can reuse the existing chess/library/books/training logic instead of rewriting it.

## 2. What this amendment does not change

All existing product requirements remain binding unless explicitly superseded later by the user, including:
- accessibility-first design;
- Windows/NVDA standalone product;
- canonical chess core;
- PGN/GameTree;
- ACSDB/Library;
- ChessBase adapters where technically/legal feasible;
- accessible books;
- Teacher/Classroom;
- online lessons;
- visual board for sighted students;
- keyboard-first teacher control;
- student interaction, assignments, courses and progress;
- privacy and consent requirements.

The Web edition expands the product surface; it does not reduce the Windows product.

## 3. Development priority rule

Do not stop the current Windows/Version 2 format and release work to build the complete Web edition.

From this point forward, new functionality should obey these architecture rules:
1. chess/domain/application logic is platform-neutral;
2. Windows controls do not become the source of chess truth;
3. presentation state stays separate from chess state;
4. commands/results use stable serializable contracts where practical;
5. filesystem/local-process assumptions are isolated behind adapters;
6. user/workspace/session identity is explicit for future remote use;
7. long operations support progress, cancellation, restart/recovery and deterministic IDs;
8. the same feature should be callable later from a Web adapter without copying chess rules.

## 4. Binding technical companion

Detailed Web/server/commercial architecture is defined in:

`docs/WEB_PRODUCT_ARCHITECTURE.md`

`docs/TECHNICAL_ROADMAP.md` must treat this amendment as part of the canonical product truth.

## 5. Completion truth

A future Web edition must have its own acceptance gates. Windows/NVDA acceptance does not automatically prove Web accessibility, and a Web prototype does not replace Windows release requirements.
