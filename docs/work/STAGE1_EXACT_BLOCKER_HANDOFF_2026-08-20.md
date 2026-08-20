# Stage 1 exact blocker handoff — 2026-08-20

Evidence cutoff: `2026-08-20T08:47:44Z`.

## Release-line control state

- Product/integration SHA: `e8cd992d306975955784118364ce950963133d7e`.
- QA SHA: `07971835cb8fc294996165e577913ed350ae9f0e`.
- Strict Windows run/job: `32220453450` / `95969810864`.
- Issue #14 and Issue #22 are open. Their latest live comments leave Windows
  release execution and harness ownership with QA; they do not transfer a
  product-source repair to Work.
- Candidate ZIP: `NO`. The old human-rejected ZIP remains forbidden.
- `NVDA_VERIFIED=NO`.

## What the strict run proved

The run built and started the exact packaged product, rejected startup error
surfaces, and traversed the cross-process WebView2 accessibility topology. Its
retained evidence reported:

- a real `ControlType.Document` named `Accessible Chess`;
- complete traversal from 11 roots, including five provider-bearing roots and
  24 provider transitions;
- one unique original connected Move Edit with runtime ID
  `42.393300.4.5.1.3`, classified `A`, `proven_original=true`, and
  `strict_valid=true`;
- legal `e4` changed the canonical FEN, cleared the input, restored focus, and
  appeared on the accessible move/history surface;
- invalid `e9` preserved both the text and the canonical FEN.

The run then stopped at the native editing check. After setting the clipboard
to `__sentinel__`, focusing the original Move Edit and sending Ctrl+A/Ctrl+C,
the clipboard still contained `__sentinel__`. The helper raised at line 156:

`Ctrl+A/Ctrl+C failed: '__sentinel__'`

The 64-square board-focus, packaged sound/Stockfish lifecycle, source-leak,
manifest/checksum, ZIP inspection and artifact publication gates were not
reached. No `packaged-uia-strict-summary.json` was retained because the helper
failed before writing it.

## Classification and ownership

The Move Edit exposure question is no longer inconclusive: the exact original
Edit is present and usable for `e4`/`e9`. The remaining clipboard failure is
`BLOCKED / NO PRODUCT ATTRIBUTION YET`. The retained evidence does not show the
focused runtime ID immediately before and after each chord, selection state, a
clipboard-change signal, or whether WebView2 received both chords. It therefore
cannot honestly distinguish a product/native-editing defect from a QA input or
clipboard-observation defect.

`CURRENT_OWNER=QA` for the next strict/focused Windows evidence pass. Work must
not patch `tools/qa/` or the strict workflow merely to make the chain green.
The next QA evidence must retain focus identity, selection state when exposed,
individual Ctrl+A and Ctrl+C delivery, clipboard readback, and the unchanged
Move Edit value, then classify the result as PRODUCT, QA_HARNESS or INFRA.

## Separate completion-line Stage 1 product evidence

Unweakened Work pytest also exposes a deterministic keymap/Help defect:

- `web/keybindings.json` declares `board.rank_1..8` and `board.file_1..8`;
- `web/index.html` correctly asks the central bridge to resolve board chords
  and dispatches the returned `actionId`;
- `acs.keybindings.DEFAULT_ACTIONS`, the runtime authority when
  `centralKeymap=true`, contains none of those 16 action IDs;
- `ActionRegistry().resolve_binding(BOARD, "1")` therefore returns `None`;
- `renderHelp()` does not include live rank/file bindings.

The stale HTML-literal regression was converted into a central-dispatch
behavior contract without weakening it. The remaining two failures now report
the actual PRODUCT gaps: central runtime exposure and Help discoverability.
Because the live Issue #14 state does not authorize a Stage 1 product-source
change, Work records but does not repair these release-facing files.

## Next exact actions

1. QA completes the focused clipboard attribution above and, if it is
   QA_HARNESS/INFRA, repairs only the QA-owned lane and resumes the one strict
   chain.
2. If Issue #14 transfers a PRODUCT repair to Work, add the 16 rank/file
   actions to the central Action Registry, generate Help from those live
   bindings, run the unweakened suite, and return the exact product SHA to QA.
3. Until either gate changes, Work continues only isolated shared-core,
   specification, parser, corruption/recovery and data-hardening work. Nothing
   from the completion branch is activated in the Stage 1 release lineage.
