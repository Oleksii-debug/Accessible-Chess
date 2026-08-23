# DEV-A finish-risk matrix — 2026-08-23

This is a **220-point finish-risk/check matrix**, not a claim that 220 Product defects are already proven. `OPEN` means DEV-A must prove/fix or close with evidence; `E2E` means individually implemented pieces still need one integrated user flow; `OTHER` means currently owned by another live lane and must not be duplicated; `GREEN` means strong existing evidence exists but regression remains in the matrix.

Live-start routing used for this matrix:
- Stage1 privacy / Stockfish runtime path diagnostics: `OTHER` (active DEV3 QA + DEV4/DEV5/DEV-C release ownership).
- Engine / ACSDB performance: `OTHER` (DEV3/DEV-B).
- PGN/ChessBase import security/publication: `OTHER` except canonical GameTree/PGN semantic interfaces (DEV4/DEV-B boundary).
- Integration/release branches: `OTHER` (DEV-C/DEV5).
- DEV-A active frontier: canonical core + UI/accessibility + GameTree/PGN semantics + Teacher/Classroom/TeachingSession integration.

## 1. Move input / native edit semantics
001. [GREEN] Move input remains a real editable control rather than a proxy/clone.
002. [OPEN] Standard Ctrl+A must remain native in every full-product text editor, not only Stage1 Move input.
003. [OPEN] Standard Ctrl+C must remain native in every full-product text editor.
004. [OPEN] Standard Ctrl+X/Ctrl+V must not be intercepted by global key routing.
005. [OPEN] Undo/redo inside text controls must not accidentally invoke chess undo/redo.
006. [OPEN] Invalid move text must remain available for correction where the UX contract requires it.
007. [GREEN] Valid move commits exactly once to canonical chess state.
008. [OPEN] Double Enter / button+Enter races must not double-commit a move.
009. [OPEN] IME/composition events must not trigger premature move dispatch.
010. [OPEN] Move-entry focus restoration must survive route/dialog transitions.
011. [OPEN] User-facing move errors must never expose parser tracebacks/provider internals.

## 2. Board 64-square semantics / focus
012. [GREEN] Exactly 64 logical squares use canonical square identities.
013. [OPEN] Every square remains keyboard reachable after full-product shell composition.
014. [OPEN] Board orientation must change visual ordering without changing canonical square identity.
015. [OPEN] Rank/file jump actions must resolve through the central action registry.
016. [OPEN] Boundary movement must never wrap from a-file to h-file or rank 1 to rank 8.
017. [OPEN] Review-position board focus must not silently jump to live-position focus.
018. [OPEN] Opening a book/database position must establish an explicit board focus target.
019. [OPEN] Returning from a temporary analysis PV must restore the exact prior board focus.
020. [OPEN] Teacher pointer focus must remain distinct from selected chess square.
021. [OPEN] Student hover must not steal keyboard focus from the blind teacher.
022. [OPEN] Board accessible names must stay correct after language/orientation changes.

## 3. Action registry / menu / keymap
023. [GREEN] Stage1 rank/file actions exist in the central registry.
024. [OPEN] Every full-product action exposed by UI must exist in one central registry.
025. [OPEN] No WebView-only second action registry may drift from Python definitions.
026. [OPEN] TeachingSession lifecycle actions need canonical action IDs instead of ad-hoc callbacks.
027. [OPEN] Student selection and student move actions must remain separate action IDs.
028. [OPEN] Teacher pointer and normal move entry must never share action identity.
029. [OPEN] Key rebinding conflicts must be detected across full-product contexts.
030. [OPEN] Help must render the live rebound shortcut rather than a stale literal.
031. [OPEN] Native menu and keyboard action must delegate the same canonical command.
032. [OPEN] Disabled actions must expose disabled state consistently to keyboard/NVDA and visual UI.
033. [OPEN] Unknown action IDs from WebView must fail closed without echoing internal IDs.

