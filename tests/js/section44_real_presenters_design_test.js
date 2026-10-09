"use strict";
/* Section 44 contract: presentation selectors must target actual canonical
 * service-driven modules, not screenshots, fixture-only DOM or demo screens.
 * Node built-ins only; runs identically on Ubuntu and Windows. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "../..");
const read = file => fs.readFileSync(path.join(root, file), "utf8");

const css = read("web/assets/accessible_chess_design.css");
const html = read("web/index.html");
const webHtml = read("web/accessible_chess_web.html");
const webClient = read("web/accessible_chess_web.js");
const bootstrap = read("web/version2_final_product_bootstrap.js");
const books = read("web/full_product_books_training.js");
const library = read("web/full_product_library.js");
const training = read("web/full_product_education.js");
const classroom = read("web/full_product_classroom.js");
const teacher = read("web/full_product_teacher.js");

function present(source, literals, label) {
  for (const literal of literals) {
    assert.ok(source.includes(literal), label + ": missing " + literal);
  }
}
function cssSelector(literal, label) {
  assert.ok(css.includes(literal), "Missing real " + label + " CSS selector " + literal);
}

present(html, ["main-content", "move-input", "board-grid"], "Windows canonical host");
present(bootstrap, ["v2-workspace", "renderProductSurface", "fullProduct"], "V2 product bootstrap");
present(css, ["#v2-workspace", "--ac41-ink", "forced-colors:active", "prefers-reduced-motion:reduce"], "Offline design system");
assert.equal(/@import\s+url\(\s*["']?https?:/i.test(css), false, "Visual layer must remain offline");

present(books, ["renderBookSurface(", "renderBookBlock(", "book-document-title",
  "book-document-author", "book-bookmark-name", 'setAttribute("role", "img")',
  'setAttribute("aria-label"'], "Real semantic Books presenter");
for (const selector of [
  "#v2-workspace #book-document-title",
  "figure[role=\"img\"]",
  'aside[role="note"]',
  "nav[aria-label]"
]) cssSelector(selector, "Books");

present(library, ["renderLibrarySurface(", "renderResults(", "renderImport(",
  "library-search-", "library-import-region", "library-export-selection",
  '"library.select"', '"library.open_game"', '"aria-selected"'], "Real Library/PGN presenter");
for (const selector of [
  "#v2-workspace #library-search-player", "#v2-workspace #library-import-region",
  "#v2-workspace #library-export-selection", 'input[type="checkbox"]'
]) cssSelector(selector, "Library");

present(training, ["renderSection(", "renderDetail(", "education-detail",
  '"role", "listbox"', '"aria-selected"'], "Real Education/AI surface");
present(books, ["renderTrainingSurface(", "training-answer", "training-solution",
  '"aria-live"'], "Real canonical training presenter");
for (const selector of [
  "#v2-workspace #training-answer", "#v2-workspace #training-solution",
  "#v2-workspace #education-detail", "#v2-workspace [data-education-kind]"
]) cssSelector(selector, "Training");

present(teacher, ["renderTeacherSurface(", "teacher-visual-region", "teacher-board-wrap",
  "teacher-visual-board", "teacher-accessible-summary", "teacher-arrow-overlay",
  '"teacher.student_event"', '"role", "grid"', '"aria-label"',
  '"aria-hidden", "true"'], "Real Teacher board + accessible arrow summary");
present(classroom, ["renderManagement(", '"management.select"', '"role", "listbox"',
  '"aria-selected"'], "Real Classroom management");
for (const selector of [
  "#v2-workspace #teacher-board-wrap", "#v2-workspace #teacher-visual-board",
  "#v2-workspace #teacher-visual-board button[data-square]",
  "#v2-workspace #teacher-arrow-overlay", "#v2-workspace #teacher-accessible-summary"
]) cssSelector(selector, "Teacher");
assert.match(css, /#v2-workspace #teacher-arrow-overlay\s*\{\s*pointer-events:none!important/);
assert.match(css, /#v2-workspace #teacher-visual-board button\[data-square\]:focus-visible/);

present(webHtml, ['id="workspace"', 'id="routes"', 'id="status"', 'id="error"',
  'role="status"', 'role="alert"'], "Actual Web application");
present(webClient, ["setRoute(", "fetch(", 'byId("workspace")',
  'byId("content")'], "Real Web commands and status");
for (const selector of ["#workspace", "#routes", "#workspace iframe",
  "#v2-workspace iframe", "@media(max-width:38rem)"]) cssSelector(selector, "Web/media");
assert.equal(/#(?:workspace|v2-workspace)\s+iframe\s*\{[^}]*pointer-events\s*:\s*none/s.test(css), false,
  "YouTube/iframe interactive controls must remain clickable");
assert.equal(/#(?:workspace|v2-workspace)\s+video\s*\{[^}]*pointer-events\s*:\s*none/s.test(css), false,
  "Native video controls must remain clickable");
console.log("Section 44 real presenter/design/keyboard/forced-colors/embedded-media contracts PASS");
