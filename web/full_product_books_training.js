(function (global) {
  "use strict";

  const inFlightRoots = new WeakMap();
  const renderEpochs = new WeakMap();
  const MAX_BOOKMARK_NAME = 80;
  const MAX_BOOK_BLOCK_VISIBLE_CHARS = 12 * 1024 * 1024;
  const MAX_BOOK_LIST_ITEMS = 65536;
  const MAX_BOOK_HEADING_PATH_PARTS = 6;
  const MAX_BOOK_HEADING_PATH_TEXT = 360;
  const MAX_BOOK_SEMANTIC_ITEMS = 10000;
  const MAX_BOOK_SEMANTIC_DEPTH = 256;
  const MAX_BOOK_SEMANTIC_TEXT_ENTRIES = 50000;
  const MAX_STARTER_BOOKLETS = 24;
  const MAX_TRAINING_SOLUTION_MOVES = 64;
  const MAX_TRAINING_SOLUTION_TEXT = 128;
  const MAX_PUBLIC_FALLBACK_TEXT = 1200;
  const FOCUS_ID_PATTERN = /^[A-Za-z0-9_-]{1,160}$/;
  const BOOK_PRESENTATION_TOKEN_PATTERN = /^[0-9a-f]{64}$/;

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
    if (text !== undefined && text !== null) {
      if (typeof text === "string") {
        element.textContent = text;
      } else if (typeof text === "number" && Number.isFinite(text)) {
        element.textContent = String(text);
      } else {
        throw new TypeError("DOM text must be primitive text or a finite number");
      }
    }
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

      let next = -1;
      if (actionId === "toolbar.next_control") {
        next = (current + 1) % controls.length;
      } else if (actionId === "toolbar.previous_control") {
        next = (current - 1 + controls.length) % controls.length;
      } else if (actionId === "toolbar.first_control") {
        next = 0;
      } else if (actionId === "toolbar.last_control") {
        next = controls.length - 1;
      } else {
        return;
      }
      if (typeof event.preventDefault === "function") event.preventDefault();
      if (typeof event.stopPropagation === "function") event.stopPropagation();
      const target = controls[next];
      setActive(target);
      if (typeof target.focus === "function") target.focus({ preventScroll: true });
    });
  }

  function safeInvoke(
    root,
    invoke,
    command,
    payload,
    onResult,
    announce,
    fallbackMessage,
    onFailure
  ) {
    const startedAtEpoch = renderEpoch(root);
    const activeFlight = inFlightRoots.get(root);
    if (activeFlight && activeFlight.epoch === startedAtEpoch) return false;
    const flight = { epoch: startedAtEpoch };
    inFlightRoots.set(root, flight);
    setBusy(root, true);

    function isCurrent() {
      return inFlightRoots.get(root) === flight &&
        renderEpoch(root) === startedAtEpoch;
    }

    function finish() {
      if (inFlightRoots.get(root) !== flight) return;
      inFlightRoots.delete(root);
      setBusy(root, false);
    }

    function fail() {
      if (!isCurrent()) return;
      if (fallbackMessage) announce(fallbackMessage);
      if (typeof onFailure === "function") onFailure();
    }

    let result;
    try {
      result = invoke(command, payload || {});
    } catch (_) {
      fail();
      finish();
      return true;
    }
    Promise.resolve(result)
      .then(function (value) {
        if (!isCurrent()) return;
        return onResult(value);
      })
      .catch(fail)
      .then(finish, finish);
    return true;
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
    if (text.length > limit || text.indexOf("\x00") >= 0) {
      throw new TypeError(label + " exceeds its canonical text contract");
    }
    return text;
  }

  function requireRenderFocus(value, surface) {
    if (value === undefined || value === null || value === "") return "";
    requireBoundedText(value, surface + " requested focus", false, 160);
    if (!FOCUS_ID_PATTERN.test(value)) {
      throw new TypeError(surface + " requested focus is invalid");
    }
    return value;
  }

  function requireFallbackMessage(value, surface) {
    if (value === undefined || value === null) return "";
    return requireBoundedText(
      value,
      surface + " fallback message",
      true,
      MAX_PUBLIC_FALLBACK_TEXT
    );
  }

  function requireTrainingSolutionArgument(solution) {
    if (solution === undefined || solution === null) return [];
    if (!Array.isArray(solution) || solution.length > MAX_TRAINING_SOLUTION_MOVES) {
      throw new TypeError("Training solution argument is invalid");
    }
    for (let index = 0; index < solution.length; index += 1) {
      if (!Object.prototype.hasOwnProperty.call(solution, index)) {
        throw new TypeError("Training solution argument must be dense");
      }
      requireBoundedText(
        solution[index],
        "Training solution move",
        false,
        MAX_TRAINING_SOLUTION_TEXT
      );
    }
    return solution;
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
      try {
        requireBoundedText(action.label, surface + " snapshot action label", false, 120);
      } catch (_) {
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

  function requireBookSemanticTree(snapshot) {
    const tree = snapshot.semantic_tree;
    const block = snapshot.block;
    const semanticKind = block.kind === "Game" ? "game" :
      (block.kind === "VariationTree" ? "variation" : "");
    const hasSemanticTree = Object.prototype.hasOwnProperty.call(
      snapshot, "semantic_tree"
    );
    if (!semanticKind) {
      if (hasSemanticTree) {
        throw new TypeError("Non-semantic Book block carries semantic tree state");
      }
      return;
    }
    if (!hasSemanticTree || tree === undefined) {
      throw new TypeError("Semantic Book block is missing semantic tree state");
    }
    if (tree === null) {
      if (!block.warning) {
        throw new TypeError("Semantic Book fallback requires an accessible warning");
      }
      return;
    }
    if (typeof tree !== "object" || Array.isArray(tree)) {
      throw new TypeError("Book semantic tree is invalid for this block");
    }
    const expectedTreeFields = [
      "kind", "label", "players_label", "players", "result_label",
      "variation_depth_label", "result", "intro_comments", "outro_comments", "items"
    ];
    if (Object.prototype.hasOwnProperty.call(tree, "details")) {
      expectedTreeFields.push("details");
    }
    const treeFields = Object.keys(tree);
    if (treeFields.length !== expectedTreeFields.length ||
        expectedTreeFields.some(function (field) {
          return !Object.prototype.hasOwnProperty.call(tree, field);
        })) {
      throw new TypeError("Book semantic tree fields are invalid");
    }
    if (tree.kind !== semanticKind) {
      throw new TypeError("Book semantic tree kind is inconsistent");
    }

    let visibleText = 0;
    let textEntries = 0;
    function addVisibleUnits(units) {
      if (!Number.isSafeInteger(units) || units < 0) {
        throw new TypeError("Book semantic visible-text accounting is invalid");
      }
      visibleText += units;
      if (visibleText > MAX_BOOK_BLOCK_VISIBLE_CHARS) {
        throw new TypeError("Book semantic visible-text budget exceeded");
      }
    }
    function semanticText(value, name, allowEmpty, maxLength, countVisible) {
      requireBoundedText(value, name, allowEmpty, maxLength);
      textEntries += 1;
      if (textEntries > MAX_BOOK_SEMANTIC_TEXT_ENTRIES) {
        throw new TypeError("Book semantic text-entry budget exceeded");
      }
      if (countVisible !== false) addVisibleUnits(value.length);
    }
    function semanticComments(values, name) {
      if (!Array.isArray(values)) {
        throw new TypeError(name + " must be an array");
      }
      for (let index = 0; index < values.length; index += 1) {
        if (!Object.prototype.hasOwnProperty.call(values, index)) {
          throw new TypeError(name + " must be dense");
        }
        semanticText(values[index], name + " item", false, MAX_BOOK_BLOCK_VISIBLE_CHARS);
      }
    }

    semanticText(tree.label, "Book semantic label", false, 360);
    semanticText(tree.players_label, "Book semantic players label", false, 120);
    semanticText(tree.players, "Book semantic players", false, 720);
    addVisibleUnits(2); // ": " between the visible players label and value.
    if (tree.details !== undefined) {
      const metadataKinds = ["event", "site", "date", "round", "eco", "opening"];
      if (!Array.isArray(tree.details) || tree.details.length > metadataKinds.length) {
        throw new TypeError("Book semantic metadata rows are invalid");
      }
      const seenMetadata = new Set();
      for (let index = 0; index < tree.details.length; index += 1) {
        const detail = tree.details[index];
        if (!Object.prototype.hasOwnProperty.call(tree.details, index) ||
            !detail || typeof detail !== "object" || Array.isArray(detail) ||
            Object.keys(detail).length !== 3 ||
            !["kind", "label", "value"].every(function (key) {
              return Object.prototype.hasOwnProperty.call(detail, key);
            }) || metadataKinds.indexOf(detail.kind) < 0 || seenMetadata.has(detail.kind)) {
          throw new TypeError("Book semantic metadata row is invalid");
        }
        seenMetadata.add(detail.kind);
        semanticText(detail.label, "Book semantic metadata label", false, 120);
        semanticText(detail.value, "Book semantic metadata value", false, 1200);
        addVisibleUnits(2);
      }
    }
    semanticText(tree.result_label, "Book semantic result label", false, 120, false);
    semanticText(
      tree.variation_depth_label,
      "Book semantic variation depth label",
      false,
      120,
      false
    );
    if (["1-0", "0-1", "1/2-1/2", "*"].indexOf(tree.result) < 0) {
      throw new TypeError("Book semantic result is invalid");
    }
    semanticText(tree.result, "Book semantic result", false, 16);
    addVisibleUnits(tree.result_label.length + 2);
    semanticComments(tree.intro_comments, "Book semantic intro comments");
    semanticComments(tree.outro_comments, "Book semantic outro comments");

    if (!Array.isArray(tree.items) || tree.items.length > MAX_BOOK_SEMANTIC_ITEMS) {
      throw new TypeError("Book semantic items are invalid");
    }
    for (let index = 0; index < tree.items.length; index += 1) {
      if (!Object.prototype.hasOwnProperty.call(tree.items, index)) {
        throw new TypeError("Book semantic items must be dense");
      }
    }

    const expectedItemFields = [
      "kind", "depth", "parent_index", "label", "leading_comments",
      "comments_before", "comments_after", "trailing_comments", "result"
    ];
    const activeAncestorIndices = [];
    let previousDepth = 0;
    tree.items.forEach(function (item, index) {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        throw new TypeError("Book semantic item is invalid");
      }
      const itemFields = Object.keys(item);
      if (itemFields.length !== expectedItemFields.length ||
          expectedItemFields.some(function (field) {
            return !Object.prototype.hasOwnProperty.call(item, field);
          })) {
        throw new TypeError("Book semantic item fields are invalid");
      }
      if (item.kind !== "move" && item.kind !== "variation") {
        throw new TypeError("Book semantic item kind is invalid");
      }
      if (!Number.isSafeInteger(item.depth) ||
          item.depth < 0 ||
          item.depth > MAX_BOOK_SEMANTIC_DEPTH) {
        throw new TypeError("Book semantic item depth is invalid");
      }
      if ((item.kind === "move" && item.depth % 2 !== 0) ||
          (item.kind === "variation" && item.depth % 2 !== 1)) {
        throw new TypeError("Book semantic item kind/depth is inconsistent");
      }
      if (index === 0 && item.depth !== 0) {
        throw new TypeError("Book semantic root depth is invalid");
      }
      if (index > 0 && item.depth > previousDepth + 1) {
        throw new TypeError("Book semantic item depth jumps unexpectedly");
      }

      if (item.depth === 0) {
        if (item.parent_index !== null) {
          throw new TypeError("Book semantic root parent is invalid");
        }
      } else {
        if (!Number.isSafeInteger(item.parent_index) ||
            item.parent_index < 0 ||
            item.parent_index >= index ||
            tree.items[item.parent_index].depth !== item.depth - 1) {
          throw new TypeError("Book semantic item parent is invalid");
        }
        if (activeAncestorIndices.length < item.depth ||
            activeAncestorIndices[item.depth - 1] !== item.parent_index) {
          throw new TypeError("Book semantic parent does not match active ancestry");
        }
        const parentKind = tree.items[item.parent_index].kind;
        const expectedParentKind = item.kind === "variation" ? "move" : "variation";
        if (parentKind !== expectedParentKind) {
          throw new TypeError("Book semantic parent kind is invalid");
        }
      }

      semanticText(item.label, "Book semantic item label", false, 1200);
      semanticComments(item.leading_comments, "Book semantic leading comments");
      semanticComments(item.comments_before, "Book semantic comments before");
      semanticComments(item.comments_after, "Book semantic comments after");
      semanticComments(item.trailing_comments, "Book semantic trailing comments");
      if (item.kind === "move") {
        if (item.leading_comments.length || item.trailing_comments.length) {
          throw new TypeError("Book semantic move carries line-level comments");
        }
        if (item.result !== "") {
          throw new TypeError("Book semantic move carries a line result");
        }
      } else if (item.comments_before.length || item.comments_after.length) {
        throw new TypeError("Book semantic variation carries move comment slots");
      }
      if (item.result !== "" &&
          ["1-0", "0-1", "1/2-1/2", "*"].indexOf(item.result) < 0) {
        throw new TypeError("Book semantic item result is invalid");
      }
      semanticText(item.result, "Book semantic item result", true, 16);
      if (item.kind === "variation") {
        const variationLevel = (item.depth + 1) / 2;
        // renderBookSemanticTree emits " — <depth label>: <level>" for every
        // variation. The label is serialized once, so count every generated
        // rendered copy and its punctuation here before DOM replacement.
        addVisibleUnits(
          3 +
          tree.variation_depth_label.length +
          2 +
          String(variationLevel).length
        );
        if (item.result) {
          // A terminated variation repeats the shared result label.
          addVisibleUnits(tree.result_label.length + 2);
        }
      }

      activeAncestorIndices.length = item.depth;
      activeAncestorIndices.push(index);
      previousDepth = item.depth;
    });
  }

  function requireBookSnapshot(snapshot) {
    const block = requireSnapshotRecord(snapshot, "block", "Book");
    requireDocumentSpec(snapshot, "Book");
    requireBoundedText(snapshot.heading, "Book snapshot heading", false, 360);
    if (snapshot.presentation_token !== undefined) {
      requireBoundedText(
        snapshot.presentation_token,
        "Book presentation token",
        false,
        64
      );
      if (!BOOK_PRESENTATION_TOKEN_PATTERN.test(snapshot.presentation_token)) {
        throw new TypeError("Book presentation token is invalid");
      }
    }
    requireBookmarkSpec(snapshot);
    if (snapshot.book_metadata !== undefined) {
      const metadata = snapshot.book_metadata;
      if (!metadata || typeof metadata !== "object" || Array.isArray(metadata) ||
          Object.keys(metadata).length !== 3 ||
          !["title", "author", "language"].every(function (key) { return Object.prototype.hasOwnProperty.call(metadata, key); })) {
        throw new TypeError("Book reading metadata is invalid");
      }
      requireBoundedText(metadata.title, "Book title", false, 360);
      requireBoundedText(metadata.author, "Book author", true, 360);
      requireBoundedText(metadata.language, "Book source language", true, 63);
      if (metadata.language && !/^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$/.test(metadata.language)) {
        throw new TypeError("Book source language is invalid");
      }
    }
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
        "book.open_game",
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
    requireBoundedText(block.kind, "Book snapshot block kind", false, 80);
    if (block.content_language !== undefined) {
      requireBoundedText(block.content_language, "Book content language", false, 63);
      if (!["Heading", "Paragraph", "List"].includes(block.kind) ||
          !/^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$/.test(block.content_language)) {
        throw new TypeError("Book content language is invalid");
      }
    }
    const roleByKind = {
      Heading: "heading",
      Paragraph: "paragraph",
      List: "list",
      Position: "group",
      Diagram: "img",
      Game: "group",
      VariationTree: "group",
      Exercise: "group",
      Note: "note"
    };
    if (!Object.prototype.hasOwnProperty.call(roleByKind, block.kind) ||
        roleByKind[block.kind] !== block.role) {
      throw new TypeError("Book snapshot block kind/role is inconsistent");
    }
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
            part.length > MAX_BOOK_HEADING_PATH_TEXT ||
            part.indexOf("\x00") >= 0;
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
        block.list.items.length > MAX_BOOK_LIST_ITEMS ||
        block.list.items.some(function (item) {
          return typeof item !== "string" ||
            !item ||
            item.length > MAX_BOOK_BLOCK_VISIBLE_CHARS ||
            item.indexOf("\x00") >= 0;
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
    const openGame = snapshot.actions[9];
    const returnFromBoard = snapshot.actions[10];
    const hasBoardState = snapshot.board_active !== undefined;
    if (hasBoardState && typeof snapshot.board_active !== "boolean") {
      throw new TypeError("Book board-active state is invalid");
    }
    requireBookSemanticTree(snapshot);
    if (hasBoardState) {
      const boardActive = snapshot.board_active;
      const hasReadableSemanticTree =
        snapshot.semantic_tree !== undefined && snapshot.semantic_tree !== null;
      // The host may safely disable a matching Board handoff only when semantic
      // content failed closed and the snapshot carries the explicit warning
      // required above. A readable canonical tree must retain its matching
      // Book -> Board continuation while the Board is inactive.
      if (openPosition.enabled && (!block.has_position || boardActive)) {
        throw new TypeError("Book open-position action disagrees with board state");
      }
      if (openGame.enabled && (block.kind !== "Game" || boardActive)) {
        throw new TypeError("Book open-game action disagrees with board state");
      }
      if (!boardActive && hasReadableSemanticTree &&
          block.kind === "VariationTree" && !openPosition.enabled) {
        throw new TypeError("Readable variation lost its Board handoff");
      }
      if (!boardActive && hasReadableSemanticTree &&
          block.kind === "Game" && !openGame.enabled) {
        throw new TypeError("Readable game lost its Board handoff");
      }
      if (returnFromBoard.enabled !== boardActive) {
        throw new TypeError("Book return action disagrees with board state");
      }
    } else {
      if (openPosition.enabled !== block.has_position) {
        throw new TypeError("Book open-position action disagrees with block position state");
      }
      if (openGame.enabled !== (block.kind === "Game")) {
        throw new TypeError("Book open-game action disagrees with block game state");
      }
      if (returnFromBoard.enabled !== true) {
        throw new TypeError("Book return action must remain enabled");
      }
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
      function (field) {
        requireBoundedText(progress[field], "Training progress label", false, 120);
      }
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

  function requireTrainingSolution(solution) {
    if (solution === undefined) return [];
    if (!Array.isArray(solution) ||
        solution.length > MAX_TRAINING_SOLUTION_MOVES) {
      throw new TypeError("Training solution payload is invalid");
    }
    for (let index = 0; index < solution.length; index += 1) {
      if (!Object.prototype.hasOwnProperty.call(solution, index)) {
        throw new TypeError("Training solution payload is invalid");
      }
      const move = solution[index];
      if (typeof move !== "string" ||
          !move ||
          move.length > MAX_TRAINING_SOLUTION_TEXT ||
          move.indexOf("\x00") >= 0) {
        throw new TypeError("Training solution payload is invalid");
      }
    }
    return solution;
  }

  function trainingActionFocusTarget(command) {
    const targets = {
      "training.hint": "training-action-hint",
      "training.reveal": "training-action-reveal",
      "training.retry": "training-action-retry",
      "training.continue": "training-action-continue",
      "training.reset.request": "training-action-reset"
    };
    return Object.prototype.hasOwnProperty.call(targets, command) ? targets[command] : "";
  }

  function canonicalTrainingFocusTarget(snapshot) {
    if (!snapshot.answer.disabled) return "training-answer";
    if (snapshot.actions[3].enabled) return "training-action-continue";
    return "training-action-reset";
  }

  function requireTrainingFocusTarget(snapshot, target, solution) {
    if (typeof target !== "string") {
      throw new TypeError("Training render focus target is invalid");
    }
    const allowed = new Set([""]);
    if (!snapshot.answer.disabled) allowed.add("training-answer");
    snapshot.actions.forEach(function (action) {
      if (!action.enabled) return;
      const actionTarget = trainingActionFocusTarget(action.command);
      if (actionTarget) allowed.add(actionTarget);
    });
    if (Array.isArray(solution) && solution.length) {
      allowed.add("training-solution");
    }
    if (!allowed.has(target)) {
      throw new TypeError("Training render focus target is invalid");
    }
  }

  function appendSemanticComments(host, comments) {
    comments.forEach(function (comment) {
      host.appendChild(node("p", comment));
    });
  }

  function renderBookSemanticTree(host, tree, blockDomId) {
    const section = node("section");
    const heading = node("h4", tree.label);
    heading.id = String(blockDomId || "") + "-semantic-heading";
    section.setAttribute("aria-labelledby", heading.id);
    section.appendChild(heading);
    section.appendChild(node("p", tree.players_label + ": " + tree.players));
    (tree.details || []).forEach(function (detail) {
      section.appendChild(node("p", detail.label + ": " + detail.value));
    });
    appendSemanticComments(section, tree.intro_comments);

    const children = tree.items.map(function () { return []; });
    const roots = [];
    tree.items.forEach(function (item, index) {
      if (item.parent_index === null) roots.push(index);
      else children[item.parent_index].push(index);
    });

    function renderItem(index) {
      const item = tree.items[index];
      const entry = node("li");
      appendSemanticComments(entry, item.comments_before);
      if (item.kind === "variation") {
        const label = node("strong", item.label);
        entry.appendChild(label);
        const variationLevel = (item.depth + 1) / 2;
        entry.appendChild(
          node(
            "span",
            " — " + tree.variation_depth_label + ": " + String(variationLevel)
          )
        );
        appendSemanticComments(entry, item.leading_comments);
      } else {
        entry.appendChild(node("span", item.label));
      }
      appendSemanticComments(entry, item.comments_after);
      if (children[index].length) {
        const nested = node("ol");
        children[index].forEach(function (childIndex) {
          nested.appendChild(renderItem(childIndex));
        });
        entry.appendChild(nested);
      }
      if (item.result) {
        entry.appendChild(node("p", tree.result_label + ": " + item.result));
      }
      // Variation-line trailing comments are semantically after the line
      // termination marker. Keep that canonical order in document reading so
      // NVDA does not hear an after-result comment before the result itself.
      appendSemanticComments(entry, item.trailing_comments);
      return entry;
    }

    if (roots.length) {
      const list = node("ol");
      roots.forEach(function (index) {
        list.appendChild(renderItem(index));
      });
      section.appendChild(list);
    }
    // The game result terminates movetext. Preserve that reading position
    // before comments that canonically occur after the game terminator.
    section.appendChild(node("p", tree.result_label + ": " + tree.result));
    appendSemanticComments(section, tree.outro_comments);
    host.appendChild(section);
    return heading.id;
  }

  function renderBookBlock(host, block, semanticTree) {
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
      if (block.title) {
        const title = node("h3", block.title);
        title.id = String(block.dom_id || "") + "-title";
        content.setAttribute("aria-labelledby", title.id);
        content.appendChild(title);
      }
      if (semanticTree) {
        const semanticHeadingId = renderBookSemanticTree(
          content, semanticTree, block.dom_id
        );
        if (!block.title) content.setAttribute("aria-labelledby", semanticHeadingId);
      } else if (block.text) {
        content.appendChild(node("p", block.text));
      }
    }
    content.id = String(block.dom_id || "");
    if (block.content_language) content.setAttribute("lang", block.content_language);
    content.tabIndex = -1;

    // Heading ancestry is reading context for the focused block, so keep the
    // breadcrumb before the canonical block in document order. The block keeps
    // the same stable DOM id/focus target; only screen-reader reading order
    // changes from "content, then context" to "context, then content".
    const headingPath = Array.isArray(block.heading_path) ? block.heading_path : [];
    if (headingPath.length) {
      const nav = node("nav");
      nav.setAttribute("aria-label", block.heading_path_label || "");
      const list = node("ol");
      headingPath.forEach(function (part) { list.appendChild(node("li", part)); });
      nav.appendChild(list);
      host.appendChild(nav);
    }
    host.appendChild(content);
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
      if (payload.action !== "book.open_position" && payload.action !== "book.open_game") {
        throw new TypeError("Book delegated action is invalid");
      }
    } else if (result.kind === "error") {
      requireBoundedText(payload.message, "Book error message", false, 1000);
    }
    if (payload.announcement) announce(payload.announcement);
    if (result.kind === "error") announce(payload.message);
  }

  function bookCommandPayload(snapshot, payload) {
    const source = payload || {};
    const result = {};
    Object.keys(source).forEach(function (key) {
      if (Object.prototype.hasOwnProperty.call(source, key)) {
        result[key] = source[key];
      }
    });
    if (typeof snapshot.presentation_token === "string") {
      result.presentation_token = snapshot.presentation_token;
    }
    return result;
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
      safeInvoke(
        root,
        invoke,
        "book.open_starter_material",
        bookCommandPayload(snapshot, { material_id: materialId }),
        function (result) {
          applyBookEvent(root, result, invoke, announce, fallbackMessage);
        },
        announce,
        fallbackMessage
      );
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
    requestedFocus = requireRenderFocus(requestedFocus, "Book");
    fallbackMessage = requireFallbackMessage(fallbackMessage, "Book");
    if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) {
      throw new TypeError("Book snapshot is required");
    }
    requireBookSnapshot(snapshot);

    const fragment = document.createDocumentFragment();
    const main = node("main");
    main.setAttribute("lang", snapshot.document.lang);
    main.appendChild(node("h2", snapshot.heading || ""));
    renderStarterMaterials(root, main, snapshot, invoke, announce, fallbackMessage);
    if (snapshot.book_metadata) {
      const metadata = snapshot.book_metadata;
      const title = node("h3", metadata.title);
      title.id = "book-document-title";
      if (metadata.language) title.setAttribute("lang", metadata.language);
      main.appendChild(title);
      if (metadata.author) {
        const author = node("p", metadata.author);
        author.id = "book-document-author";
        if (metadata.language) author.setAttribute("lang", metadata.language);
        main.appendChild(author);
      }
    }
    const block = snapshot.block || {};
    renderBookBlock(main, block, snapshot.semantic_tree || null);

    const toolbar = node("div");
    toolbar.setAttribute("role", "toolbar");
    toolbar.setAttribute("aria-label", snapshot.heading);
    toolbar.setAttribute("aria-orientation", "horizontal");
    const actions = Array.isArray(snapshot.actions) ? snapshot.actions : [];
    actions.forEach(function (action) {
      const button = node("button", action.label || action.command || "");
      button.type = "button";
      button.disabled = !action.enabled;
      button.addEventListener("click", function () {
        safeInvoke(
          root,
          invoke,
          String(action.command || ""),
          bookCommandPayload(snapshot, {}),
          function (result) {
            applyBookEvent(root, result, invoke, announce, fallbackMessage);
          },
          announce,
          fallbackMessage
        );
      });
      toolbar.appendChild(button);
    });
    wireToolbarKeyboard(toolbar);
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
      safeInvoke(
        root,
        invoke,
        "book.bookmark.save",
        bookCommandPayload(snapshot, { name: input.value }),
        function (result) {
          applyBookEvent(root, result, invoke, announce, fallbackMessage);
        },
        announce,
        fallbackMessage
      );
    });
    restore.addEventListener("click", function () {
      safeInvoke(
        root,
        invoke,
        "book.bookmark.restore",
        bookCommandPayload(snapshot, { name: input.value }),
        function (result) {
          applyBookEvent(root, result, invoke, announce, fallbackMessage);
        },
        announce,
        fallbackMessage
      );
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
      // Confirm starts a real canonical reset; it is not cancellable once the
      // command is in flight. Keep the modal/focus ownership intact until the
      // host either commits a new render or reports a retryable failure.
      if (resetPending) return;
      if (dialog.open) dialog.close();
      if (opener && typeof opener.focus === "function") opener.focus({ preventScroll: true });
    }

    let resetPending = false;
    confirm.addEventListener("click", function () {
      if (resetPending) return;
      resetPending = true;
      confirm.disabled = true;
      cancel.disabled = true;
      const started = safeInvoke(
        root,
        invoke,
        "training.reset",
        { confirmed: true },
        function (result) {
          applyTrainingEvent(root, result, invoke, announce, fallbackMessage);
          if (result && result.kind === "error") {
            resetPending = false;
            confirm.disabled = false;
            cancel.disabled = false;
            if (dialog.open) confirm.focus({ preventScroll: true });
            return;
          }
          if (dialog.open) dialog.close();
        },
        announce,
        fallbackMessage,
        function () {
          resetPending = false;
          confirm.disabled = false;
          cancel.disabled = false;
          if (dialog.open) confirm.focus({ preventScroll: true });
        }
      );
      if (!started) {
        resetPending = false;
        confirm.disabled = false;
        cancel.disabled = false;
        if (dialog.open) confirm.focus({ preventScroll: true });
      }
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
        const activeFlight = inFlightRoots.get(root);
        if (activeFlight && activeFlight.epoch === renderEpoch(root)) return;
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
      if (payload.clear_answer !== undefined && typeof payload.clear_answer !== "boolean") {
        throw new TypeError("Training clear-answer flag is invalid");
      }
      const safeSolution = requireTrainingSolution(payload.solution);
      requireTrainingFocusTarget(
        payload.snapshot,
        payload.focus_target,
        safeSolution
      );
      renderTrainingSurface(
        root,
        payload.snapshot,
        invoke,
        announce,
        payload.focus_target,
        fallbackMessage,
        safeSolution
      );
      if (!payload.clear_answer && priorAnswer) {
        const next = root.querySelector("#training-answer");
        if (next) next.value = priorAnswer;
      }
    } else {
      requireBoundedText(payload.message, "Training error message", false, 1200);
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
    requestedFocus = requireRenderFocus(requestedFocus, "Training");
    fallbackMessage = requireFallbackMessage(fallbackMessage, "Training");
    solution = requireTrainingSolutionArgument(solution);
    if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) {
      throw new TypeError("Training snapshot is required");
    }
    requireTrainingSnapshot(snapshot);
    solution = requireTrainingSolution(solution);
    const answerSpec = snapshot.answer || {};
    let effectiveFocus = requestedFocus || "";
    if (effectiveFocus === "training-answer" && answerSpec.disabled) {
      effectiveFocus = canonicalTrainingFocusTarget(snapshot);
    }
    requireTrainingFocusTarget(snapshot, effectiveFocus, solution);

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
    toolbar.setAttribute("aria-label", snapshot.heading);
    toolbar.setAttribute("aria-orientation", "horizontal");
    const actions = Array.isArray(snapshot.actions) ? snapshot.actions : [];
    actions.forEach(function (action) {
      const button = node("button", action.label || action.command || "");
      button.type = "button";
      button.id = trainingActionFocusTarget(action.command);
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
    wireToolbarKeyboard(toolbar);
    main.appendChild(toolbar);
    main.appendChild(resetDialog.dialog);

    fragment.appendChild(main);
    root.replaceChildren(fragment);
    markRendered(root);
    focusTarget(root, effectiveFocus);
  }

  global.AccessibleChessBookSurface = Object.freeze({ render: renderBookSurface });
  global.AccessibleChessTrainingSurface = Object.freeze({ render: renderTrainingSurface });
})(window);