## 4. Accessibility semantics / error projection
034. [OPEN] Every route needs one stable heading/focus entry contract.
035. [OPEN] Every dialog must restore opener focus on close/cancel/error.
036. [OPEN] Rerender must not move focus unless an explicit focus target is supplied.
037. [OPEN] Background state refresh must not create polite/assertive live-region spam.
038. [OPEN] Errors must be concise, localized and free of local paths.
039. [OPEN] Errors must not speak raw UCI/provider/transport internals.
040. [OPEN] Status blocks must not duplicate the same announcement through two ARIA channels.
041. [OPEN] Visual selection and accessible selected state must be atomically derived.
042. [OPEN] Hidden private fields must not remain reachable in the accessibility tree.
043. [OPEN] UA/EN language changes must not alter stable action/domain identity.
044. [OPEN] High-contrast/system-color rendering must not erase selection/highlight meaning.

## 5. Canonical chess state / atomicity
045. [GREEN] One canonical Board/Position legality source exists.
046. [OPEN] Every new full-product feature must consume canonical Position rather than copy FEN logic.
047. [OPEN] Invalid full-product commands must leave Position unchanged.
048. [OPEN] Presentation failure after a valid move must not roll back/duplicate the canonical move unpredictably.
049. [OPEN] Save/persistence failure must not partially mutate in-memory chess state.
050. [OPEN] Stale async callbacks must not commit a move against a newer position.
051. [OPEN] Student move acceptance must require explicit MOVE_ALLOWED policy.
052. [OPEN] Teacher annotations must never mutate side-to-move/castling/en-passant counters.
053. [OPEN] Book/PGN/database open flows must use explicit replace/new-document policy.
054. [OPEN] Full-product state snapshots must reject bool-as-int and lossy scalar coercions.
055. [OPEN] Canonical mutation boundaries must remain exception-atomic under callbacks.

## 6. History / review / undo / redo
056. [GREEN] Long-history and repeated undo/redo have strong existing regression evidence.
057. [OPEN] Full-product shell must expose review navigation without creating a second cursor.
058. [OPEN] Undo from engine game must restore clock/session state according to one policy.
059. [OPEN] Alternate move after undo must create/preserve variation rather than silently truncate evidence.
060. [OPEN] Review analysis target must not mutate live history cursor.
061. [OPEN] Returning from review must restore exact live node and focus.
062. [OPEN] Direct jump to nonexistent node must be fully atomic.
063. [OPEN] Deleted/promoted variation must not leave stale UI selection IDs.
064. [OPEN] History snapshots restored from persistence must preserve branch identity.
065. [OPEN] Teacher lesson temporary navigation must not become game-history mutation.
066. [OPEN] Student-game review must distinguish live lesson board from historical game board.

## 7. FEN / Position Editor
067. [GREEN] Canonical FEN validation and en-passant provenance have dedicated tests.
068. [OPEN] Full-product FEN fields must remain standard editable controls.
069. [OPEN] Invalid FEN must preserve the user text where correction UX requires it.
070. [OPEN] Position Editor must never partially apply a multi-field invalid state.
071. [OPEN] Editor side-to-move/castling/en-passant controls must serialize through canonical validation.
072. [OPEN] Training/composition positions need explicit relaxed-vs-game legality policy.
073. [OPEN] Opening a teaching FEN must not expose source provenance as local path text.
074. [OPEN] FEN load during active engine analysis needs explicit analysis invalidation/retarget behavior.
075. [OPEN] FEN load during active TeachingSession must be disallowed unless canonical session command permits it.
076. [OPEN] Editor reset/clear must have explicit history semantics.
077. [OPEN] FEN copy must copy canonical text, not hidden UI/debug state.

## 8. GameTree navigation / editing
078. [GREEN] Canonical navigation/editing/insertion/snapshot modules have broad DEV2 evidence.
079. [OPEN] UI selection must use stable GameTree node identity across rerenders.
080. [OPEN] Promote-variation UI must restore focus to the promoted line.
081. [OPEN] Delete-variation UI must choose a deterministic surviving focus target.
082. [OPEN] Editing a comment must preserve comment style/provenance rules.
083. [OPEN] NAG editing must reject invalid numeric/symbolic values without tree mutation.
084. [OPEN] Nested RAV navigation needs explicit parent-return semantics in UI.
085. [OPEN] Deep-tree accessible navigation must remain bounded and cancellable.
086. [OPEN] Inserting analysis PV must preserve existing mainline/variation according to canonical policy.
087. [OPEN] GameTree export must fail closed on corrupted/unreachable/cyclic structures.
088. [OPEN] Multiple open games/documents must not share a mutable GameTree cursor.

