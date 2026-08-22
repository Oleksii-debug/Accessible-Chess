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

  function safeInvoke(invoke, command, payload, onResult, announce, fallbackMessage) {
    Promise.resolve(invoke(command, payload || {})).then(onResult).catch(function () {
      if (fallbackMessage) announce(String(fallbackMessage));
    });
  }

  function renderBookBlock(host, block) {
    const role = String(block.role || "group");
    let content;
    if (role === "heading") {
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
    if (!result || typeof result !== "object") return;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    if (result.kind === "render" && payload.snapshot) {
      renderBookSurface(root, payload.snapshot, invoke, announce, payload.focus_target || "", fallbackMessage);
    }
    if (payload.announcement) announce(String(payload.announcement));
    if (result.kind === "error" && payload.message) announce(String(payload.message));
  }

  function renderBookSurface(root, snapshot, invoke, announce, requestedFocus, fallbackMessage) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new TypeError("Book root must support replaceChildren");
    }
    requireFunction(invoke, "Book invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "Book announce");
    if (!snapshot || typeof snapshot !== "object") throw new TypeError("Book snapshot is required");

    const fragment = document.createDocumentFragment();
    const main = node("section");
    main.appendChild(node("h2", snapshot.heading || ""));
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
        safeInvoke(invoke, String(action.command || ""), {}, function (result) {
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
      safeInvoke(invoke, "book.bookmark.save", { name: input.value }, function (result) {
        applyBookEvent(root, result, invoke, announce, fallbackMessage);
      }, announce, fallbackMessage);
    });
    restore.addEventListener("click", function () {
      safeInvoke(invoke, "book.bookmark.restore", { name: input.value }, function (result) {
        applyBookEvent(root, result, invoke, announce, fallbackMessage);
      }, announce, fallbackMessage);
    });
    main.appendChild(form);

    fragment.appendChild(main);
    root.replaceChildren(fragment);
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
      safeInvoke(invoke, "training.reset", { confirmed: true }, function (result) {
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
    if (!result || typeof result !== "object") return;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    let priorAnswer = "";
    const prior = root.querySelector("#training-answer");
    if (prior && typeof prior.value === "string") priorAnswer = prior.value;
    if (result.kind === "render" && payload.snapshot) {
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

    const fragment = document.createDocumentFragment();
    const main = node("section");
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
      safeInvoke(invoke, "training.submit", { answer: input.value }, function (result) {
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
        safeInvoke(invoke, command, {}, function (result) {
          applyTrainingEvent(root, result, invoke, announce, fallbackMessage);
        }, announce, fallbackMessage);
      });
      toolbar.appendChild(button);
    });
    main.appendChild(toolbar);
    main.appendChild(resetDialog.dialog);

    fragment.appendChild(main);
    root.replaceChildren(fragment);
    focusTarget(root, requestedFocus || "");
  }

  global.AccessibleChessBookSurface = Object.freeze({ render: renderBookSurface });
  global.AccessibleChessTrainingSurface = Object.freeze({ render: renderTrainingSurface });
})(window);
