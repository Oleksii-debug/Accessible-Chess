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
window.addEventListener("accessible-chess-design-change", () => {
  // Presentation-only repaint from the last authenticated canonical snapshot.
  // No network effect, chess move or new Board truth is introduced here.
  if (lastSnapshot) renderBoard(lastSnapshot);
});

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

// Only project the selected route's canonical visual board. Never reuse a
// stale Play board for Teacher/Book/Media after switching workspaces.
function canonicalSquares(cells) {
  if (!Array.isArray(cells) || cells.length !== 64) return false;
  const names = cells.map(cell => cell && cell.square);
  return names.every(x => typeof x === "string" && /^[a-h][1-8]$/.test(x))
    && new Set(names).size === 64
    && cells.every(cell => cell && typeof cell === "object" &&
      (cell.piece == null || (typeof cell.piece === "string" &&
        (cell.piece === "" || /^[KQRBNPkqrbnp]$/.test(cell.piece))))
      && (cell.label == null || (typeof cell.label === "string" && cell.label.length <= 256)));
}
function activeVisualBoard(snapshot) {
  if (!snapshot || typeof snapshot !== "object") return null;
  const route = String(currentRoute || "board");
  const surfaceForRoute = {board:"ordinary_play",teacher:"teacher",
    online:"online",spectator:"spectator",books:"book",media:"media"};
  const top = snapshot.visualBoard;
  const correctlyScoped = top && top.surface === surfaceForRoute[route] ? top : null;
  const routeObjects = {
    board:[correctlyScoped,snapshot.board && snapshot.board.visualBoard],
    teacher:[correctlyScoped,snapshot.teacher && snapshot.teacher.visualBoard],
    online:[correctlyScoped,snapshot.online && snapshot.online.visualBoard],
    spectator:[correctlyScoped,snapshot.spectator && snapshot.spectator.visualBoard],
    books:[correctlyScoped,snapshot.books && snapshot.books.visualBoard,
           snapshot.book && snapshot.book.visualBoard],
    media:[correctlyScoped,snapshot.media && snapshot.media.visualBoard]
  };
  const possible = routeObjects[route] || [];
  for (const candidate of possible) {
    if (candidate && canonicalSquares(candidate.cells)) return candidate;
  }
  return null;
}
function boardCells(snapshot) {
  const visual=activeVisualBoard(snapshot);
  if (visual) return visual.cells;
  // Legacy V2 board fallback belongs only to the real Play route.
  if (currentRoute !== "board") return [];
  const candidates = [snapshot && snapshot.board && snapshot.board.cells,
    snapshot && snapshot.screen && snapshot.screen.board,
    snapshot && snapshot.position && snapshot.position.cells];
  for (const value of candidates) {
    if (canonicalSquares(value)) return value;
  }
  return [];
}