## 9. PGN semantic correctness / round trip
089. [GREEN] Missing termination-marker recovery now carries explicit loss evidence.
090. [OPEN] UI must visibly distinguish warning/recovered PGN from full-fidelity import.
091. [OPEN] Semicolon comments must round-trip without unwanted normalization.
092. [OPEN] Brace comments and nested RAV must preserve ordering.
093. [OPEN] Multi-game import must isolate one corrupt game from later valid games.
094. [OPEN] Result header/movetext result disagreement needs deterministic user-visible handling.
095. [OPEN] SetUp/FEN PGN must open the exact canonical initial position.
096. [OPEN] Duplicate tags must never be silently overwritten without evidence.
097. [OPEN] Export selected variation must not accidentally export unrelated siblings.
098. [OTHER] PGN filesystem publication/no-clobber/path security remains DEV4/DEV-B ownership.
099. [OPEN] Accessible PGN editor must preserve unsupported/lossy evidence explicitly.

## 10. Full-product shell / routing
100. [GREEN] DEV1 shell/WebView adapters have exact-green isolated evidence.
101. [OPEN] Route transitions must keep domain services alive without duplicating their state.
102. [OPEN] Route back/forward semantics need deterministic focus restoration.
103. [OPEN] Dialog-open route changes must not strand focus in a hidden route.
104. [OPEN] Full-product route snapshot must not include secrets/FEN unless that route explicitly requires it.
105. [OPEN] Backend dispatcher return values must be allowlisted before browser projection.
106. [OPEN] A failed route action must not switch route before error projection.
107. [OPEN] Shell language switch must rerender labels without resetting domain state.
108. [OPEN] Shell route IDs must remain stable across persistence/restart if stored.
109. [OPEN] New Teacher/Classroom routes need the same keyboard/focus contract as existing routes.
110. [OPEN] End-to-end shell composition still needs one authoritative full-product tree.

## 11. Library / Search presentation boundary
111. [GREEN] DEV1 Library UI and DEV3 Unicode-aware Search have isolated green evidence.
112. [OTHER] Query-plan/large-data search performance remains DEV3/DEV-B ownership.
113. [OPEN] Search result focus must survive paging when the selected game remains visible.
114. [OPEN] Empty-result state needs one concise accessible message without live-region spam.
115. [OPEN] Filter edits must preserve native selection/copy/edit shortcuts.
116. [OPEN] Search cancellation must not publish stale result pages after a newer query.
117. [OPEN] Opening selected game must use stable game identity rather than row index.
118. [OPEN] Deleted/missing source between search and open must fail closed.
119. [OPEN] Unicode-normalized search display must preserve original human-readable metadata.
120. [OPEN] Library import warning counts must be reachable without exposing parser internals.
121. [OPEN] Search/open/Stockfish vertical still needs exact-tree integrated validation.

## 12. Books / semantic reader
122. [GREEN] DEV1 Books WebView package has exact-green isolated evidence.
123. [GREEN] Canonical BookDocument/BookReader have substantial backend evidence.
124. [OPEN] Book browser view and canonical BookReader cursor need exact stable identity integration.
125. [OPEN] Return-from-board must restore exact semantic block and keyboard focus.
126. [OPEN] Return-from-analysis must restore exact semantic block and analysis context isolation.
127. [OPEN] Book diagram position must come from canonical validated FEN only.
128. [OPEN] Book variation navigation must preserve mainline return point.
129. [OPEN] Warnings/source anchors must be accessible without leaking local source paths.
130. [OPEN] Book bookmark persistence must reject stale document revision.
131. [OPEN] Deleted/changed book content must fail closed on stale bookmark restore.
132. [OPEN] Large semantic books need bounded navigation/index memory behavior.

