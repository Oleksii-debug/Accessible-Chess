(function (global) {
  "use strict";

  function requireFunction(value, name) {
    if (typeof value !== "function") throw new TypeError(name + " must be a function");
    return value;
  }

  function node(tag, text) {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function safeInvoke(invoke, command, payload, onResult, announce, fallbackMessage) {
    Promise.resolve(invoke(command, payload || {})).then(onResult).catch(function () {
      if (fallbackMessage) announce(String(fallbackMessage));
    });
  }

  function focusTarget(root, targetId) {
    if (!targetId) return;
    const candidates = root.querySelectorAll("[id]");
    for (let index = 0; index < candidates.length; index += 1) {
      if (candidates[index].id === targetId && typeof candidates[index].focus === "function") {
        candidates[index].focus({ preventScroll: true });
        return;
      }
    }
  }

  function boardSquares(orientation) {
    const result = [];
    const files = orientation === "black" ? "hgfedcba" : "abcdefgh";
    const ranks = orientation === "black" ? "12345678" : "87654321";
    for (let rankIndex = 0; rankIndex < ranks.length; rankIndex += 1) {
      for (let fileIndex = 0; fileIndex < files.length; fileIndex += 1) {
        result.push(files[fileIndex] + ranks[rankIndex]);
      }
    }
    return result;
  }

  function applySquareState(button, snapshot) {
    const square = button.getAttribute("data-square");
    const pointer = snapshot.pointer && snapshot.pointer.square === square;
    const highlights = Array.isArray(snapshot.highlights) ? snapshot.highlights : [];
    const highlight = highlights.find(function (item) { return item.square === square; });
    button.setAttribute("data-pointer", pointer ? "true" : "false");
    button.setAttribute("data-highlight", highlight ? String(highlight.purpose || "custom") : "");
    if (pointer) button.style.outline = "4px solid #ff8c00";
    if (highlight && highlight.color) button.style.backgroundColor = String(highlight.color);
  }

  function renderVisual(snapshot, invoke, announce, fallbackMessage) {
    const visual = node("section");
    visual.id = "teacher-visual-region";
    const boardState = snapshot.board || {};
    const grid = node("div");
    grid.id = "teacher-visual-board";
    grid.setAttribute("role", "grid");
    grid.setAttribute("aria-label", "Teaching board");
    grid.style.display = "grid";
    grid.style.gridTemplateColumns = "repeat(8, minmax(2.5rem, 1fr))";
    boardSquares(String(boardState.orientation || "white")).forEach(function (square) {
      const cell = node("div");
      cell.setAttribute("role", "gridcell");
      const button = node("button", boardState.coordinates_visible === false ? "" : square);
      button.type = "button";
      button.id = "teacher-square-" + square;
      button.setAttribute("data-square", square);
      button.setAttribute("aria-label", square);
      applySquareState(button, snapshot);
      button.addEventListener("mouseenter", function () {
        safeInvoke(invoke, "teacher.student_event", { kind: "hover", square: square, piece_name: "" }, function (result) {
          applyTeacherEvent(visual.parentNode, result, invoke, announce, fallbackMessage);
        }, announce, fallbackMessage);
      });
      button.addEventListener("click", function () {
        safeInvoke(invoke, "teacher.student_event", { kind: "select", square: square, piece_name: "" }, function (result) {
          applyTeacherEvent(visual.parentNode, result, invoke, announce, fallbackMessage);
        }, announce, fallbackMessage);
      });
      cell.appendChild(button);
      grid.appendChild(cell);
    });
    visual.appendChild(grid);

    const arrows = Array.isArray(snapshot.arrows) ? snapshot.arrows : [];
    if (arrows.length) {
      const overlay = node("div");
      overlay.setAttribute("aria-hidden", "true");
      arrows.forEach(function (arrow) {
        const marker = node("span", String(arrow.start_square || "") + "→" + String(arrow.end_square || ""));
        marker.setAttribute("data-purpose", String(arrow.purpose || "custom"));
        if (arrow.color) marker.style.color = String(arrow.color);
        overlay.appendChild(marker);
      });
      visual.appendChild(overlay);
    }

    const summary = node("p", snapshot.accessible_summary || "");
    summary.id = "teacher-accessible-summary";
    summary.setAttribute("aria-live", "off");
    visual.appendChild(summary);
    return visual;
  }

  function replaceVisual(root, snapshot, invoke, announce, fallbackMessage) {
    const previous = root.querySelector("#teacher-visual-region");
    const replacement = renderVisual(snapshot, invoke, announce, fallbackMessage);
    if (previous && typeof previous.replaceWith === "function") previous.replaceWith(replacement);
  }

  function applyTeacherEvent(root, result, invoke, announce, fallbackMessage) {
    if (!root || !result || typeof result !== "object") return;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    if ((result.kind === "render-pointer" || result.kind === "render-visual") && payload.snapshot) {
      replaceVisual(root, payload.snapshot, invoke, announce, fallbackMessage);
    }
    if (payload.clear_editor) {
      const input = root.querySelector("#teacher-pointer-input");
      if (input) input.value = "";
    }
    if (payload.announcement) announce(String(payload.announcement));
    if (result.kind === "error" && payload.message) announce(String(payload.message));
    focusTarget(root, payload.focus_target || "");
  }

  function renderTeacherSurface(root, snapshot, invoke, announce, requestedFocus, fallbackMessage) {
    if (!root || typeof root.replaceChildren !== "function") throw new TypeError("Teacher root must support replaceChildren");
    requireFunction(invoke, "Teacher invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "Teacher announce");
    if (!snapshot || typeof snapshot !== "object") throw new TypeError("Teacher snapshot is required");

    const fragment = document.createDocumentFragment();
    const main = node("section");
    main.appendChild(node("h2", "Teacher/Classroom"));

    const form = node("form");
    const label = node("label", "Teacher pointer square");
    const input = node("input");
    input.id = "teacher-pointer-input";
    input.type = "text";
    input.maxLength = 2;
    input.autocomplete = "off";
    input.spellcheck = false;
    label.htmlFor = input.id;
    const submit = node("button", "Set pointer");
    submit.type = "submit";
    form.appendChild(label);
    form.appendChild(input);
    form.appendChild(submit);

    function submitPointer() {
      if (input.value.length !== 2) return;
      safeInvoke(invoke, "teacher.pointer_input", { coordinate: input.value }, function (result) {
        applyTeacherEvent(root, result, invoke, announce, fallbackMessage);
      }, announce, fallbackMessage);
    }
    input.addEventListener("input", submitPointer);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      submitPointer();
    });
    main.appendChild(form);

    const orientation = node("button", "Toggle orientation");
    orientation.id = "teacher-orientation-toggle";
    orientation.type = "button";
    orientation.addEventListener("click", function () {
      safeInvoke(invoke, "teacher.orientation.toggle", {}, function (result) {
        applyTeacherEvent(root, result, invoke, announce, fallbackMessage);
      }, announce, fallbackMessage);
    });
    main.appendChild(orientation);
    main.appendChild(renderVisual(snapshot, invoke, announce, fallbackMessage));
    fragment.appendChild(main);
    root.replaceChildren(fragment);
    focusTarget(root, requestedFocus || "");
  }

  global.AccessibleChessTeacherSurface = Object.freeze({
    render: renderTeacherSurface,
    apply: applyTeacherEvent
  });
})(window);
