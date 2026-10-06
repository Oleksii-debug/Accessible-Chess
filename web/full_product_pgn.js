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
  const MAX_PGN_TAG_NAME = 80;
  const MAX_PGN_TAG_VALUE = 360;
  const FOCUS_ID_PATTERN = /^[A-Za-z0-9_-]{1,160}$/;
  const PGN_DOM_ID_PATTERN = /^pgn-node-[0-9a-f]{20}$/;
  const PRESENTATION_TOKEN_PATTERN = /^[0-9a-f]{64}$/;
  const ACTIONS = [
    "pgn.previous_game",
    "pgn.next_game",
    "pgn.parent",
    "pgn.comment_edit",
    "pgn.comment_delete",
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
  }

  function requireMetadataEditor(editor) {
    requireRecord(editor, "PGN metadata editor");
    for (const field of [
      "open_label", "title", "tag_select_label", "new_tag_label",
      "tag_name_label", "tag_value_label", "tag_save_label",
      "tag_delete_label", "result_label", "result_save_label", "close_label"
    ]) {
      requireText(editor[field], "PGN metadata " + field, false, 120);
    }
    if (["1-0", "0-1", "1/2-1/2", "*"].indexOf(editor.result) < 0) {
      throw new TypeError("PGN metadata result is invalid");
    }
    if (!Array.isArray(editor.editable_tags) || editor.editable_tags.length > MAX_PGN_TAGS) {
      throw new TypeError("PGN editable tags exceed their item-count contract");
    }
    const seen = new Set();
    editor.editable_tags.forEach(function (entry, index) {
      if (!Object.prototype.hasOwnProperty.call(editor.editable_tags, index)) {
        throw new TypeError("PGN editable tags must be dense");
      }
      const tag = requireRecord(entry, "PGN editable tag");
      requireText(tag.name, "PGN editable tag name", false, MAX_PGN_TAG_NAME);
      requireText(tag.value, "PGN editable tag value", true, MAX_PGN_TAG_VALUE);
      if (tag.name === "SetUp" || tag.name === "FEN" || tag.name === "Result" || seen.has(tag.name)) {
        throw new TypeError("PGN editable tag contract is invalid");
      }
      seen.add(tag.name);
    });
  }

  function requireGameManager(manager) {
    requireRecord(manager, "PGN game manager");
    for (const field of [
      "add_label", "delete_label", "delete_title", "delete_message",
      "delete_confirm_label", "cancel_label"
    ]) {
      requireText(manager[field], "PGN game manager " + field, false, 240);
    }
    if (typeof manager.can_delete !== "boolean") {
      throw new TypeError("PGN game manager delete state is invalid");
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
    requireMetadataEditor(snapshot.metadata_editor);
    requireGameManager(snapshot.game_manager);

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
        snapshot.metadata_editor.editable_tags.length !== 0 ||
        snapshot.game_manager.can_delete !== false ||
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

    if (snapshot.game_manager.can_delete !== (game.count > 1)) {
      throw new TypeError("PGN game delete state is inconsistent");
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
      if (
        ACTIONS.indexOf(payload.action) < 0 &&
        ["pgn.tag_edit", "pgn.tag_delete", "pgn.result_set", "pgn.game_add", "pgn.game_delete"].indexOf(payload.action) < 0
      ) {
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

  function buildGameControls(root, snapshot, invoke, announce) {
    const manager = snapshot.game_manager;
    const host = node("div");
    host.setAttribute("role", "group");

    const add = node("button", manager.add_label);
    add.type = "button";
    add.id = "pgn-game-add";
    const remove = node("button", manager.delete_label);
    remove.type = "button";
    remove.id = "pgn-game-delete";
    remove.disabled = !manager.can_delete;

    const dialog = node("dialog");
    dialog.id = "pgn-game-delete-dialog";
    dialog.setAttribute("aria-busy", "false");
    const title = node("h2", manager.delete_title);
    title.id = "pgn-game-delete-title";
    dialog.setAttribute("aria-labelledby", title.id);
    dialog.appendChild(title);
    dialog.appendChild(node("p", manager.delete_message));
    const confirm = node("button", manager.delete_confirm_label);
    confirm.type = "button";
    const cancel = node("button", manager.cancel_label);
    cancel.type = "button";
    dialog.appendChild(confirm);
    dialog.appendChild(cancel);

    let pending = false;
    function hasActiveFlight() {
      const flight = root._pgnFlight;
      const epoch = root._pgnRenderEpoch || 0;
      return !!(flight && flight.epoch === epoch);
    }
    function setPending(value) {
      pending = value === true;
      add.disabled = pending;
      remove.disabled = pending || !manager.can_delete;
      confirm.disabled = pending;
      cancel.disabled = pending;
      dialog.setAttribute("aria-busy", pending ? "true" : "false");
    }
    function closeDelete() {
      if (pending) return;
      if (dialog.open) dialog.close();
      if (typeof remove.focus === "function") remove.focus({ preventScroll: true });
    }

    add.addEventListener("click", function () {
      if (pending || hasActiveFlight()) return;
      setPending(true);
      const started = invokeCommand(
        root,
        invoke,
        announce,
        "pgn.game_add",
        {},
        {
          afterResult: function (result) {
            if (result.kind === "error") {
              setPending(false);
              add.focus({ preventScroll: true });
              return;
            }
            setPending(false);
          },
          afterFailure: function () {
            setPending(false);
            add.focus({ preventScroll: true });
          }
        }
      );
      if (!started) setPending(false);
    });

    remove.addEventListener("click", function () {
      if (remove.disabled || pending || hasActiveFlight()) return;
      dialog.showModal();
      confirm.focus();
    });
    confirm.addEventListener("click", function () {
      if (pending) return;
      setPending(true);
      const started = invokeCommand(
        root,
        invoke,
        announce,
        "pgn.game_delete",
        {},
        {
          afterResult: function (result) {
            if (result.kind === "error") {
              setPending(false);
              confirm.focus({ preventScroll: true });
              return;
            }
            setPending(false);
            if (result.kind === "delegated") closeDelete();
          },
          afterFailure: function () {
            setPending(false);
            confirm.focus({ preventScroll: true });
          }
        }
      );
      if (!started) setPending(false);
    });
    cancel.addEventListener("click", closeDelete);
    dialog.addEventListener("cancel", function (event) {
      event.preventDefault();
      closeDelete();
    });

    host.appendChild(add);
    host.appendChild(remove);
    return { host: host, dialog: dialog };
  }

  function buildMetadataDialog(root, snapshot, invoke, announce) {
    const editor = snapshot.metadata_editor;
    const dialog = node("dialog");
    dialog.id = "pgn-metadata-dialog";
    dialog.setAttribute("aria-busy", "false");

    const title = node("h2", editor.title);
    title.id = "pgn-metadata-dialog-title";
    dialog.setAttribute("aria-labelledby", title.id);
    dialog.appendChild(title);

    const selectLabel = node("label", editor.tag_select_label);
    const tagSelect = node("select");
    tagSelect.id = "pgn-metadata-tag-select";
    selectLabel.htmlFor = tagSelect.id;
    const newOption = node("option", editor.new_tag_label);
    newOption.value = "";
    tagSelect.appendChild(newOption);
    editor.editable_tags.forEach(function (entry) {
      const option = node("option", entry.name);
      option.value = entry.name;
      tagSelect.appendChild(option);
    });
    dialog.appendChild(selectLabel);
    dialog.appendChild(tagSelect);

    const nameLabel = node("label", editor.tag_name_label);
    const nameInput = node("input");
    nameInput.id = "pgn-metadata-tag-name";
    nameInput.type = "text";
    nameInput.maxLength = MAX_PGN_TAG_NAME;
    nameLabel.htmlFor = nameInput.id;
    dialog.appendChild(nameLabel);
    dialog.appendChild(nameInput);

    const valueLabel = node("label", editor.tag_value_label);
    const valueInput = node("input");
    valueInput.id = "pgn-metadata-tag-value";
    valueInput.type = "text";
    valueInput.maxLength = MAX_PGN_TAG_VALUE;
    valueLabel.htmlFor = valueInput.id;
    dialog.appendChild(valueLabel);
    dialog.appendChild(valueInput);

    const saveTag = node("button", editor.tag_save_label);
    saveTag.type = "button";
    const deleteTag = node("button", editor.tag_delete_label);
    deleteTag.type = "button";
    deleteTag.disabled = true;

    const resultLabel = node("label", editor.result_label);
    const resultSelect = node("select");
    resultSelect.id = "pgn-metadata-result";
    resultLabel.htmlFor = resultSelect.id;
    ["*", "1-0", "0-1", "1/2-1/2"].forEach(function (value) {
      const option = node("option", value);
      option.value = value;
      if (value === editor.result) option.selected = true;
      resultSelect.appendChild(option);
    });
    resultSelect.value = editor.result;
    const saveResult = node("button", editor.result_save_label);
    saveResult.type = "button";
    const close = node("button", editor.close_label);
    close.type = "button";

    let opener = null;
    let pending = false;
    const tagByName = new Map();
    editor.editable_tags.forEach(function (entry) {
      tagByName.set(entry.name, entry.value);
    });

    function syncTagFields() {
      const selected = tagSelect.value;
      if (selected && tagByName.has(selected)) {
        nameInput.value = selected;
        valueInput.value = tagByName.get(selected);
        deleteTag.disabled = pending;
      } else {
        nameInput.value = "";
        valueInput.value = "";
        deleteTag.disabled = true;
      }
    }

    function setPending(value) {
      pending = value === true;
      dialog.setAttribute("aria-busy", pending ? "true" : "false");
      tagSelect.disabled = pending;
      nameInput.readOnly = pending;
      valueInput.readOnly = pending;
      resultSelect.disabled = pending;
      saveTag.disabled = pending;
      saveResult.disabled = pending;
      close.disabled = pending;
      deleteTag.disabled = pending || !tagSelect.value;
    }

    function recover(focusNode) {
      setPending(false);
      if (dialog.open && focusNode && typeof focusNode.focus === "function") {
        focusNode.focus({ preventScroll: true });
      }
    }

    function run(command, payload, focusNode) {
      if (pending) return;
      setPending(true);
      const started = invokeCommand(
        root,
        invoke,
        announce,
        command,
        payload,
        {
          afterResult: function (result) {
            if (result.kind === "error") {
              recover(focusNode);
              return;
            }
            setPending(false);
            if (result.kind === "delegated") closeAndRestore();
          },
          afterFailure: function () { recover(focusNode); }
        }
      );
      if (!started) recover(focusNode);
    }

    tagSelect.addEventListener("change", syncTagFields);
    saveTag.addEventListener("click", function () {
      run("pgn.tag_edit", { name: nameInput.value, value: valueInput.value }, valueInput);
    });
    deleteTag.addEventListener("click", function () {
      if (!tagSelect.value) return;
      run("pgn.tag_delete", { name: tagSelect.value }, tagSelect);
    });
    saveResult.addEventListener("click", function () {
      run("pgn.result_set", { result: resultSelect.value }, resultSelect);
    });
    function closeAndRestore() {
      if (pending) return;
      if (dialog.open) dialog.close();
      if (opener && typeof opener.focus === "function") opener.focus({ preventScroll: true });
    }
    close.addEventListener("click", closeAndRestore);
    dialog.addEventListener("cancel", function (event) {
      event.preventDefault();
      closeAndRestore();
    });

    dialog.appendChild(saveTag);
    dialog.appendChild(deleteTag);
    dialog.appendChild(resultLabel);
    dialog.appendChild(resultSelect);
    dialog.appendChild(saveResult);
    dialog.appendChild(close);
    syncTagFields();

    return {
      dialog: dialog,
      openButton: (function () {
        const button = node("button", editor.open_label);
        button.type = "button";
        button.id = "pgn-metadata-open";
        button.addEventListener("click", function () {
          const activeFlight = root._pgnFlight;
          const epoch = root._pgnRenderEpoch || 0;
          if (activeFlight && activeFlight.epoch === epoch) return;
          opener = button;
          syncTagFields();
          dialog.showModal();
          tagSelect.focus();
        });
        return button;
      })()
    };
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
    const cancel = node("button", editor.cancel_label);
    cancel.type = "button";
    let opener = null;
    let savePending = false;

    function setSavePending(value) {
      savePending = value === true;
      save.disabled = savePending || !editor.enabled;
      cancel.disabled = savePending;
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
      const started = invokeCommand(
        root,
        invoke,
        announce,
        "pgn.comment_edit",
        { text: textarea.value },
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
        if (!editor.enabled) return;
        const activeFlight = root._pgnFlight;
        const epoch = root._pgnRenderEpoch || 0;
        if (activeFlight && activeFlight.epoch === epoch) return;
        opener = button;
        dialog.showModal();
        textarea.focus();
        textarea.select();
      }
    };
  }

  function renderActions(root, host, snapshot, invoke, announce, commentDialog) {
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
        if (action.action === "pgn.comment_edit") {
          commentDialog.open(button);
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
    const gameControls = buildGameControls(root, snapshot, invoke, announce);
    main.appendChild(gameControls.host);
    const metadataDialog = buildMetadataDialog(root, snapshot, invoke, announce);
    main.appendChild(metadataDialog.openButton);
    renderWarnings(main, game);
    renderTree(root, main, snapshot, invoke, announce);
    const commentDialog = buildCommentDialog(
      root,
      snapshot,
      invoke,
      announce
    );
    renderActions(root, main, snapshot, invoke, announce, commentDialog);
    main.appendChild(commentDialog.dialog);
    main.appendChild(metadataDialog.dialog);
    main.appendChild(gameControls.dialog);
    fragment.appendChild(main);
    commitRender(root, fragment, snapshot);
    focusTarget(root, requestedFocus);
  }

  global.AccessibleChessPgnSurface = Object.freeze({
    render: renderPgnSurface
  });
})(window);
