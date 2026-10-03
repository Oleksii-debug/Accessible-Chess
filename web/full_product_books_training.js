(function (global) {
  "use strict";

  const MAX_BOOK_SEMANTIC_ITEMS = 10000;

  const TRAINING_ACTION_IDS = Object.freeze({
    "training.hint": "training-action-hint",
    "training.reveal": "training-action-reveal",
    "training.retry": "training-action-retry",
    "training.continue": "training-action-continue",
    "training.reset.request": "training-action-reset"
  });

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

  function semanticTextArray(value, name) {
    if (value === undefined || value === null) return [];
    if (!Array.isArray(value)) throw new TypeError(name + " must be an array");
    return value.map(function (item) {
      if (typeof item !== "string") throw new TypeError(name + " must contain text");
      return item;
    });
  }

  function semanticResult(value, name) {
    if (value === undefined || value === null || value === "") return "";
    if (typeof value !== "string") throw new TypeError(name + " must be text");
    if (!["1-0", "0-1", "1/2-1/2", "*"].includes(value)) {
      throw new TypeError(name + " is invalid");
    }
    return value;
  }

  function appendSemanticTextList(container, label, items, headingId) {
    if (!items.length) return;
    const heading = node("h4", label || "");
    heading.id = headingId;
    const list = node("ul");
    list.setAttribute("aria-labelledby", heading.id);
    items.forEach(function (item) {
      list.appendChild(node("li", item));
    });
    container.appendChild(heading);
    container.appendChild(list);
  }

  function renderBookSemanticTree(container, block) {
    const semantic = block.semantic_tree;
    if (!semantic || typeof semantic !== "object") {
      throw new TypeError("book semantic tree must be an object");
    }
    if (semantic.kind !== "game" && semantic.kind !== "variation") {
      throw new TypeError("book semantic tree kind is invalid");
    }

    if (semantic.players) {
      if (typeof semantic.players !== "string") {
        throw new TypeError("book semantic players must be text");
      }
      container.appendChild(node("p", String(semantic.players_label || "Players") + ": " + semantic.players));
    }

    const gameResult = semanticResult(semantic.result, "book semantic result");
    if (gameResult) {
      container.appendChild(node("p", String(semantic.result_label || "Result") + ": " + gameResult));
    }

    appendSemanticTextList(
      container,
      semantic.intro_comments_label || semantic.comments_label || "",
      semanticTextArray(semantic.intro_comments, "book semantic intro comments"),
      String(block.dom_id || "") + "-semantic-intro-heading"
    );

    const heading = node("h4", semantic.label || "");
    heading.id = String(block.dom_id || "") + "-semantic-heading";
    container.appendChild(heading);

    if (!Array.isArray(semantic.items)) {
      throw new TypeError("book semantic items must be an array");
    }
    const items = semantic.items;
    if (items.length > MAX_BOOK_SEMANTIC_ITEMS) {
      throw new TypeError("book semantic item limit exceeded");
    }
    const rootList = node("ol");
    rootList.setAttribute("aria-labelledby", heading.id);
    container.appendChild(rootList);

    const lists = [rootList];
    const lastItems = [];
    const deferredVariationEndings = [];
    let previousDepth = 0;

    items.forEach(function (item, index) {
      if (!item || typeof item !== "object") {
        throw new TypeError("book semantic item must be an object");
      }
      if (item.kind !== "move" && item.kind !== "variation") {
        throw new TypeError("book semantic item kind is invalid");
      }
      if (typeof item.label !== "string" || !item.label.trim()) {
        throw new TypeError("book semantic item label is invalid");
      }
      const depth = Number(item.depth);
      if (!Number.isSafeInteger(depth) || depth < 0) {
        throw new TypeError("book semantic item depth is invalid");
      }
      if ((index === 0 && depth !== 0) || (index > 0 && depth > previousDepth + 1)) {
        throw new TypeError("book semantic item depth is not contiguous");
      }
      while (lists.length > depth + 1) lists.pop();
      while (lists.length < depth + 1) {
        const parent = lastItems[lists.length - 1];
        if (!parent) throw new TypeError("book semantic nesting has no parent");
        const nested = node("ol");
        parent.appendChild(nested);
        lists.push(nested);
      }

      const listItem = node("li");
      const comments = semanticTextArray(item.comments, "book semantic item comments");
      const commentsBefore = semanticTextArray(
        item.comments_before,
        "book semantic comments before move"
      );
      const commentsAfter = semanticTextArray(
        item.comments_after,
        "book semantic comments after move"
      );
      const exactMoveComments = item.kind === "move" && (
        item.comments_before !== undefined || item.comments_after !== undefined
      );

      function appendItemComments(values) {
        if (!values.length) return;
        const commentList = node("ul");
        commentList.setAttribute("aria-label", semantic.comments_label || "");
        values.forEach(function (comment) {
          commentList.appendChild(node("li", comment));
        });
        listItem.appendChild(commentList);
      }

      if (exactMoveComments) appendItemComments(commentsBefore);
      listItem.appendChild(node("span", item.label));
      if (exactMoveComments) {
        appendItemComments(commentsAfter);
      } else {
        appendItemComments(comments);
      }

      const trailingComments = semanticTextArray(
        item.trailing_comments,
        "book semantic item trailing comments"
      );
      const itemResult = semanticResult(
        item.result,
        "book semantic item result"
      );
      if (item.kind !== "variation" && itemResult) {
        throw new TypeError("book semantic move must not carry a line result");
      }
      lists[depth].appendChild(listItem);
      if (itemResult || trailingComments.length) {
        deferredVariationEndings.push({
          item: listItem,
          result: itemResult,
          comments: trailingComments
        });
      }
      lastItems[depth] = listItem;
      lastItems.length = depth + 1;
      previousDepth = depth;
    });

    deferredVariationEndings.forEach(function (entry) {
      // A nested line's explicit result comes after its moves in PGN reading
      // order. Append only after the full depth walk has built the child list.
      if (entry.result) {
        entry.item.appendChild(
          node("p", String(semantic.result_label || "Result") + ": " + entry.result)
        );
      }
      if (entry.comments.length) {
        const commentList = node("ul");
        commentList.setAttribute("aria-label", semantic.comments_label || "");
        entry.comments.forEach(function (comment) {
          commentList.appendChild(node("li", comment));
        });
        // Tail comments follow both the nested moves and the line result.
        entry.item.appendChild(commentList);
      }
    });

    appendSemanticTextList(
      container,
      semantic.outro_comments_label || semantic.comments_label || "",
      semanticTextArray(semantic.outro_comments, "book semantic outro comments"),
      String(block.dom_id || "") + "-semantic-outro-heading"
    );

    appendSemanticTextList(
      container,
      semantic.warnings_label || "",
      semanticTextArray(semantic.warnings, "book semantic warnings"),
      String(block.dom_id || "") + "-semantic-warnings-heading"
    );
  }

  function renderBookBlock(host, block) {
    const role = String(block.role || "group");
    let content;
    if (block.semantic_tree && typeof block.semantic_tree === "object") {
      content = node("section");
      content.setAttribute("role", "group");
      if (block.title) {
        const title = node("h3", block.title);
        title.id = String(block.dom_id || "") + "-title";
        content.setAttribute("aria-labelledby", title.id);
        content.appendChild(title);
      }
      renderBookSemanticTree(content, block);
    } else if (block.list && Array.isArray(block.list.items)) {
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
    if (!result || typeof result !== "object") return;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    if (result.kind === "render" && payload.snapshot) {
      renderBookSurface(root, payload.snapshot, invoke, announce, payload.focus_target || "", fallbackMessage);
    }
    if (payload.announcement) announce(String(payload.announcement));
    if (result.kind === "error" && payload.message) announce(String(payload.message));
  }

  function renderStarterMaterials(main, snapshot, invoke, announce, fallbackMessage) {
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
      safeInvoke(invoke, "book.open_starter_material", { material_id: materialId }, function (result) {
        applyBookEvent(main.parentNode, result, invoke, announce, fallbackMessage);
      }, announce, fallbackMessage);
    });
    section.appendChild(open);
    main.appendChild(section);
  }

  function applySnapshotLanguage(element, snapshot) {
    const documentState = snapshot && snapshot.document && typeof snapshot.document === "object"
      ? snapshot.document
      : {};
    const language = typeof documentState.lang === "string"
      ? documentState.lang.trim().toLowerCase()
      : "";
    if (language === "en" || language === "uk") {
      element.setAttribute("lang", language);
    }
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
    applySnapshotLanguage(main, snapshot);
    main.appendChild(node("h2", snapshot.heading || ""));
    renderStarterMaterials(main, snapshot, invoke, announce, fallbackMessage);
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
    applySnapshotLanguage(main, snapshot);
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
      solutionSection.id = "training-solution";
      solutionSection.tabIndex = -1;
      const solutionHeading = node("h3", snapshot.solution_label || "");
      solutionHeading.id = "training-solution-heading";
      solutionSection.setAttribute("aria-labelledby", solutionHeading.id);
      solutionSection.appendChild(solutionHeading);
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
      const command = String(action.command || "");
      if (Object.prototype.hasOwnProperty.call(TRAINING_ACTION_IDS, command)) {
        button.id = TRAINING_ACTION_IDS[command];
      }
      button.addEventListener("click", function () {
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