## 13. Training / exercises
133. [GREEN] Canonical ExerciseSession and DEV1 Training WebView have isolated evidence.
134. [OPEN] Training presenter must not leak accepted solution before explicit reveal.
135. [OPEN] Incorrect answer must remain editable while canonical progress remains unchanged.
136. [OPEN] Accepted move answer must use canonical chess legality/session state.
137. [OPEN] Reset must require explicit action and never silently erase progress.
138. [OPEN] Retry/hint/reveal ordering needs deterministic persisted progress semantics.
139. [OPEN] Book-derived exercise must retain source provenance without path leakage.
140. [OPEN] Teacher-created exercise needs one versioned canonical format, not a second trainer model.
141. [OPEN] Training completion must integrate with student/course progress exactly once.
142. [OPEN] Stale progress CAS failure must never overwrite newer student work.
143. [OPEN] Training-to-analysis handoff must not mutate answer/session state.

## 14. Teacher pointer / annotations / sighted board
144. [GREEN] Teacher pointer input `f3` -> immediate pointer + auto-clear has DEV1 coverage.
145. [OPEN] Pointer input and move input must remain separate controls/actions in final composition.
146. [OPEN] Pointer visual cell and NVDA summary must derive atomically from one snapshot.
147. [OPEN] Pointer on orientation flip must stay on same canonical square.
148. [OPEN] Highlight legal moves must derive from canonical legality, never UI pseudo-legality.
149. [OPEN] Multiple arrows must remain presentation-only and bounded.
150. [OPEN] Annotation clear must not clear chess selection/history.
151. [OPEN] Coordinate-label toggle must not change square accessible identity.
152. [OPEN] Color/theme annotation choices need non-color semantic equivalents.
153. [OPEN] Teacher engine visibility policy must not leak engine data to student projection.
154. [OPEN] Teacher controls must remain fully keyboard reachable without mouse movement.

## 15. TeachingSession canonical-to-presentation integration
155. [GREEN] Canonical TeachingSession has eight activities, CAS revisioning and canonical move execution.
156. [GREEN] DEV2 adversarial TeachingSession state/presentation invariants are isolated-green.
157. [E2E] No single role-aware projection currently joins TeachingSession plan/state with Classroom pseudonyms.
158. [E2E] Student-facing projection must never reveal target_square before the exercise policy permits it.
159. [E2E] Student-facing projection must never reveal target_piece answer prematurely.
160. [E2E] Student-facing projection must never reveal another student's response.
161. [E2E] Teacher-facing projection needs pseudonym rather than raw student ID.
162. [E2E] Completed/paused projection must advertise locked board + hidden engine coherently.
163. [E2E] Solution reveal must expose solution only when canonical policy says visible.
164. [E2E] TeachingSession view must not expose raw FEN/source_ref/plan digest/session internals to browser/NVDA.
165. [E2E] Presentation must fail closed on plan/state/classroom mismatch without echoing internal validation text.

## 16. Classroom domain / management UI
166. [GREEN] Canonical Classroom domain has versioned privacy/consent/deletion invariants.
167. [GREEN] DEV1 classroom management WebView package has exact-green isolated evidence.
168. [E2E] Management UI records still need authoritative mapping from canonical ClassroomSnapshot.
169. [E2E] Deleted student tombstones must never appear as normal active students.
170. [E2E] Student pseudonym must be the display identity unless explicit consent policy allows more.
171. [E2E] Teacher notes must remain behind consent/privacy boundary.
172. [E2E] Assignment open must preserve class/course/lesson context.
173. [E2E] Student-game links must use canonical game identity, not copied PGN text as identity.
174. [E2E] Progress updates must be monotonic/versioned or explicitly reversible.
175. [E2E] Consent withdrawal must remove/minimize dependent private records according to canonical cascade policy.
176. [E2E] Classroom list rerenders must not focus the first item in four independent lists automatically.

## 17. Student reverse channel
177. [GREEN] Hover and selection are separate canonical event families.
178. [OPEN] Hover must never become a chess move.
179. [OPEN] Selection must never become a chess move without explicit teaching policy.
180. [OPEN] Repeated hover events need bounded/coalesced feedback to avoid NVDA flooding.
181. [OPEN] Selection answer should be announced once with pseudonym + square/piece as policy allows.
182. [OPEN] Reverse-channel event ordering must be deterministic across reconnect/replay.
183. [OPEN] Duplicate remote event IDs must be idempotently ignored.
184. [OPEN] Out-of-order stale student events must not replace newer selection state.
185. [OPEN] Events from students outside the active lesson/cohort must fail closed.
186. [OPEN] Deleted/withdrawn student identity must not reappear through historical live feedback.
187. [OPEN] Teacher feedback history must be bounded without breaking further lesson input.

