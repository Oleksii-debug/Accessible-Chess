"use strict";
// Section44.5: canonical, restored Web/Online/Spectator and subscription styling.
// Run: node tests/js/section44_web_online_premium_contract_test.js
// This verifies the actual shipped sources, not mock screenshot/CI success.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "../..");
const load = file => fs.readFileSync(path.join(root, file), "utf8");
const webHtml = load("web/accessible_chess_web.html");
const webJs = load("web/accessible_chess_web.js");
const subscriptionHtml = load("web/accessible_chess_subscription.html");
const subscriptionJs = load("web/accessible_chess_subscription.js");
const premiumCss = load("web/design_system.css");
const webAsgi = load("acs/web_client_http.py");
const subscriptionAsgi = load("acs/subscription_web.py");
const gateway = load("acs/web_client_gateway.py");
const multiplayer = load("acs/multiplayer_coordination.py");
const spectator = load("acs/multiplayer_spectator.py");
const plans = load("acs/subscription_plans.py");
const entitlements = load("acs/entitlements.py");

assert.match(webHtml, /<body class="ac44-web-page">/);
assert.match(subscriptionHtml, /<body class="ac44-subscription-page">/);
assert.match(webHtml, /href="\/assets\/accessible_chess_web_design.css"/);
assert.match(subscriptionHtml, /href="\/assets\/accessible_chess_subscription_design.css"/);
assert.match(webAsgi, /path == "\/assets\/accessible_chess_web_design.css"/);
assert.match(subscriptionAsgi, /path == "\/assets\/accessible_chess_subscription_design.css"/);
assert.match(webAsgi, /_trusted_principal\(scope\)[\s\S]{0,130}_asset_bytes\("design_system.css"\)/);
assert.match(webAsgi, /_CSS_TYPE = b"text\/css; charset=utf-8"/);
assert.match(subscriptionAsgi, /_CSS_TYPE = b"text\/css; charset=utf-8"/);
assert.match(subscriptionAsgi, /_asset\("design_system.css"\)/);
assert.match(webAsgi, /Query strings are not supported/);
assert.match(subscriptionAsgi, /Query strings are not supported/);
for (const part of [webAsgi, subscriptionAsgi]) {
  assert.match(part, /b"no-store"/);
  assert.match(part, /b"nosniff"/);
}
for (const area of ["board", "pgn", "library", "books", "training",
                    "media", "teacher", "classes", "online", "spectator"]) {
  assert.ok(webHtml.includes('data-route="' + area + '"'),
    "real Web client missing original route: " + area);
}
assert.match(gateway, /"online", "spectator"/);
assert.match(gateway, /CanonicalWebGateway/);
assert.match(multiplayer, /MULTIPLAYER_SCHEMA_VERSION/);
assert.match(spectator, /class SpectatorGameView/);
assert.match(plans, /class SubscriptionActionKind/);
assert.match(entitlements, /LOCAL_DATA_SAFETY_FEATURE_IDS/);
assert.match(webJs, /currentRoute/);
assert.match(webJs, /credentials: "same-origin"/);
assert.match(webJs, /redirect: "error"/);
assert.doesNotMatch(webJs, /window\.pywebview/);
assert.doesNotMatch(webJs, /innerHTML/);
for (const id of ["status", "error", "workspace", "routes", "board-grid",
                  "content", "progress-text", "commands"]) {
  assert.ok(webHtml.includes('id="' + id + '"'));
  assert.ok(premiumCss.includes("#" + id));
}
for (const id of ["status", "error", "account-state", "plan-form",
                  "plans", "cadence", "checkout", "confirmation", "cancel-confirmation",
                  "data-safety"]) {
  assert.ok(subscriptionHtml.includes('id="' + id + '"'));
}
assert.match(subscriptionHtml, /Клавіатурна та екранна доступність не залежать від тарифу/);
assert.match(subscriptionJs, /credentials: "same-origin"/);
assert.doesNotMatch(subscriptionJs, /window\.open/);
assert.doesNotMatch(subscriptionJs, /innerHTML/);
for (const token of [".ac44-web-page", ".ac44-subscription-page",
                     ".route-button[aria-current=\"page\"]", "role=\"gridcell\"",
                     "@media(forced-colors:active)", "@media(prefers-reduced-motion:reduce)",
                     ":focus-visible", "--ac-text", "--ac-surface", "--ac-focus"]) {
  assert.ok(premiumCss.includes(token), "missing shared premium token: " + token);
}
for (const token of ['role="grid"', 'role="status"', 'role="alert"',
                     'id="route-heading"', 'id="progress-text"']) {
  assert.ok(webHtml.includes(token), "Web semantic node missing: " + token);
}
const css = premiumCss.slice(premiumCss.indexOf("Section 44.5: exact, shared real Web"));
assert.doesNotMatch(css, /@import\s+url|https?:\/\//);
assert.doesNotMatch(css, /pointer-events\s*:\s*none/);
console.log("SECTION44_WEB_ONLINE_PREMIUM_SOURCE_CONTRACT_PASS");
