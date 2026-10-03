(function (global) {
  "use strict";

  const MAX_BOOK_SEMANTIC_ITEMS = 10000;
  const MAX_BOOK_SEMANTIC_DEPTH = 256;
  const MAX_BOOK_SEMANTIC_VISIBLE_CHARS = 12 * 1024 * 1024;
  const MAX_BOOK_SEMANTIC_DETAILS = 4;
  const MAX_BOOK_SEMANTIC_TEXT_ENTRIES = 50128;
  const BOOK_SEMANTIC_DETAIL_KINDS = Object.freeze({
    event: true,
    site: true,
    date: true,
    round: true
  });
  const BOOK_SEMANTIC_RESULTS = Object.freeze({
    "1-0": true,
    "0-1": true,
    "1/2-1/2": true,
    "*": true
  });
  const BOOK_ACTION_ORDER = Object.freeze([
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
  ]);
  const BOOK_ACTION_IDS = Object.freeze(
    BOOK_ACTION_ORDER.reduce(function (out, command) {
      out[command] = true;
      return out;
    }, Object.create(null))
  );
  const MAX_STARTER_MATERIALS = 64;
  const MAX_STARTER_TEXT = 360;
  const BOOKMARK_MAX_LENGTH = 80;

  const TRAINING_ANSWER_MAX_LENGTH = 128;
  const MAX_TRAINING_ACTIONS = 5;
  const MAX_TRAINING_SOLUTION_MOVES = 64;
  const TRAINING_STATUS_IDS = Object.freeze({
    ready: true,
    in_progress: true,
    completed: true
  });

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

  function semanticText(value, name, budget) {
    if (typeof value !== "string") throw new TypeError(name + " must be text");
    budget.entries += 1;
    if (budget.entries > MAX_BOOK_SEMANTIC_TEXT_ENTRIES) {
      throw new TypeError("book semantic text-entry budget exceeded");
    }
    budget.used += value.length;
    if (budget.used > MAX_BOOK_SEMANTIC_VISIBLE_CHARS) {
      throw new TypeError("book semantic visible-text budget exceeded");
    }
    return value;
  }

  function semanticOptionalText(value, name, budget, fallback) {
    if (value === undefined || value === null || value === "") return fallback;
    return semanticText(value, name, budget);
  }

  function semanticRequiredText(value, name, budget) {
    const text = semanticText(value, name, budget);
    if (!text.trim()) throw new TypeError(name + " must contain visible text");
    return text;
  }

  function semanticTextArray(value, name, budget) {
    if (!Array.isArray(value)) throw new TypeError(name + " must be an array");
    if (value.length > MAX_BOOK_SEMANTIC_TEXT_ENTRIES) {
      throw new TypeError(name + " has too many entries");
    }
    const out = [];
    for (let index = 0; index < value.length; index += 1) {
      if (!Object.prototype.hasOwnProperty.call(value, index)) {
        throw new TypeError(name + " must be dense");
      }
      const text = semanticText(value[index], name, budget);
      if (!text.trim()) throw new TypeError(name + " must contain visible text");
      out.push(text);
    }
    return out;
  }

  function semanticDetails(value, budget) {
    if (!Array.isArray(value)) throw new TypeError("book semantic details must be an array");
    if (value.length > MAX_BOOK_SEMANTIC_DETAILS) {
      throw new TypeError("book semantic details limit exceeded");
    }
    const out = [];
    for (let index = 0; index < value.length; index += 1) {
      if (!Object.prototype.hasOwnProperty.call(value, index)) {
        throw new TypeError("book semantic details must be dense");
      }
      const item = value[index];
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        throw new TypeError("book semantic detail must be an object");
      }
      const kind = item.kind;
      if (
        typeof kind !== "string" ||
        !Object.prototype.hasOwnProperty.call(BOOK_SEMANTIC_DETAIL_KINDS, kind)
      ) {
        throw new TypeError("book semantic detail kind is invalid");
      }
      if (out.some(function (entry) { return entry.kind === kind; })) {
        throw new TypeError("book semantic detail kind is duplicated");
      }
      const label = semanticRequiredText(
        item.label, "book semantic detail label", budget
      );
      const detailValue = semanticRequiredText(
        item.value, "book semantic detail value", budget
      );
      out.push({ kind: kind, label: label, value: detailValue });
    }
    return out;
  }

  function requiredUiText(value, name, maxLength) {
    if (typeof value !== "string" || !value.trim()) {
      throw new TypeError(name + " must contain visible text");
    }
    if (!Number.isSafeInteger(maxLength) || maxLength < 1 || value.length > maxLength) {
      throw new TypeError(name + " exceeds its text limit");
    }
    return value;
  }

  function validateBookActions(value) {
    if (!Array.isArray(value) || value.length !== BOOK_ACTION_ORDER.length) {
      throw new TypeError("book actions must contain the canonical command set");
    }
    return value.map(function (action, index) {
      if (!Object.prototype.hasOwnProperty.call(value, index)) {
        throw new TypeError("book actions must be dense");
      }
      if (!action || typeof action !== "object" || Array.isArray(action)) {
        throw new TypeError("book action must be an object");
      }
      const command = action.command;
      if (
        command !== BOOK_ACTION_ORDER[index] ||
        !Object.prototype.hasOwnProperty.call(BOOK_ACTION_IDS, command)
      ) {
        throw new TypeError("book action order/identity is invalid");
      }
      if (typeof action.enabled !== "boolean") {
        throw new TypeError("book action enabled flag is invalid");
      }
      return {
        command: command,
        label: requiredUiText(action.label, "book action label", 160),
        enabled: action.enabled
      };
    });
  }

  function validateBookmark(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new TypeError("book bookmark specification is invalid");
    }
    if (value.max_length !== BOOKMARK_MAX_LENGTH) {
      throw new TypeError("book bookmark length contract is invalid");
    }
    const bookmarkValue = requiredUiText(
      value.value, "book bookmark value", BOOKMARK_MAX_LENGTH
    );
    return {
      label: requiredUiText(value.label, "book bookmark label", 160),
      value: bookmarkValue,
      save_label: requiredUiText(value.save_label, "book bookmark save label", 160),
      restore_label: requiredUiText(
        value.restore_label, "book bookmark restore label", 160
      ),
      max_length: BOOKMARK_MAX_LENGTH
    };
  }

  function validateStarterCatalogue(value) {
    if (value === undefined || value === null) return null;
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new TypeError("starter material catalogue must be an object");
    }
    if (
      !Array.isArray(value.items) ||
      value.items.length < 1 ||
      value.items.length > MAX_STARTER_MATERIALS
    ) {
      throw new TypeError("starter material inventory is invalid");
    }
    const seen = Object.create(null);
    const items = value.items.map(function (item, index) {
      if (!Object.prototype.hasOwnProperty.call(value.items, index)) {
        throw new TypeError("starter material inventory must be dense");
      }
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        throw new TypeError("starter material entry must be an object");
      }
      const materialId = requiredUiText(
        item.material_id, "starter material id", 160
      );
      if (seen[materialId]) throw new TypeError("starter material id is duplicated");
      seen[materialId] = true;
      return {
        material_id: materialId,
        title: requiredUiText(item.title, "starter material title", MAX_STARTER_TEXT)
      };
    });
    const currentId = value.current_id;
    if (
      typeof currentId !== "string" ||
      (currentId && !Object.prototype.hasOwnProperty.call(seen, currentId))
    ) {
      throw new TypeError("starter material current id is invalid");
    }
    if (
      !Number.isSafeInteger(value.booklet_count) ||
      value.booklet_count < 0 ||
      value.booklet_count !== items.length - 1
    ) {
      throw new TypeError("starter material booklet count is invalid");
    }
    if (typeof value.description !== "string" || value.description.length > 2000) {
      throw new TypeError("starter material description is invalid");
    }
    return {
      heading: requiredUiText(value.heading, "starter material heading", MAX_STARTER_TEXT),
      label: requiredUiText(value.label, "starter material label", MAX_STARTER_TEXT),
      open_label: requiredUiText(
        value.open_label, "starter material open label", MAX_STARTER_TEXT
      ),
      description: value.description,
      current_id: currentId,
      booklet_count: value.booklet_count,
      items: items
    };
  }

  function validateBookBlock(block) {
    if (!block || typeof block !== "object" || Array.isArray(block)) {
      throw new TypeError("Book snapshot block is required");
    }
    if (!Number.isSafeInteger(block.index) || block.index < 0) {
      throw new TypeError("Book snapshot block index is invalid");
    }
    const expectedBlockId = "book-block-" + String(block.index);
    if (block.dom_id !== expectedBlockId) {
      throw new TypeError("Book snapshot block identity is invalid");
    }
    const roles = {
      heading: true,
      paragraph: true,
      img: true,
      group: true,
      tree: true,
      note: true,
      list: true
    };
    if (
      typeof block.role !== "string" ||
      !Object.prototype.hasOwnProperty.call(roles, block.role)
    ) {
      throw new TypeError("Book block role is invalid");
    }
    ["kind", "title", "text", "source_anchor", "source_label", "warning"].forEach(
      function (name) {
        if (
          block[name] !== undefined &&
          block[name] !== null &&
          typeof block[name] !== "string"
        ) {
          throw new TypeError("Book block " + name + " must be text");
        }
      }
    );
    if (block.has_position !== undefined && typeof block.has_position !== "boolean") {
      throw new TypeError("Book block position flag is invalid");
    }
    if (
      block.heading_level !== undefined &&
      block.heading_level !== null &&
      (!Number.isSafeInteger(block.heading_level) ||
        block.heading_level < 1 ||
        block.heading_level > 6)
    ) {
      throw new TypeError("Book heading level is invalid");
    }
    if (!Array.isArray(block.heading_path)) {
      throw new TypeError("Book heading path must be an array");
    }
    for (let index = 0; index < block.heading_path.length; index += 1) {
      if (
        !Object.prototype.hasOwnProperty.call(block.heading_path, index) ||
        typeof block.heading_path[index] !== "string" ||
        !block.heading_path[index].trim()
      ) {
        throw new TypeError("Book heading path is invalid");
      }
    }
    if (block.heading_path.length && (
      typeof block.heading_path_label !== "string" ||
      !block.heading_path_label.trim()
    )) {
      throw new TypeError("Book heading path label is invalid");
    }
    if (block.source_anchor && (
      typeof block.source_label !== "string" || !block.source_label.trim()
    )) {
      throw new TypeError("Book source label is invalid");
    }

    const hasList = block.list !== undefined && block.list !== null;
    if (block.role === "list") {
      if (!hasList || typeof block.list !== "object" || Array.isArray(block.list)) {
        throw new TypeError("Book list specification is invalid");
      }
      if (
        !Array.isArray(block.list.items) ||
        block.list.items.length < 1 ||
        typeof block.list.ordered !== "boolean"
      ) {
        throw new TypeError("Book list contents are invalid");
      }
      for (let index = 0; index < block.list.items.length; index += 1) {
        if (
          !Object.prototype.hasOwnProperty.call(block.list.items, index) ||
          typeof block.list.items[index] !== "string" ||
          !block.list.items[index].trim()
        ) {
          throw new TypeError("Book list items are invalid");
        }
      }
      if (
        block.list.start !== null &&
        block.list.start !== undefined &&
        (!Number.isSafeInteger(block.list.start) || block.list.start < 1)
      ) {
        throw new TypeError("Book list start is invalid");
      }
      if (!block.list.ordered && block.list.start !== null && block.list.start !== undefined) {
        throw new TypeError("unordered Book list cannot have a start");
      }
    } else if (hasList) {
      throw new TypeError("non-list Book block contains list metadata");
    }
    return expectedBlockId;
  }

  function validateBookLanguage(snapshot) {
    if (
      !snapshot.document ||
      typeof snapshot.document !== "object" ||
      Array.isArray(snapshot.document) ||
      (snapshot.document.lang !== "en" && snapshot.document.lang !== "uk")
    ) {
      throw new TypeError("Book document language is invalid");
    }
    return snapshot.document.lang;
  }

  function validateTrainingSnapshot(snapshot, solution, requestedFocus) {
    if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) {
      throw new TypeError("Training snapshot is required");
    }
    if (
      !snapshot.document ||
      typeof snapshot.document !== "object" ||
      Array.isArray(snapshot.document) ||
      (snapshot.document.lang !== "en" && snapshot.document.lang !== "uk")
    ) {
      throw new TypeError("Training document language is invalid");
    }
    requiredUiText(snapshot.heading, "Training heading", 360);
    requiredUiText(snapshot.title, "Training title", 360);
    if (
      snapshot.status !== "ready" &&
      snapshot.status !== "in_progress" &&
      snapshot.status !== "completed"
    ) {
      throw new TypeError("Training status is invalid");
    }
    if (typeof snapshot.message !== "string" || snapshot.message.length > 1200) {
      throw new TypeError("Training message is invalid");
    }

    const progress = snapshot.progress;
    if (!progress || typeof progress !== "object" || Array.isArray(progress)) {
      throw new TypeError("Training progress is invalid");
    }
    ["step_label", "of_label", "attempts_label", "mistakes_label", "hints_label"].forEach(
      function (name) {
        requiredUiText(progress[name], "Training progress label", 160);
      }
    );
    ["step", "total", "attempts", "mistakes", "hints_used"].forEach(function (name) {
      if (!Number.isSafeInteger(progress[name]) || progress[name] < 0) {
        throw new TypeError("Training progress counter is invalid");
      }
    });
    if (
      progress.total < 1 ||
      progress.step < 1 ||
      progress.step > progress.total ||
      progress.mistakes > progress.attempts ||
      typeof progress.completed !== "boolean" ||
      progress.completed !== (snapshot.status === "completed")
    ) {
      throw new TypeError("Training progress state is inconsistent");
    }

    const answer = snapshot.answer;
    if (!answer || typeof answer !== "object" || Array.isArray(answer)) {
      throw new TypeError("Training answer specification is invalid");
    }
    requiredUiText(answer.label, "Training answer label", 160);
    requiredUiText(answer.submit_label, "Training submit label", 160);
    if (
      answer.max_length !== 128 ||
      typeof answer.disabled !== "boolean" ||
      answer.disabled !== progress.completed
    ) {
      throw new TypeError("Training answer state is inconsistent");
    }

    if (!Array.isArray(snapshot.actions) || snapshot.actions.length !== 5) {
      throw new TypeError("Training actions are invalid");
    }
    const expectedCommands = [
      "training.hint",
      "training.reveal",
      "training.retry",
      "training.continue",
      "training.reset.request"
    ];
    const actions = [];
    for (let index = 0; index < expectedCommands.length; index += 1) {
      if (!Object.prototype.hasOwnProperty.call(snapshot.actions, index)) {
        throw new TypeError("Training actions must be dense");
      }
      const action = snapshot.actions[index];
      if (!action || typeof action !== "object" || Array.isArray(action)) {
        throw new TypeError("Training action must be an object");
      }
      if (action.command !== expectedCommands[index]) {
        throw new TypeError("Training action order/identity is invalid");
      }
      requiredUiText(action.label, "Training action label", 160);
      if (typeof action.enabled !== "boolean") {
        throw new TypeError("Training action enabled state is invalid");
      }
      actions.push(action);
    }
    const expectedExerciseEnabled = !progress.completed;
    if (
      actions[0].enabled !== expectedExerciseEnabled ||
      actions[1].enabled !== expectedExerciseEnabled ||
      actions[2].enabled !== expectedExerciseEnabled ||
      actions[4].enabled !== true ||
      (!progress.completed && actions[3].enabled)
    ) {
      throw new TypeError("Training action availability is inconsistent");
    }

    const reset = snapshot.reset_dialog;
    if (!reset || typeof reset !== "object" || Array.isArray(reset)) {
      throw new TypeError("Training reset dialog is invalid");
    }
    ["title", "text", "confirm_label", "cancel_label"].forEach(function (name) {
      requiredUiText(reset[name], "Training reset dialog text", 600);
    });
    requiredUiText(snapshot.solution_label, "Training solution label", 160);
    if (!Array.isArray(solution) || solution.length > 64) {
      throw new TypeError("Training solution must be a bounded dense array");
    }
    for (let index = 0; index < solution.length; index += 1) {
      if (
        !Object.prototype.hasOwnProperty.call(solution, index) ||
        typeof solution[index] !== "string" ||
        !solution[index].trim() ||
        solution[index].length > 128 ||
        solution[index].indexOf("\u0000") !== -1
      ) {
        throw new TypeError("Training solution item is invalid");
      }
    }

    const allowedFocus = Object.create(null);
    allowedFocus[""] = true;
    if (!answer.disabled) allowedFocus["training-answer"] = true;
    if (solution.length) allowedFocus["training-solution"] = true;
    actions.forEach(function (action) {
      if (
        action.enabled &&
        Object.prototype.hasOwnProperty.call(TRAINING_ACTION_IDS, action.command)
      ) {
        allowedFocus[TRAINING_ACTION_IDS[action.command]] = true;
      }
    });
    if (
      typeof requestedFocus !== "string" ||
      !Object.prototype.hasOwnProperty.call(allowedFocus, requestedFocus)
    ) {
      throw new TypeError("Training focus target is invalid");
    }

    return {
      progress: progress,
      answer: answer,
      actions: actions,
      reset_dialog: reset,
      solution: solution.slice()
    };
  }

  function appendSemanticDetails(container, label, items, headingId) {
    if (!items.length) return;
    const heading = node("h4", label);
    heading.id = headingId;
    const list = node("dl");
    list.setAttribute("aria-labelledby", heading.id);
    items.forEach(function (item) {
      list.appendChild(node("dt", item.label));
      list.appendChild(node("dd", item.value));
    });
    container.appendChild(heading);
    container.appendChild(list);
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

    const budget = { used: 0, entries: 0 };
    const playersLabel = semanticRequiredText(
      semantic.players_label, "book semantic players label", budget
    );
    const resultLabel = semanticRequiredText(
      semantic.result_label, "book semantic result label", budget
    );
    const detailsLabel = semanticRequiredText(
      semantic.details_label, "book semantic details label", budget
    );
    const commentsLabel = semanticRequiredText(
      semantic.comments_label, "book semantic comments label", budget
    );
    const introCommentsLabel = semanticRequiredText(
      semantic.intro_comments_label,
      "book semantic intro comments label",
      budget
    );
    const outroCommentsLabel = semanticRequiredText(
      semantic.outro_comments_label,
      "book semantic outro comments label",
      budget
    );
    const warningsLabel = semanticRequiredText(
      semantic.warnings_label, "book semantic warnings label", budget
    );
    const movesLabel = semanticRequiredText(
      semantic.label, "book semantic moves label", budget
    );
    const players = semanticOptionalText(
      semantic.players, "book semantic players", budget, ""
    );
    const result = semanticRequiredText(
      semantic.result, "book semantic result", budget
    );
    if (!Object.prototype.hasOwnProperty.call(BOOK_SEMANTIC_RESULTS, result)) {
      throw new TypeError("book semantic result is invalid");
    }

    if (players) {
      container.appendChild(node("p", playersLabel + ": " + players));
    }

    if (result) {
      container.appendChild(node("p", resultLabel + ": " + result));
    }

    appendSemanticDetails(
      container,
      detailsLabel,
      semanticDetails(semantic.details, budget),
      String(block.dom_id || "") + "-semantic-details-heading"
    );

    appendSemanticTextList(
      container,
      introCommentsLabel,
      semanticTextArray(semantic.intro_comments, "book semantic intro comments", budget),
      String(block.dom_id || "") + "-semantic-intro-heading"
    );

    const heading = node("h4", movesLabel);
    heading.id = String(block.dom_id || "") + "-semantic-heading";
    container.appendChild(heading);

    if (!Array.isArray(semantic.items)) {
      throw new TypeError("book semantic items must be an array");
    }
    const items = semantic.items;
    if (items.length > MAX_BOOK_SEMANTIC_ITEMS) {
      throw new TypeError("book semantic item limit exceeded");
    }
    for (let index = 0; index < items.length; index += 1) {
      if (!Object.prototype.hasOwnProperty.call(items, index)) {
        throw new TypeError("book semantic items must be dense");
      }
    }
    const rootList = node("ol");
    rootList.setAttribute("aria-labelledby", heading.id);
    container.appendChild(rootList);

    const lists = [rootList];
    const lastItems = [];
    const deferredTrailingComments = [];
    const activeAncestorIndices = [];
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
      const depth = item.depth;
      if (!Number.isSafeInteger(depth) || depth < 0) {
        throw new TypeError("book semantic item depth is invalid");
      }
      if (depth > MAX_BOOK_SEMANTIC_DEPTH) {
        throw new TypeError("book semantic item depth limit exceeded");
      }
      if (
        (item.kind === "move" && depth % 2 !== 0) ||
        (item.kind === "variation" && depth % 2 !== 1)
      ) {
        throw new TypeError("book semantic item kind/depth alternation is invalid");
      }
      if ((index === 0 && depth !== 0) || (index > 0 && depth > previousDepth + 1)) {
        throw new TypeError("book semantic item depth is not contiguous");
      }
      const parentIndex = item.parent_index;
      if (depth === 0) {
        if (parentIndex !== null) {
          throw new TypeError("book semantic root parent index is invalid");
        }
      } else {
        if (
          !Number.isSafeInteger(parentIndex) ||
          parentIndex < 0 ||
          parentIndex >= index ||
          activeAncestorIndices.length < depth ||
          activeAncestorIndices[depth - 1] !== parentIndex
        ) {
          throw new TypeError("book semantic parent index is invalid");
        }
        const parentKind = items[parentIndex].kind;
        if (
          (item.kind === "variation" && parentKind !== "move") ||
          (item.kind === "move" && parentKind !== "variation")
        ) {
          throw new TypeError("book semantic parent kind is invalid");
        }
      }
      while (lists.length > depth + 1) lists.pop();
      while (lists.length < depth + 1) {
        const parent = lastItems[lists.length - 1];
        if (!parent) throw new TypeError("book semantic nesting has no parent");
        const nested = node("ol");
        parent.appendChild(nested);
        lists.push(nested);
      }

      const itemLabel = semanticText(item.label, "book semantic item label", budget);
      const listItem = node("li");
      const comments = semanticTextArray(
        item.comments, "book semantic item comments", budget
      );
      const commentsBefore = semanticTextArray(
        item.comments_before,
        "book semantic comments before move",
        budget
      );
      const commentsAfter = semanticTextArray(
        item.comments_after,
        "book semantic comments after move",
        budget
      );
      const exactMoveComments = item.kind === "move" && (
        item.comments_before !== undefined || item.comments_after !== undefined
      );

      function appendItemComments(values) {
        if (!values.length) return;
        const commentList = node("ul");
        commentList.setAttribute("aria-label", commentsLabel);
        values.forEach(function (comment) {
          commentList.appendChild(node("li", comment));
        });
        listItem.appendChild(commentList);
      }

      if (exactMoveComments) appendItemComments(commentsBefore);
      listItem.appendChild(node("span", itemLabel));
      if (exactMoveComments) {
        appendItemComments(commentsAfter);
      } else {
        appendItemComments(comments);
      }

      const trailingComments = semanticTextArray(
        item.trailing_comments,
        "book semantic item trailing comments",
        budget
      );
      lists[depth].appendChild(listItem);
      if (trailingComments.length) {
        deferredTrailingComments.push({ item: listItem, comments: trailingComments });
      }
      lastItems[depth] = listItem;
      lastItems.length = depth + 1;
      activeAncestorIndices.length = depth;
      activeAncestorIndices.push(index);
      previousDepth = depth;
    });

    deferredTrailingComments.forEach(function (entry) {
      const commentList = node("ul");
      commentList.setAttribute("aria-label", commentsLabel);
      entry.comments.forEach(function (comment) {
        commentList.appendChild(node("li", comment));
      });
      // Appending after the full depth walk keeps variation-tail comments
      // after that variation's nested move list instead of before its moves.
      entry.item.appendChild(commentList);
    });

    appendSemanticTextList(
      container,
      outroCommentsLabel,
      semanticTextArray(semantic.outro_comments, "book semantic outro comments", budget),
      String(block.dom_id || "") + "-semantic-outro-heading"
    );

    appendSemanticTextList(
      container,
      warningsLabel,
      semanticTextArray(semantic.warnings, "book semantic warnings", budget),
      String(block.dom_id || "") + "-semantic-warnings-heading"
    );
  }

  function renderBookBlock(host, block) {
    const role = block.role;
    let content;
    const hasSemanticTree = Object.prototype.hasOwnProperty.call(block, "semantic_tree") &&
      block.semantic_tree !== undefined && block.semantic_tree !== null;
    if (hasSemanticTree) {
      if (!block.semantic_tree || typeof block.semantic_tree !== "object" || Array.isArray(block.semantic_tree)) {
        throw new TypeError("book semantic tree must be an object");
      }
      content = node("section");
      content.setAttribute("role", "group");
      if (block.title) {
        const title = node("h3", block.title);
        title.id = block.dom_id + "-title";
        content.setAttribute("aria-labelledby", title.id);
        content.appendChild(title);
      }
      renderBookSemanticTree(content, block);
      if (!content.attributes["aria-labelledby"]) {
        content.setAttribute("aria-labelledby", block.dom_id + "-semantic-heading");
      }
    } else if (role === "list") {
      content = node(block.list.ordered ? "ol" : "ul");
      if (block.list.ordered && Number.isSafeInteger(block.list.start) && block.list.start > 0) {
        content.setAttribute("start", String(block.list.start));
      }
      block.list.items.forEach(function (text) { content.appendChild(node("li", text)); });
    } else if (role === "heading") {
      const level = block.heading_level || 2;
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

    const headingPath = block.heading_path;
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
    if (!result || typeof result !== "object" || Array.isArray(result)) {
      throw new TypeError("Book event must be an object");
    }
    if (result.kind !== "render" && result.kind !== "delegated" && result.kind !== "error") {
      throw new TypeError("Book event kind is invalid");
    }
    const payload = result.payload;
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new TypeError("Book event payload must be an object");
    }
    if (
      payload.announcement !== undefined &&
      typeof payload.announcement !== "string"
    ) {
      throw new TypeError("Book event announcement must be text");
    }

    if (result.kind === "render") {
      if (!payload.snapshot || typeof payload.snapshot !== "object" || Array.isArray(payload.snapshot)) {
        throw new TypeError("Book render event snapshot is invalid");
      }
      if (
        payload.focus_target !== undefined &&
        typeof payload.focus_target !== "string"
      ) {
        throw new TypeError("Book render focus target must be text");
      }
      renderBookSurface(
        root,
        payload.snapshot,
        invoke,
        announce,
        payload.focus_target || "",
        fallbackMessage
      );
    } else if (result.kind === "delegated") {
      if (payload.action !== "book.open_position") {
        throw new TypeError("Book delegated event action is invalid");
      }
    } else {
      if (typeof payload.message !== "string" || !payload.message.trim()) {
        throw new TypeError("Book error event message is invalid");
      }
    }

    if (payload.announcement) announce(payload.announcement);
    if (result.kind === "error") announce(payload.message);
  }

  function renderStarterMaterials(main, catalogue, invoke, announce, fallbackMessage) {
    if (!catalogue) return;
    const items = catalogue.items;

    const section = node("section");
    const heading = node("h3", catalogue.heading);
    heading.id = "book-starter-materials-heading";
    section.setAttribute("aria-labelledby", heading.id);
    section.appendChild(heading);
    if (catalogue.description) section.appendChild(node("p", catalogue.description));

    const label = node("label", catalogue.label);
    const select = node("select");
    select.id = "book-starter-material";
    label.htmlFor = select.id;
    items.forEach(function (item) {
      const option = node("option", item.title);
      option.value = item.material_id;
      select.appendChild(option);
    });
    const currentId = catalogue.current_id;
    if (currentId) select.value = currentId;
    label.appendChild(select);
    section.appendChild(label);

    const open = node("button", catalogue.open_label);
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
    if (
      !snapshot ||
      !snapshot.document ||
      typeof snapshot.document !== "object" ||
      Array.isArray(snapshot.document) ||
      (snapshot.document.lang !== "en" && snapshot.document.lang !== "uk")
    ) {
      throw new TypeError("snapshot document language is invalid");
    }
    element.setAttribute("lang", snapshot.document.lang);
  }

  function renderBookSurface(root, snapshot, invoke, announce, requestedFocus, fallbackMessage) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new TypeError("Book root must support replaceChildren");
    }
    requireFunction(invoke, "Book invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "Book announce");
    if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) {
      throw new TypeError("Book snapshot is required");
    }
    validateBookLanguage(snapshot);
    const expectedBlockId = validateBookBlock(snapshot.block);
    if (requestedFocus && requestedFocus !== expectedBlockId) {
      throw new TypeError("Book focus target does not match the rendered block");
    }
    const actions = validateBookActions(snapshot.actions);
    const bookmark = validateBookmark(snapshot.bookmark);
    const starterCatalogue = validateStarterCatalogue(snapshot.starter_materials);

    const fragment = document.createDocumentFragment();
    const main = node("section");
    applySnapshotLanguage(main, snapshot);
    main.appendChild(node("h2", snapshot.heading || ""));
    renderStarterMaterials(main, starterCatalogue, invoke, announce, fallbackMessage);
    const block = snapshot.block;
    renderBookBlock(main, block);

    const toolbar = node("div");
    toolbar.setAttribute("role", "toolbar");
    actions.forEach(function (action) {
      const button = node("button", action.label);
      button.type = "button";
      button.disabled = !action.enabled;
      button.addEventListener("click", function () {
        safeInvoke(invoke, action.command, {}, function (result) {
          applyBookEvent(root, result, invoke, announce, fallbackMessage);
        }, announce, fallbackMessage);
      });
      toolbar.appendChild(button);
    });
    main.appendChild(toolbar);

    const form = node("form");
    const label = node("label", bookmark.label);
    const input = node("input");
    input.id = "book-bookmark-name";
    input.type = "text";
    input.maxLength = bookmark.max_length;
    input.value = bookmark.value;
    label.htmlFor = input.id;
    form.appendChild(label);
    form.appendChild(input);
    const save = node("button", bookmark.save_label);
    save.type = "submit";
    const restore = node("button", bookmark.restore_label);
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
    if (!result || typeof result !== "object" || Array.isArray(result)) {
      throw new TypeError("Training event must be an object");
    }
    if (result.kind !== "render" && result.kind !== "error") {
      throw new TypeError("Training event kind is invalid");
    }
    const payload = result.payload;
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw new TypeError("Training event payload must be an object");
    }
    if (
      payload.announcement !== undefined &&
      typeof payload.announcement !== "string"
    ) {
      throw new TypeError("Training event announcement must be text");
    }

    if (result.kind === "render") {
      if (!payload.snapshot || typeof payload.snapshot !== "object" || Array.isArray(payload.snapshot)) {
        throw new TypeError("Training render snapshot is invalid");
      }
      if (
        payload.focus_target !== undefined &&
        typeof payload.focus_target !== "string"
      ) {
        throw new TypeError("Training focus target must be text");
      }
      if (
        payload.clear_answer !== undefined &&
        typeof payload.clear_answer !== "boolean"
      ) {
        throw new TypeError("Training clear-answer flag is invalid");
      }
      if (payload.solution !== undefined && !Array.isArray(payload.solution)) {
        throw new TypeError("Training solution must be an array");
      }
      const solution = payload.solution || [];
      if (solution.length > 256) {
        throw new TypeError("Training solution is too large");
      }
      for (let index = 0; index < solution.length; index += 1) {
        if (
          !Object.prototype.hasOwnProperty.call(solution, index) ||
          typeof solution[index] !== "string" ||
          !solution[index].trim() ||
          solution[index].length > 128
        ) {
          throw new TypeError("Training solution item is invalid");
        }
      }

      let priorAnswer = "";
      const prior = root.querySelector("#training-answer");
      if (prior && typeof prior.value === "string") priorAnswer = prior.value;
      renderTrainingSurface(
        root,
        payload.snapshot,
        invoke,
        announce,
        payload.focus_target || "",
        fallbackMessage,
        solution
      );
      if (payload.clear_answer !== true && priorAnswer) {
        const next = root.querySelector("#training-answer");
        if (next) next.value = priorAnswer;
      }
    } else {
      if (typeof payload.message !== "string" || !payload.message.trim()) {
        throw new TypeError("Training error event message is invalid");
      }
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
    const validated = validateTrainingSnapshot(snapshot, requestedFocus, solution);
    const progress = validated.progress;
    const answerSpec = validated.answer;
    const actions = validated.actions;
    const resetSpec = validated.reset_dialog;
    solution = validated.solution;

    const fragment = document.createDocumentFragment();
    const main = node("section");
    applySnapshotLanguage(main, snapshot);
    main.appendChild(node("h2", snapshot.heading));
    main.appendChild(node("h3", snapshot.title));

    const stats = node("dl");
    [
      [progress.step_label, String(progress.step) + " " + progress.of_label + " " + String(progress.total)],
      [progress.attempts_label, progress.attempts],
      [progress.mistakes_label, progress.mistakes],
      [progress.hints_label, progress.hints_used]
    ].forEach(function (pair) {
      stats.appendChild(node("dt", pair[0]));
      stats.appendChild(node("dd", pair[1]));
    });
    main.appendChild(stats);

    if (snapshot.message) {
      const message = node("p", snapshot.message);
      message.setAttribute("aria-live", "off");
      main.appendChild(message);
    }

    const form = node("form");
    const label = node("label", answerSpec.label);
    const input = node("input");
    input.id = "training-answer";
    input.type = "text";
    input.maxLength = answerSpec.max_length;
    input.disabled = answerSpec.disabled;
    input.autocomplete = "off";
    input.spellcheck = false;
    label.htmlFor = input.id;
    const submit = node("button", answerSpec.submit_label);
    submit.type = "submit";
    submit.disabled = answerSpec.disabled;
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

    if (solution.length) {
      const solutionSection = node("section");
      solutionSection.id = "training-solution";
      solutionSection.tabIndex = -1;
      const solutionHeading = node("h3", snapshot.solution_label);
      solutionHeading.id = "training-solution-heading";
      solutionSection.setAttribute("aria-labelledby", solutionHeading.id);
      solutionSection.appendChild(solutionHeading);
      const list = node("ul");
      solution.forEach(function (move) { list.appendChild(node("li", move)); });
      solutionSection.appendChild(list);
      main.appendChild(solutionSection);
    }

    const resetDialog = buildResetDialog(root, resetSpec, invoke, announce, fallbackMessage);
    const toolbar = node("div");
    toolbar.setAttribute("role", "toolbar");
    actions.forEach(function (action) {
      const button = node("button", action.label);
      button.type = "button";
      button.disabled = !action.enabled;
      const command = action.command;
      button.id = TRAINING_ACTION_IDS[command];
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
    focusTarget(root, requestedFocus);
  }

  global.AccessibleChessBookSurface = Object.freeze({ render: renderBookSurface });
  global.AccessibleChessTrainingSurface = Object.freeze({ render: renderTrainingSurface });
})(window);
