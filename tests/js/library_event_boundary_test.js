"use strict";

const fs = require("fs");
const vm = require("vm");

global.window = {};

const source = fs.readFileSync("web/full_product_library.js", "utf8");
vm.runInThisContext(source, { filename: "full_product_library.js" });

function check(condition, message) {
  if (!condition) throw new Error(message);
}

function expectTypeError(callback, message) {
  let rejected = false;
  try {
    callback();
  } catch (error) {
    rejected = error instanceof TypeError;
  }
  check(rejected, message);
}

const root = {
  querySelector() { return null; }
};
const invoke = () => Promise.resolve(null);
const announcements = [];
const announce = (message) => announcements.push(message);
const surface = window.AccessibleChessLibrarySurface;

check(surface && typeof surface.apply === "function", "Library surface apply boundary is missing");

surface.apply(
  root,
  { kind: "delegated", payload: { action: "library.import" } },
  invoke,
  announce
);
surface.apply(
  root,
  { kind: "delegated", payload: { action: "library.open_game" } },
  invoke,
  announce
);
surface.apply(
  root,
  { kind: "delegated", payload: { action: "library.export", scope: "selected" } },
  invoke,
  announce
);
surface.apply(
  root,
  { kind: "delegated", payload: { action: "library.export", scope: "filtered" } },
  invoke,
  announce
);
check(announcements.length === 0, "delegated Library events must not synthesize announcements");

surface.apply(
  root,
  { kind: "error", payload: { message: "Could not complete action." } },
  invoke,
  announce
);
check(
  announcements.length === 1 && announcements[0] === "Could not complete action.",
  "canonical Library error message was not announced exactly once"
);

let hostileMessageTouched = false;
expectTypeError(
  () => surface.apply(
    root,
    {
      kind: "error",
      payload: {
        message: {
          toString() {
            hostileMessageTouched = true;
            return "hostile";
          }
        }
      }
    },
    invoke,
    announce
  ),
  "hostile Library error message was accepted"
);
check(!hostileMessageTouched, "hostile Library error message reached String coercion");
check(announcements.length === 1, "invalid Library error event was announced");

let hostileAnnouncementTouched = false;
expectTypeError(
  () => surface.apply(
    root,
    {
      kind: "delegated",
      payload: {
        action: "library.import",
        announcement: {
          toString() {
            hostileAnnouncementTouched = true;
            return "hostile";
          }
        }
      }
    },
    invoke,
    announce
  ),
  "delegated Library event accepted an undeclared announcement field"
);
check(!hostileAnnouncementTouched, "undeclared Library announcement reached coercion");
check(announcements.length === 1, "malformed delegated event changed announcements");

expectTypeError(
  () => surface.apply(
    root,
    { kind: "delegated", payload: { action: "library.export", scope: "all" } },
    invoke,
    announce
  ),
  "Library export delegated event accepted an invalid scope"
);
expectTypeError(
  () => surface.apply(
    root,
    { kind: "delegated", payload: { action: "library.unknown" } },
    invoke,
    announce
  ),
  "Library delegated event accepted an unknown action"
);
expectTypeError(
  () => surface.apply(
    root,
    { kind: "status", payload: { announcement: "unexpected" } },
    invoke,
    announce
  ),
  "Library surface accepted a native-only status event on the browser-result boundary"
);
expectTypeError(
  () => surface.apply(root, 7, invoke, announce),
  "Library surface accepted a scalar browser result"
);

surface.apply(root, null, invoke, announce);
check(announcements.length === 1, "null no-result changed Library announcements");

console.log("LIBRARY_EVENT_BOUNDARY=PASS");
