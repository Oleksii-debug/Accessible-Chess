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

  function setText(element, value) {
    element.textContent = value == null ? "" : String(value);
  }

  function applyEvent(result, announce) {
    if (!result || typeof result !== "object") return;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    if (payload.announcement) announce(String(payload.announcement));
    if (result.kind === "error" && payload.message) announce(String(payload.message));
  }

  function renderManagement(host, section, invoke, announce) {
    const wrapper = node("section");
    const heading = node("h2", section.heading || "");
    wrapper.appendChild(heading);

    if (section.message) {
      const message = node("p", section.message);
      wrapper.appendChild(message);
    }

    const items = Array.isArray(section.items) ? section.items : [];
    if (!items.length) {
      wrapper.appendChild(node("p", section.empty_message || ""));
      host.appendChild(wrapper);
      return;
    }

    const list = node("ul");
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", section.heading || section.kind || "");

    items.forEach(function (item) {
      const option = node("li");
      option.id = String(item.dom_id || "");
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", item.selected ? "true" : "false");
      option.tabIndex = item.selected ? 0 : -1;

      const primary = node("span", item.label || "");
      option.appendChild(primary);
      if (item.secondary) {
        option.appendChild(document.createTextNode(" — "));
        option.appendChild(node("span", item.secondary));
      }
      if (item.status) {
        option.appendChild(document.createTextNode(" — "));
        option.appendChild(node("span", item.status));
      }

      option.addEventListener("click", function () {
        Promise.resolve(invoke("management.select", {
          kind: section.kind,
          record_id: item.record_id
        })).then(function (result) { applyEvent(result, announce); });
      });

      option.addEventListener("keydown", function (event) {
        let command = null;
        let payload = null;
        if (event.key === "ArrowUp") {
          command = "management.move";
          payload = { kind: section.kind, delta: -1 };
        } else if (event.key === "ArrowDown") {
          command = "management.move";
          payload = { kind: section.kind, delta: 1 };
        } else if (event.key === "Enter") {
          command = "management.open";
          payload = { kind: section.kind };
        }
        if (!command) return;
        event.preventDefault();
        Promise.resolve(invoke(command, payload)).then(function (result) {
          applyEvent(result, announce);
        });
      });

      list.appendChild(option);
    });

    wrapper.appendChild(list);
    host.appendChild(wrapper);
  }

  function renderRemote(host, remote, invoke, announce) {
    const wrapper = node("section");
    wrapper.appendChild(node("h2", remote.heading || ""));

    const status = node("p", remote.accessible_status || remote.status_text || "");
    status.setAttribute("aria-live", "off");
    wrapper.appendChild(status);

    if (remote.message) wrapper.appendChild(node("p", remote.message));

    const inputSpec = remote.lesson_input || {};
    const label = node("label", inputSpec.label || "");
    const input = node("input");
    input.type = "text";
    input.id = String(inputSpec.id || "remote-lesson-id");
    input.autocomplete = "off";
    input.spellcheck = false;
    label.htmlFor = input.id;
    wrapper.appendChild(label);
    wrapper.appendChild(input);

    const actions = Array.isArray(remote.actions) ? remote.actions : [];
    actions.forEach(function (action) {
      const button = node("button", action.label || action.action || "");
      button.type = "button";
      button.disabled = !action.enabled;
      button.addEventListener("click", function () {
        let command = String(action.action || "");
        let payload = {};
        if (command === "remote.connect") payload.lesson_id = input.value;
        Promise.resolve(invoke(command, payload)).then(function (result) {
          applyEvent(result, announce);
        });
      });
      wrapper.appendChild(button);
    });

    host.appendChild(wrapper);
  }

  function renderClassroomSurface(root, snapshot, invoke, announce) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new TypeError("classroom root must support replaceChildren");
    }
    requireFunction(invoke, "classroom invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "classroom announce");
    if (!snapshot || typeof snapshot !== "object") throw new TypeError("classroom snapshot is required");

    const fragment = document.createDocumentFragment();
    const management = Array.isArray(snapshot.management) ? snapshot.management : [];
    management.forEach(function (section) {
      renderManagement(fragment, section || {}, invoke, announce);
    });
    renderRemote(fragment, snapshot.remote || {}, invoke, announce);
    root.replaceChildren(fragment);

    const selected = root.querySelector('[role="option"][aria-selected="true"]');
    if (selected && typeof selected.focus === "function") selected.focus({ preventScroll: true });
  }

  global.AccessibleChessClassroomSurface = Object.freeze({
    render: renderClassroomSurface
  });
})(window);
