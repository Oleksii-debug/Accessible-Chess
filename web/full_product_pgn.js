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
      snapshot.status !== "empty"
      && snapshot.status !== "ready"
      && snapshot.status !== "unavailable"
    ) {
      throw new TypeError("PGN status is invalid");
    }
    if (
      snapshot.presentation_token !== undefined
      && (
        typeof snapshot.presentation_token !== "string"
        || !/^[0-9a-f]{64}$/.test(snapshot.presentation_token)
      )
    ) {
      throw new TypeError("PGN presentation token is invalid");
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
      const unavailableGame = requireRecord(
        snapshot.game,
        "PGN unavailable game"
      );
      if (
        Object.keys(unavailableGame).length !== 0
        || snapshot.tree.length !== 0
        || snapshot.focus_target !== "pgn-refresh-view"
        || !Array.isArray(snapshot.actions)
        || snapshot.actions.length !== 0
        || snapshot.comment_editor.enabled !== false
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

  function wireToolbarKeyboard(toolbar) {
    if (!toolbar || typeof toolbar.addEventListener !== "function") {
      throw new TypeError("toolbar must support keyboard events");
    }
    const controls = [];
    for (let index = 0; index < toolbar.children.length; index += 1) {
      const control = toolbar.children[index];
      if (!control || control.tagName !== "BUTTON") continue;
      control.tabIndex = -1;
      if (!control.disabled) controls.push(control);
    }
    if (!controls.length) return;

    function setActive(control) {
      controls.forEach(function (candidate) {
        candidate.tabIndex = candidate === control ? 0 : -1;
      });
    }

    setActive(controls[0]);
    controls.forEach(function (control) {
      control.addEventListener("focus", function () {
        setActive(control);
      });
    });

    toolbar.addEventListener("keydown", function (event) {
      const current = controls.indexOf(event.target);
      if (current < 0) return;
      let next = current;
      if (event.key === "ArrowRight") {
        next = (current + 1) % controls.length;
      } else if (event.key === "ArrowLeft") {
        next = (current - 1 + controls.length) % controls.length;
      } else if (event.key === "Home") {
        next = 0;
      } else if (event.key === "End") {
        next = controls.length - 1;
      } else {
        return;
      }
      if (typeof event.preventDefault === "function") event.preventDefault();
      const target = controls[next];
      setActive(target);
      if (typeof target.focus === "function") {
        target.focus({ preventScroll: true });
      }
    });
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

  function commandFlightIsCurrent(root, token, epoch) {
    return root._pgnCommandFlight === token && root._pgnRenderEpoch === epoch;
  }

  function invokeCommand(root, invoke, announce, command, payload, onResult) {
    if (root._pgnCommandFlight) return false;
    const focusBefore = document.activeElement;
    const epoch = root._pgnRenderEpoch;
    const token = {};
    root._pgnCommandFlight = token;
    Promise.resolve()
      .then(function () {
        if (!commandFlightIsCurrent(root, token, epoch)) return null;
        const commandPayload = Object.assign({}, payload || {});
        if (root._pgnPresentationToken) {
          commandPayload.presentation_token = root._pgnPresentationToken;
        }
        return invoke(command, commandPayload);
      })
      .then(
        function (result) {
          if (!commandFlightIsCurrent(root, token, epoch)) return;
          root._pgnCommandFlight = null;
          try {
            if (typeof onResult === "function") onResult(result);
            applyEvent(root, result, invoke, announce);
          } catch (_) {
            announceRejected(root, announce, focusBefore);
          }
        },
        function () {
          if (!commandFlightIsCurrent(root, token, epoch)) return;
          root._pgnCommandFlight = null;
          announceRejected(root, announce, focusBefore);
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
      const level = item.aria_level;
      const nextItem =
        itemIndex + 1 < snapshot.tree.length
          ? snapshot.tree[itemIndex + 1]
          : null;
      const hasVisibleChild = Boolean(
        nextItem && nextItem.aria_level === level + 1
      );
      const treeItem = node("li");
      treeItem.id = item.dom_id;
      treeItem.setAttribute("role", "treeitem");
      treeItem.setAttribute("aria-level", item.aria_level);
      treeItem.setAttribute("aria-selected", item.selected ? "true" : "false");
      if (hasVisibleChild) treeItem.setAttribute("aria-expanded", "true");
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
        // Modified arrows belong to the central application keymap.
        if (event.altKey || event.ctrlKey || event.shiftKey || event.metaKey) return;
        const navigationKey =
          event.key === "ArrowUp"
          || event.key === "ArrowDown"
          || event.key === "ArrowLeft"
          || event.key === "ArrowRight"
          || event.key === "Home"
          || event.key === "End";
        if (!navigationKey) return;
        if (typeof event.preventDefault === "function") event.preventDefault();

        let command = "";
        let payload = {};
        if (event.key === "ArrowUp") {
          if (itemIndex > 0) {
            command = "pgn.move";
            payload = { delta: -1 };
          }
        } else if (event.key === "ArrowDown") {
          if (itemIndex + 1 < snapshot.tree.length) {
            command = "pgn.move";
            payload = { delta: 1 };
          }
        } else if (event.key === "ArrowLeft") {
          if (item.has_parent) command = "pgn.parent";
        } else if (event.key === "ArrowRight") {
          if (hasVisibleChild) {
            command = "pgn.select";
            payload = { node_id: nextItem.node_id };
          }
        } else if (event.key === "Home") {
          if (itemIndex > 0) {
            command = "pgn.select";
            payload = { node_id: snapshot.tree[0].node_id };
          }
        } else if (event.key === "End") {
          const lastIndex = snapshot.tree.length - 1;
          if (itemIndex < lastIndex) {
            command = "pgn.select";
            payload = { node_id: snapshot.tree[lastIndex].node_id };
          }
        }
        if (!command) return;
        invokeCommand(root, invoke, announce, command, payload);
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

    function closeAndRestore() {
      if (dialog.open) dialog.close();
      if (opener && typeof opener.focus === "function") {
        opener.focus({ preventScroll: true });
      }
    }

    save.addEventListener("click", function () {
      invokeCommand(
        root,
        invoke,
        announce,
        "pgn.comment_edit",
        { text: textarea.value },
        function (result) {
          if (result && result.kind !== "error") closeAndRestore();
        }
      );
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
    snapshot.actions.forEach(function (action) {
      const button = node("button", action.label);
      button.type = "button";
      button.disabled = !action.enabled;
      button.dataset.action = action.action;
      button.addEventListener("click", function () {
        if (action.action === "pgn.comment_edit") {
          commentDialog.open(button);
          return;
        }
        invokeCommand(root, invoke, announce, action.action, {});
      });
      toolbar.appendChild(button);
    });
    wireToolbarKeyboard(toolbar);
    host.appendChild(toolbar);
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

    const committedPresentationToken = snapshot.presentation_token || "";
    root._pgnRenderEpoch = Number(root._pgnRenderEpoch || 0) + 1;
    root._pgnCommandFlight = null;
    root._pgnErrorMessage = snapshot.error_message;

    const fragment = document.createDocumentFragment();
    const main = node("section");
    if (snapshot.status === "empty") {
      main.appendChild(node("p", snapshot.empty_message));
      fragment.appendChild(main);
      root.replaceChildren(fragment);
      root._pgnPresentationToken = committedPresentationToken;
      return;
    }

    if (snapshot.status === "unavailable") {
      main.appendChild(node("p", snapshot.unavailable_message));
      const refresh = node("button", snapshot.refresh_label);
      refresh.type = "button";
      refresh.id = "pgn-refresh-view";
      refresh.addEventListener("click", function () {
        invokeCommand(root, invoke, announce, "pgn.refresh", {});
      });
      main.appendChild(refresh);
      fragment.appendChild(main);
      root.replaceChildren(fragment);
      root._pgnPresentationToken = committedPresentationToken;
      if (
        requestedFocus === refresh.id
        && typeof refresh.focus === "function"
      ) {
        refresh.focus({ preventScroll: true });
      }
      return;
    }

    const game = snapshot.game;
    main.appendChild(node("h2", game.heading));
    main.appendChild(node("p", game.position_label));
    main.appendChild(node("p", game.result_label + ": " + game.result));
    renderTags(main, game);
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
    fragment.appendChild(main);
    root.replaceChildren(fragment);
    root._pgnPresentationToken = committedPresentationToken;
    focusTarget(root, requestedFocus);
  }

  global.AccessibleChessPgnSurface = Object.freeze({
    render: renderPgnSurface
  });
})(window);
