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

  function safeInvoke(invoke, command, payload, onResult, announce, fallbackMessage) {
    Promise.resolve(invoke(command, payload || {})).then(onResult).catch(function () {
      if (fallbackMessage) announce(String(fallbackMessage));
    });
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

  function renderDetail(detail) {
    const wrapper = node("section");
    wrapper.id = "education-detail";
    wrapper.setAttribute("aria-labelledby", "education-detail-heading");
    if (!detail || typeof detail !== "object") {
      wrapper.setAttribute("hidden", "hidden");
      return wrapper;
    }

    const heading = node("h2", detail.heading || "");
    heading.id = "education-detail-heading";
    heading.tabIndex = -1;
    wrapper.appendChild(heading);
    if (detail.secondary) wrapper.appendChild(node("p", detail.secondary));
    if (detail.status) wrapper.appendChild(node("p", detail.status));
    return wrapper;
  }

  function activeIdInside(root) {
    const active = document.activeElement;
    if (!active || !active.id || !root || typeof root.contains !== "function") return "";
    return root.contains(active) ? String(active.id) : "";
  }

  function applyEducationEvent(root, result, invoke, announce, fallbackMessage) {
    if (!root || !result || typeof result !== "object") return;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    const previousFocus = activeIdInside(root);
    if ((result.kind === "selection" || result.kind === "page") && payload.snapshot) {
      const previous = root.querySelector("#" + String(payload.snapshot.dom_id || ""));
      if (previous && typeof previous.replaceWith === "function") {
        previous.replaceWith(renderSection(payload.snapshot, invoke, announce, fallbackMessage));
      }
    }
    if (result.kind === "delegated" && payload.detail && typeof payload.detail === "object") {
      const previousDetail = root.querySelector("#education-detail");
      if (previousDetail && typeof previousDetail.replaceWith === "function") {
        previousDetail.replaceWith(renderDetail(payload.detail));
      }
    }
    if (payload.collaboration && typeof payload.collaboration === "object") {
      const previousCollaboration = root.querySelector("#classroom-collaboration");
      if (previousCollaboration && typeof previousCollaboration.replaceWith === "function") {
        previousCollaboration.replaceWith(
          renderCollaboration(payload.collaboration, invoke, announce, fallbackMessage)
        );
      }
    }
    if (payload.announcement) announce(String(payload.announcement));
    if (result.kind === "error" && payload.message) announce(String(payload.message));
    focusTarget(root, payload.focus_target || previousFocus || "");
  }

  function invokeSection(invoke, command, payload, root, announce, fallbackMessage) {
    safeInvoke(invoke, command, payload, function (result) {
      applyEducationEvent(root, result, invoke, announce, fallbackMessage);
    }, announce, fallbackMessage);
  }

  function renderSection(section, invoke, announce, fallbackMessage) {
    const wrapper = node("section");
    wrapper.id = String(section.dom_id || "education-section-" + String(section.kind || ""));
    wrapper.setAttribute("data-education-kind", String(section.kind || ""));
    wrapper.appendChild(node("h2", section.heading || ""));

    const rootForEvents = function () { return wrapper.parentNode; };
    const create = section.create_action && typeof section.create_action === "object"
      ? section.create_action : null;
    if (create && create.command) {
      const createButton = node("button", create.label || create.command);
      createButton.type = "button";
      createButton.setAttribute("data-command", String(create.command));
      createButton.addEventListener("click", function () {
        invokeSection(invoke, String(create.command), {}, rootForEvents(), announce, fallbackMessage);
      });
      wrapper.appendChild(createButton);
    }

    const pageControls = node("div");
    const previous = node("button", section.previous_label || "Previous page");
    previous.type = "button";
    previous.disabled = !section.can_previous;
    previous.setAttribute("data-command", "education.page.previous");
    previous.addEventListener("click", function () {
      invokeSection(invoke, "education.page", {
        kind: section.kind,
        direction: -1
      }, rootForEvents(), announce, fallbackMessage);
    });
    pageControls.appendChild(previous);
    const pageStatus = node("span", section.page_label || "");
    pageStatus.setAttribute("aria-live", "off");
    pageControls.appendChild(pageStatus);
    const next = node("button", section.next_label || "Next page");
    next.type = "button";
    next.disabled = !section.can_next;
    next.setAttribute("data-command", "education.page.next");
    next.addEventListener("click", function () {
      invokeSection(invoke, "education.page", {
        kind: section.kind,
        direction: 1
      }, rootForEvents(), announce, fallbackMessage);
    });
    pageControls.appendChild(next);
    wrapper.appendChild(pageControls);

    const items = Array.isArray(section.items) ? section.items : [];
    if (!items.length) {
      wrapper.appendChild(node("p", section.empty_message || ""));
      return wrapper;
    }

    const list = node("ul");
    list.setAttribute("role", "listbox");
    list.setAttribute("aria-label", section.heading || section.kind || "");
    items.forEach(function (item) {
      const option = node("li");
      option.id = String(item.dom_id || "");
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", item.selected ? "true" : "false");
      option.setAttribute("data-item-key", String(item.item_key || ""));
      option.tabIndex = item.selected ? 0 : -1;
      option.appendChild(node("span", item.label || ""));
      if (item.secondary) {
        option.appendChild(document.createTextNode(" — "));
        option.appendChild(node("span", item.secondary));
      }
      if (item.status) {
        option.appendChild(document.createTextNode(" — "));
        option.appendChild(node("span", item.status));
      }
      option.addEventListener("click", function () {
        invokeSection(invoke, "education.select", {
          kind: section.kind,
          item_key: item.item_key
        }, rootForEvents(), announce, fallbackMessage);
      });
      option.addEventListener("keydown", function (event) {
        let command = "";
        let payload = {};
        if (event.key === "ArrowUp") {
          command = "education.move";
          payload = { kind: section.kind, direction: -1 };
        } else if (event.key === "ArrowDown") {
          command = "education.move";
          payload = { kind: section.kind, direction: 1 };
        } else if (event.key === "Enter" && section.open_enabled) {
          command = "education.open";
          payload = { kind: section.kind };
        }
        if (!command) return;
        event.preventDefault();
        invokeSection(invoke, command, payload, rootForEvents(), announce, fallbackMessage);
      });
      list.appendChild(option);
    });
    wrapper.appendChild(list);

    if (section.open_enabled) {
      const open = node("button", section.open_label || "Open");
      open.type = "button";
      open.setAttribute("data-command", "education.open");
      open.addEventListener("click", function () {
        invokeSection(invoke, "education.open", { kind: section.kind }, rootForEvents(), announce, fallbackMessage);
      });
      wrapper.appendChild(open);
    }
    return wrapper;
  }

  function invokeCollaboration(invoke, command, payload, wrapper, announce, fallbackMessage) {
    const root = wrapper.parentNode;
    safeInvoke(invoke, command, payload, function (result) {
      applyEducationEvent(root, result, invoke, announce, fallbackMessage);
    }, announce, fallbackMessage);
  }

  function renderCollaboration(snapshot, invoke, announce, fallbackMessage) {
    const wrapper = node("section");
    wrapper.id = "classroom-collaboration";
    wrapper.setAttribute("aria-labelledby", "classroom-collaboration-heading");
    const heading = node("h2", snapshot.heading || "");
    heading.id = "classroom-collaboration-heading";
    wrapper.appendChild(heading);
    if (snapshot.available === false) {
      const status = node("p", snapshot.status_message || "");
      status.id = "classroom-collaboration-status";
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "off");
      wrapper.appendChild(status);
      return wrapper;
    }

    const chat = snapshot.chat && typeof snapshot.chat === "object" ? snapshot.chat : {};
    const chatSection = node("section");
    chatSection.setAttribute("aria-labelledby", "collaboration-chat-heading");
    const chatHeading = node("h3", chat.heading || "");
    chatHeading.id = "collaboration-chat-heading";
    chatSection.appendChild(chatHeading);

    const unread = node("p", chat.unread_label || "");
    unread.id = "collaboration-unread-status";
    unread.setAttribute("aria-live", "off");
    chatSection.appendChild(unread);

    const chatActions = node("div");
    const sync = node("button", chat.sync_label || "Refresh chat");
    sync.type = "button";
    sync.setAttribute("data-command", "collaboration.chat.sync");
    sync.addEventListener("click", function () {
      invokeCollaboration(invoke, "collaboration.chat.sync", {}, wrapper, announce, fallbackMessage);
    });
    chatActions.appendChild(sync);
    const markRead = node("button", chat.mark_read_label || "Mark read");
    markRead.type = "button";
    markRead.disabled = !(Number(chat.unread_count || 0) > 0);
    markRead.setAttribute("data-command", "collaboration.chat.mark_read");
    markRead.addEventListener("click", function () {
      invokeCollaboration(invoke, "collaboration.chat.mark_read", {}, wrapper, announce, fallbackMessage);
    });
    chatActions.appendChild(markRead);
    if (chat.moderation_available) {
      const muteAll = node("button", chat.mute_all_label || "Mute all students");
      muteAll.type = "button";
      muteAll.setAttribute("data-command", "collaboration.chat.mute_all_students");
      muteAll.addEventListener("click", function () {
        invokeCollaboration(
          invoke,
          "collaboration.chat.mute_all_students",
          {},
          wrapper,
          announce,
          fallbackMessage
        );
      });
      chatActions.appendChild(muteAll);
      const allowAll = node("button", chat.allow_all_label || "Allow all students");
      allowAll.type = "button";
      allowAll.setAttribute("data-command", "collaboration.chat.allow_all_students");
      allowAll.addEventListener("click", function () {
        invokeCollaboration(
          invoke,
          "collaboration.chat.allow_all_students",
          {},
          wrapper,
          announce,
          fallbackMessage
        );
      });
      chatActions.appendChild(allowAll);
    }
    chatSection.appendChild(chatActions);

    const form = node("form");
    form.id = "collaboration-chat-form";
    const label = node("label", chat.composer_label || "Message");
    label.setAttribute("for", "collaboration-chat-input");
    form.appendChild(label);
    const input = node("textarea");
    input.id = "collaboration-chat-input";
    input.rows = 3;
    const maxBody = Number(chat.max_body_chars || 0);
    if (Number.isFinite(maxBody) && maxBody > 0) input.maxLength = maxBody;
    form.appendChild(input);
    const send = node("button", chat.send_label || "Send");
    send.type = "submit";
    send.setAttribute("data-command", "collaboration.chat.send");
    form.appendChild(send);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (!String(input.value || "").trim()) return;
      invokeCollaboration(
        invoke,
        "collaboration.chat.send",
        { body: String(input.value) },
        wrapper,
        announce,
        fallbackMessage
      );
    });
    chatSection.appendChild(form);

    const messages = Array.isArray(chat.messages) ? chat.messages : [];
    if (!messages.length) {
      chatSection.appendChild(node("p", chat.empty_message || ""));
    } else {
      const history = node("ol");
      history.id = "collaboration-chat-history";
      history.setAttribute("aria-label", chat.heading || "Chat");
      messages.forEach(function (message) {
        const item = node("li");
        item.id = String(message.dom_id || "");
        if (message.unread) item.setAttribute("data-unread", "true");
        item.appendChild(node("strong", message.sender || ""));
        item.appendChild(document.createTextNode(": "));
        item.appendChild(node("span", message.body || ""));
        if (message.can_hide && message.message_key) {
          const hide = node("button", chat.hide_label || "Hide message");
          hide.type = "button";
          hide.setAttribute("data-command", "collaboration.chat.hide");
          hide.addEventListener("click", function () {
            invokeCollaboration(
              invoke,
              "collaboration.chat.hide",
              { message_key: message.message_key },
              wrapper,
              announce,
              fallbackMessage
            );
          });
          item.appendChild(hide);
        }
        if (message.can_moderate_sender && message.message_key) {
          const mute = node("button", chat.mute_sender_label || "Mute sender");
          mute.type = "button";
          mute.setAttribute("data-command", "collaboration.chat.mute_sender");
          mute.addEventListener("click", function () {
            invokeCollaboration(
              invoke,
              "collaboration.chat.mute_sender",
              { message_key: message.message_key },
              wrapper,
              announce,
              fallbackMessage
            );
          });
          item.appendChild(mute);
          const allow = node("button", chat.allow_sender_label || "Allow sender");
          allow.type = "button";
          allow.setAttribute("data-command", "collaboration.chat.allow_sender");
          allow.addEventListener("click", function () {
            invokeCollaboration(
              invoke,
              "collaboration.chat.allow_sender",
              { message_key: message.message_key },
              wrapper,
              announce,
              fallbackMessage
            );
          });
          item.appendChild(allow);
        }
        if (message.can_remove_sender && message.message_key) {
          const remove = node("button", chat.remove_sender_label || "Remove participant");
          remove.type = "button";
          remove.setAttribute("data-command", "collaboration.participant.remove_sender");
          remove.addEventListener("click", function () {
            invokeCollaboration(
              invoke,
              "collaboration.participant.remove_sender",
              { message_key: message.message_key },
              wrapper,
              announce,
              fallbackMessage
            );
          });
          item.appendChild(remove);
          const block = node("button", chat.block_sender_label || "Remove and block participant");
          block.type = "button";
          block.setAttribute("data-command", "collaboration.participant.block_sender");
          block.addEventListener("click", function () {
            invokeCollaboration(
              invoke,
              "collaboration.participant.block_sender",
              { message_key: message.message_key },
              wrapper,
              announce,
              fallbackMessage
            );
          });
          item.appendChild(block);
        }
        history.appendChild(item);
      });
      chatSection.appendChild(history);
    }
    wrapper.appendChild(chatSection);

    const files = snapshot.files && typeof snapshot.files === "object" ? snapshot.files : {};
    const fileSection = node("section");
    fileSection.setAttribute("aria-labelledby", "collaboration-files-heading");
    const fileHeading = node("h3", files.heading || "");
    fileHeading.id = "collaboration-files-heading";
    fileSection.appendChild(fileHeading);
    const choose = node("button", files.choose_upload_label || "Choose and send file");
    choose.type = "button";
    choose.disabled = !files.can_choose_upload;
    choose.setAttribute("data-command", "collaboration.file.choose_upload");
    choose.addEventListener("click", function () {
      invokeCollaboration(invoke, "collaboration.file.choose_upload", {}, wrapper, announce, fallbackMessage);
    });
    fileSection.appendChild(choose);

    const fileItems = Array.isArray(files.items) ? files.items : [];
    if (!fileItems.length) {
      fileSection.appendChild(node("p", files.empty_message || ""));
    } else {
      const list = node("ul");
      list.id = "collaboration-file-list";
      fileItems.forEach(function (file) {
        const item = node("li");
        item.id = String(file.dom_id || "");
        item.appendChild(node("strong", file.name || ""));
        if (file.sender) {
          item.appendChild(document.createTextNode(" — "));
          item.appendChild(node("span", file.sender));
        }
        [file.size_label, file.type_label, file.status_label, file.scan_label].forEach(function (value) {
          if (!value) return;
          item.appendChild(document.createTextNode(" — "));
          item.appendChild(node("span", value));
        });
        if (file.can_save) {
          const save = node("button", files.save_label || "Save");
          save.type = "button";
          save.setAttribute("data-command", "collaboration.file.save");
          save.addEventListener("click", function () {
            invokeCollaboration(invoke, "collaboration.file.save", { file_key: file.file_key }, wrapper, announce, fallbackMessage);
          });
          item.appendChild(save);
        }
        if (file.can_open) {
          const open = node("button", files.open_label || "Open");
          open.type = "button";
          open.setAttribute("data-command", "collaboration.file.open");
          open.addEventListener("click", function () {
            invokeCollaboration(
              invoke,
              "collaboration.file.open",
              { file_key: file.file_key },
              wrapper,
              announce,
              fallbackMessage
            );
          });
          item.appendChild(open);
        }
        if (file.can_retry) {
          const retry = node("button", files.retry_label || "Retry");
          retry.type = "button";
          retry.setAttribute("data-command", "collaboration.file.retry");
          retry.addEventListener("click", function () {
            invokeCollaboration(invoke, "collaboration.file.retry", { file_key: file.file_key }, wrapper, announce, fallbackMessage);
          });
          item.appendChild(retry);
        }
        if (file.can_cancel) {
          const cancel = node("button", files.cancel_label || "Cancel");
          cancel.type = "button";
          cancel.setAttribute("data-command", "collaboration.file.cancel");
          cancel.addEventListener("click", function () {
            invokeCollaboration(invoke, "collaboration.file.cancel", { file_key: file.file_key }, wrapper, announce, fallbackMessage);
          });
          item.appendChild(cancel);
        }
        list.appendChild(item);
      });
      fileSection.appendChild(list);
    }
    wrapper.appendChild(fileSection);
    return wrapper;
  }

  function renderEducationSurface(root, snapshot, invoke, announce, requestedFocus, fallbackMessage) {
    if (!root || typeof root.replaceChildren !== "function") {
      throw new TypeError("education root must support replaceChildren");
    }
    requireFunction(invoke, "education invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "education announce");
    if (!snapshot || typeof snapshot !== "object") throw new TypeError("education snapshot is required");

    const fragment = document.createDocumentFragment();
    const main = node("main");
    const documentState = snapshot.document || {};
    if (documentState.lang) main.setAttribute("lang", String(documentState.lang));
    main.appendChild(node("h1", documentState.heading || ""));
    const sections = Array.isArray(snapshot.sections) ? snapshot.sections : [];
    sections.forEach(function (section) {
      main.appendChild(renderSection(section || {}, invoke, announce, fallbackMessage));
    });
    main.appendChild(renderDetail(snapshot.detail || null));
    if (snapshot.collaboration && typeof snapshot.collaboration === "object") {
      main.appendChild(renderCollaboration(snapshot.collaboration, invoke, announce, fallbackMessage));
    }
    fragment.appendChild(main);
    root.replaceChildren(fragment);
    focusTarget(root, requestedFocus || "");
  }

  global.AccessibleChessEducationSurface = Object.freeze({
    render: renderEducationSurface,
    apply: applyEducationEvent
  });
})(window);
