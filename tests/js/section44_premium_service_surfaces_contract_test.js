"use strict";
/* Section 44 real-product integration gate.
   Run with: node tests/js/section44_premium_service_surfaces_contract_test.js
   The executable DOM/ARIA/keyboard behavior tests are run alongside this
   source-to-service and shared-style gate in section44-premium-surfaces.yml. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "../..");
const load = name => fs.readFileSync(path.join(root, name), "utf8");

const html = load("web/index.html");
const css = load("web/design_system.css");
const v2 = load("web/version2_final_product_bootstrap.js");
const nativeUi = load("acs/version2_release_ui.py");
const canonicalApplication = load("acs/version2_final_product_application.py");
const assets = {
  books: load("web/full_product_books_training.js"),
  library: load("web/full_product_library.js"),
  education: load("web/full_product_education.js"),
  teacher: load("web/full_product_teacher.js"),
  classroom: load("web/full_product_classroom.js"),
  pgn: load("web/full_product_pgn.js")
};

assert.match(html, /<link\s+rel="stylesheet"\s+href="design_system\.css"/);
assert.match(html, /id="live"\s+role="status"\s+aria-live="polite"/);
assert.match(v2, /v2_browser_command/);
assert.match(nativeUi, /def v2_browser_command\(/);
assert.match(nativeUi, /return self\._version2\(\)\.browser_command\(area, command, payload\)/);
assert.match(canonicalApplication, /def browser_command\(/);
assert.match(v2, /function restoreProductFocus\(/);
assert.match(v2, /aria-current/);
assert.match(css, /@media \(forced-colors:\s*active\)/);
assert.match(css, /@media \(prefers-reduced-motion:\s*reduce\)/);
assert.match(css, /:focus-visible/);

const routes = [
  ["pgn", "AccessibleChessPgnSurface", "pgn"],
  ["library", "AccessibleChessLibrarySurface", "library"],
  ["books", "AccessibleChessBookSurface", "books"],
  ["training", "AccessibleChessTrainingSurface", "books"],
  ["teacher", "AccessibleChessTeacherSurface", "teacher"],
  ["classes", "AccessibleChessEducationSurface", "education"]
];
for (const [route, surface, file] of routes) {
  assert.ok(v2.includes('routeId === "' + route + '"'), "missing real route: " + route);
  assert.ok(v2.includes(surface), "route not bound to service presenter: " + surface);
  assert.ok(assets[file].includes(surface), "presenter not exported by real module: " + surface);
}
assert.ok(assets.classroom.includes("AccessibleChessClassroomSurface"), "live classroom surface missing");

const styledLiveControls = [
  ["#book-document-title", assets.books, "book-document-title"],
  ["#book-document-author", assets.books, "book-document-author"],
  ["#book-bookmark-name", assets.books, "book-bookmark-name"],
  ["#training-answer", assets.books, "training-answer"],
  ["#training-solution", assets.books, "training-solution"],
  ["#library-import-region", assets.library, "library-import-region"],
  ["#library-export-selection", assets.library, "library-export-selection"],
  ["#education-detail", assets.education, "education-detail"],
  ["#teacher-orientation-toggle", assets.teacher, "teacher-orientation-toggle"],
  ["#teacher-pointer-input", assets.teacher, "teacher-pointer-input"],
  ["#pgn-comment-text", assets.pgn, "pgn-comment-text"],
  ["#pgn-refresh-view", assets.pgn, "pgn-refresh-view"]
];
for (const [selector, source, identifier] of styledLiveControls) {
  assert.ok(css.includes(selector), "missing premium styling: " + selector);
  assert.ok(source.includes('"' + identifier + '"'), "styling detached from real module: " + identifier);
}
for (const role of ["tree", "treeitem", "listbox", "option", "toolbar"]) {
  assert.ok(css.includes('[role="' + role + '"]'), "missing keyboard/ARIA visual state: " + role);
}
for (const role of ["tree", "treeitem", "toolbar"]) {
  assert.ok(assets.books.includes('"' + role + '"') ||
            assets.pgn.includes('"' + role + '"') ||
            assets.library.includes('"' + role + '"'),
            "role is only decorative and has no real presenter: " + role);
}
assert.ok(css.includes('#v2-navigation') && css.includes('#v2-workspace'));
assert.ok(css.includes('#teacher-visual-board [role="gridcell"]'));
assert.ok(assets.teacher.includes('setAttribute("role", "grid")'), "teacher chessboard semantic grid missing");

for (const id of ["youtube-player", "local-video", "ai-agent-region", "analysis-lines"]) {
  assert.ok(html.includes('id="' + id + '"'), "existing media/engine/AI control lost: " + id);
  assert.ok(css.includes("#" + id), "media/engine/AI lacks shared styling: " + id);
}
const youtubeRules = css.match(/#youtube-player[^{}]*\{[^}]*\}/g) || [];
assert.ok(youtubeRules.length > 0, "YouTube player lost");
for (const rule of youtubeRules) {
  assert.doesNotMatch(rule, /pointer-events\s*:\s*none|display\s*:\s*none|visibility\s*:\s*hidden/,
    "do not obscure YouTube's native controls");
}
for (const scenario of [
  "books_training_surface_dom_test.js",
  "library_surface_dom_test.js",
  "education_surface_dom_test.js",
  "teacher_surface_dom_test.js",
  "classroom_surface_dom_test.js",
  "pgn_surface_dom_test.js",
  "pgn_tree_keyboard_dom_test.js",
  "version2_release_bootstrap_dom_test.js"
]) {
  assert.ok(fs.existsSync(path.join(root, "tests/js", scenario)),
    "real behavioral DOM/ARIA/keyboard regression is absent: " + scenario);
}
console.log("Section 44: PASS — 6 real V2 routes, canonical presenters, 12 styled controls, media/AI, accessibility and existing DOM suites");
