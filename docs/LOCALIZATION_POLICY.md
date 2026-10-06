# Accessible Chess — Ukrainian + English Localization Policy

Status: binding product-completion rule.

## Product rule

Accessible Chess is a bilingual product. Ukrainian and English are mandatory user-interface languages.

A user-facing feature is not product-complete until both Ukrainian and English versions are implemented and tested.

This rule applies to existing functionality and every future feature, update, repair and redesign.

## Required bilingual surfaces

Both languages are required for all user-visible product text, including:

- Windows/WebView headings, labels, buttons, forms and dialogs;
- native Windows menus and accelerator descriptions;
- Board, Move Input, History, Analysis and Engine Play;
- Settings, Keyboard/Commands, recovery and validation;
- PGN, Library/ACSDB, import/export and search;
- Books, semantic navigation, warnings, bookmarks and return-to-reading flows;
- Training, hints, answer feedback, progress and recovery;
- Teacher/Classroom, lessons, assignments, chat, files, audio/video permissions and moderation;
- accessible announcements, live/status messages and concise error text;
- launcher/package diagnostics intended for end users;
- Web client user experience;
- account, authentication, subscription and commercial user journeys;
- Help and user documentation shipped with a release.

Internal developer logs, protocol tokens, stable action IDs, database keys and file-format syntax do not need translation unless they are intentionally exposed as user-facing text.

## Language ownership

Use the existing canonical language state and localization mechanisms. Do not create a second independent translation system.

The saved application language must drive all currently materialized presentation surfaces consistently.

Changing language must not:

- change chess state;
- lose Library/Book/Training state;
- corrupt settings;
- reset focus without reason;
- produce mixed Ukrainian/English UI;
- introduce raw developer/debug errors.

If a language change cannot be persisted or fully applied, fail safely and keep the previously active language.

## English completeness rule

English mode must not show Ukrainian fallback text merely because an error, recovery path or rarely used command was missed.

Generic failure paths, validation, recovery, empty states, progress messages and exceptional UI states are part of localization acceptance, not optional polish.

Ukrainian mode is held to the same completeness rule.

## Development gate

Every new or modified user-facing feature must include, in the same coherent workline:

1. Ukrainian text;
2. English text;
3. parity of localization keys/contracts;
4. keyboard/screen-reader compatible presentation in both languages;
5. tests that cover language switching or bilingual catalog completeness where applicable;
6. no known mixed-language fallback.

A PR that adds user-facing functionality without both languages is incomplete.

## Release gate

Before a candidate is described as product-complete, automated qualification must verify the bilingual contract on the current exact candidate.

Physical Windows/NVDA testing remains a separate human acceptance gate and must not be inferred from automated localization tests.
