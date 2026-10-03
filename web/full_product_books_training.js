(function (global) {
  "use strict";

  const inFlightRoots = new WeakMap();
  const renderEpochs = new WeakMap();

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

  function requireBookSnapshot(snapshot) {
    const block = requireSnapshotRecord(snapshot, "block", "Book");
    requireSnapshotRecord(snapshot, "bookmark", "Book");
    requireDocumentSpec(snapshot, "Book");
    if (!Array.isArray(snapshot.actions)) {
      throw new TypeError("Book snapshot actions must be an array");
    }
    if (typeof block.dom_id !== "string" || !block.dom_id) {
      throw new TypeError("Book snapshot block requires a DOM id");
    }
  }

  function requireTrainingSnapshot(snapshot) {
    requireSnapshotRecord(snapshot, "progress", "Training");
    requireSnapshotRecord(snapshot, "answer", "Training");
    requireSnapshotRecord(snapshot, "reset_dialog", "Training");
    requireDocumentSpec(snapshot, "Training");
    if (!Array.isArray(snapshot.actions)) {
      throw new TypeError("Training snapshot actions must be an array");
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
    if (result.kind === "render") {
      requireBookSnapshot(payload.snapshot);
      renderBookSurface(root, payload.snapshot, invoke, announce, payload.focus_target || "", fallbackMessage);
    }
    if (payload.announcement) announce(String(payload.announcement));
    if (result.kind === "error" && payload.message) announce(String(payload.message));
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
        applyBookEvent(main.parentNode, result, invoke, announce, fallbackMessage);
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
    const main = node("main");\n    main.setAttribute("lang", snapshot.document.lang);
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
        if (dialog.open) dialog.close();
        applyTrainingEvent(root, result, invoke, announce, fallbackMessage);
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
    let priorAnswer = "";
    const prior = root.querySelector("#training-answer");
    if (prior && typeof prior.value === "string") priorAnswer = prior.value;
    if (result.kind === "render") {
      requireTrainingSnapshot(payload.snapshot);
      renderTrainingSurface(
        root,
        payload.snapshot,
        invoke,
        announce,
        payload.focus_target || "",
        fallbackMessage,
        Array.isArray(payload.solution) ? payload.solution : []
      );
      if (!payload.clear_answer && priorAnswer) {
        const next = root.querySelector("#training-answer");
        if (next) next.value = priorAnswer;
      }
    }
    if (payload.announcement) announce(String(payload.announcement));
    if (result.kind === "error" && payload.message) announce(String(payload.message));
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
    const main = node("main");\n    main.setAttribute("lang", snapshot.document.lang);
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
