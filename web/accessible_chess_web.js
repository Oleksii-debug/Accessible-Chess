(() => {
"use strict";

const byId = (id) => document.getElementById(id);
const statusNode = byId("status");
const errorNode = byId("error");
const workspace = byId("workspace");
const contentNode = byId("content");
const commandsNode = byId("commands");
const boardSurface = byId("board-surface");
const boardGrid = byId("board-grid");
const progress = byId("progress");
const progressText = byId("progress-text");
let currentRoute = "board";
let lastSnapshot = null;
let busy = false;

function text(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 2);
}

function announce(message) {
  statusNode.textContent = "";
  window.setTimeout(() => { statusNode.textContent = String(message || ""); }, 10);
}

function fail(message) {
  errorNode.textContent = "";
  window.setTimeout(() => {
    errorNode.textContent = String(message || "Не вдалося виконати дію.");
  }, 10);
}

async function request(path, options) {
  const response = await fetch(path, {
    credentials: "same-origin",
    cache: "no-store",
    redirect: "error",
    ...options
  });
  const body = await response.json();
  if (!response.ok || !body || body.ok !== true) {
    throw new Error(body && body.error ? body.error : "Не вдалося виконати дію.");
  }
  return body;
}

function setRouteButtons(route) {
  document.querySelectorAll(".route-button").forEach((button) => {
    const active = button.dataset.route === route;
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
}

function routeSnapshot(snapshot, route) {
  if (!snapshot || typeof snapshot !== "object") return null;
  const aliases = {
    board: ["board", "screen"],
    pgn: ["pgn"],
    library: ["library"],
    books: ["books"],
    training: ["training"],
    media: ["media", "recorded_media", "live_media"],
    teacher: ["teacher"],
    classes: ["education", "classes", "classroom"],
    online: ["online", "multiplayer"],
    spectator: ["spectator", "online"]
  };
  for (const key of aliases[route] || [route]) {
    if (snapshot[key] !== undefined && snapshot[key] !== null) return snapshot[key];
  }
  return null;
}

function flattenText(value, depth = 0) {
  if (depth > 5 || value === null || value === undefined) return [];
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return [String(value)];
  }
  if (Array.isArray(value)) {
    return value.slice(0, 200).flatMap((item) => flattenText(item, depth + 1));
  }
  if (typeof value === "object") {
    const lines = [];
    Object.keys(value).slice(0, 100).forEach((key) => {
      const pieces = flattenText(value[key], depth + 1);
      if (pieces.length) lines.push(key + ": " + pieces.join(" | "));
    });
    return lines;
  }
  return [];
}

function boardCells(snapshot) {
  const candidates = [
    snapshot && snapshot.board && snapshot.board.cells,
    snapshot && snapshot.screen && snapshot.screen.board,
    snapshot && snapshot.position && snapshot.position.cells
  ];
  for (const value of candidates) {
    if (Array.isArray(value) && value.length === 64) return value;
  }
  return [];
}

function renderBoard(snapshot) {
  const cells = boardCells(snapshot);
  boardGrid.replaceChildren();
  if (!cells.length) {
    boardSurface.hidden = true;
    return;
  }
  boardSurface.hidden = false;
  cells.forEach((cell, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "gridcell");
    const square = cell && typeof cell === "object"
      ? String(cell.square || cell.name || "")
      : "";
    const label = cell && typeof cell === "object"
      ? String(cell.label || cell.description || square || ("Клітинка " + (index + 1)))
      : String(cell || ("Клітинка " + (index + 1)));
    button.textContent = square || label;
    button.setAttribute("aria-label", label);
    button.dataset.index = String(index);
    button.addEventListener("keydown", (event) => {
      let delta = 0;
      if (event.key === "ArrowRight") delta = 1;
      else if (event.key === "ArrowLeft") delta = -1;
      else if (event.key === "ArrowDown") delta = 8;
      else if (event.key === "ArrowUp") delta = -8;
      if (!delta) return;
      const next = Math.max(0, Math.min(63, index + delta));
      const target = boardGrid.querySelector('[data-index="' + next + '"]');
      if (target) {
        event.preventDefault();
        target.focus();
      }
    });
    boardGrid.appendChild(button);
  });
}

function renderProgress(value) {
  const candidate = value && typeof value === "object"
    ? (value.progress || value.import_progress || value.job_progress || null)
    : null;
  let percent = 0;
  let message = "";
  if (candidate && typeof candidate === "object") {
    if (Number.isFinite(Number(candidate.percent))) percent = Number(candidate.percent);
    else if (Number.isFinite(Number(candidate.completed)) && Number.isFinite(Number(candidate.total)) && Number(candidate.total) > 0) {
      percent = Number(candidate.completed) * 100 / Number(candidate.total);
    }
    message = String(candidate.message || candidate.status || "");
  }
  progress.value = Math.max(0, Math.min(100, percent));
  progressText.textContent = message || (Math.round(progress.value) + "%");
}

function renderCommands(snapshot) {
  commandsNode.replaceChildren();
  const route = currentRoute;
  const commands = [];
  if (route === "training") commands.push(["training", "training.hint", "Підказка"], ["training", "training.reveal_solution", "Показати розв'язок"]);
  if (route === "books") commands.push(["books", "book.previous", "Попередній блок"], ["books", "book.next", "Наступний блок"]);
  if (route === "pgn") commands.push(["pgn", "pgn.previous_item", "Попередній елемент"], ["pgn", "pgn.next_item", "Наступний елемент"]);
  if (route === "media") commands.push(["media", "media.play", "Відтворити"], ["media", "media.pause", "Пауза"], ["media", "media.restore_position", "Відновити позицію"]);
  if (route === "online") commands.push(["online", "online.sync", "Синхронізувати"]);
  if (route === "spectator") commands.push(["spectator", "spectator.sync", "Оновити"]);
  commands.forEach(([area, command, label], index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.id = "route-command-" + route + "-" + String(index);
    button.textContent = label;
    button.addEventListener("click", () => dispatch(area, command, {}));
    commandsNode.appendChild(button);
  });
  if (!commands.length) {
    const p = document.createElement("p");
    p.textContent = "Дії цього розділу надаються канонічним сервісом.";
    commandsNode.appendChild(p);
  }
}

function render(body, focus = false) {
  const snapshot = body.snapshot || body.result || {};
  lastSnapshot = snapshot;
  const screen = snapshot.screen && typeof snapshot.screen === "object" ? snapshot.screen : {};
  const route = String(currentRoute || screen.route_id || "board");
  currentRoute = route;
  setRouteButtons(route);
  byId("route-heading").textContent = String(screen.heading || route);
  byId("route-description").textContent = String(screen.description || "");
  const current = routeSnapshot(snapshot, route);
  const lines = flattenText(current === null ? snapshot : current);
  contentNode.textContent = lines.length ? lines.join("\n") : "Немає даних для відображення.";
  renderBoard(snapshot);
  renderProgress(current || snapshot);
  renderCommands(snapshot);
  const ctx = body.context || {};
  byId("account-context").textContent =
    ctx.workspace_id ? ("Робочий простір: " + ctx.workspace_id) : "";
  document.documentElement.lang =
    snapshot.document && snapshot.document.lang === "en" ? "en" : "uk";
  if (focus) workspace.focus({preventScroll: true});
}

async function refresh(focus = false) {
  if (busy) return;
  busy = true;
  try {
    errorNode.textContent = "";
    const body = await request("/v1/snapshot", {method: "GET"});
    render(body, focus);
  } catch (error) {
    fail(error && error.message);
  } finally {
    busy = false;
  }
}

async function dispatch(area, command, payload) {
  if (busy) return;
  busy = true;
  const active = document.activeElement;
  const activeId = active && active.id ? String(active.id) : "";
  const activeRoute = active && active.dataset ? active.dataset.route : "";
  try {
    errorNode.textContent = "";
    const body = await request("/v1/command", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({area, command, payload})
    });
    announce("Дію виконано.");
    busy = false;
    await refresh(false);
    let restored = false;
    if (activeId) {
      const same = document.getElementById(activeId);
      if (same && typeof same.focus === "function") {
        same.focus({preventScroll: true});
        restored = document.activeElement === same;
      }
    }
    if (!restored && activeRoute) {
      const target = document.querySelector('.route-button[data-route="' + activeRoute + '"]');
      if (target) target.focus({preventScroll: true});
    }
    return body;
  } catch (error) {
    fail(error && error.message);
    if (active && typeof active.focus === "function") active.focus({preventScroll: true});
    return null;
  } finally {
    busy = false;
  }
}

document.querySelectorAll(".route-button").forEach((button) => {
  button.addEventListener("click", () => {
    const route = String(button.dataset.route || "");
    currentRoute = route;
    setRouteButtons(route);
    if (lastSnapshot) render({snapshot: lastSnapshot}, true);
    else refresh(true);
  });
});

document.addEventListener("keydown", (event) => {
  const editable = event.target && (
    /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName) ||
    event.target.isContentEditable
  );
  if (editable && event.ctrlKey && ["a", "c", "x", "v", "z", "y"].includes(event.key.toLowerCase())) {
    return;
  }
});

refresh(true);
})();
