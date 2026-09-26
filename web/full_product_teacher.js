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

  function svgNode(tag) {
    if (typeof document.createElementNS === "function") {
      return document.createElementNS("http://www.w3.org/2000/svg", tag);
    }
    return document.createElement(tag);
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

  function pieceMap(snapshot) {
    const pieces = Array.isArray(snapshot.pieces) ? snapshot.pieces : [];
    const result = Object.create(null);
    pieces.forEach(function (item) {
      if (!item || typeof item !== "object") return;
      const square = String(item.square || "");
      if (/^[a-h][1-8]$/.test(square)) result[square] = item;
    });
    return result;
  }

  function safeImageUrl(value) {
    const text = typeof value === "string" ? value : "";
    return /^data:image\/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(text) ? text : "";
  }

  function pieceAssetId(symbol) {
    const ids = {
      K: "white_king", Q: "white_queen", R: "white_rook",
      B: "white_bishop", N: "white_knight", P: "white_pawn",
      k: "black_king", q: "black_queen", r: "black_rook",
      b: "black_bishop", n: "black_knight", p: "black_pawn"
    };
    return ids[String(symbol || "")] || "";
  }

  function squareIsLight(square) {
    if (!/^[a-h][1-8]$/.test(square)) return false;
    return ((square.charCodeAt(0) - 97 + Number(square[1])) % 2) === 0;
  }

  function visibleCoordinate(square, mode, orientation) {
    if (mode === "off") return "";
    if (mode === "every_square") return square;
    if (mode !== "edges") return square;
    const bottomRank = orientation === "black" ? "8" : "1";
    const leftFile = orientation === "black" ? "h" : "a";
    let text = "";
    if (square[1] === bottomRank) text += square[0];
    if (square[0] === leftFile) text += square[1];
    return text;
  }

  function withCachedVisualAssets(root, snapshot) {
    if (!snapshot || typeof snapshot !== "object") return snapshot;
    const visual = snapshot.visual && typeof snapshot.visual === "object" ? snapshot.visual : null;
    if (!visual) return snapshot;
    const existingRegion = root && typeof root.querySelector === "function"
      ? root.querySelector("#teacher-visual-region")
      : null;
    const owner = existingRegion && existingRegion.parentNode ? existingRegion.parentNode : root;
    if (!owner) return snapshot;
    if (visual.assets && typeof visual.assets === "object") {
      owner.__accessibleChessVisualAssets = visual.assets;
      return snapshot;
    }
    if (!owner.__accessibleChessVisualAssets) return snapshot;
    const copy = Object.assign({}, snapshot);
    copy.visual = Object.assign({}, visual, { assets: owner.__accessibleChessVisualAssets });
    return copy;
  }

  function optionNode(value, text, disabled) {
    const option = node("option", text);
    option.value = String(value);
    option.disabled = Boolean(disabled);
    return option;
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

  function cellCenter(cell) {
    if (!cell || typeof cell !== "object") return null;
    const row = Number(cell.row);
    const column = Number(cell.column);
    if (!Number.isInteger(row) || row < 1 || row > 8 || !Number.isInteger(column) || column < 1 || column > 8) return null;
    return { x: column - 0.5, y: row - 0.5 };
  }

  function renderArrowOverlay(arrows) {
    const overlay = svgNode("svg");
    overlay.id = "teacher-arrow-overlay";
    overlay.setAttribute("viewBox", "0 0 8 8");
    overlay.setAttribute("preserveAspectRatio", "none");
    overlay.setAttribute("aria-hidden", "true");
    overlay.style.position = "absolute";
    overlay.style.inset = "0";
    overlay.style.width = "100%";
    overlay.style.height = "100%";
    overlay.style.pointerEvents = "none";

    arrows.forEach(function (arrow, index) {
      const start = cellCenter(arrow.start_cell);
      const end = cellCenter(arrow.end_cell);
      if (!start || !end) return;
      const color = String(arrow.color || "#ffa726");
      const markerId = "teacher-arrow-head-" + index;
      const defs = svgNode("defs");
      const marker = svgNode("marker");
      marker.setAttribute("id", markerId);
      marker.setAttribute("markerWidth", "0.8");
      marker.setAttribute("markerHeight", "0.8");
      marker.setAttribute("refX", "0.65");
      marker.setAttribute("refY", "0.3");
      marker.setAttribute("orient", "auto");
      marker.setAttribute("markerUnits", "userSpaceOnUse");
      const head = svgNode("path");
      head.setAttribute("d", "M0,0 L0.7,0.3 L0,0.6 z");
      head.setAttribute("fill", color);
      marker.appendChild(head);
      defs.appendChild(marker);
      overlay.appendChild(defs);

      const line = svgNode("line");
      line.setAttribute("x1", String(start.x));
      line.setAttribute("y1", String(start.y));
      line.setAttribute("x2", String(end.x));
      line.setAttribute("y2", String(end.y));
      line.setAttribute("stroke", color);
      line.setAttribute("stroke-width", "0.12");
      line.setAttribute("stroke-linecap", "round");
      line.setAttribute("vector-effect", "non-scaling-stroke");
      line.setAttribute("marker-end", "url(#" + markerId + ")");
      line.setAttribute("data-start-square", String(arrow.start_square || ""));
      line.setAttribute("data-end-square", String(arrow.end_square || ""));
      line.setAttribute("data-purpose", String(arrow.purpose || "custom"));
      overlay.appendChild(line);
    });
    return overlay;
  }

  function renderVisual(snapshot, invoke, announce, fallbackMessage) {
    const visual = node("section");
    visual.id = "teacher-visual-region";
    const boardState = snapshot.board || {};
    const visualState = snapshot.visual && typeof snapshot.visual === "object" ? snapshot.visual : null;
    const preferences = visualState && visualState.preferences && typeof visualState.preferences === "object"
      ? visualState.preferences
      : null;
    const effective = visualState && visualState.effective && typeof visualState.effective === "object"
      ? visualState.effective
      : {};
    const assets = visualState && visualState.assets && typeof visualState.assets === "object"
      ? visualState.assets
      : {};
    const boardAssets = assets.board && typeof assets.board === "object" ? assets.board : {};
    const pieceAssets = assets.pieces && typeof assets.pieces === "object" ? assets.pieces : {};
    const pieces = pieceMap(snapshot);

    if (preferences) {
      const controls = node("fieldset");
      controls.id = "teacher-visual-controls";
      controls.appendChild(node("legend", "Board appearance"));

      function updateField(field, value) {
        safeInvoke(invoke, "teacher.visual.update", { field: field, value: value }, function (result) {
          applyTeacherEvent(visual.parentNode, result, invoke, announce, fallbackMessage);
        }, announce, fallbackMessage);
      }

      function addSelect(id, labelText, field, rows, value) {
        const label = node("label", labelText);
        const select = node("select");
        select.id = id;
        label.htmlFor = id;
        rows.forEach(function (item) {
          if (!item || typeof item !== "object") return;
          const option = optionNode(
            item.pack_id || "",
            String(item.title || item.pack_id || ""),
            item.renderable === false
          );
          select.appendChild(option);
        });
        select.value = String(value || "classic");
        select.addEventListener("change", function () {
          updateField(field, String(select.value));
        });
        controls.appendChild(label);
        controls.appendChild(select);
      }

      const themes = visualState.themes && typeof visualState.themes === "object" ? visualState.themes : {};
      addSelect(
        "teacher-visual-board-theme",
        "Board theme",
        "board_theme_id",
        Array.isArray(themes.board) ? themes.board : [],
        preferences.board_theme_id
      );
      addSelect(
        "teacher-visual-piece-theme",
        "Piece theme",
        "piece_theme_id",
        Array.isArray(themes.pieces) ? themes.pieces : [],
        preferences.piece_theme_id
      );

      const coordinateLabel = node("label", "Visible coordinates");
      const coordinate = node("select");
      coordinate.id = "teacher-visual-coordinate-mode";
      coordinateLabel.htmlFor = coordinate.id;
      coordinate.appendChild(optionNode("off", "Off", false));
      coordinate.appendChild(optionNode("edges", "Board edges", false));
      coordinate.appendChild(optionNode("every_square", "Every square", false));
      coordinate.value = String(preferences.coordinate_mode || "edges");
      coordinate.addEventListener("change", function () {
        updateField("coordinate_mode", String(coordinate.value));
      });
      controls.appendChild(coordinateLabel);
      controls.appendChild(coordinate);

      function addScale(id, labelText, field, value, minimum, maximum) {
        const label = node("label", labelText);
        const input = node("input");
        input.id = id;
        input.type = "number";
        input.min = String(minimum);
        input.max = String(maximum);
        input.step = "5";
        input.value = String(value);
        label.htmlFor = id;
        input.addEventListener("change", function () {
          const parsed = Number(input.value);
          if (Number.isInteger(parsed)) updateField(field, parsed);
        });
        controls.appendChild(label);
        controls.appendChild(input);
      }

      addScale(
        "teacher-visual-board-scale",
        "Board size percent",
        "board_scale_percent",
        preferences.board_scale_percent,
        50,
        200
      );
      addScale(
        "teacher-visual-piece-scale",
        "Piece size percent",
        "piece_scale_percent",
        preferences.piece_scale_percent,
        50,
        150
      );

      function addFlag(id, labelText, field, checked) {
        const label = node("label", labelText);
        const input = node("input");
        input.id = id;
        input.type = "checkbox";
        input.checked = checked === true;
        label.htmlFor = id;
        input.addEventListener("change", function () {
          updateField(field, Boolean(input.checked));
        });
        controls.appendChild(label);
        controls.appendChild(input);
      }

      addFlag(
        "teacher-visual-show-last-move",
        "Show last move",
        "show_last_move",
        preferences.show_last_move
      );
      addFlag(
        "teacher-visual-reduced-motion",
        "Reduce motion",
        "reduced_motion",
        preferences.reduced_motion
      );

      const reset = node("button", "Reset appearance");
      reset.id = "teacher-visual-reset";
      reset.type = "button";
      reset.addEventListener("click", function () {
        safeInvoke(invoke, "teacher.visual.reset", {}, function (result) {
          applyTeacherEvent(visual.parentNode, result, invoke, announce, fallbackMessage);
        }, announce, fallbackMessage);
      });
      controls.appendChild(reset);
      visual.appendChild(controls);
    }
    const boardWrap = node("div");
    boardWrap.id = "teacher-board-wrap";
    boardWrap.style.position = "relative";
    boardWrap.setAttribute("data-board-theme", String(effective.board_theme_id || "classic"));
    boardWrap.setAttribute(
      "data-reduced-motion",
      preferences && preferences.reduced_motion === true ? "true" : "false"
    );
    const boardScale = preferences ? Number(preferences.board_scale_percent) : 100;
    if (Number.isInteger(boardScale) && boardScale >= 50 && boardScale <= 200) {
      boardWrap.style.width = "min(100%, " + String(32 * boardScale / 100) + "rem)";
    }
    const grid = node("div");
    grid.id = "teacher-visual-board";
    grid.setAttribute("role", "grid");
    grid.setAttribute("aria-label", "Teaching board");
    grid.setAttribute("data-piece-theme", String(effective.piece_theme_id || "classic"));
    grid.style.display = "grid";
    grid.style.gridTemplateColumns = "repeat(8, minmax(2.5rem, 1fr))";
    const orientation = String(boardState.orientation || "white");
    const coordinateMode = boardState.coordinates_visible === false
      ? "off"
      : (preferences ? String(preferences.coordinate_mode || "edges") : "every_square");
    grid.setAttribute("data-coordinate-mode", coordinateMode);
    const pieceScale = preferences ? Number(preferences.piece_scale_percent) : 100;
    boardSquares(orientation).forEach(function (square) {
      const cell = node("div");
      cell.setAttribute("role", "gridcell");
      const piece = pieces[square] || null;
      const coordinate = visibleCoordinate(square, coordinateMode, orientation);
      const glyph = piece ? String(piece.glyph || "") : "";
      const pieceId = piece ? pieceAssetId(piece.symbol) : "";
      const pieceUrl = pieceId ? safeImageUrl(pieceAssets[pieceId]) : "";
      const visibleText = piece
        ? (pieceUrl ? coordinate : (glyph + (coordinate ? " " + coordinate : "")))
        : coordinate;
      const button = node("button", visibleText);
      button.type = "button";
      button.id = "teacher-square-" + square;
      button.setAttribute("data-square", square);
      button.setAttribute("data-piece", piece ? String(piece.symbol || "") : "");
      button.setAttribute("aria-label", piece && piece.name ? square + ", " + String(piece.name) : square);
      const squareAsset = safeImageUrl(
        boardAssets[squareIsLight(square) ? "light_square" : "dark_square"]
      );
      if (squareAsset) {
        button.style.backgroundImage = 'url("' + squareAsset + '")';
        button.style.backgroundSize = "cover";
      }
      if (Number.isInteger(pieceScale) && pieceScale >= 50 && pieceScale <= 150) {
        button.style.fontSize = String(pieceScale / 100) + "em";
      }
      if (pieceUrl) {
        const image = node("img");
        image.src = pieceUrl;
        image.alt = "";
        image.draggable = false;
        image.setAttribute("aria-hidden", "true");
        image.setAttribute("data-piece-image", pieceId);
        button.appendChild(image);
      }
      applySquareState(button, snapshot);
      button.addEventListener("mouseenter", function () {
        safeInvoke(invoke, "teacher.student_event", {
          kind: "hover",
          square: square,
          piece_name: piece && piece.name ? String(piece.name) : ""
        }, function (result) {
          applyTeacherEvent(visual.parentNode, result, invoke, announce, fallbackMessage);
        }, announce, fallbackMessage);
      });
      button.addEventListener("click", function () {
        safeInvoke(invoke, "teacher.student_event", {
          kind: "select",
          square: square,
          piece_name: piece && piece.name ? String(piece.name) : ""
        }, function (result) {
          applyTeacherEvent(visual.parentNode, result, invoke, announce, fallbackMessage);
        }, announce, fallbackMessage);
      });
      cell.appendChild(button);
      grid.appendChild(cell);
    });
    boardWrap.appendChild(grid);

    const arrows = Array.isArray(snapshot.arrows) ? snapshot.arrows : [];
    if (arrows.length) boardWrap.appendChild(renderArrowOverlay(arrows));
    visual.appendChild(boardWrap);

    const summary = node("p", snapshot.accessible_summary || "");
    summary.id = "teacher-accessible-summary";
    summary.setAttribute("aria-live", "off");
    visual.appendChild(summary);
    return visual;
  }

  function replaceVisual(root, snapshot, invoke, announce, fallbackMessage) {
    const previous = root.querySelector("#teacher-visual-region");
    const hydrated = withCachedVisualAssets(root, snapshot);
    const replacement = renderVisual(hydrated, invoke, announce, fallbackMessage);
    if (previous && typeof previous.replaceWith === "function") previous.replaceWith(replacement);
  }

  function applyTeacherEvent(root, result, invoke, announce, fallbackMessage, preservePointerEditorValue) {
    if (!root || !result || typeof result !== "object") return;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    if ((result.kind === "render-pointer" || result.kind === "render-visual") && payload.snapshot) {
      replaceVisual(root, payload.snapshot, invoke, announce, fallbackMessage);
    }
    if (payload.clear_editor && !preservePointerEditorValue) {
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

    let pointerRequestSequence = 0;
    function submitPointer() {
      if (input.value.length !== 2) return;
      const coordinate = input.value;
      input.value = "";
      pointerRequestSequence += 1;
      const requestSequence = pointerRequestSequence;
      safeInvoke(invoke, "teacher.pointer_input", { coordinate: coordinate }, function (result) {
        if (requestSequence !== pointerRequestSequence) return;
        applyTeacherEvent(root, result, invoke, announce, fallbackMessage, true);
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
    const hydrated = withCachedVisualAssets(main, snapshot);
    main.appendChild(renderVisual(hydrated, invoke, announce, fallbackMessage));
    fragment.appendChild(main);
    root.replaceChildren(fragment);
    focusTarget(root, requestedFocus || "");
  }

  global.AccessibleChessTeacherSurface = Object.freeze({
    render: renderTeacherSurface,
    apply: applyTeacherEvent
  });
})(window);
