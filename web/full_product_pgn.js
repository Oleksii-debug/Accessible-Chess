(function (global) {
  "use strict";

  const MAX_PGN_TREE_ITEMS = 10000;
  const MAX_PGN_TAGS = 256;
  const MAX_PGN_WARNINGS = 256;
  const MAX_PGN_COMMENTS_PER_ITEM = 256;
  const MAX_PGN_NAGS_PER_ITEM = 64;
  const MAX_PGN_DEPTH = 256;
  const MAX_PGN_NODE_ID = 4096;
  const MAX_PGN_COMMENT_TEXT = 8000;
  const FOCUS_ID_PATTERN = /^[A-Za-z0-9_-]{1,160}$/;
  const PGN_DOM_ID_PATTERN = /^pgn-node-[0-9a-f]{20}$/;
  const PRESENTATION_TOKEN_PATTERN = /^[0-9a-f]{64}$/;
  const ACTIONS = [
    "pgn.previous_game",
    "pgn.next_game",
    "pgn.search",
    "pgn.append_moves",
    "pgn.tag_edit",
    "pgn.tag_delete",
    "pgn.parent",
    "pgn.comment_edit",
    "pgn.comment_delete",
    "pgn.nag_edit",
    "pgn.variation_add",
    "pgn.variation_delete",
    "pgn.variation_promote",
    "pgn.copy_selection",
    "pgn.export_selection"
  ];

  function requireFunction(value, name) {
    if (typeof value !== "function") throw new TypeError(name + " must be a function");
    return value;
  }

  function requireRecord(value, label) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new TypeError(label + " must be an object");
    }
    return value;
  }

  function requireText(value, label, allowEmpty, limit) {
    if (typeof value !== "string" || (!allowEmpty && !value)) {
      throw new TypeError(label + " must be text");
    }
    if (value.length > limit || value.indexOf("\x00") >= 0) {
      throw new TypeError(label + " exceeds its canonical text contract");
    }
    return value;
  }

  function requireDenseTextArray(value, label, maxItems, textLimit) {
    if (!Array.isArray(value) || value.length > maxItems) {
      throw new TypeError(label + " must be a bounded array");
    }
    for (let index = 0; index < value.length; index += 1) {
      if (!Object.prototype.hasOwnProperty.call(value, index)) {
        throw new TypeError(label + " must be dense");
      }
      requireText(value[index], label + " item", false, textLimit);
    }
    return value;
  }

  function node(tag, text) {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) {
      if (typeof text === "string") {
        element.textContent = text;
      } else if (typeof text === "number" && Number.isFinite(text)) {
        element.textContent = String(text);
      } else {
        throw new TypeError("PGN DOM text must be primitive");
      }
    }
    return element;
  }

  function requireRequestedFocus(value) {
    if (value === undefined || value === null || value === "") return "";
    requireText(value, "PGN requested focus", false, 160);
    if (!FOCUS_ID_PATTERN.test(value)) {
      throw new TypeError("PGN requested focus is invalid");
    }
    return value;
  }

  function requireCommentEditor(editor) {
    requireRecord(editor, "PGN comment editor");
    if (typeof editor.enabled !== "boolean") {
      throw new TypeError("PGN comment editor enabled flag is invalid");
    }
    requireText(editor.value, "PGN comment editor value", true, MAX_PGN_COMMENT_TEXT);
    requireText(editor.message, "PGN comment editor message", true, 1200);
    requireText(editor.title, "PGN comment editor title", false, 120);
    requireText(editor.label, "PGN comment editor label", false, 120);
    requireText(editor.save_label, "PGN comment editor save label", false, 120);
    requireText(editor.cancel_label, "PGN comment editor cancel label", false, 120);
    if (editor.entries !== undefined) {
      if (!Array.isArray(editor.entries) || editor.entries.length > MAX_PGN_COMMENTS_PER_ITEM * 2) {
        throw new TypeError("PGN comment editor entries are invalid");
      }
      editor.entries.forEach(function (entry) {
        requireRecord(entry, "PGN comment entry");
        if (["before", "after", "leading", "trailing"].indexOf(entry.slot) < 0 ||
            !Number.isSafeInteger(entry.index) || entry.index < 0 ||
            entry.index >= MAX_PGN_COMMENTS_PER_ITEM) {
          throw new TypeError("PGN comment entry target is invalid");
        }
        requireText(entry.label, "PGN comment entry label", false, 160);
        requireText(entry.value, "PGN comment entry value", true, MAX_PGN_COMMENT_TEXT);
      });
    }
    if (editor.add_slots !== undefined) {
      if (!Array.isArray(editor.add_slots) || editor.add_slots.length > 4) {
        throw new TypeError("PGN comment add slots are invalid");
      }
      editor.add_slots.forEach(function (entry) {
        requireRecord(entry, "PGN comment add slot");
        if (["before", "after", "leading", "trailing"].indexOf(entry.slot) < 0) {
          throw new TypeError("PGN comment add slot is invalid");
        }
        requireText(entry.label, "PGN comment add slot label", false, 160);
      });
    }
  }

  function requireActions(actions, game) {
    if (!Array.isArray(actions) || actions.length !== ACTIONS.length) {
      throw new TypeError("PGN actions are incomplete");
    }
    for (let index = 0; index < actions.length; index += 1) {
      if (!Object.prototype.hasOwnProperty.call(actions, index)) {
        throw new TypeError("PGN actions must be dense");
      }
      const action = requireRecord(actions[index], "PGN action");
      if (action.action !== ACTIONS[index]) {
        throw new TypeError("PGN action order is invalid");
      }
      requireText(action.label, "PGN action label", false, 120);
      if (typeof action.enabled !== "boolean") {
        throw new TypeError("PGN action enabled flag is invalid");
      }
    }
    if (
      actions[0].enabled !== game.can_previous_game ||
      actions[1].enabled !== game.can_next_game
    ) {
      throw new TypeError("PGN game navigation actions are inconsistent");
    }
  }

  function requireSnapshot(snapshot) {
    requireRecord(snapshot, "PGN snapshot");
    const documentSpec = requireRecord(snapshot.document, "PGN document");
    if (documentSpec.landmark !== "main" ||
        (documentSpec.lang !== "uk" && documentSpec.lang !== "en")) {
      throw new TypeError("PGN document contract is invalid");
    }

    requireText(snapshot.error_message, "PGN error message", false, 240);
    if (
      snapshot.status !== "empty" &&
      snapshot.status !== "ready" &&
      snapshot.status !== "unavailable"
    ) {
      throw new TypeError("PGN status is invalid");
    }
    if (snapshot.presentation_token !== undefined) {
      requireText(
        snapshot.presentation_token,
        "PGN presentation token",
        false,
        64
      );
      if (!PRESENTATION_TOKEN_PATTERN.test(snapshot.presentation_token)) {
        throw new TypeError("PGN presentation token is invalid");
      }
    }
    requireCommentEditor(snapshot.comment_editor);

    if (!Array.isArray(snapshot.tree) ||
        snapshot.tree.length > MAX_PGN_TREE_ITEMS) {
      throw new TypeError("PGN tree exceeds its item-count contract");
    }

    if (snapshot.status === "unavailable") {
      requireText(
        snapshot.unavailable_message,
        "PGN unavailable message",
        false,
        720
      );
      requireText(snapshot.refresh_label, "PGN refresh label", false, 120);
      const game = requireRecord(snapshot.game, "PGN unavailable game");
      if (
        Object.keys(game).length !== 0 ||
        snapshot.tree.length !== 0 ||
        snapshot.focus_target !== "pgn-refresh-view" ||
        !Array.isArray(snapshot.actions) ||
        snapshot.actions.length !== 0 ||
        snapshot.comment_editor.enabled !== false
      ) {
        throw new TypeError("PGN unavailable snapshot is inconsistent");
      }
      return snapshot;
    }

    requireText(snapshot.empty_message, "PGN empty message", true, 720);
    if (typeof snapshot.focus_target !== "string" ||
        snapshot.focus_target.length > 160 ||
        snapshot.focus_target.indexOf("\x00") >= 0 ||
        (snapshot.focus_target && !PGN_DOM_ID_PATTERN.test(snapshot.focus_target))) {
      throw new TypeError("PGN focus target is invalid");
    }

    if (snapshot.status === "empty") {
      const game = requireRecord(snapshot.game, "PGN empty game");
      if (Object.keys(game).length !== 0 ||
          snapshot.tree.length !== 0 ||
          snapshot.focus_target !== "" ||
          !Array.isArray(snapshot.actions) ||
          snapshot.actions.length !== 0 ||
          snapshot.comment_editor.enabled !== false) {
        throw new TypeError("PGN empty snapshot is inconsistent");
      }
      return snapshot;
    }

    const game = requireRecord(snapshot.game, "PGN game");
    for (const field of ["index", "number", "count"]) {
      if (!Number.isSafeInteger(game[field])) {
        throw new TypeError("PGN game numbering is invalid");
      }
    }
    if (
      game.index < 0 ||
      game.count < 1 ||
      game.index >= game.count ||
      game.number !== game.index + 1
    ) {
      throw new TypeError("PGN game numbering is inconsistent");
    }
    requireText(game.heading, "PGN game heading", true, 240);
    requireText(game.position_label, "PGN position label", false, 240);
    requireText(game.result_label, "PGN result label", false, 120);
    requireText(game.result, "PGN result", true, 32);
    requireText(game.tags_heading, "PGN tags heading", false, 120);
    requireText(game.warnings_heading, "PGN warnings heading", false, 120);
    requireText(game.tree_heading, "PGN tree heading", false, 120);
    if (
      typeof game.can_previous_game !== "boolean" ||
      typeof game.can_next_game !== "boolean" ||
      game.can_previous_game !== (game.index > 0) ||
      game.can_next_game !== (game.index + 1 < game.count)
    ) {
      throw new TypeError("PGN game navigation flags are inconsistent");
    }

    if (!Array.isArray(game.tags) || game.tags.length > MAX_PGN_TAGS) {
      throw new TypeError("PGN tags exceed their item-count contract");
    }
    for (let index = 0; index < game.tags.length; index += 1) {
      if (!Object.prototype.hasOwnProperty.call(game.tags, index)) {
        throw new TypeError("PGN tags must be dense");
      }
      const tag = requireRecord(game.tags[index], "PGN tag");
      requireText(tag.name, "PGN tag name", false, 80);
      requireText(tag.value, "PGN tag value", true, 360);
    }
    requireDenseTextArray(
      game.warnings,
      "PGN warnings",
      MAX_PGN_WARNINGS,
      720
    );
    if (game.leading_comments !== undefined) {
      requireText(game.leading_comments_heading, "PGN main-line leading comment heading", false, 160);
      requireDenseTextArray(
        game.leading_comments,
        "PGN main-line leading comments",
        MAX_PGN_COMMENTS_PER_ITEM,
        1200
      );
    }
    if (game.trailing_comments !== undefined) {
      requireText(game.trailing_comments_heading, "PGN main-line trailing comment heading", false, 160);
      requireDenseTextArray(
        game.trailing_comments,
        "PGN main-line trailing comments",
        MAX_PGN_COMMENTS_PER_ITEM,
        1200
      );
    }

    const nodeIds = new Set();
    const domIds = new Set();
    let selectedDomId = "";
    let selectedCount = 0;
    for (let index = 0; index < snapshot.tree.length; index += 1) {
      if (!Object.prototype.hasOwnProperty.call(snapshot.tree, index)) {
        throw new TypeError("PGN tree must be dense");
      }
      const item = requireRecord(snapshot.tree[index], "PGN tree item");
      requireText(item.node_id, "PGN node id", false, MAX_PGN_NODE_ID);
      if (nodeIds.has(item.node_id)) {
        throw new TypeError("PGN node id is duplicated");
      }
      nodeIds.add(item.node_id);

      requireText(item.dom_id, "PGN DOM id", false, 160);
      if (!PGN_DOM_ID_PATTERN.test(item.dom_id) || domIds.has(item.dom_id)) {
        throw new TypeError("PGN DOM id is invalid or duplicated");
      }
      domIds.add(item.dom_id);

      if (item.kind !== "move" && item.kind !== "variation") {
        throw new TypeError("PGN tree item kind is invalid");
      }
      if (!Number.isSafeInteger(item.aria_level) ||
          item.aria_level < 1 ||
          item.aria_level > MAX_PGN_DEPTH) {
        throw new TypeError("PGN aria level is invalid");
      }
      if (typeof item.selected !== "boolean" ||
          typeof item.has_parent !== "boolean") {
        throw new TypeError("PGN tree item flags are invalid");
      }
      requireText(item.label, "PGN tree item label", true, 240);
      requireText(item.san, "PGN SAN", true, 80);
      requireDenseTextArray(
        item.comments,
        "PGN comments",
        MAX_PGN_COMMENTS_PER_ITEM,
        1200
      );
      requireDenseTextArray(
        item.nags,
        "PGN annotations",
        MAX_PGN_NAGS_PER_ITEM,
        40
      );
      if (item.selected) {
        selectedCount += 1;
        selectedDomId = item.dom_id;
      }
    }

    if (
      (snapshot.tree.length === 0 && selectedCount !== 0) ||
      (snapshot.tree.length > 0 && selectedCount !== 1) ||
      snapshot.focus_target !== selectedDomId
    ) {
      throw new TypeError("PGN selection/focus contract is inconsistent");
    }
    requireActions(snapshot.actions, game);
    return snapshot;
  }

  function requireHostEvent(result) {
    const event = requireRecord(result, "PGN host result");
    if (["selection", "delegated", "error"].indexOf(event.kind) < 0) {
      throw new TypeError("PGN host result kind is invalid");
    }
    const payload = requireRecord(event.payload, "PGN host payload");
    if (payload.announcement !== undefined) {
      requireText(payload.announcement, "PGN announcement", true, 1000);
    }
    if (event.kind === "selection") {
      requireSnapshot(payload.snapshot);
      if (
        typeof payload.focus_target !== "string" ||
        payload.focus_target !== payload.snapshot.focus_target
      ) {
        throw new TypeError("PGN selection focus target is invalid");
      }
    } else if (event.kind === "error") {
      requireText(payload.message, "PGN host error message", false, 1000);
    } else {
      requireText(payload.action, "PGN delegated action", false, 80);
      if (ACTIONS.indexOf(payload.action) < 0) {
        throw new TypeError("PGN delegated action is invalid");
      }
    }
    return payload;
  }

  function focusTarget(root, targetId) {
    if (!targetId) return;
    const items = root.querySelectorAll('[role="treeitem"]');
    for (let index = 0; index < items.length; index += 1) {
      if (
        items[index].id === targetId &&
        typeof items[index].focus === "function"
      ) {
        items[index].focus({ preventScroll: true });
        return;
      }
    }
  }

  function renderTags(host, game) {
    if (!game.tags.length) return;
    const section = node("section");
    section.appendChild(node("h3", game.tags_heading));
    const list = node("dl");
    game.tags.forEach(function (entry) {
      list.appendChild(node("dt", entry.name));
      list.appendChild(node("dd", entry.value));
    });
    section.appendChild(list);
    host.appendChild(section);
  }

  function renderMainLineComments(host, game) {
    [
      [game.leading_comments_heading, game.leading_comments],
      [game.trailing_comments_heading, game.trailing_comments]
    ].forEach(function (entry) {
      const heading = entry[0];
      const comments = Array.isArray(entry[1]) ? entry[1] : [];
      if (!comments.length) return;
      const section = node("section");
      section.appendChild(node("h3", heading || "PGN comments"));
      comments.forEach(function (comment) {
        section.appendChild(node("p", comment));
      });
      host.appendChild(section);
    });
  }

  function renderWarnings(host, game) {
    if (!game.warnings.length) return;
    const section = node("section");
    section.setAttribute("aria-live", "off");
    section.appendChild(node("h3", game.warnings_heading));
    const list = node("ul");
    game.warnings.forEach(function (warning) {
      list.appendChild(node("li", warning));
    });
    section.appendChild(list);
    host.appendChild(section);
  }

  function applyEvent(root, result, invoke, announce) {
    const payload = requireHostEvent(result);
    if (result.kind === "selection") {
      renderPgnSurface(
        root,
        payload.snapshot,
        invoke,
        announce,
        payload.focus_target
      );
    }
    if (payload.announcement) announce(payload.announcement);
    if (result.kind === "error") announce(payload.message);
  }

  function announceRejected(root, announce, focusBefore) {
    announce(
      typeof root._pgnErrorMessage === "string" && root._pgnErrorMessage
        ? root._pgnErrorMessage
        : "The action could not be completed."
    );
    if (focusBefore && typeof focusBefore.focus === "function") {
      focusBefore.focus({ preventScroll: true });
    }
  }

  function commandPayload(root, payload, omitLease) {
    const source = payload || {};
    const result = {};
    Object.keys(source).forEach(function (key) {
      result[key] = source[key];
    });
    if (!omitLease && root._pgnPresentationToken) {
      result.presentation_token = root._pgnPresentationToken;
    }
    return result;
  }

  function invokeCommand(root, invoke, announce, command, payload, options) {
    options = options || {};
    const epoch = root._pgnRenderEpoch || 0;
    const active = root._pgnFlight;
    if (active && active.epoch === epoch) return false;

    const focusBefore = document.activeElement;
    const flight = { epoch: epoch };
    root._pgnFlight = flight;
    const outbound = commandPayload(root, payload, options.omitLease === true);

    function recoverAfterFailure() {
      if (typeof options.afterFailure !== "function") return;
      try {
        options.afterFailure();
      } catch (_) {
        // Presentation recovery must never become command/domain authority.
      }
    }

    Promise.resolve()
      .then(function () { return invoke(command, outbound); })
      .then(
        function (result) {
          if (
            root._pgnRenderEpoch !== epoch ||
            root._pgnFlight !== flight
          ) {
            return;
          }
          try {
            applyEvent(root, result, invoke, announce);
          } catch (_) {
            if (
              root._pgnRenderEpoch === epoch &&
              root._pgnFlight === flight
            ) {
              root._pgnFlight = null;
              try {
                announceRejected(root, announce, focusBefore);
              } finally {
                recoverAfterFailure();
              }
            }
            return;
          }
          if (
            root._pgnRenderEpoch === epoch &&
            root._pgnFlight === flight
          ) {
            root._pgnFlight = null;
          }
          if (typeof options.afterResult === "function") {
            options.afterResult(result);
          }
        },
        function () {
          if (
            root._pgnRenderEpoch !== epoch ||
            root._pgnFlight !== flight
          ) {
            return;
          }
          root._pgnFlight = null;
          try {
            announceRejected(root, announce, focusBefore);
          } finally {
            recoverAfterFailure();
          }
        }
      );
    return true;
  }

  function renderTree(root, host, snapshot, invoke, announce) {
    const game = snapshot.game;
    const section = node("section");
    section.appendChild(node("h3", game.tree_heading));
    const tree = node("ul");
    tree.setAttribute("role", "tree");
    tree.setAttribute("aria-label", game.tree_heading);

    snapshot.tree.forEach(function (item, itemIndex) {
      const treeItem = node("li");
      treeItem.id = item.dom_id;
      treeItem.setAttribute("role", "treeitem");
      treeItem.setAttribute("aria-level", item.aria_level);
      treeItem.setAttribute("aria-selected", item.selected ? "true" : "false");
      const next = snapshot.tree[itemIndex + 1];
      const hasChild = !!next && next.aria_level > item.aria_level;
      if (hasChild) treeItem.setAttribute("aria-expanded", "true");
      treeItem.dataset.kind = item.kind;
      treeItem.tabIndex = item.selected ? 0 : -1;
      treeItem.style.paddingInlineStart =
        Math.max(0, item.aria_level - 1) + "rem";
      treeItem.appendChild(node("span", item.label));

      if (item.comments.length) {
        const commentGroup = node("div");
        commentGroup.className = "pgn-comments";
        item.comments.forEach(function (comment) {
          commentGroup.appendChild(node("p", comment));
        });
        treeItem.appendChild(commentGroup);
      }

      treeItem.addEventListener("click", function () {
        invokeCommand(
          root,
          invoke,
          announce,
          "pgn.select",
          { node_id: item.node_id }
        );
      });
      treeItem.addEventListener("keydown", function (event) {
        const resolve = global.accessibleChessKeymapAction;
        let actionId = "";
        let resolverReady = false;
        if (typeof resolve === "function") {
          const resolved = resolve(event, "pgn_tree");
          if (resolved !== null && resolved !== undefined) {
            resolverReady = true;
            actionId = typeof resolved === "string" ? resolved : "";
          }
        }
        if (
          !resolverReady &&
          !event.altKey && !event.ctrlKey && !event.shiftKey && !event.metaKey
        ) {
          if (event.key === "ArrowUp") actionId = "pgn.previous_item";
          else if (event.key === "ArrowDown") actionId = "pgn.next_item";
          else if (event.key === "ArrowLeft") actionId = "pgn.parent_variation";
          else if (event.key === "ArrowRight") actionId = "pgn.first_child";
          else if (event.key === "Home") actionId = "pgn.first_item";
          else if (event.key === "End") actionId = "pgn.last_item";
        }

        let command = "";
        let payload = {};
        let handled = false;
        if (actionId === "pgn.previous_item") {
          handled = true;
          if (itemIndex > 0) {
            command = "pgn.move";
            payload = { delta: -1 };
          }
        } else if (actionId === "pgn.next_item") {
          handled = true;
          if (itemIndex + 1 < snapshot.tree.length) {
            command = "pgn.move";
            payload = { delta: 1 };
          }
        } else if (actionId === "pgn.parent_variation") {
          handled = true;
          if (item.has_parent) command = "pgn.parent";
        } else if (actionId === "pgn.first_child") {
          handled = true;
          if (hasChild) {
            command = "pgn.select";
            payload = { node_id: snapshot.tree[itemIndex + 1].node_id };
          }
        } else if (actionId === "pgn.first_item") {
          handled = true;
          if (itemIndex > 0 && snapshot.tree.length) {
            command = "pgn.select";
            payload = { node_id: snapshot.tree[0].node_id };
          }
        } else if (actionId === "pgn.last_item") {
          handled = true;
          if (itemIndex + 1 < snapshot.tree.length) {
            command = "pgn.select";
            payload = {
              node_id: snapshot.tree[snapshot.tree.length - 1].node_id
            };
          }
        }

        if (!handled) return;
        event.preventDefault();
        if (typeof event.stopPropagation === "function") event.stopPropagation();
        if (command) {
          invokeCommand(root, invoke, announce, command, payload);
        }
      });
      tree.appendChild(treeItem);
    });

    section.appendChild(tree);
    host.appendChild(section);
  }

  function buildCommentDialog(root, snapshot, invoke, announce) {
    const editor = snapshot.comment_editor;
    const dialog = node("dialog");
    dialog.id = "pgn-comment-dialog";
    const title = node("h2", editor.title);
    title.id = "pgn-comment-dialog-title";
    dialog.setAttribute("aria-labelledby", title.id);
    dialog.setAttribute("aria-busy", "false");
    dialog.appendChild(title);

    const entries = Array.isArray(editor.entries) ? editor.entries : [];
    const addSlots = Array.isArray(editor.add_slots) ? editor.add_slots : [];
    const targetLabel = node("label", snapshot.document.lang === "en" ? "Comment position" : "Місце коментаря");
    const target = node("select");
    target.id = "pgn-comment-target";
    targetLabel.htmlFor = target.id;
    entries.forEach(function (entry, entryIndex) {
      const option = node("option", entry.label);
      option.value = "existing:" + entryIndex;
      target.appendChild(option);
    });
    addSlots.forEach(function (slot, slotIndex) {
      const option = node(
        "option",
        (snapshot.document.lang === "en" ? "New: " : "Новий: ") + slot.label
      );
      option.value = "new:" + slotIndex;
      target.appendChild(option);
    });
    if (entries.length || addSlots.length) {
      dialog.appendChild(targetLabel);
      dialog.appendChild(target);
    }

    const label = node("label", editor.label);
    const textarea = node("textarea");
    textarea.id = "pgn-comment-text";
    textarea.value = editor.value;
    textarea.maxLength = MAX_PGN_COMMENT_TEXT;
    label.htmlFor = textarea.id;
    dialog.appendChild(label);
    dialog.appendChild(textarea);
    if (editor.message) dialog.appendChild(node("p", editor.message));

    const save = node("button", editor.save_label);
    save.type = "button";
    save.disabled = !editor.enabled;
    const remove = node("button", snapshot.document.lang === "en" ? "Delete comment" : "Видалити коментар");
    remove.type = "button";
    const cancel = node("button", editor.cancel_label);
    cancel.type = "button";
    let opener = null;
    let savePending = false;

    function currentTarget() {
      if (!entries.length && !addSlots.length) return null;
      const value = target.value || (entries.length ? "existing:0" : "new:0");
      const parts = value.split(":");
      const index = Number(parts[1]);
      if (parts[0] === "existing") {
        const entry = entries[index];
        return entry ? { slot: entry.slot, index: entry.index, existing: true, value: entry.value } : null;
      }
      const slot = addSlots[index];
      return slot ? { slot: slot.slot, index: -1, existing: false, value: "" } : null;
    }

    function syncTarget() {
      const selected = currentTarget();
      if (!selected) {
        textarea.value = editor.value;
        remove.disabled = true;
        return;
      }
      textarea.value = selected.value;
      remove.disabled = !selected.existing || savePending;
    }
    target.addEventListener("change", syncTarget);

    function setSavePending(value) {
      savePending = value === true;
      save.disabled = savePending || !editor.enabled;
      cancel.disabled = savePending;
      remove.disabled = savePending || !(currentTarget() && currentTarget().existing);
      target.disabled = savePending;
      textarea.readOnly = savePending;
      dialog.setAttribute("aria-busy", savePending ? "true" : "false");
    }

    function recoverEditor() {
      setSavePending(false);
      if (!dialog.open) return;
      textarea.focus({ preventScroll: true });
      if (typeof textarea.select === "function") textarea.select();
    }

    function closeAndRestore() {
      // Once a canonical comment mutation is in flight, Cancel/Escape must not
      // imply that it can be rolled back. Keep modal ownership until the host
      // reports success/failure or a replacement render takes ownership.
      if (savePending) return;
      if (dialog.open) dialog.close();
      if (opener && typeof opener.focus === "function") {
        opener.focus({ preventScroll: true });
      }
    }

    save.addEventListener("click", function () {
      if (savePending) return;
      setSavePending(true);
      // Keep deterministic focus inside the modal on a selectable/copyable,
      // read-only text surface instead of leaving focus on a disabled button.
      textarea.focus({ preventScroll: true });
      const selected = currentTarget();
      const payload = selected
        ? { text: textarea.value, slot: selected.slot, index: selected.index }
        : { text: textarea.value };
      const started = invokeCommand(
        root,
        invoke,
        announce,
        "pgn.comment_edit",
        payload,
        {
          afterResult: function (result) {
            if (result.kind === "error") {
              recoverEditor();
              return;
            }
            setSavePending(false);
            if (result.kind === "delegated") closeAndRestore();
            // A selection result replaces this whole DOM through applyEvent();
            // that canonical render owns focus, so never restore the stale opener.
          },
          afterFailure: recoverEditor
        }
      );
      if (!started) recoverEditor();
    });
    remove.addEventListener("click", function () {
      if (savePending) return;
      const selected = currentTarget();
      if (!selected || !selected.existing) return;
      setSavePending(true);
      textarea.focus({ preventScroll: true });
      const started = invokeCommand(
        root,
        invoke,
        announce,
        "pgn.comment_delete",
        { slot: selected.slot, index: selected.index },
        {
          afterResult: function (result) {
            if (result.kind === "error") {
              recoverEditor();
              return;
            }
            setSavePending(false);
            if (result.kind === "delegated") closeAndRestore();
          },
          afterFailure: recoverEditor
        }
      );
      if (!started) recoverEditor();
    });
    cancel.addEventListener("click", closeAndRestore);
    dialog.addEventListener("cancel", function (event) {
      event.preventDefault();
      closeAndRestore();
    });
    dialog.appendChild(save);
    dialog.appendChild(remove);
    dialog.appendChild(cancel);

    return {
      dialog: dialog,
      open: function (button) {
        if (!editor.enabled) return;
        const activeFlight = root._pgnFlight;
        const epoch = root._pgnRenderEpoch || 0;
        if (activeFlight && activeFlight.epoch === epoch) return;
        opener = button;
        dialog.showModal();
        if (entries.length || addSlots.length) {
          target.value = entries.length ? "existing:0" : "new:0";
          syncTarget();
          target.focus();
        } else {
          textarea.value = editor.value;
          textarea.focus();
          textarea.select();
        }
      }
    };
  }

  function buildTagDialog(root, snapshot, invoke, announce) {
    const en = snapshot.document.lang === "en";
    const dialog = node("dialog");
    dialog.id = "pgn-tag-dialog";
    const title = node("h2", en ? "Edit PGN tag" : "Редагувати тег PGN");
    title.id = "pgn-tag-dialog-title";
    dialog.setAttribute("aria-labelledby", title.id);
    dialog.setAttribute("aria-busy", "false");
    dialog.appendChild(title);

    const existingLabel = node("label", en ? "Existing tags" : "Наявні теги");
    const existing = node("select");
    existing.id = "pgn-tag-existing";
    existingLabel.htmlFor = existing.id;
    const custom = node("option", en ? "Custom tag" : "Власний тег");
    custom.value = "";
    existing.appendChild(custom);
    snapshot.game.tags.forEach(function (tag) {
      const option = node("option", tag.name + ": " + tag.value);
      option.value = tag.name;
      existing.appendChild(option);
    });
    dialog.appendChild(existingLabel);
    dialog.appendChild(existing);

    const nameLabel = node("label", en ? "Tag name" : "Назва тегу");
    const nameInput = node("input");
    nameInput.id = "pgn-tag-name";
    nameInput.maxLength = 80;
    nameLabel.htmlFor = nameInput.id;
    dialog.appendChild(nameLabel);
    dialog.appendChild(nameInput);

    const valueLabel = node("label", en ? "Tag value" : "Значення тегу");
    const valueInput = node("textarea");
    valueInput.id = "pgn-tag-value";
    valueInput.maxLength = 360;
    valueLabel.htmlFor = valueInput.id;
    dialog.appendChild(valueLabel);
    dialog.appendChild(valueInput);

    const save = node("button", en ? "Save" : "Зберегти");
    save.type = "button";
    const remove = node("button", en ? "Delete tag" : "Видалити тег");
    remove.type = "button";
    const cancel = node("button", en ? "Cancel" : "Скасувати");
    cancel.type = "button";
    let opener = null;
    let pending = false;

    function selectedTag() {
      const name = existing.value || nameInput.value.trim();
      return snapshot.game.tags.find(function (tag) { return tag.name === name; }) || null;
    }
    function syncFromExisting() {
      if (!existing.value) return;
      const tag = selectedTag();
      nameInput.value = existing.value;
      valueInput.value = tag ? tag.value : "";
    }
    existing.addEventListener("change", syncFromExisting);

    function setPending(value) {
      pending = value === true;
      save.disabled = pending;
      remove.disabled = pending;
      cancel.disabled = pending;
      existing.disabled = pending;
      nameInput.readOnly = pending;
      valueInput.readOnly = pending;
      dialog.setAttribute("aria-busy", pending ? "true" : "false");
    }
    function restore() {
      setPending(false);
      if (dialog.open) nameInput.focus({ preventScroll: true });
    }
    function closeAndRestore() {
      if (pending) return;
      if (dialog.open) dialog.close();
      if (opener && typeof opener.focus === "function") opener.focus({ preventScroll: true });
    }
    function submit(command) {
      const name = nameInput.value.trim();
      if (!name) {
        announce(en ? "Enter a tag name." : "Введіть назву тегу.");
        nameInput.focus({ preventScroll: true });
        return;
      }
      if ((name === "SetUp" || name === "FEN")) {
        announce(en ? "Use the position workflow to change SetUp/FEN." : "Для SetUp/FEN використайте роботу з позицією.");
        nameInput.focus({ preventScroll: true });
        return;
      }
      if (command === "pgn.tag_delete" && name === "Result") {
        announce(en ? "Result cannot be deleted." : "Тег Result не можна видалити.");
        nameInput.focus({ preventScroll: true });
        return;
      }
      setPending(true);
      const payload = command === "pgn.tag_edit" ? { name: name, value: valueInput.value } : { name: name };
      const started = invokeCommand(root, invoke, announce, command, payload, {
        afterResult: function (result) {
          if (result.kind === "error") {
            restore();
            return;
          }
          setPending(false);
          if (result.kind === "delegated") closeAndRestore();
        },
        afterFailure: restore
      });
      if (!started) restore();
    }
    save.addEventListener("click", function () { submit("pgn.tag_edit"); });
    remove.addEventListener("click", function () { submit("pgn.tag_delete"); });
    cancel.addEventListener("click", closeAndRestore);
    dialog.addEventListener("cancel", function (event) {
      event.preventDefault();
      closeAndRestore();
    });
    dialog.appendChild(save);
    dialog.appendChild(remove);
    dialog.appendChild(cancel);

    return {
      dialog: dialog,
      open: function (button) {
        const activeFlight = root._pgnFlight;
        const epoch = root._pgnRenderEpoch || 0;
        if (activeFlight && activeFlight.epoch === epoch) return;
        opener = button;
        existing.value = "";
        nameInput.value = "";
        valueInput.value = "";
        setPending(false);
        dialog.showModal();
        existing.focus();
      }
    };
  }

  function buildSimpleEditDialog(root, snapshot, invoke, announce, spec) {
    const dialog = node("dialog");
    const title = node("h2", spec.title);
    const titleId = spec.id + "-title";
    title.id = titleId;
    dialog.id = spec.id;
    dialog.setAttribute("aria-labelledby", titleId);
    dialog.setAttribute("aria-busy", "false");
    dialog.appendChild(title);

    const label = node("label", spec.label);
    const textarea = node("textarea");
    textarea.id = spec.id + "-text";
    textarea.maxLength = spec.maxLength;
    label.htmlFor = textarea.id;
    dialog.appendChild(label);
    dialog.appendChild(textarea);

    const save = node("button", spec.saveLabel);
    save.type = "button";
    const cancel = node("button", spec.cancelLabel);
    cancel.type = "button";
    let opener = null;
    let pending = false;

    function setPending(value) {
      pending = value === true;
      save.disabled = pending;
      cancel.disabled = pending;
      textarea.readOnly = pending;
      dialog.setAttribute("aria-busy", pending ? "true" : "false");
    }

    function closeAndRestore() {
      if (pending) return;
      if (dialog.open) dialog.close();
      if (opener && typeof opener.focus === "function") {
        opener.focus({ preventScroll: true });
      }
    }

    function recover() {
      setPending(false);
      if (dialog.open) {
        textarea.focus({ preventScroll: true });
        if (typeof textarea.select === "function") textarea.select();
      }
    }

    save.addEventListener("click", function () {
      if (pending) return;
      const value = textarea.value;
      if (spec.command === "pgn.search") root._pgnLastSearch = value;
      if (spec.requireNonEmpty && !value.trim()) {
        announce(spec.emptyMessage);
        textarea.focus({ preventScroll: true });
        return;
      }
      setPending(true);
      textarea.focus({ preventScroll: true });
      const started = invokeCommand(
        root,
        invoke,
        announce,
        spec.command,
        { text: value },
        {
          afterResult: function (result) {
            if (result.kind === "error") {
              recover();
              return;
            }
            setPending(false);
            if (result.kind === "delegated") closeAndRestore();
          },
          afterFailure: recover
        }
      );
      if (!started) recover();
    });
    cancel.addEventListener("click", closeAndRestore);
    dialog.addEventListener("cancel", function (event) {
      event.preventDefault();
      closeAndRestore();
    });
    dialog.appendChild(save);
    dialog.appendChild(cancel);

    return {
      dialog: dialog,
      open: function (button) {
        const activeFlight = root._pgnFlight;
        const epoch = root._pgnRenderEpoch || 0;
        if (activeFlight && activeFlight.epoch === epoch) return;
        opener = button;
        textarea.value = typeof spec.initialValue === "function" ? spec.initialValue() : "";
        dialog.showModal();
        textarea.focus();
        if (typeof textarea.select === "function") textarea.select();
      }
    };
  }

  function renderActions(root, host, snapshot, invoke, announce, searchDialog, appendDialog, tagDialog, commentDialog, nagDialog, variationDialog) {
    const toolbar = node("div");
    toolbar.setAttribute("role", "toolbar");
    toolbar.setAttribute("aria-orientation", "horizontal");
    const buttons = [];

    snapshot.actions.forEach(function (action) {
      const button = node("button", action.label);
      button.type = "button";
      button.disabled = !action.enabled;
      button.tabIndex = -1;
      button.dataset.action = action.action;
      button.addEventListener("focus", function () {
        if (button.disabled) return;
        buttons.forEach(function (candidate) {
          candidate.tabIndex = candidate === button ? 0 : -1;
        });
      });
      button.addEventListener("click", function () {
        if (button.disabled) return;
        if (action.action === "pgn.search") {
          searchDialog.open(button);
          return;
        }
        if (action.action === "pgn.append_moves") {
          appendDialog.open(button);
          return;
        }
        if (action.action === "pgn.tag_edit" || action.action === "pgn.tag_delete") {
          tagDialog.open(button);
          return;
        }
        if (action.action === "pgn.comment_edit") {
          commentDialog.open(button);
          return;
        }
        if (action.action === "pgn.nag_edit") {
          nagDialog.open(button);
          return;
        }
        if (action.action === "pgn.variation_add") {
          variationDialog.open(button);
          return;
        }
        invokeCommand(root, invoke, announce, action.action, {});
      });
      button.addEventListener("keydown", function (event) {
        if (button.disabled) return;
        const enabled = buttons.filter(function (candidate) {
          return !candidate.disabled;
        });
        if (!enabled.length) return;
        const current = enabled.indexOf(button);
        if (current < 0) return;

        const resolve = global.accessibleChessKeymapAction;
        let actionId = "";
        let resolverReady = false;
        if (typeof resolve === "function") {
          const resolved = resolve(event, "toolbar");
          if (resolved !== null && resolved !== undefined) {
            resolverReady = true;
            actionId = typeof resolved === "string" ? resolved : "";
          }
        }
        if (
          !resolverReady &&
          !event.altKey && !event.ctrlKey && !event.shiftKey && !event.metaKey
        ) {
          if (event.key === "ArrowRight") actionId = "toolbar.next_control";
          else if (event.key === "ArrowLeft") actionId = "toolbar.previous_control";
          else if (event.key === "Home") actionId = "toolbar.first_control";
          else if (event.key === "End") actionId = "toolbar.last_control";
        }

        let target = -1;
        if (actionId === "toolbar.next_control") {
          target = (current + 1) % enabled.length;
        } else if (actionId === "toolbar.previous_control") {
          target = (current + enabled.length - 1) % enabled.length;
        } else if (actionId === "toolbar.first_control") {
          target = 0;
        } else if (actionId === "toolbar.last_control") {
          target = enabled.length - 1;
        } else {
          return;
        }

        event.preventDefault();
        if (typeof event.stopPropagation === "function") event.stopPropagation();
        enabled.forEach(function (candidate, index) {
          candidate.tabIndex = index === target ? 0 : -1;
        });
        enabled[target].focus({ preventScroll: true });
      });
      buttons.push(button);
      toolbar.appendChild(button);
    });

    const firstEnabled = buttons.find(function (button) {
      return !button.disabled;
    });
    if (firstEnabled) firstEnabled.tabIndex = 0;
    host.appendChild(toolbar);
  }

  function commitRender(root, fragment, snapshot) {
    root.replaceChildren(fragment);
    root._pgnErrorMessage = snapshot.error_message;
    root._pgnPresentationToken =
      typeof snapshot.presentation_token === "string"
        ? snapshot.presentation_token
        : "";
    root._pgnRenderEpoch = (root._pgnRenderEpoch || 0) + 1;
    root._pgnFlight = null;
  }

  function renderPgnSurface(root, snapshot, invoke, announce, requestedFocus) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new TypeError("PGN root must support replaceChildren");
    }
    requireFunction(invoke, "PGN invoke");
    announce =
      announce == null ? function () {} : requireFunction(announce, "PGN announce");
    requestedFocus = requireRequestedFocus(requestedFocus);
    requireSnapshot(snapshot);

    const fragment = document.createDocumentFragment();
    const main = node("section");

    if (snapshot.status === "unavailable") {
      const message = node("p", snapshot.unavailable_message);
      const refresh = node("button", snapshot.refresh_label);
      refresh.type = "button";
      refresh.id = "pgn-refresh-view";
      refresh.addEventListener("click", function () {
        invokeCommand(
          root,
          invoke,
          announce,
          "pgn.refresh",
          {},
          { omitLease: true }
        );
      });
      main.appendChild(message);
      main.appendChild(refresh);
      fragment.appendChild(main);
      commitRender(root, fragment, snapshot);
      if (requestedFocus === refresh.id && typeof refresh.focus === "function") {
        refresh.focus({ preventScroll: true });
      }
      return;
    }

    if (snapshot.status === "empty") {
      main.appendChild(node("p", snapshot.empty_message));
      fragment.appendChild(main);
      commitRender(root, fragment, snapshot);
      return;
    }

    const game = snapshot.game;
    main.appendChild(node("h2", game.heading));
    main.appendChild(node("p", game.position_label));
    main.appendChild(node("p", game.result_label + ": " + game.result));
    renderTags(main, game);
    renderWarnings(main, game);
    renderMainLineComments(main, game);
    renderTree(root, main, snapshot, invoke, announce);
    const commentDialog = buildCommentDialog(
      root,
      snapshot,
      invoke,
      announce
    );
    const selected = snapshot.tree.find(function (item) { return item.selected; });
    const en = snapshot.document.lang === "en";
    const searchDialog = buildSimpleEditDialog(root, snapshot, invoke, announce, {
      id: "pgn-search-dialog",
      title: en ? "Search PGN" : "Пошук у PGN",
      label: en ? "Search tags, moves, comments and NAGs" : "Пошук у тегах, ходах, коментарях і NAG",
      saveLabel: en ? "Find next" : "Знайти далі",
      cancelLabel: en ? "Close" : "Закрити",
      command: "pgn.search",
      maxLength: 4096,
      requireNonEmpty: true,
      emptyMessage: en ? "Enter search text." : "Введіть текст для пошуку.",
      initialValue: function () { return root._pgnLastSearch || ""; }
    });
    const tagDialog = buildTagDialog(root, snapshot, invoke, announce);
    const appendDialog = buildSimpleEditDialog(root, snapshot, invoke, announce, {
      id: "pgn-append-dialog",
      title: en ? "Continue current line" : "Продовжити поточну лінію",
      label: en ? "Enter legal SAN moves from the current position, for example Nf3 Nc6" : "Введіть легальні SAN-ходи від поточної позиції, наприклад Nf3 Nc6",
      saveLabel: en ? "Add moves" : "Додати ходи",
      cancelLabel: en ? "Cancel" : "Скасувати",
      command: "pgn.append_moves",
      maxLength: 8192,
      requireNonEmpty: true,
      emptyMessage: en ? "Enter at least one move." : "Введіть хоча б один хід.",
      initialValue: function () { return ""; }
    });
    const nagDialog = buildSimpleEditDialog(root, snapshot, invoke, announce, {
      id: "pgn-nag-dialog",
      title: en ? "NAG annotations" : "Анотації NAG",
      label: en ? "NAGs separated by spaces, for example ! ? $1 $2" : "NAG через пробіл, наприклад ! ? $1 $2",
      saveLabel: en ? "Save" : "Зберегти",
      cancelLabel: en ? "Cancel" : "Скасувати",
      command: "pgn.nag_edit",
      maxLength: 512,
      requireNonEmpty: false,
      emptyMessage: "",
      initialValue: function () {
        return selected && Array.isArray(selected.nags) ? selected.nags.join(" ") : "";
      }
    });
    const variationDialog = buildSimpleEditDialog(root, snapshot, invoke, announce, {
      id: "pgn-variation-dialog",
      title: en ? "Add variation" : "Додати варіант",
      label: en ? "Enter legal SAN moves from the position before the selected move, for example c5 Nf3" : "Введіть легальні SAN-ходи від позиції перед вибраним ходом, наприклад c5 Nf3",
      saveLabel: en ? "Add" : "Додати",
      cancelLabel: en ? "Cancel" : "Скасувати",
      command: "pgn.variation_add",
      maxLength: 8192,
      requireNonEmpty: true,
      emptyMessage: en ? "Enter at least one move." : "Введіть хоча б один хід.",
      initialValue: function () { return ""; }
    });
    renderActions(root, main, snapshot, invoke, announce, searchDialog, appendDialog, tagDialog, commentDialog, nagDialog, variationDialog);
    main.appendChild(commentDialog.dialog);
    main.appendChild(searchDialog.dialog);
    main.appendChild(appendDialog.dialog);
    main.appendChild(tagDialog.dialog);
    main.appendChild(nagDialog.dialog);
    main.appendChild(variationDialog.dialog);
    fragment.appendChild(main);
    commitRender(root, fragment, snapshot);
    focusTarget(root, requestedFocus);
  }

  global.AccessibleChessPgnSurface = Object.freeze({
    render: renderPgnSurface
  });
})(window);
