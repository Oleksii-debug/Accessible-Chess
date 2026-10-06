(function (global) {
  "use strict";

  const renderTokens = new WeakMap();
  const importTokens = new WeakMap();
  const commandFlights = new WeakMap();
  const commandTails = new WeakMap();
  const listboxKeyFlights = new WeakMap();
  const activeLibrarySurfaces = new WeakMap();
  const librarySurfaceEpochs = new WeakMap();
  const commandRenderRoots = new WeakMap();

  function requireFunction(value, name) {
    if (typeof value !== "function") throw new TypeError(name + " must be a function");
    return value;
  }

  const IMPORT_PHASES = new Set([
    "idle",
    "running",
    "cancelling",
    "completed",
    "cancelled",
    "error",
    "empty"
  ]);
  const IMPORT_ACTIONS = [
    ["library.import", "library-import-file"],
    ["library.cancel_import", "library-import-cancel"]
  ];

  function plainObject(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return false;
    const prototype = Object.getPrototypeOf(value);
    return prototype === Object.prototype || prototype === null;
  }

  function requireBoundedText(value, name, allowEmpty, limit) {
    if (typeof value !== "string" ||
        (!allowEmpty && !value) ||
        value.length > limit ||
        value.indexOf("\x00") >= 0) {
      throw new TypeError(name + " is invalid");
    }
    return value;
  }

  function requireExactFields(value, expected, name) {
    if (!plainObject(value)) throw new TypeError(name + " must be an object");
    const fields = Object.keys(value);
    if (fields.length !== expected.length ||
        expected.some(function (field) {
          return !Object.prototype.hasOwnProperty.call(value, field);
        })) {
      throw new TypeError(name + " fields are invalid");
    }
  }

  function requireImportSnapshot(state) {
    requireExactFields(
      state,
      [
        "phase",
        "heading",
        "description",
        "processed_games",
        "total_games",
        "progress_label",
        "message",
        "actions"
      ],
      "Library import snapshot"
    );
    if (!IMPORT_PHASES.has(state.phase)) {
      throw new TypeError("Library import phase is invalid");
    }
    requireBoundedText(state.heading, "Library import heading", false, 240);
    requireBoundedText(state.description, "Library import description", true, 500);
    requireBoundedText(state.progress_label, "Library import progress label", true, 500);
    requireBoundedText(state.message, "Library import message", true, 500);
    if (!Number.isSafeInteger(state.processed_games) ||
        !Number.isSafeInteger(state.total_games) ||
        state.processed_games < 0 ||
        state.total_games < 0 ||
        state.processed_games > state.total_games) {
      throw new TypeError("Library import counts are invalid");
    }
    if (!Array.isArray(state.actions) || state.actions.length !== IMPORT_ACTIONS.length) {
      throw new TypeError("Library import actions are invalid");
    }
    for (let index = 0; index < state.actions.length; index += 1) {
      if (!Object.prototype.hasOwnProperty.call(state.actions, index)) {
        throw new TypeError("Library import actions must be dense");
      }
      const action = state.actions[index];
      requireExactFields(
        action,
        ["action", "dom_id", "label", "enabled"],
        "Library import action"
      );
      const expected = IMPORT_ACTIONS[index];
      if (action.action !== expected[0] || action.dom_id !== expected[1]) {
        throw new TypeError("Library import action identity is invalid");
      }
      requireBoundedText(action.label, "Library import action label", false, 240);
      if (typeof action.enabled !== "boolean") {
        throw new TypeError("Library import action enabled state is invalid");
      }
    }
    return state;
  }

  function requireImportEvent(result) {
    requireExactFields(result, ["kind", "payload"], "Library event");
    if (result.kind !== "render-import") {
      throw new TypeError("Library import event kind is invalid");
    }
    const payload = result.payload;
    requireExactFields(
      payload,
      ["import", "focus_target", "announcement"],
      "Library import event payload"
    );
    requireImportSnapshot(payload.import);
    if (payload.focus_target !== "" &&
        payload.focus_target !== "library-import-file" &&
        payload.focus_target !== "library-import-cancel") {
      throw new TypeError("Library import focus target is invalid");
    }
    requireBoundedText(
      payload.announcement,
      "Library import announcement",
      true,
      500
    );
    return payload;
  }

  const LIBRARY_STATUS = new Set(["ready", "loading", "empty", "error"]);
  const LIBRARY_FILTERS = [
    ["player", "text"],
    ["event", "text"],
    ["eco", "text"],
    ["opening", "text"],
    ["result", "select"],
    ["source_id", "number"],
    ["source_name", "text"],
    ["limit", "select"],
    ["date_from", "text"],
    ["date_to", "text"]
  ];
  const LIBRARY_ACTIONS = [
    "library.previous_page",
    "library.next_page",
    "library.open_game",
    "library.reset_filters"
  ];
  const LIBRARY_EXPORT_ACTIONS = [
    "library.export_selected",
    "library.export_filtered",
    "library.clear_export_selection"
  ];
  const LIBRARY_ACTION_DOM_IDS = new Map([
    ["library.previous_page", "library-previous-page"],
    ["library.next_page", "library-next-page"],
    ["library.open_game", "library-open-game"],
    ["library.reset_filters", "library-reset-filters"],
    ["library.export_selected", "library-export-selected"],
    ["library.export_filtered", "library-export-filtered"],
    ["library.clear_export_selection", "library-clear-export-selection"]
  ]);
  const GAME_DOM_PATTERN = /^library-game-[0-9a-f]{20}$/;

  function requireSafePositiveInteger(value, name) {
    if (!Number.isSafeInteger(value) || value <= 0) {
      throw new TypeError(name + " is invalid");
    }
    return value;
  }

  function requireFilterOption(option) {
    requireExactFields(option, ["value", "label"], "Library filter option");
    requireBoundedText(option.value, "Library filter option value", true, 256);
    requireBoundedText(option.label, "Library filter option label", true, 240);
  }

  function requireLibraryFilter(filter, index) {
    const expected = LIBRARY_FILTERS[index];
    const fields = expected[1] === "select"
      ? ["id", "kind", "label", "value", "options"]
      : expected[1] === "number"
        ? ["id", "kind", "label", "value", "minimum"]
        : ["id", "kind", "label", "value"];
    requireExactFields(filter, fields, "Library filter");
    if (filter.id !== expected[0] || filter.kind !== expected[1]) {
      throw new TypeError("Library filter identity is invalid");
    }
    requireBoundedText(filter.label, "Library filter label", false, 240);
    requireBoundedText(filter.value, "Library filter value", true, 256);
    if (filter.kind === "number") {
      if (filter.minimum !== 1 ||
          (filter.value !== "" &&
           (!/^[0-9]{1,19}$/.test(filter.value) || Number(filter.value) <= 0))) {
        throw new TypeError("Library numeric filter is invalid");
      }
    }
    if (filter.kind === "select") {
      const expectedCount = filter.id === "result" ? 5 : 4;
      if (!Array.isArray(filter.options) || filter.options.length !== expectedCount) {
        throw new TypeError("Library select options are invalid");
      }
      filter.options.forEach(requireFilterOption);
      if (filter.id === "result") {
        const values = ["", "1-0", "0-1", "1/2-1/2", "*"];
        if (filter.options.some(function (option, optionIndex) {
          return option.value !== values[optionIndex];
        }) || values.indexOf(filter.value) < 0) {
          throw new TypeError("Library result filter is invalid");
        }
      } else {
        const values = ["25", "50", "100", "200"];
        if (filter.options.some(function (option, optionIndex) {
          return option.value !== values[optionIndex];
        }) || values.indexOf(filter.value) < 0) {
          throw new TypeError("Library limit filter is invalid");
        }
      }
    }
  }

  function requireLibraryRow(row, index, exportMode) {
    const fields = exportMode
      ? [
          "dom_id",
          "game_id",
          "position",
          "selected",
          "label",
          "source_label",
          "result",
          "export_selected",
          "export_dom_id",
          "export_label"
        ]
      : [
          "dom_id",
          "game_id",
          "position",
          "selected",
          "label",
          "source_label",
          "result"
        ];
    requireExactFields(row, fields, "Library row");
    requireSafePositiveInteger(row.game_id, "Library game id");
    if (row.position !== index + 1 || typeof row.selected !== "boolean") {
      throw new TypeError("Library row position/selection is invalid");
    }
    if (typeof row.dom_id !== "string" || !GAME_DOM_PATTERN.test(row.dom_id)) {
      throw new TypeError("Library row DOM id is invalid");
    }
    requireBoundedText(row.label, "Library row label", true, 520);
    requireBoundedText(row.source_label, "Library row source label", true, 160);
    requireBoundedText(row.result, "Library row result", true, 32);
    if (exportMode) {
      if (typeof row.export_selected !== "boolean" ||
          row.export_dom_id !== row.dom_id + "-export") {
        throw new TypeError("Library export row identity is invalid");
      }
      requireBoundedText(row.export_label, "Library export row label", false, 760);
    }
  }

  function requireLibraryAction(action, expectedAction) {
    requireExactFields(
      action,
      ["action", "label", "enabled"],
      "Library action"
    );
    if (action.action !== expectedAction || typeof action.enabled !== "boolean") {
      throw new TypeError("Library action identity/state is invalid");
    }
    requireBoundedText(action.label, "Library action label", false, 240);
  }

  function requireLibraryFocusTarget(snapshot, target, allowEmpty) {
    if (typeof target !== "string" || target.length > 96 || target.indexOf("\x00") >= 0) {
      throw new TypeError("Library focus target is invalid");
    }
    if (!target && allowEmpty) return target;
    const allowed = new Set(["library-search-player", "library-import-file", "library-import-cancel"]);
    snapshot.filters.forEach(function (filter) {
      allowed.add("library-search-" + filter.id);
    });
    snapshot.rows.forEach(function (row) {
      allowed.add(row.dom_id);
      if (row.export_dom_id) allowed.add(row.export_dom_id);
    });
    snapshot.actions.forEach(function (action) {
      const domId = LIBRARY_ACTION_DOM_IDS.get(action.action);
      if (domId) allowed.add(domId);
    });
    if (!allowed.has(target)) throw new TypeError("Library focus target is invalid");
    return target;
  }

  function requireLibrarySnapshot(snapshot) {
    if (!plainObject(snapshot)) throw new TypeError("Library snapshot is required");
    const exportMode =
      Object.prototype.hasOwnProperty.call(snapshot, "export_selection_heading") ||
      Object.prototype.hasOwnProperty.call(snapshot, "export_selection_count");
    const fields = [
      "document",
      "status",
      "heading",
      "description",
      "filters_heading",
      "results_heading",
      "search_label",
      "transport_error_message",
      "import",
      "filters",
      "rows",
      "selected_game_id",
      "focus_target",
      "message",
      "summary",
      "actions"
    ];
    if (exportMode) {
      fields.push("export_selection_heading", "export_selection_count");
    }
    requireExactFields(snapshot, fields, "Library snapshot");

    requireExactFields(snapshot.document, ["lang", "landmark"], "Library document");
    if ((snapshot.document.lang !== "uk" && snapshot.document.lang !== "en") ||
        snapshot.document.landmark !== "main") {
      throw new TypeError("Library document metadata is invalid");
    }
    if (!LIBRARY_STATUS.has(snapshot.status)) {
      throw new TypeError("Library status is invalid");
    }
    [
      ["heading", false, 240],
      ["description", true, 500],
      ["filters_heading", false, 240],
      ["results_heading", false, 240],
      ["search_label", false, 240],
      ["transport_error_message", false, 500],
      ["message", true, 500],
      ["summary", true, 500]
    ].forEach(function (spec) {
      requireBoundedText(snapshot[spec[0]], "Library " + spec[0], spec[1], spec[2]);
    });
    requireImportSnapshot(snapshot.import);

    // Accept the established eight-field snapshot as well as its date-filter
    // successor; both retain exact ordered field validation.
    if (!Array.isArray(snapshot.filters) ||
        (snapshot.filters.length !== 8 && snapshot.filters.length !== LIBRARY_FILTERS.length)) {
      throw new TypeError("Library filters are invalid");
    }
    snapshot.filters.forEach(requireLibraryFilter);

    if (!Array.isArray(snapshot.rows) || snapshot.rows.length > 200) {
      throw new TypeError("Library rows are invalid");
    }
    let selectedRow = null;
    snapshot.rows.forEach(function (row, index) {
      requireLibraryRow(row, index, exportMode);
      if (row.selected) {
        if (selectedRow !== null) throw new TypeError("Library selection is ambiguous");
        selectedRow = row;
      }
    });
    if (snapshot.selected_game_id === null) {
      if (selectedRow !== null) throw new TypeError("Library selection is inconsistent");
    } else {
      requireSafePositiveInteger(snapshot.selected_game_id, "Library selected game id");
      if (selectedRow === null || selectedRow.game_id !== snapshot.selected_game_id) {
        throw new TypeError("Library selection is inconsistent");
      }
    }

    const expectedActions = exportMode
      ? LIBRARY_ACTIONS.concat(LIBRARY_EXPORT_ACTIONS)
      : LIBRARY_ACTIONS;
    if (!Array.isArray(snapshot.actions) || snapshot.actions.length !== expectedActions.length) {
      throw new TypeError("Library actions are invalid");
    }
    snapshot.actions.forEach(function (action, index) {
      requireLibraryAction(action, expectedActions[index]);
    });

    if (exportMode) {
      requireBoundedText(
        snapshot.export_selection_heading,
        "Library export selection heading",
        false,
        240
      );
      if (!Number.isSafeInteger(snapshot.export_selection_count) ||
          snapshot.export_selection_count < 0 ||
          snapshot.export_selection_count > 5000) {
        throw new TypeError("Library export selection count is invalid");
      }
    }

    requireLibraryFocusTarget(snapshot, snapshot.focus_target, false);
    if (selectedRow === null && snapshot.focus_target !== "library-search-player") {
      throw new TypeError("Library focus/selection is inconsistent");
    }
    if (selectedRow !== null && snapshot.focus_target !== selectedRow.dom_id) {
      throw new TypeError("Library focus/selection is inconsistent");
    }
    return snapshot;
  }

  function requireLibraryRenderEvent(result) {
    requireExactFields(result, ["kind", "payload"], "Library event");
    if (result.kind !== "render") throw new TypeError("Library render event kind is invalid");
    requireExactFields(
      result.payload,
      ["snapshot", "focus_target", "announcement"],
      "Library render payload"
    );
    const snapshot = requireLibrarySnapshot(result.payload.snapshot);
    requireLibraryFocusTarget(snapshot, result.payload.focus_target, false);
    requireBoundedText(
      result.payload.announcement,
      "Library render announcement",
      true,
      500
    );
    return result.payload;
  }

  function requireLibraryDelegatedEvent(result) {
    requireExactFields(result, ["kind", "payload"], "Library event");
    if (result.kind !== "delegated") {
      throw new TypeError("Library delegated event kind is invalid");
    }
    const payload = result.payload;
    if (plainObject(payload) && payload.action === "library.export") {
      requireExactFields(payload, ["action", "scope"], "Library delegated payload");
      if (payload.scope !== "selected" && payload.scope !== "filtered") {
        throw new TypeError("Library export delegated scope is invalid");
      }
      return payload;
    }
    requireExactFields(payload, ["action"], "Library delegated payload");
    if (payload.action !== "library.import" && payload.action !== "library.open_game") {
      throw new TypeError("Library delegated action is invalid");
    }
    return payload;
  }

  function requireLibraryErrorEvent(result) {
    requireExactFields(result, ["kind", "payload"], "Library event");
    if (result.kind !== "error") throw new TypeError("Library error event kind is invalid");
    requireExactFields(result.payload, ["message"], "Library error payload");
    requireBoundedText(result.payload.message, "Library error message", true, 500);
    return result.payload;
  }

  function node(tag, text) {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function focusRequestedOption(root, focusTarget) {
    if (!focusTarget) return false;
    const importTarget = focusTarget === "library-import-file" ||
      focusTarget === "library-import-cancel";
    const actionTarget = Array.from(LIBRARY_ACTION_DOM_IDS.values()).indexOf(focusTarget) >= 0;
    if (LIBRARY_FILTERS.some(function (filter) { return focusTarget === "library-search-" + filter[0]; }) ||
        importTarget ||
        actionTarget ||
        (focusTarget.indexOf("library-game-") === 0 && focusTarget.endsWith("-export"))) {
      const control = root.querySelector("#" + focusTarget);
      if (control && !control.disabled && typeof control.focus === "function") {
        control.focus({ preventScroll: true });
        return true;
      }
      // Import/export operation and toolbar state can replace or disable the
      // previously focused control. A real browser rejects focus on disabled
      // controls, so keep keyboard/NVDA focus on the stable Library search field.
      if (importTarget || actionTarget) {
        const search = root.querySelector("#library-search-player");
        if (search && !search.disabled && typeof search.focus === "function") {
          search.focus({ preventScroll: true });
          return true;
        }
      }
      return false;
    }
    const options = root.querySelectorAll('[role="option"]');
    for (let index = 0; index < options.length; index += 1) {
      if (options[index].id === focusTarget && typeof options[index].focus === "function") {
        options[index].focus({ preventScroll: true });
        return true;
      }
    }
    return false;
  }

  function reconcileOperationActions(snapshot, importSnapshot) {
    const busy = importSnapshot.actions[0].enabled === false;
    const count = Number(snapshot.export_selection_count) || 0;
    const hasRows = Array.isArray(snapshot.rows) && snapshot.rows.length > 0;
    const actions = (Array.isArray(snapshot.actions) ? snapshot.actions : []).map(function (action) {
      if (!action || typeof action.action !== "string") return action;
      let enabled = action.enabled;
      if (action.action === "library.export_selected" ||
          action.action === "library.clear_export_selection") {
        enabled = count > 0 && !busy;
      } else if (action.action === "library.export_filtered") {
        enabled = hasRows && !busy;
      }
      return enabled === action.enabled
        ? action
        : Object.assign({}, action, { enabled: enabled });
    });
    return Object.assign({}, snapshot, {
      import: importSnapshot,
      actions: actions
    });
  }

  function syncOperationActionButtons(root, snapshot) {
    if (!root || typeof root.querySelectorAll !== "function") return;
    const enabledByAction = {};
    (Array.isArray(snapshot.actions) ? snapshot.actions : []).forEach(function (action) {
      if (action && typeof action.action === "string" &&
          LIBRARY_EXPORT_ACTIONS.indexOf(action.action) >= 0) {
        enabledByAction[action.action] = action.enabled === true;
      }
    });
    const buttons = root.querySelectorAll('button[data-action]');
    for (let index = 0; index < buttons.length; index += 1) {
      const button = buttons[index];
      const actionId = button && button.dataset ? button.dataset.action : "";
      if (Object.prototype.hasOwnProperty.call(enabledByAction, actionId)) {
        button.disabled = !enabledByAction[actionId];
      }
    }
  }

  function applyEvent(root, result, invoke, announce) {
    if (result == null) return;
    if (!plainObject(result)) throw new TypeError("Library event must be an object");
    if (result.kind === "render") {
      const renderPayload = requireLibraryRenderEvent(result);
      renderLibrarySurface(
        root,
        renderPayload.snapshot,
        invoke,
        announce,
        renderPayload.focus_target
      );
      if (renderPayload.announcement) announce(renderPayload.announcement);
      return;
    }
    if (result.kind === "render-import") {
      const importPayload = requireImportEvent(result);
      const current = root.__accessibleChessLibrarySnapshot;
      if (current && typeof current === "object") {
        const updated = reconcileOperationActions(current, importPayload.import);
        const region = root.querySelector("#library-import-region");
        const active = document.activeElement;
        const restore = region && active && region.contains(active) &&
          typeof active.id === "string" ? active.id : "";
        const replacement = buildImportSection(root, updated, invoke, announce);
        if (region && replacement && typeof region.replaceWith === "function") {
          region.replaceWith(replacement);
          root.__accessibleChessLibrarySnapshot = updated;
          syncOperationActionButtons(root, updated);
          importTokens.set(root, {});
          focusRequestedOption(root, importPayload.focus_target || restore);
        } else {
          renderLibrarySurface(
            root,
            updated,
            invoke,
            announce,
            importPayload.focus_target || ""
          );
        }
      }
      if (importPayload.announcement) announce(importPayload.announcement);
      return;
    }
    if (result.kind === "delegated") {
      const delegated = requireLibraryDelegatedEvent(result);
      if (delegated.action === "library.open_game") {
        // A successful Open Game has already committed the PGN route through
        // the outer publication protocol. Retire this Library surface before
        // any command queued from its old DOM can enter the canonical host.
        activeLibrarySurfaces.set(root, false);
      }
      return;
    }
    if (result.kind === "error") {
      const errorPayload = requireLibraryErrorEvent(result);
      if (errorPayload.message) announce(errorPayload.message);
      return;
    }
    throw new TypeError("Library event kind is invalid");
  }

  function invokeCommand(root, invoke, announce, snapshot, command, payload) {
    const generic = snapshot && typeof snapshot.transport_error_message === "string"
      ? snapshot.transport_error_message
      : "";
    const queuedEpoch = librarySurfaceEpochs.get(root);
    const queuedImportToken = importTokens.get(root);
    const importRegionCommand =
      command === "library.import" || command === "library.cancel_import";
    const priorTail = commandTails.get(root);
    const gate = priorTail && typeof priorTail.then === "function"
      ? priorTail
      : Promise.resolve();

    const current = gate.then(function () {
      // Serialize canonical Library mutations. A second key/search/export/import
      // command must not enter the host until the prior command and its returned
      // presentation have settled. Route deactivation/re-entry changes the
      // surface epoch; partial Import/Cancel replacement changes its own token.
      // Intent queued by either detached presentation is discarded before invoke.
      if (activeLibrarySurfaces.get(root) !== true ||
          librarySurfaceEpochs.get(root) !== queuedEpoch ||
          (importRegionCommand && importTokens.get(root) !== queuedImportToken)) {
        return null;
      }

      const flight = {
        renderToken: renderTokens.get(root), importToken: importTokens.get(root)
      };
      commandFlights.set(root, flight);
      function isCurrent() {
        return commandFlights.get(root) === flight &&
          renderTokens.get(root) === flight.renderToken &&
          activeLibrarySurfaces.get(root) === true &&
          librarySurfaceEpochs.get(root) === queuedEpoch;
      }

      return Promise.resolve().then(function () {
        if (!isCurrent()) return null;
        return invoke(command, payload || {});
      }).then(function (result) {
        if (!isCurrent()) return null;
        if (importTokens.get(root) !== flight.importToken && plainObject(result)) {
          if (result.kind === "render-import") {
            requireImportEvent(result);
            return null;
          }
          if (result.kind === "render") {
            const payload = requireLibraryRenderEvent(result);
            // Background import feedback is an independent host authority. Keep
            // newer validated progress while still applying this current search.
            result = { kind: "render", payload: Object.assign({}, payload, {
              snapshot: Object.assign({}, payload.snapshot, {
                import: root.__accessibleChessLibrarySnapshot.import
              })
            }) };
          }
        }
        commandRenderRoots.set(root, true);
        try {
          applyEvent(root, result, invoke, announce);
        } finally {
          commandRenderRoots.delete(root);
        }
        return result;
      }).catch(function () {
        if (isCurrent() && generic) announce(generic);
        return null;
      }).then(function (result) {
        if (commandFlights.get(root) === flight) commandFlights.delete(root);
        return result;
      });
    });

    const settled = current.then(
      function () { return null; },
      function () { return null; }
    );
    commandTails.set(root, settled);
    settled.then(function () {
      if (commandTails.get(root) === settled) commandTails.delete(root);
    });
    return current;
  }

  function invokeListboxKeyCommand(root, invoke, announce, snapshot, command, payload) {
    // A selected option remains alive until its canonical command settles.
    // Ignore repeated/mixed Arrow/Enter events from that stale DOM node instead
    // of queueing intent whose local selection belonged to the prior render.
    if (listboxKeyFlights.get(root)) return null;
    const current = invokeCommand(root, invoke, announce, snapshot, command, payload);
    listboxKeyFlights.set(root, current);
    const release = function (value) {
      if (listboxKeyFlights.get(root) === current) listboxKeyFlights.delete(root);
      return value;
    };
    return current.then(release, function (error) {
      if (listboxKeyFlights.get(root) === current) listboxKeyFlights.delete(root);
      throw error;
    });
  }

  function appendOptions(select, options, selectedValue) {
    (Array.isArray(options) ? options : []).forEach(function (entry) {
      const option = node("option", entry.label || entry.value || "");
      option.value = String(entry.value || "");
      option.selected = option.value === String(selectedValue || "");
      select.appendChild(option);
    });
  }

  function buildFilterControl(filter) {
    const wrapper = node("div");
    const id = "library-search-" + String(filter.id || "field");
    const label = node("label", filter.label || "");
    label.htmlFor = id;
    let control;
    if (filter.kind === "select") {
      control = node("select");
      appendOptions(control, filter.options, filter.value);
    } else {
      control = node("input");
      control.type = filter.kind === "number" ? "number" : "text";
      control.value = filter.value == null ? "" : String(filter.value);
      if (filter.minimum !== undefined) control.min = String(filter.minimum);
      if (filter.kind !== "number") control.maxLength = 256;
    }
    control.id = id;
    control.name = String(filter.id || "");
    wrapper.appendChild(label);
    wrapper.appendChild(control);
    return { wrapper: wrapper, control: control };
  }

  function renderFilters(root, host, snapshot, invoke, announce) {
    const form = node("form");
    form.setAttribute("aria-label", snapshot.filters_heading || "");
    form.appendChild(node("h3", snapshot.filters_heading || ""));
    const controls = [];
    (Array.isArray(snapshot.filters) ? snapshot.filters : []).forEach(function (filter) {
      const built = buildFilterControl(filter || {});
      controls.push(built.control);
      form.appendChild(built.wrapper);
    });
    const submit = node("button", snapshot.search_label || "");
    submit.type = "submit";
    form.appendChild(submit);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      const payload = {};
      controls.forEach(function (control) {
        payload[control.name] = control.value;
      });
      invokeCommand(root, invoke, announce, snapshot, "library.search", payload);
    });
    host.appendChild(form);
  }

  function buildImportSection(root, snapshot, invoke, announce) {
    const state = snapshot.import == null ? null : requireImportSnapshot(snapshot.import);
    if (!state) return null;
    const section = node("section");
    section.id = "library-import-region";
    section.appendChild(node("h3", state.heading || ""));
    section.appendChild(node("p", state.description || ""));
    if (Number(state.total_games) > 0) {
      const progress = node("progress");
      progress.max = Number(state.total_games);
      progress.value = Math.min(Number(state.processed_games) || 0, progress.max);
      progress.setAttribute("aria-label", state.progress_label || "");
      section.appendChild(progress);
    }
    const status = node("p", state.progress_label || "");
    status.setAttribute("aria-live", "off");
    section.appendChild(status);
    (Array.isArray(state.actions) ? state.actions : []).forEach(function (action) {
      const button = node("button", action.label || action.action || "");
      button.type = "button";
      button.id = String(action.dom_id || "");
      button.disabled = !action.enabled;
      button.addEventListener("click", function () {
        invokeCommand(root, invoke, announce, snapshot, String(action.action || ""), {});
      });
      section.appendChild(button);
    });
    return section;
  }

  function renderImport(root, host, snapshot, invoke, announce) {
    const section = buildImportSection(root, snapshot, invoke, announce);
    if (section) host.appendChild(section);
  }

  function renderResults(root, host, snapshot, invoke, announce) {
    const section = node("section");
    section.appendChild(node("h3", snapshot.results_heading || ""));
    const summary = node("p", snapshot.summary || "");
    summary.setAttribute("aria-live", "off");
    section.appendChild(summary);

    const rows = Array.isArray(snapshot.rows) ? snapshot.rows : [];
    const list = node("ul");
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", snapshot.results_heading || "");
    rows.forEach(function (row, index) {
      const option = node("li");
      option.id = String(row.dom_id || "");
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", row.selected ? "true" : "false");
      option.tabIndex = row.selected ? 0 : -1;
      const label = node("span", row.label || "");
      option.appendChild(label);
      if (row.source_label) {
        const source = node("span", " — " + String(row.source_label));
        source.className = "library-source";
        option.appendChild(source);
      }
      option.addEventListener("click", function () {
        invokeCommand(root, invoke, announce, snapshot, "library.select", { game_id: row.game_id });
      });
      option.addEventListener("keydown", function (event) {
        const resolve = global.accessibleChessKeymapAction;
        let actionId = "";
        let resolverReady = false;
        if (typeof resolve === "function") {
          const resolved = resolve(event, "library_results");
          if (resolved !== null && resolved !== undefined) {
            resolverReady = true;
            actionId = typeof resolved === "string" ? resolved : "";
          }
        }
        if (
          !resolverReady &&
          !event.altKey && !event.ctrlKey && !event.shiftKey && !event.metaKey
        ) {
          if (event.key === "ArrowUp") actionId = "library.previous_result";
          else if (event.key === "ArrowDown") actionId = "library.next_result";
          else if (event.key === "Home") actionId = "library.first_result";
          else if (event.key === "End") actionId = "library.last_result";
          else if (event.key === "Enter") actionId = "library.open_game";
        }

        let command = "";
        let payload = {};
        let handled = true;
        if (actionId === "library.previous_result") {
          if (index > 0) {
            command = "library.move";
            payload = { delta: -1 };
          }
        } else if (actionId === "library.next_result") {
          if (index + 1 < rows.length) {
            command = "library.move";
            payload = { delta: 1 };
          }
        } else if (actionId === "library.first_result") {
          if (index > 0 && rows.length) {
            command = "library.select";
            payload = { game_id: rows[0].game_id };
          }
        } else if (actionId === "library.last_result") {
          if (index + 1 < rows.length) {
            command = "library.select";
            payload = { game_id: rows[rows.length - 1].game_id };
          }
        } else if (actionId === "library.open_game") {
          command = "library.open_game";
        } else {
          handled = false;
        }
        if (!handled) return;
        event.preventDefault();
        if (typeof event.stopPropagation === "function") event.stopPropagation();
        if (!command) return;
        invokeListboxKeyCommand(root, invoke, announce, snapshot, command, payload);
      });
      list.appendChild(option);
    });
    section.appendChild(list);
    host.appendChild(section);
  }

  function renderExportSelection(root, host, snapshot, invoke, announce) {
    const rows = Array.isArray(snapshot.rows) ? snapshot.rows : [];
    if (!snapshot.export_selection_heading || !rows.length) return;
    const fieldset = node("fieldset");
    fieldset.id = "library-export-selection";
    fieldset.appendChild(node("legend", snapshot.export_selection_heading));
    rows.forEach(function (row) {
      if (!row.export_dom_id || !row.export_label) return;
      const wrapper = node("div");
      const checkbox = node("input");
      checkbox.type = "checkbox";
      checkbox.id = String(row.export_dom_id);
      checkbox.checked = !!row.export_selected;
      const label = node("label", row.export_label);
      label.htmlFor = checkbox.id;
      checkbox.addEventListener("change", function () {
        invokeCommand(root, invoke, announce, snapshot, "library.toggle_export_selection", {
          game_id: row.game_id
        });
      });
      wrapper.appendChild(checkbox);
      wrapper.appendChild(label);
      fieldset.appendChild(wrapper);
    });
    host.appendChild(fieldset);
  }

  function renderActions(root, host, snapshot, invoke, announce) {
    const toolbar = node("div");
    toolbar.setAttribute("role", "toolbar");
    (Array.isArray(snapshot.actions) ? snapshot.actions : []).forEach(function (action) {
      const button = node("button", action.label || action.action || "");
      button.type = "button";
      button.id = LIBRARY_ACTION_DOM_IDS.get(action.action) || "";
      button.disabled = !action.enabled;
      button.dataset.action = String(action.action || "");
      button.addEventListener("click", function () {
        invokeCommand(root, invoke, announce, snapshot, String(action.action || ""), {});
      });
      toolbar.appendChild(button);
    });
    host.appendChild(toolbar);
  }

  function renderLibrarySurface(root, snapshot, invoke, announce, requestedFocus) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new TypeError("Library root must support replaceChildren");
    }
    requireFunction(invoke, "Library invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "Library announce");
    snapshot = requireLibrarySnapshot(snapshot);
    requireLibraryFocusTarget(snapshot, requestedFocus || snapshot.focus_target, true);

    const fragment = document.createDocumentFragment();
    const main = node("section");
    main.appendChild(node("h2", snapshot.heading || ""));
    main.appendChild(node("p", snapshot.description || ""));
    // Existing games are the primary surface; search/import are additional actions.
    renderResults(root, main, snapshot, invoke, announce);
    renderImport(root, main, snapshot, invoke, announce);
    renderFilters(root, main, snapshot, invoke, announce);
    renderExportSelection(root, main, snapshot, invoke, announce);
    renderActions(root, main, snapshot, invoke, announce);
    if (snapshot.message) {
      const message = node("p", snapshot.message);
      message.setAttribute("aria-live", "off");
      main.appendChild(message);
    }
    fragment.appendChild(main);
    root.replaceChildren(fragment);
    renderTokens.set(root, {});
    importTokens.set(root, {});
    commandFlights.delete(root);
    activeLibrarySurfaces.set(root, true);
    // A render returned by the currently serialized Library command is the
    // authoritative settlement that queued user intent is waiting for, so keep
    // that queue's epoch. Any independent/native/full refresh replaces the DOM
    // outside that command transaction and must invalidate intent already queued
    // from the now-detached presentation.
    if (!commandRenderRoots.get(root) || !librarySurfaceEpochs.has(root)) {
      librarySurfaceEpochs.set(root, {});
      // This snapshot did not come from the serialized command currently at the
      // head of the queue. Treat it as a new presentation incarnation: old
      // transport completions remain fenced by their captured epoch, while
      // controls in this freshly rendered DOM must not wait behind them.
      commandTails.delete(root);
      listboxKeyFlights.delete(root);
    }
    root.__accessibleChessLibrarySnapshot = snapshot;
    focusRequestedOption(root, requestedFocus || "");
  }

  function deactivateLibrarySurface(root) {
    if (!root || typeof root !== "object") return;
    activeLibrarySurfaces.set(root, false);
    librarySurfaceEpochs.set(root, {});
    // Any unresolved result belongs to DOM that is no longer authoritative.
    renderTokens.set(root, {});
    importTokens.set(root, {});
    commandFlights.delete(root);
    // Detach unresolved work from any future Library incarnation. Its own
    // completion still observes the old epoch and cannot publish; identity
    // checks in the settled callbacks prevent it from deleting newer queues.
    commandTails.delete(root);
    listboxKeyFlights.delete(root);
  }

  function applyLibraryEvent(root, result, invoke, announce) {
    if (!root || typeof root.querySelector !== "function") {
      throw new TypeError("Library root must support queries");
    }
    requireFunction(invoke, "Library invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "Library announce");
    applyEvent(root, result, invoke, announce);
  }

  global.AccessibleChessLibrarySurface = Object.freeze({
    render: renderLibrarySurface,
    apply: applyLibraryEvent,
    deactivate: deactivateLibrarySurface
  });
})(window);
