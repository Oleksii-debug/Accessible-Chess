"use strict";

const fs = require("fs");
const vm = require("vm");

function check(condition, message) {
  if (!condition) throw new Error(message);
}

const source = fs.readFileSync("web/index.html", "utf8");
const match = source.match(
  /function renderHelp\(\)\{.*?\}(?=\nfunction projectedOwnedAction)/s
);
check(match, "main Help renderer is missing");

const helpNode = { textContent: "stale" };
global.document = {
  documentElement: { lang: "en" }
};
global.setText = (id, value) => {
  check(id === "help", "Help renderer wrote outside the Help target");
  helpNode.textContent = String(value);
};
global.keymap = [
  {
    id: "board.last_move",
    binding: "L",
    alias: null,
    labelEn: "Last move",
    labelUk: "Останній хід"
  },
  {
    id: "move.undo",
    binding: null,
    alias: "u",
    labelEn: "Undo move command",
    labelUk: "Команда undo"
  },
  {
    id: "board.material",
    binding: null,
    alias: null,
    labelEn: "Material balance",
    labelUk: "Матеріальний баланс"
  },
  {
    id: "future.bound_action",
    binding: "Ctrl+Alt+9",
    alias: null,
    labelEn: "Future action",
    labelUk: "Майбутня дія"
  }
];

vm.runInThisContext(match[0], { filename: "index.renderHelp.js" });
const renderHelp = global.renderHelp;
check(typeof renderHelp === "function", "Help renderer did not evaluate");

renderHelp();
check(
  helpNode.textContent ===
    "L — Last move\nu — Undo move command\nCtrl+Alt+9 — Future action",
  "English Help did not project every live bound action in snapshot order"
);
check(
  !helpNode.textContent.includes("Material balance"),
  "unbound action leaked into Help"
);

document.documentElement.lang = "uk";
renderHelp();
check(
  helpNode.textContent ===
    "L — Останній хід\nu — Команда undo\nCtrl+Alt+9 — Майбутня дія",
  "Ukrainian Help did not follow live labels"
);

global.keymap = [];
renderHelp();
check(helpNode.textContent === "", "empty keymap left stale Help text visible");

console.log("DYNAMIC_KEYMAP_HELP=PASS");