function renderBoard(snapshot) {
  const cells = boardCells(snapshot);
  const oldCells = [...boardGrid.querySelectorAll('[role="gridcell"]')];
  const focusedSquare = document.activeElement &&
    document.activeElement.closest && document.activeElement.closest("#board-grid") === boardGrid
    ? document.activeElement.dataset.square : null;
  const oldPieces = new Map(oldCells.map(node => [node.dataset.square, node.dataset.piece || ""]));
  boardGrid.replaceChildren();
  if (!cells.length) {
    boardSurface.hidden = true;
    return;
  }
  boardSurface.hidden = false;
  const visual = activeVisualBoard(snapshot) || {};
  const canonicalPrefs = visual.preferences && typeof visual.preferences === "object" ? visual.preferences : {};
  const themes = ["classic", "high_contrast", "blue", "classic_wood",
    "modern_graphite", "tournament_blue", "light_minimal"];
  const userPrefs=window.accessibleChessDesignPreferences;
  const override=userPrefs && typeof userPrefs === "object" && !Array.isArray(userPrefs)
    ? userPrefs : null;
  const p=override ? {
    ...canonicalPrefs,
    boardTheme: themes.includes(override.board_theme)
      ? override.board_theme : canonicalPrefs.boardTheme,
    pieceTheme: ["unicode","letters","rhosgfx"].includes(override.piece_theme)
      ? override.piece_theme : canonicalPrefs.pieceTheme,
    orientation: ["white","black"].includes(override.orientation)
      ? override.orientation : canonicalPrefs.orientation,
    coordinateMode: ["off","edges","every_square"].includes(override.coordinates)
      ? override.coordinates : canonicalPrefs.coordinateMode,
    scalePercent: [75,100,125,150,175,200].includes(override.board_scale)
      ? override.board_scale : canonicalPrefs.scalePercent,
    showLastMove: typeof override.highlight === "boolean"
      ? override.highlight : canonicalPrefs.showLastMove,
    animateMoves: typeof override.animations === "boolean"
      ? override.animations : canonicalPrefs.animateMoves
  } : canonicalPrefs;
  const theme = themes.includes(p.boardTheme) ? p.boardTheme : "classic";
  const style = ["unicode", "letters", "rhosgfx"].includes(p.pieceTheme) ? p.pieceTheme : "unicode";
  const ordered = p.orientation === "black" ? [...cells].reverse() : [...cells];
  const legal = new Set(Array.isArray(visual.legalTargets) ?
    visual.legalTargets.slice(0,64).filter(x => typeof x === "string" && /^[a-h][1-8]$/.test(x)) : []);
  const last = visual.lastMove && typeof visual.lastMove === "object"
    ? [visual.lastMove.from, visual.lastMove.to] : [];
  const activeSquare = typeof visual.selectedSquare === "string" ? visual.selectedSquare : null;
  const glyphs = {K:"♔",Q:"♕",R:"♖",B:"♗",N:"♘",P:"♙",
    k:"♚",q:"♛",r:"♜",b:"♝",n:"♞",p:"♟"};
  const scale = [75,100,125,150,175,200].includes(Number(p.scalePercent))
    ? Number(p.scalePercent) : 100;
  boardGrid.dataset.theme = theme;
  boardGrid.dataset.pieceTheme = style;
  boardGrid.dataset.presentation = p.presentationMode === true ? "true" : "false";
  boardGrid.dataset.motion = p.animateMoves === true && p.lowPowerMode !== true ? "true" : "false";
  boardGrid.dataset.power = p.lowPowerMode === true ? "low" : "normal";
  boardGrid.style.maxWidth = p.fitToWindow === true
    ? "min(100%,calc(100dvh - 6rem))"
    : p.presentationMode === true ? "min(98vw,85rem)" : String(52*scale/100)+"rem";
  const activeIndex = Math.max(0,ordered.findIndex(cell =>
    cell && typeof cell === "object" && String(cell.square || cell.name || "") === focusedSquare));
  ordered.forEach((cell, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.setAttribute("role", "gridcell");
    const square = cell && typeof cell === "object"
      ? String(cell.square || cell.name || "") : "";
    const validSquare = /^[a-h][1-8]$/.test(square);
    const token = cell && typeof cell === "object" && typeof cell.piece === "string"
      && /^[KQRBNPkqrbnp]$/.test(cell.piece) ? cell.piece : "";
    const fallback = String(cell || ("Клітинка " + (index+1)));
    const rawLabel = cell && typeof cell === "object"
      ? String(cell.label || cell.description || square || fallback) : fallback;
    const label = rawLabel.replace(/[\x00-\x1f\x7f]/g," ").trim().slice(0,256) || square;
    button.dataset.square = square;
    button.dataset.index = String(index);
    button.dataset.piece = token;
    button.tabIndex = index === activeIndex ? 0 : -1;
    button.setAttribute("aria-label", label);
    button.setAttribute("aria-rowindex", String(Math.floor(index/8)+1));
    button.setAttribute("aria-colindex", String(index%8+1));
    button.setAttribute("aria-selected", square && square === activeSquare ? "true" : "false");
    if (validSquare) {
      const file = square.charCodeAt(0)-97, rank = Number(square[1])-1;
      button.dataset.light = (file+rank)%2===1 ? "true" : "false";
      if (p.showLastMove !== false && last.includes(square)) button.dataset.lastMove = "true";
      if (legal.has(square)) button.dataset.legalTarget = "true";
    }
    const decoration = document.createElement("span");
    decoration.className = "board-piece";
    decoration.setAttribute("aria-hidden", "true");
    if (token && style === "rhosgfx") {
      const image = document.createElement("img");
      const file = (token === token.toUpperCase() ? "w" : "b") + token.toUpperCase() + ".svg";
      image.src = "assets/pieces/rhosgfx/" + file;
      image.alt = "";
      image.className = "ac42-piece-art";
      image.setAttribute("aria-hidden", "true");
      image.draggable = false;
      image.addEventListener("error", () => {
        image.remove();
        decoration.textContent = glyphs[token] || token;
      });
      decoration.appendChild(image);
      const backup=document.createElement('span');
      backup.className='ac42-piece-fallback';
      backup.textContent=glyphs[token]||token;
      backup.setAttribute('aria-hidden','true');
      decoration.appendChild(backup);
      image.addEventListener('error',()=>{backup.style.display='inline'});
    } else {
      decoration.textContent = !token ? "" : style === "letters" ? token : glyphs[token];
    }
    if (p.animateMoves === true && validSquare && last[1] === square
      && oldPieces.has(square) && oldPieces.get(square) !== token) {
      decoration.dataset.ac42Animate = "true";
    }
    button.appendChild(decoration);
    if (validSquare && p.coordinateMode !== "off") {
      const position = p.coordinateMode === "every_square" ? square
        : (index >= 56 && index%8 === 0) ? square
        : index >= 56 ? square[0] : index%8 === 0 ? square[1] : "";
      if (position) {
        const node = document.createElement("span");
        node.className = "board-coordinate";
        node.setAttribute("aria-hidden", "true");
        node.textContent = position;
        button.appendChild(node);
      }
    }
    button.addEventListener("keydown", (event) => {
      let delta = 0;
      if (event.key === "ArrowRight") delta = 1;
      else if (event.key === "ArrowLeft") delta = -1;
      else if (event.key === "ArrowDown") delta = 8;
      else if (event.key === "ArrowUp") delta = -8;
      if (!delta) return;
      const next = Math.max(0,Math.min(63,index+delta));
      const target = boardGrid.querySelector('[data-index="' + next + '"]');
      if (target) {
        event.preventDefault();
        button.tabIndex = -1;
        target.tabIndex = 0;
        target.focus();
      }
    });
    boardGrid.appendChild(button);
  });
  const overlayRenderer = globalThis.AccessibleChessBoardOverlay;
  if (overlayRenderer && typeof overlayRenderer.project === "function") {
    overlayRenderer.project(boardGrid, ordered, visual);
  }
  if (focusedSquare && boardGrid.children[activeIndex]) {
    boardGrid.children[activeIndex].focus({preventScroll:true});
  }
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