## 18. Remote/shared lessons
188. [GREEN] Canonical remote-session domain and DEV1 remote presentation have isolated evidence.
189. [OPEN] Remote transport/auth implementation remains a missing production vertical.
190. [OPEN] Session reconnect must retain canonical position/event revision without duplicating moves.
191. [OPEN] Teacher pointer replay after reconnect must not mutate chess state.
192. [OPEN] Annotation replay must be ordered/idempotent.
193. [OPEN] Active-student ownership needs deterministic transfer semantics.
194. [OPEN] Student move must be rejected when remote session policy is not MOVE_ALLOWED.
195. [OPEN] Reconnect must not expose private session/token material to browser/NVDA.
196. [OPEN] Transport errors must be sanitized and recoverable without resetting lesson domain state.
197. [OPEN] Multi-student simultaneous events need conflict/order policy.
198. [OPEN] Remote lesson record/replay must be bounded and versioned.

## 19. Security / privacy / resource boundaries
199. [OTHER] Live Stage1 Stockfish runtime path privacy defect is owned by DEV3 QA + DEV4/DEV5/DEV-C; do not duplicate.
200. [OTHER] Stage1 accepted-authority promotion and fresh Windows candidate chain are DEV-C/DEV5 ownership.
201. [GREEN] Shared PGN/ChessBase/import security slice has strong DEV4 3e15 evidence.
202. [OPEN] New Teacher/Classroom projections must never serialize FEN unless explicitly required by a board adapter.
203. [OPEN] New Teacher/Classroom projections must never serialize raw plan digests/source refs/session secrets.
204. [OPEN] New role-aware projections must enforce bounded text before browser transfer.
205. [OPEN] Unknown/malformed classroom values must yield neutral user-facing errors.
206. [OPEN] Arbitrary backend return objects must never be copied wholesale into WebView messages.
207. [OPEN] Resource limits must be enforced before materializing unbounded iterables where applicable.
208. [OPEN] Revision counters crossing JavaScript boundary must stay within exact integer range.
209. [OPEN] Privacy tests must cover POSIX, Windows drive, UNC and traversal-looking strings in user-visible fields.

## 20. Cross-module end-to-end finish gates
210. [E2E] PGN -> GameTree -> edit -> export must run on one integrated tree.
211. [E2E] PGN -> ACSDB -> Search -> open -> Stockfish must run on one integrated tree.
212. [E2E] ChessBase -> adapter -> canonical GameTree/metadata/provenance -> ACSDB still needs full supported-family vertical proof.
213. [E2E] Book -> Board -> Analysis -> exact Book return must run on one integrated tree.
214. [E2E] Book/Teacher -> Training -> Progress must run on one integrated tree.
215. [E2E] TeachingSession -> Teacher visual board + NVDA view must derive from one canonical state.
216. [E2E] Student hover/select/move policy -> teacher accessible reverse channel needs one integrated vertical.
217. [E2E] Class -> Lesson -> Assignment -> StudentGame -> Review -> Progress needs one integrated vertical.
218. [E2E] Remote session ordering/dedupe/reconnect/replay needs one integrated vertical.
219. [OTHER] Stage1 Windows machine-release chain must remain separate and owned by release/audit lanes while full-product work continues.
220. [OPEN] Final product completion requires one auditable full-product integration authority with no duplicate chess/application cores and a complete keyboard/NVDA path for every user-facing function.

## DEV-A first implementation slice selected from the matrix

The first non-duplicating P1/E2E slice is **155–165**: role-aware TeachingSession presentation over the already-green canonical TeachingSession + Classroom domain. The existing pieces are individually strong but there is no single projection that safely exposes teacher/student views without leaking answer targets, raw student IDs, FEN/source references, plan digests or other internal state. This branch will add that projection and adversarial tests without touching Stage1 release/privacy work, engine/ACSDB, importer/ChessBase security or integration ownership.
