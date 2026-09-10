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

  function focusRequestedOption(root, focusTarget) {
    if (!focusTarget) return;
    if (focusTarget === "library-search-player" ||
        focusTarget === "library-import-file" ||
        focusTarget === "library-import-cancel" ||
        (focusTarget.indexOf("library-game-") === 0 && focusTarget.endsWith("-export"))) {
      const control = root.querySelector("#" + focusTarget);
      if (control && typeof control.focus === "function") control.focus({ preventScroll: true });
      return;
    }
    const options = root.querySelectorAll('[role="option"]');
    for (let index = 0; index < options.length; index += 1) {
      if (options[index].id === focusTarget && typeof options[index].focus === "function") {
        options[index].focus({ preventScroll: true });
        return;
      }
    }
  }

  function applyEvent(root, result, invoke, announce) {
    if (!result || typeof result !== "object") return;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    if (result.kind === "render" && payload.snapshot) {
      renderLibrarySurface(root, payload.snapshot, invoke, announce, payload.focus_target || "");
    }
    if (result.kind === "render-import" && payload.import) {
      const current = root.__accessibleChessLibrarySnapshot;
      if (current && typeof current === "object") {
        const updated = Object.assign({}, current, { import: payload.import });
        const region = root.querySelector("#library-import-region");
        const active = document.activeElement;
        const restore = region && active && region.contains(active) ? String(active.id || "") : "";
        const replacement = buildImportSection(root, updated, invoke, announce);
        if (region && replacement && typeof region.replaceWith === "function") {
          region.replaceWith(replacement);
          root.__accessibleChessLibrarySnapshot = updated;
          focusRequestedOption(root, payload.focus_target || restore);
        } else {
          renderLibrarySurface(root, updated, invoke, announce, payload.focus_target || "");
        }
      }
    }
    if (payload.announcement) announce(String(payload.announcement));
    if (result.kind === "error" && payload.message) announce(String(payload.message));
  }

  function invokeCommand(root, invoke, announce, snapshot, command, payload) {
    const generic = snapshot && snapshot.transport_error_message ? String(snapshot.transport_error_message) : "";
    return Promise.resolve().then(function () {
      return invoke(command, payload || {});
    }).then(function (result) {
      applyEvent(root, result, invoke, announce);
      return result;
    }).catch(function () {
      if (generic) announce(generic);
      return null;
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
    const state = snapshot.import && typeof snapshot.import === "object" ? snapshot.import : null;
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
    rows.forEach(function (row) {
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
        if (event.key === "ArrowUp" || event.key === "ArrowDown") {
          event.preventDefault();
          invokeCommand(root, invoke, announce, snapshot, "library.move", {
            delta: event.key === "ArrowUp" ? -1 : 1
          });
        } else if (event.key === "Enter") {
          event.preventDefault();
          invokeCommand(root, invoke, announce, snapshot, "library.open_game", {});
        }
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
    if (!snapshot || typeof snapshot !== "object") throw new TypeError("Library snapshot is required");

    const fragment = document.createDocumentFragment();
    const main = node("section");
    main.appendChild(node("h2", snapshot.heading || ""));
    main.appendChild(node("p", snapshot.description || ""));
    renderImport(root, main, snapshot, invoke, announce);
    renderFilters(root, main, snapshot, invoke, announce);
    renderResults(root, main, snapshot, invoke, announce);
    renderExportSelection(root, main, snapshot, invoke, announce);
    renderActions(root, main, snapshot, invoke, announce);
    if (snapshot.message) {
      const message = node("p", snapshot.message);
      message.setAttribute("aria-live", "off");
      main.appendChild(message);
    }
    fragment.appendChild(main);
    root.replaceChildren(fragment);
    root.__accessibleChessLibrarySnapshot = snapshot;
    focusRequestedOption(root, requestedFocus || "");
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
    apply: applyLibraryEvent
  });
})(window);
