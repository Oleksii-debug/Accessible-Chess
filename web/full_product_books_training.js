(function (global) {
  "use strict";

  const inFlightRoots = new WeakMap();
  const renderEpochs = new WeakMap();
  const MAX_BOOKMARK_NAME = 80;
  const MAX_BOOK_BLOCK_VISIBLE_CHARS = 12 * 1024 * 1024;
  const MAX_BOOK_HEADING_PATH_PARTS = 6;
  const MAX_BOOK_HEADING_PATH_TEXT = 360;
  const MAX_STARTER_BOOKLETS = 24;
  const MAX_TRAINING_SOLUTION_MOVES = 64;
  const MAX_TRAINING_SOLUTION_TEXT = 128;

  function renderEpoch(root) {
    return renderEpochs.get(root) || 0;
  }

  function markRendered(root) {
    renderEpochs.set(root, renderEpoch(root) + 1);
    inFlightRoots.delete(root);
    setBusy(root, false);
  }

  function setBusy(root, busy) {
    if (!root || typeof root.setAttribute !== "function") return;
    if (busy) {
      root.setAttribute("aria-busy", "true");
      return;
    }
    if (typeof root.removeAttribute === "function") {
      root.removeAttribute("aria-busy");
    } else {
      root.setAttribute("aria-busy", "false");
    }
  }

  function requireFunction(value, name) {
    if (typeof value !== "function") throw new TypeError(name + " must be a function");
    return value;
  }

  function node(tag, text) {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
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

  function safeInvoke(root, invoke, command, payload, onResult, announce, fallbackMessage) {
    const startedAtEpoch = renderEpoch(root);
    const activeFlight = inFlightRoots.get(root);
    if (activeFlight && activeFlight.epoch === startedAtEpoch) return;
    const flight = { epoch: startedAtEpoch };
    inFlightRoots.set(root, flight);
    setBusy(root, true);

    function finish() {
      if (inFlightRoots.get(root) !== flight) return;
      inFlightRoots.delete(root);
      setBusy(root, false);
    }

    let result;
    try {
      result = invoke(command, payload || {});
    } catch (_) {
      finish();
      if (renderEpoch(root) === startedAtEpoch && fallbackMessage) {
        announce(String(fallbackMessage));
      }
      return;
    }
    Promise.resolve(result)
      .then(function (value) {
        if (renderEpoch(root) !== startedAtEpoch) return;
        return onResult(value);
      })
      .catch(function () {
        if (renderEpoch(root) === startedAtEpoch && fallbackMessage) {
          announce(String(fallbackMessage));
        }
      })
      .then(finish, finish);
  }

  function requireHostEvent(result, allowedKinds, surface) {
    if (!result || typeof result !== "object" || Array.isArray(result)) {
      throw new TypeError(surface + " host result must be an object");
    }
    if (typeof result.kind !== "string" || allowedKinds.indexOf(result.kind) < 0) {
      throw new TypeError(surface + " host result kind is invalid");
    }
    if (!result.payload || typeof result.payload !== "object" || Array.isArray(result.payload)) {
      throw new TypeError(surface + " host result payload must be an object");
    }
    if (
      result.kind === "render" &&
      (!result.payload.snapshot ||
        typeof result.payload.snapshot !== "object" ||
        Array.isArray(result.payload.snapshot))
    ) {
      throw new TypeError(surface + " render result requires a snapshot");
    }
    return result.payload;
  }

  function requireSnapshotRecord(snapshot, field, surface) {
    const value = snapshot[field];
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new TypeError(surface + " snapshot " + field + " must be an object");
    }
    return value;
  }

  function requireDocumentSpec(snapshot, surface) {
    const documentSpec = requireSnapshotRecord(snapshot, "document", surface);
    if (documentSpec.landmark !== "main") {
      throw new TypeError(surface + " snapshot landmark must be main");
    }
    if (documentSpec.lang !== "uk" && documentSpec.lang !== "en") {
      throw new TypeError(surface + " snapshot language is invalid");
    }
    return documentSpec;
  }

  function requireText(value, label, allowEmpty) {
    if (typeof value !== "string" || (!allowEmpty && !value)) {
      throw new TypeError(label + " must be text");
    }
    return value;
  }

  function requireBoundedText(value, label, allowEmpty, limit) {
    const text = requireText(value, label, allowEmpty);
    if (text.indexOf("\x00") >= 0 || text.length > limit) {
      throw new TypeError(label + " exceeds its canonical text contract");
    }
    return text;
  }

  function requireActions(actions, commands, surface) {
    if (!Array.isArray(actions) || actions.length !== commands.length) {
      throw new TypeError(surface + " snapshot actions are incomplete");
    }
    actions.forEach(function (action, index) {
      if (!action || typeof action !== "object" || Array.isArray(action)) {
        throw new TypeError(surface + " snapshot action is invalid");
      }
      if (action.command !== commands[index]) {
        throw new TypeError(surface + " snapshot action command/order is invalid");
      }
      if (typeof action.label !== "string" || !action.label) {
        throw new TypeError(surface + " snapshot action label is invalid");
      }
      if (typeof action.enabled !== "boolean") {
        throw new TypeError(surface + " snapshot action enabled flag is invalid");
      }
    });
  }

  function requireBookmarkSpec(snapshot) {
    const bookmark = requireSnapshotRecord(snapshot, "bookmark", "Book");
    requireBoundedText(bookmark.label, "Book bookmark label", false, 120);
    requireBoundedText(bookmark.value, "Book bookmark value", false, MAX_BOOKMARK_NAME);
    requireBoundedText(bookmark.save_label, "Book bookmark save label", false, 120);
    requireBoundedText(bookmark.restore_label, "Book bookmark restore label", false, 120);
    if (bookmark.max_length !== MAX_BOOKMARK_NAME) {
      throw new TypeError("Book bookmark max length is invalid");
    }
  }

  function requireStarterMaterials(snapshot) {
    const catalogue = snapshot.starter_materials;
    if (catalogue === undefined || catalogue === null) return;
    if (typeof catalogue !== "object" || Array.isArray(catalogue)) {
      throw new TypeError("Book starter catalogue must be an object");
    }
    requireBoundedText(catalogue.heading, "Book starter heading", false, 360);
    requireBoundedText(catalogue.label, "Book starter label", false, 120);
    requireBoundedText(catalogue.open_label, "Book starter open label", false, 120);
    requireBoundedText(catalogue.description, "Book starter description", true, 1200);
    requireBoundedText(catalogue.current_id, "Book starter current id", true, 80);
    if (!Number.isSafeInteger(catalogue.booklet_count) ||
        catalogue.booklet_count < 0 ||
        catalogue.booklet_count > MAX_STARTER_BOOKLETS) {
      throw new TypeError("Book starter booklet count is invalid");
    }
    if (!Array.isArray(catalogue.items) || catalogue.items.length !== catalogue.booklet_count + 1) {
      throw new TypeError("Book starter item count is inconsistent");
    }
    const ids = new Set();
    catalogue.items.forEach(function (item) {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        throw new TypeError("Book starter item is invalid");
      }
      requireBoundedText(item.material_id, "Book starter material id", false, 80);
      requireBoundedText(item.title, "Book starter material title", false, 360);
      if (ids.has(item.material_id)) {
        throw new TypeError("Book starter material id is duplicated");
      }
      ids.add(item.material_id);
    });
    if (catalogue.current_id && !ids.has(catalogue.current_id)) {
      throw new TypeError("Book starter current id is unknown");
    }
  }

  function requireBookSnapshot(snapshot) {
    const block = requireSnapshotRecord(snapshot, "block", "Book");
    requireDocumentSpec(snapshot, "Book");
    requireBoundedText(snapshot.heading, "Book snapshot heading", false, 360);
    requireBookmarkSpec(snapshot);
    requireStarterMaterials(snapshot);
    requireActions(
      snapshot.actions,
      [
        "book.previous",
        "book.next",
        "book.previous_heading",
        "book.next_heading",
        "book.previous_position",
        "book.next_position",
        "book.previous_game",
        "book.next_game",
        "book.open_position",
        "book.return_from_board"
      ],
      "Book"
    );
    if (!Number.isSafeInteger(block.index) || block.index < 0) {
      throw new TypeError("Book snapshot block index is invalid");
    }
    if (block.dom_id !== "book-block-" + String(block.index)) {
      throw new TypeError("Book snapshot block DOM id is not canonical");
    }
    const roles = ["heading", "paragraph", "img", "group", "tree", "note", "list"];
    if (typeof block.role !== "string" || roles.indexOf(block.role) < 0) {
      throw new TypeError("Book snapshot block role is invalid");
    }
    const roleByKind = {
      Heading: "heading",
      Paragraph: "paragraph",
      List: "list",
      Position: "group",
      Diagram: "img",
      Game: "group",
      VariationTree: "tree",
      Exercise: "group",
      Note: "note"
    };
    if (!Object.prototype.hasOwnProperty.call(roleByKind, block.kind) ||
        roleByKind[block.kind] !== block.role) {
      throw new TypeError("Book snapshot block kind/role is inconsistent");
    }
    requireBoundedText(block.kind, "Book snapshot block kind", true, 80);
    requireBoundedText(block.title, "Book snapshot block title", true, 360);
    requireBoundedText(
      block.text,
      "Book snapshot block text",
      true,
      MAX_BOOK_BLOCK_VISIBLE_CHARS
    );
    requireBoundedText(block.heading_path_label, "Book heading path label", false, 120);
    requireBoundedText(block.source_anchor, "Book source anchor", true, 160);
    requireBoundedText(block.source_label, "Book source label", false, 120);
    requireBoundedText(block.warning, "Book warning", true, 1000);
    if (typeof block.has_position !== "boolean") {
      throw new TypeError("Book snapshot position flag is invalid");
    }
    const positionKinds = ["Position", "Diagram", "Exercise", "VariationTree"];
    if (block.has_position !== (positionKinds.indexOf(block.kind) >= 0)) {
      throw new TypeError("Book snapshot position flag disagrees with semantic kind");
    }
    if (!Array.isArray(block.heading_path) ||
        block.heading_path.length > MAX_BOOK_HEADING_PATH_PARTS ||
        block.heading_path.some(function (part) {
          return typeof part !== "string" ||
            !part ||
            part.indexOf("\x00") >= 0 ||
            part.length > MAX_BOOK_HEADING_PATH_TEXT;
        })) {
      throw new TypeError("Book heading path is invalid");
    }
    if (block.role === "heading") {
      if (!Number.isSafeInteger(block.heading_level) ||
          block.heading_level < 1 ||
          block.heading_level > 6) {
        throw new TypeError("Book heading level is invalid");
      }
    } else if (block.heading_level !== null && block.heading_level !== undefined) {
      throw new TypeError("Non-heading Book block contains heading level");
    }
    const hasList = block.list !== undefined && block.list !== null;
    if (block.role === "list") {
      if (!hasList || typeof block.list !== "object" || Array.isArray(block.list)) {
        throw new TypeError("Book list block requires list metadata");
      }
      if (
        !Array.isArray(block.list.items) ||
        block.list.items.length < 1 ||
        block.list.items.some(function (item) {
          return typeof item !== "string" || !item || item.indexOf("\x00") >= 0;
        })
      ) {
        throw new TypeError("Book list items are invalid");
      }
      let listVisibleChars = 0;
      block.list.items.forEach(function (item) {
        listVisibleChars += item.length;
        if (listVisibleChars > MAX_BOOK_BLOCK_VISIBLE_CHARS) {
          throw new TypeError("Book list exceeds the canonical visible-text budget");
        }
      });
      if (typeof block.list.ordered !== "boolean") {
        throw new TypeError("Book list ordered flag is invalid");
      }
      if (
        block.list.start !== null &&
        block.list.start !== undefined &&
        (!Number.isSafeInteger(block.list.start) || block.list.start < 1)
      ) {
        throw new TypeError("Book list start is invalid");
      }
      if (!block.list.ordered && block.list.start !== null && block.list.start !== undefined) {
        throw new TypeError("Unordered Book list cannot define a start");
      }
    } else if (hasList) {
      throw new TypeError("Non-list Book block contains list metadata");
    }
    const openPosition = snapshot.actions[8];
    const returnFromBoard = snapshot.actions[9];
    if (openPosition.enabled !== block.has_position) {
      throw new TypeError("Book open-position action disagrees with block position state");
    }
    if (returnFromBoard.enabled !== true) {
      throw new TypeError("Book return action must remain enabled");
    }
  }

  function requireTrainingSnapshot(snapshot) {
    const progress = requireSnapshotRecord(snapshot, "progress", "Training");
    const answer = requireSnapshotRecord(snapshot, "answer", "Training");
    const resetDialog = requireSnapshotRecord(snapshot, "reset_dialog", "Training");
    requireDocumentSpec(snapshot, "Training");
    requireBoundedText(snapshot.heading, "Training snapshot heading", false, 360);
    requireBoundedText(snapshot.title, "Training snapshot title", false, 360);
    requireBoundedText(snapshot.message, "Training snapshot message", true, 1200);
    requireBoundedText(snapshot.solution_label, "Training solution label", false, 120);
    if (snapshot.status !== "ready" &&
        snapshot.status !== "in_progress" &&
        snapshot.status !== "completed") {
      throw new TypeError("Training status is invalid");
    }
    const counterFields = ["step", "total", "attempts", "mistakes", "hints_used"];
    counterFields.forEach(function (field) {
      if (!Number.isSafeInteger(progress[field]) || progress[field] < 0) {
        throw new TypeError("Training progress counter is invalid");
      }
    });
    if (progress.total < 1 || progress.step < 1 || progress.step > progress.total) {
      throw new TypeError("Training step counters are inconsistent");
    }
    if (progress.mistakes > progress.attempts) {
      throw new TypeError("Training mistakes exceed attempts");
    }
    if (typeof progress.completed !== "boolean" ||
        progress.completed !== (snapshot.status === "completed")) {
      throw new TypeError("Training completion state is inconsistent");
    }
    ["step_label", "of_label", "attempts_label", "mistakes_label", "hints_label"].forEach(
      function (field) { requireText(progress[field], "Training progress label", false); }
    );
    requireBoundedText(answer.label, "Training answer label", false, 120);
    requireBoundedText(answer.submit_label, "Training submit label", false, 120);
    if (answer.max_length !== MAX_TRAINING_SOLUTION_TEXT) {
      throw new TypeError("Training answer max length is invalid");
    }
    if (typeof answer.disabled !== "boolean" || answer.disabled !== progress.completed) {
      throw new TypeError("Training answer disabled state is inconsistent");
    }
    ["title", "text", "confirm_label", "cancel_label"].forEach(function (field) {
      requireBoundedText(resetDialog[field], "Training reset dialog text", false, 1200);
    });
    requireActions(
      snapshot.actions,
      [
        "training.hint",
        "training.reveal",
        "training.retry",
        "training.continue",
        "training.reset.request"
      ],
      "Training"
    );
    const expectedInteractive = !progress.completed;
    if (snapshot.actions[0].enabled !== expectedInteractive ||
        snapshot.actions[1].enabled !== expectedInteractive ||
        snapshot.actions[2].enabled !== expectedInteractive) {
      throw new TypeError("Training active actions disagree with completion state");
    }
    if (snapshot.actions[3].enabled && !progress.completed) {
      throw new TypeError("Training continue action is enabled before completion");
    }
    if (snapshot.actions[4].enabled !== true) {
      throw new TypeError("Training reset action must remain enabled");
    }
  }

  function renderBookBlock(host, block) {
    const role = String(block.role || "group");
    let content;
    if (block.list && Array.isArray(block.list.items)) {
      content = node(block.list.ordered ? "ol" : "ul");
      if (block.list.ordered && Number.isSafeInteger(block.list.start) && block.list.start > 0) {
        content.setAttribute("start", String(block.list.start));
      }
      block.list.items.forEach(function (text) { content.appendChild(node("li", text)); });
    } else if (role === "heading") {
      const level = Math.min(6, Math.max(1, Number(block.heading_level || 2)));
      content = node("h" + level, block.text || block.title || "");
    } else if (role === "paragraph") {
      content = node("p", block.text || "");
    } else if (role === "img") {
      content = node("figure");
      content.setAttribute("role", "img");
      content.setAttribute("aria-label", block.text || block.title || "");
      if (block.title) content.appendChild(node("figcaption", block.title));
      if (block.text && block.text !== block.title) content.appendChild(node("p", block.text));
    } else if (role === "note") {
      content = node("aside");
      content.setAttribute("role", "note");
      if (block.title) content.appendChild(node("h3", block.title));
      content.appendChild(node("p", block.text || ""));
    } else if (role === "tree") {
      content = node("div");
      content.setAttribute("role", "tree");
      const item = node("div", block.text || block.title || "");
      item.setAttribute("role", "treeitem");
      item.setAttribute("aria-level", "1");
      content.appendChild(item);
    } else {
      content = node("section");
      content.setAttribute("role", "group");
      if (block.title) content.appendChild(node("h3", block.title));
      if (block.text) content.appendChild(node("p", block.text));
    }
    content.id = String(block.dom_id || "");
    content.tabIndex = -1;
    host.appendChild(content);

    const headingPath = Array.isArray(block.heading_path) ? block.heading_path : [];
    if (headingPath.length) {
      const nav = node("nav");
      nav.setAttribute("aria-label", block.heading_path_label || "");
      const list = node("ol");
      headingPath.forEach(function (part) { list.appendChild(node("li", part)); });
      nav.appendChild(list);
      host.appendChild(nav);
    }
    if (block.source_anchor) {
      host.appendChild(node("p", (block.source_label || "") + ": " + block.source_anchor));
    }
    if (block.warning) {
      const warning = node("p", block.warning);
      warning.setAttribute("aria-live", "off");
      host.appendChild(warning);
    }
  }

  function applyBookEvent(root, result, invoke, announce, fallbackMessage) {
    const payload = requireHostEvent(result, ["render", "error", "delegated"], "Book");
    if (payload.announcement !== undefined) {
      requireBoundedText(payload.announcement, "Book announcement", true, 1000);
    }
    if (result.kind === "render") {
      requireBookSnapshot(payload.snapshot);
      if (typeof payload.focus_target !== "string" ||
          (payload.focus_target && payload.focus_target !== payload.snapshot.block.dom_id)) {
        throw new TypeError("Book render focus target is invalid");
      }
      renderBookSurface(root, payload.snapshot, invoke, announce, payload.focus_target, fallbackMessage);
    } else if (result.kind === "delegated") {
      if (payload.action !== "book.open_position") {
        throw new TypeError("Book delegated action is invalid");
      }
    } else if (typeof payload.message !== "string" || !payload.message) {
      throw new TypeError("Book error message is invalid");
    }
    if (payload.announcement) announce(payload.announcement);
    if (result.kind === "error") announce(payload.message);
  }

  function renderStarterMaterials(root, main, snapshot, invoke, announce, fallbackMessage) {
    const catalogue = snapshot.starter_materials;
    const items = catalogue && Array.isArray(catalogue.items) ? catalogue.items : [];
    if (!catalogue || !items.length) return;

    const section = node("section");
    const heading = node("h3", catalogue.heading || "");
    heading.id = "book-starter-materials-heading";
    section.setAttribute("aria-labelledby", heading.id);
    section.appendChild(heading);
    if (catalogue.description) section.appendChild(node("p", catalogue.description));

    const label = node("label", catalogue.label || "");
    const select = node("select");
    select.id = "book-starter-material";
    label.htmlFor = select.id;
    items.forEach(function (item) {
      if (!item || typeof item !== "object") return;
      const materialId = String(item.material_id || "");
      if (!materialId) return;
      const option = node("option", item.title || materialId);
      option.value = materialId;
      select.appendChild(option);
    });
    const currentId = String(catalogue.current_id || "");
    if (currentId && items.some(function (item) { return String(item.material_id || "") === currentId; })) {
      select.value = currentId;
    }
    label.appendChild(select);
    section.appendChild(label);

    const open = node("button", catalogue.open_label || "");
    open.type = "button";
    open.addEventListener("click", function () {
      const materialId = String(select.value || "");
      if (!materialId) return;
      safeInvoke(root, invoke, "book.open_starter_material", { material_id: materialId }, function (result) {
        applyBookEvent(root, result, invoke, announce, fallbackMessage);
      }, announce, fallbackMessage);
    });
    section.appendChild(open);
    main.appendChild(section);
  }

  function renderBookSurface(root, snapshot, invoke, announce, requestedFocus, fallbackMessage) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new TypeError("Book root must support replaceChildren");
    }
    requireFunction(invoke, "Book invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "Book announce");
    if (!snapshot || typeof snapshot !== "object") throw new TypeError("Book snapshot is required");
    requireBookSnapshot(snapshot);

    const fragment = document.createDocumentFragment();
    const main = node("main");
    main.setAttribute("lang", snapshot.document.lang);
    main.appendChild(node("h2", snapshot.heading || ""));
    renderStarterMaterials(root, main, snapshot, invoke, announce, fallbackMessage);
    const block = snapshot.block || {};
    renderBookBlock(main, block);

    const toolbar = node("div");
    toolbar.setAttribute("role", "toolbar");
    const actions = Array.isArray(snapshot.actions) ? snapshot.actions : [];
    actions.forEach(function (action) {
      const button = node("button", action.label || action.command || "");
      button.type = "button";
      button.disabled = !action.enabled;
      button.addEventListener("click", function () {
        safeInvoke(root, invoke, String(action.command || ""), {}, function (result) {
          applyBookEvent(root, result, invoke, announce, fallbackMessage);
        }, announce, fallbackMessage);
      });
      toolbar.appendChild(button);
    });
    main.appendChild(toolbar);

    const bookmark = snapshot.bookmark || {};
    const form = node("form");
    const label = node("label", bookmark.label || "");
    const input = node("input");
    input.id = "book-bookmark-name";
    input.type = "text";
    input.maxLength = Number(bookmark.max_length || 80);
    input.value = bookmark.value || "default";
    label.htmlFor = input.id;
    form.appendChild(label);
    form.appendChild(input);
    const save = node("button", bookmark.save_label || "");
    save.type = "submit";
    const restore = node("button", bookmark.restore_label || "");
    restore.type = "button";
    form.appendChild(save);
    form.appendChild(restore);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      safeInvoke(root, invoke, "book.bookmark.save", { name: input.value }, function (result) {
        applyBookEvent(root, result, invoke, announce, fallbackMessage);
      }, announce, fallbackMessage);
    });
    restore.addEventListener("click", function () {
      safeInvoke(root, invoke, "book.bookmark.restore", { name: input.value }, function (result) {
        applyBookEvent(root, result, invoke, announce, fallbackMessage);
      }, announce, fallbackMessage);
    });
    main.appendChild(form);

    fragment.appendChild(main);
    root.replaceChildren(fragment);
    markRendered(root);
    focusTarget(root, requestedFocus || "");
  }

  function buildResetDialog(root, spec, invoke, announce, fallbackMessage) {
    const dialog = node("dialog");
    dialog.id = "training-reset-dialog";
    const title = node("h3", spec.title || "");
    title.id = "training-reset-title";
    dialog.setAttribute("aria-labelledby", title.id);
    dialog.appendChild(title);
    dialog.appendChild(node("p", spec.text || ""));
    const confirm = node("button", spec.confirm_label || "");
    confirm.type = "button";
    const cancel = node("button", spec.cancel_label || "");
    cancel.type = "button";
    let opener = null;

    function closeAndRestore() {
      if (dialog.open) dialog.close();
      if (opener && typeof opener.focus === "function") opener.focus({ preventScroll: true });
    }

    confirm.addEventListener("click", function () {
      safeInvoke(root, invoke, "training.reset", { confirmed: true }, function (result) {
        applyTrainingEvent(root, result, invoke, announce, fallbackMessage);
        if (result && result.kind === "render" && dialog.open) dialog.close();
      }, announce, fallbackMessage);
    });
    cancel.addEventListener("click", closeAndRestore);
    dialog.addEventListener("cancel", function (event) {
      event.preventDefault();
      closeAndRestore();
    });
    dialog.appendChild(confirm);
    dialog.appendChild(cancel);
    return {
      dialog: dialog,
      open: function (button) {
        opener = button;
        dialog.showModal();
        confirm.focus();
      }
    };
  }

  function applyTrainingEvent(root, result, invoke, announce, fallbackMessage) {
    const payload = requireHostEvent(result, ["render", "error"], "Training");
    if (payload.announcement !== undefined) {
      requireBoundedText(payload.announcement, "Training announcement", true, 1200);
    }
    let priorAnswer = "";
    const prior = root.querySelector("#training-answer");
    if (prior && typeof prior.value === "string") priorAnswer = prior.value;
    if (result.kind === "render") {
      requireTrainingSnapshot(payload.snapshot);
      if (typeof payload.focus_target !== "string" ||
          (payload.focus_target && payload.focus_target !== "training-answer")) {
        throw new TypeError("Training render focus target is invalid");
      }
      if (payload.clear_answer !== undefined && typeof payload.clear_answer !== "boolean") {
        throw new TypeError("Training clear-answer flag is invalid");
      }
      if (payload.solution !== undefined &&
          (!Array.isArray(payload.solution) ||
           payload.solution.length > MAX_TRAINING_SOLUTION_MOVES ||
           payload.solution.some(function (move) {
             return typeof move !== "string" ||
               !move ||
               move.indexOf("\x00") >= 0 ||
               move.length > MAX_TRAINING_SOLUTION_TEXT;
           }))) {
        throw new TypeError("Training solution payload is invalid");
      }
      renderTrainingSurface(
        root,
        payload.snapshot,
        invoke,
        announce,
        payload.focus_target,
        fallbackMessage,
        payload.solution || []
      );
      if (!payload.clear_answer && priorAnswer) {
        const next = root.querySelector("#training-answer");
        if (next) next.value = priorAnswer;
      }
    } else if (typeof payload.message !== "string" || !payload.message) {
      throw new TypeError("Training error message is invalid");
    }
    if (payload.announcement) announce(payload.announcement);
    if (result.kind === "error") announce(payload.message);
  }

  function renderTrainingSurface(root, snapshot, invoke, announce, requestedFocus, fallbackMessage, solution) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new TypeError("Training root must support replaceChildren");
    }
    requireFunction(invoke, "Training invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "Training announce");
    if (!snapshot || typeof snapshot !== "object") throw new TypeError("Training snapshot is required");
    requireTrainingSnapshot(snapshot);

    const fragment = document.createDocumentFragment();
    const main = node("main");
    main.setAttribute("lang", snapshot.document.lang);
    main.appendChild(node("h2", snapshot.heading || ""));
    main.appendChild(node("h3", snapshot.title || ""));

    const progress = snapshot.progress || {};
    const stats = node("dl");
    [
      [progress.step_label, String(progress.step || 0) + " " + (progress.of_label || "") + " " + String(progress.total || 0)],
      [progress.attempts_label, progress.attempts],
      [progress.mistakes_label, progress.mistakes],
      [progress.hints_label, progress.hints_used]
    ].forEach(function (pair) {
      stats.appendChild(node("dt", pair[0] || ""));
      stats.appendChild(node("dd", pair[1]));
    });
    main.appendChild(stats);

    if (snapshot.message) {
      const message = node("p", snapshot.message);
      message.setAttribute("aria-live", "off");
      main.appendChild(message);
    }

    const answerSpec = snapshot.answer || {};
    const form = node("form");
    const label = node("label", answerSpec.label || "");
    const input = node("input");
    input.id = "training-answer";
    input.type = "text";
    input.maxLength = Number(answerSpec.max_length || 128);
    input.disabled = !!answerSpec.disabled;
    input.autocomplete = "off";
    input.spellcheck = false;
    label.htmlFor = input.id;
    const submit = node("button", answerSpec.submit_label || "");
    submit.type = "submit";
    submit.disabled = !!answerSpec.disabled;
    form.appendChild(label);
    form.appendChild(input);
    form.appendChild(submit);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      safeInvoke(root, invoke, "training.submit", { answer: input.value }, function (result) {
        applyTrainingEvent(root, result, invoke, announce, fallbackMessage);
      }, announce, fallbackMessage);
    });
    main.appendChild(form);

    if (Array.isArray(solution) && solution.length) {
      const solutionSection = node("section");
      solutionSection.appendChild(node("h3", snapshot.solution_label || ""));
      const list = node("ul");
      solution.forEach(function (move) { list.appendChild(node("li", move)); });
      solutionSection.appendChild(list);
      main.appendChild(solutionSection);
    }

    const resetDialog = buildResetDialog(root, snapshot.reset_dialog || {}, invoke, announce, fallbackMessage);
    const toolbar = node("div");
    toolbar.setAttribute("role", "toolbar");
    const actions = Array.isArray(snapshot.actions) ? snapshot.actions : [];
    actions.forEach(function (action) {
      const button = node("button", action.label || action.command || "");
      button.type = "button";
      button.disabled = !action.enabled;
      button.addEventListener("click", function () {
        const command = String(action.command || "");
        if (command === "training.reset.request") {
          const activeFlight = inFlightRoots.get(root);
          if (activeFlight && activeFlight.epoch === renderEpoch(root)) return;
          resetDialog.open(button);
          return;
        }
        safeInvoke(root, invoke, command, {}, function (result) {
          applyTrainingEvent(root, result, invoke, announce, fallbackMessage);
        }, announce, fallbackMessage);
      });
      toolbar.appendChild(button);
    });
    main.appendChild(toolbar);
    main.appendChild(resetDialog.dialog);

    fragment.appendChild(main);
    root.replaceChildren(fragment);
    markRendered(root);
    focusTarget(root, requestedFocus || "");
  }

  global.AccessibleChessBookSurface = Object.freeze({ render: renderBookSurface });
  global.AccessibleChessTrainingSurface = Object.freeze({ render: renderTrainingSurface });
})(window);
