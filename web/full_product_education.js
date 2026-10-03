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

  function safeInvoke(
    invoke,
    command,
    payload,
    onResult,
    announce,
    fallbackMessage,
    onFailure
  ) {
    Promise.resolve()
      .then(function () { return invoke(command, payload || {}); })
      .then(onResult)
      .catch(function () {
        let shouldAnnounceFailure = true;
        if (typeof onFailure === "function") {
          try {
            if (onFailure() === false) shouldAnnounceFailure = false;
          } catch (_error) {
            // Recovery cleanup must not hide the bounded user-facing failure.
          }
        }
        if (shouldAnnounceFailure && fallbackMessage) {
          announce(String(fallbackMessage));
        }
      });
  }

  function focusTarget(root, targetId) {
    if (!targetId) return false;
    const candidates = root.querySelectorAll("[id]");
    for (let index = 0; index < candidates.length; index += 1) {
      if (
        candidates[index].id === targetId &&
        !candidates[index].disabled &&
        typeof candidates[index].focus === "function"
      ) {
        candidates[index].focus({ preventScroll: true });
        return true;
      }
    }
    return false;
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

  function collaborationOwnsFocus(root) {
    if (!root || typeof root.querySelector !== "function") return false;
    const collaboration = root.querySelector("#classroom-collaboration");
    return !!(
      collaboration &&
      typeof collaboration.contains === "function" &&
      collaboration.contains(document.activeElement)
    );
  }

  function collaborationFocusTarget(value) {
    if (typeof value !== "string") return "";
    return [
      "classroom-collaboration-heading",
      "collaboration-chat-input",
      "collaboration-chat-sync",
      "collaboration-chat-older",
      "collaboration-chat-newer",
      "collaboration-file-older",
      "collaboration-file-newer",
      "collaboration-file-choose"
    ].indexOf(value) >= 0 ? value : "";
  }

  function collaborationPendingState(root) {
    if (!root || typeof root.querySelector !== "function") return null;
    const wrapper = root.querySelector("#classroom-collaboration");
    if (!wrapper || wrapper.getAttribute("aria-busy") !== "true") return null;
    return {
      command: String(wrapper.getAttribute("data-pending-command") || ""),
      lockComposer: wrapper.getAttribute("data-pending-lock-composer") === "true",
      focusControlId: String(
        wrapper.getAttribute("data-pending-focus-control") || ""
      )
    };
  }

  function applyCollaborationPendingState(wrapper, pending) {
    if (!wrapper || !pending) return;
    wrapper.setAttribute("aria-busy", "true");
    wrapper.setAttribute("data-pending-command", String(pending.command || ""));
    wrapper.setAttribute(
      "data-pending-lock-composer",
      pending.lockComposer ? "true" : "false"
    );
    if (pending.focusControlId) {
      wrapper.setAttribute(
        "data-pending-focus-control",
        String(pending.focusControlId)
      );
    } else {
      wrapper.removeAttribute("data-pending-focus-control");
    }
    wrapper.querySelectorAll("BUTTON").forEach(function (control) {
      control.setAttribute(
        "data-pending-was-disabled",
        control.disabled ? "true" : "false"
      );
      if (!pending.focusControlId || control.id !== pending.focusControlId) {
        control.disabled = true;
      }
      control.setAttribute("aria-disabled", "true");
    });
    if (pending.lockComposer) {
      const composer = wrapper.querySelector("#collaboration-chat-input");
      const form = wrapper.querySelector("#collaboration-chat-form");
      if (composer) composer.readOnly = true;
      if (form) form.setAttribute("aria-busy", "true");
    }
  }

  function clearCollaborationPendingState(wrapper) {
    if (!wrapper) return;
    const lockComposer = wrapper.getAttribute("data-pending-lock-composer") === "true";
    wrapper.setAttribute("aria-busy", "false");
    wrapper.removeAttribute("data-pending-command");
    wrapper.removeAttribute("data-pending-lock-composer");
    wrapper.removeAttribute("data-pending-focus-control");
    wrapper.querySelectorAll("BUTTON").forEach(function (control) {
      const wasDisabled = control.getAttribute("data-pending-was-disabled");
      if (wasDisabled === "false") control.disabled = false;
      control.removeAttribute("data-pending-was-disabled");
      control.removeAttribute("aria-disabled");
    });
    if (lockComposer) {
      const composer = wrapper.querySelector("#collaboration-chat-input");
      const form = wrapper.querySelector("#collaboration-chat-form");
      if (composer) composer.readOnly = false;
      if (form) form.setAttribute("aria-busy", "false");
    }
  }

  function collaborationDraftInside(root) {
    if (!root || typeof root.querySelector !== "function") return null;
    const input = root.querySelector("#collaboration-chat-input");
    if (!input) return null;
    return {
      value: String(input.value || ""),
      selectionStart: Number.isInteger(input.selectionStart) ? input.selectionStart : null,
      selectionEnd: Number.isInteger(input.selectionEnd) ? input.selectionEnd : null
    };
  }

  function restoreCollaborationDraft(root, draft) {
    if (!draft || !root || typeof root.querySelector !== "function") return;
    const input = root.querySelector("#collaboration-chat-input");
    if (!input) return;
    input.value = draft.value;
    if (
      typeof input.setSelectionRange === "function" &&
      Number.isInteger(draft.selectionStart) &&
      Number.isInteger(draft.selectionEnd)
    ) {
      try {
        input.setSelectionRange(draft.selectionStart, draft.selectionEnd);
      } catch (_error) {
        // Keep the draft even when this host cannot restore a text selection.
      }
    }
  }

  function setCollaborationStatus(wrapper, message) {
    if (!wrapper || typeof wrapper.querySelector !== "function") return;
    const status = wrapper.querySelector("#classroom-collaboration-status");
    if (status) status.textContent = String(message || "");
  }

  function applyCollaborationFileProgress(root, progressInfo) {
    if (
      !root ||
      !progressInfo ||
      typeof progressInfo !== "object" ||
      typeof root.querySelector !== "function"
    ) {
      return false;
    }
    const wrapper = root.querySelector("#classroom-collaboration");
    if (!wrapper) return false;
    const sessionKey = String(progressInfo.session_key || "");
    if (
      !sessionKey ||
      wrapper.getAttribute("data-collaboration-session") !== sessionKey
    ) {
      return false;
    }
    const transferred = Number(progressInfo.transferred_bytes);
    const total = Number(progressInfo.total_bytes);
    if (
      !Number.isSafeInteger(transferred) ||
      !Number.isSafeInteger(total) ||
      transferred < 0 ||
      total < 0 ||
      transferred > total
    ) {
      return false;
    }
    const container = wrapper.querySelector("#collaboration-file-transfer-progress");
    if (!container || typeof container.replaceChildren !== "function") return false;
    const meter = node("progress");
    meter.id = "collaboration-file-transfer-meter";
    const semanticMax = total === 0 ? 1 : total;
    const semanticValue = (
      total === 0 && progressInfo.complete === true ? 1 : transferred
    );
    meter.setAttribute("max", String(semanticMax));
    meter.setAttribute("value", String(semanticValue));
    const label = String(progressInfo.label || "File transfer progress");
    const name = String(progressInfo.name || "");
    meter.setAttribute("aria-label", name ? (label + ": " + name) : label);
    const text = node("span", String(progressInfo.text || ""));
    text.id = "collaboration-file-transfer-text";
    text.setAttribute("aria-live", "off");
    if (text.textContent) meter.setAttribute("aria-valuetext", text.textContent);
    container.replaceChildren(meter, document.createTextNode(" "), text);
    return true;
  }

  function applyEducationEvent(
    root,
    result,
    invoke,
    announce,
    fallbackMessage,
    settledCollaborationCommand
  ) {
    if (!root || !result || typeof result !== "object") return;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    if (result.kind === "collaboration.file.progress") {
      applyCollaborationFileProgress(root, payload.file_progress);
      return;
    }
    const previousFocus = activeIdInside(root);
    const collaborationWasFocused = collaborationOwnsFocus(root);
    const previousPending = collaborationPendingState(root);
    const previousDraft = collaborationDraftInside(root);
    const previousStatus = root.querySelector("#classroom-collaboration-status");
    const previousStatusText = previousStatus
      ? String(previousStatus.textContent || "")
      : "";
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
        if (result.kind !== "collaboration.chat.sent") {
          restoreCollaborationDraft(root, previousDraft);
        }
        if (
          previousPending &&
          previousPending.command !== String(settledCollaborationCommand || "")
        ) {
          applyCollaborationPendingState(
            root.querySelector("#classroom-collaboration"),
            previousPending
          );
        }
      }
    }
    const visibleStatus = (
      result.kind === "error" && payload.message
        ? String(payload.message)
        : payload.announcement
          ? String(payload.announcement)
          : settledCollaborationCommand
            ? ""
            : previousStatusText
    );
    if (payload.collaboration && typeof payload.collaboration === "object") {
      setCollaborationStatus(
        root.querySelector("#classroom-collaboration"),
        visibleStatus
      );
    }
    if (payload.announcement) announce(String(payload.announcement));
    if (result.kind === "error" && payload.message) announce(String(payload.message));
    const payloadFocus = payload.collaboration
      ? (
        collaborationWasFocused
          ? collaborationFocusTarget(payload.focus_target)
          : ""
      )
      : (typeof payload.focus_target === "string" ? payload.focus_target : "");
    const pendingOriginFocus = (
      previousPending && typeof previousPending.focusControlId === "string"
        ? previousPending.focusControlId
        : ""
    );
    const requestedFocus = payloadFocus || previousFocus || pendingOriginFocus || "";
    if (
      !focusTarget(root, requestedFocus) &&
      payload.collaboration &&
      requestedFocus
    ) {
      focusTarget(root, "classroom-collaboration-heading");
    }
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

  function invokeCollaboration(
    invoke,
    command,
    payload,
    wrapper,
    announce,
    fallbackMessage,
    options
  ) {
    if (!wrapper || wrapper.getAttribute("aria-busy") === "true") return false;
    const root = wrapper.parentNode;
    const sessionKey = String(
      wrapper.getAttribute("data-collaboration-session") || ""
    );
    const active = document.activeElement;
    const pending = {
      command: String(command || ""),
      lockComposer: !!(options && options.lockComposer),
      focusControlId: (
        active &&
        active.tagName === "BUTTON" &&
        typeof wrapper.contains === "function" &&
        wrapper.contains(active)
      ) ? String(active.id || "") : ""
    };
    applyCollaborationPendingState(wrapper, pending);
    const pendingAnnouncement = (
      options && typeof options.pendingAnnouncement === "string"
        ? options.pendingAnnouncement
        : ""
    );
    if (pendingAnnouncement) {
      setCollaborationStatus(wrapper, pendingAnnouncement);
      announce(pendingAnnouncement);
    }

    function releasePendingState() {
      const current = (
        root && typeof root.querySelector === "function"
          ? root.querySelector("#classroom-collaboration")
          : null
      );
      [wrapper, current].forEach(function (candidate, index, values) {
        if (
          candidate &&
          values.indexOf(candidate) === index &&
          candidate.getAttribute("data-pending-command") === pending.command &&
          (
            !sessionKey ||
            candidate.getAttribute("data-collaboration-session") === sessionKey
          )
        ) {
          clearCollaborationPendingState(candidate);
        }
      });
    }

    safeInvoke(invoke, command, payload, function (result) {
      const current = (
        root && typeof root.querySelector === "function"
          ? root.querySelector("#classroom-collaboration")
          : null
      );
      const resultPayload = (
        result && result.payload && typeof result.payload === "object"
          ? result.payload
          : {}
      );
      const resultCollaboration = (
        resultPayload.collaboration &&
        typeof resultPayload.collaboration === "object"
          ? resultPayload.collaboration
          : null
      );
      const resultSessionKey = resultCollaboration
        ? String(resultCollaboration.session_key || "")
        : "";
      if (
        sessionKey &&
        (
          !current ||
          current.getAttribute("data-collaboration-session") !== sessionKey ||
          (resultSessionKey && resultSessionKey !== sessionKey)
        )
      ) {
        return;
      }
      applyEducationEvent(
        root,
        result,
        invoke,
        announce,
        fallbackMessage,
        pending.command
      );
      if (wrapper.parentNode) releasePendingState();
    }, announce, fallbackMessage, function () {
      const current = (
        root && typeof root.querySelector === "function"
          ? root.querySelector("#classroom-collaboration")
          : null
      );
      if (
        sessionKey &&
        (
          !current ||
          current.getAttribute("data-collaboration-session") !== sessionKey
        )
      ) {
        return false;
      }
      releasePendingState();
      if (current) setCollaborationStatus(current, fallbackMessage || "");
      return true;
    });
    return true;
  }

  function renderCollaboration(snapshot, invoke, announce, fallbackMessage) {
    const wrapper = node("section");
    wrapper.id = "classroom-collaboration";
    wrapper.setAttribute("aria-labelledby", "classroom-collaboration-heading");
    if (typeof snapshot.session_key === "string" && snapshot.session_key) {
      wrapper.setAttribute(
        "data-collaboration-session",
        String(snapshot.session_key).slice(0, 128)
      );
    }
    const heading = node("h2", snapshot.heading || "");
    heading.id = "classroom-collaboration-heading";
    heading.tabIndex = -1;
    wrapper.appendChild(heading);
    const status = node(
      "p",
      snapshot.available === false ? (snapshot.status_message || "") : ""
    );
    status.id = "classroom-collaboration-status";
    status.setAttribute("aria-live", "off");
    if (snapshot.available === false) status.setAttribute("role", "status");
    wrapper.appendChild(status);
    if (snapshot.available === false) {
      return wrapper;
    }

    const chat = snapshot.chat && typeof snapshot.chat === "object" ? snapshot.chat : {};
    const chatSection = node("section");
    chatSection.setAttribute("aria-labelledby", "collaboration-chat-heading");
    const chatHeading = node("h3", chat.heading || "");
    chatHeading.id = "collaboration-chat-heading";
    chatSection.appendChild(chatHeading);

    if (chat.retention_policy_label) {
      const retentionPolicy = node("p", chat.retention_policy_label);
      retentionPolicy.id = "collaboration-chat-retention-policy";
      retentionPolicy.setAttribute("aria-live", "off");
      chatSection.appendChild(retentionPolicy);
    }

    const unread = node("p", chat.unread_label || "");
    unread.id = "collaboration-unread-status";
    unread.setAttribute("aria-live", "off");
    chatSection.appendChild(unread);

    const chatActions = node("div");
    const sync = node("button", chat.sync_label || "Refresh chat");
    sync.id = "collaboration-chat-sync";
    sync.type = "button";
    sync.setAttribute("data-command", "collaboration.chat.sync");
    sync.addEventListener("click", function () {
      invokeCollaboration(invoke, "collaboration.chat.sync", {}, wrapper, announce, fallbackMessage);
    });
    chatActions.appendChild(sync);
    const markRead = node("button", chat.mark_read_label || "Mark read");
    markRead.id = "collaboration-chat-mark-read";
    markRead.type = "button";
    markRead.disabled = !(Number(chat.unread_count || 0) > 0);
    markRead.setAttribute("data-command", "collaboration.chat.mark_read");
    markRead.addEventListener("click", function () {
      invokeCollaboration(invoke, "collaboration.chat.mark_read", {}, wrapper, announce, fallbackMessage);
    });
    chatActions.appendChild(markRead);

    const olderMessages = node("button", chat.older_label || "Older messages");
    olderMessages.id = "collaboration-chat-older";
    olderMessages.type = "button";
    olderMessages.disabled = !chat.can_older;
    olderMessages.setAttribute("aria-describedby", "collaboration-chat-page-status");
    olderMessages.setAttribute("data-command", "collaboration.chat.older");
    olderMessages.addEventListener("click", function () {
      invokeCollaboration(invoke, "collaboration.chat.older", {}, wrapper, announce, fallbackMessage);
    });
    chatActions.appendChild(olderMessages);
    const pageStatus = node("span", chat.page_label || "");
    pageStatus.id = "collaboration-chat-page-status";
    pageStatus.setAttribute("aria-live", "off");
    chatActions.appendChild(pageStatus);
    const newerMessages = node("button", chat.newer_label || "Newer messages");
    newerMessages.id = "collaboration-chat-newer";
    newerMessages.type = "button";
    newerMessages.disabled = !chat.can_newer;
    newerMessages.setAttribute("aria-describedby", "collaboration-chat-page-status");
    newerMessages.setAttribute("data-command", "collaboration.chat.newer");
    newerMessages.addEventListener("click", function () {
      invokeCollaboration(invoke, "collaboration.chat.newer", {}, wrapper, announce, fallbackMessage);
    });
    chatActions.appendChild(newerMessages);
    if (chat.moderation_available) {
      const muteAll = node("button", chat.mute_all_label || "Mute all students");
      muteAll.id = "collaboration-chat-mute-all";
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
      allowAll.id = "collaboration-chat-allow-all";
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
    input.setAttribute("dir", "auto");
    const maxBody = Number(chat.max_body_chars || 0);
    if (Number.isFinite(maxBody) && maxBody > 0) input.maxLength = maxBody;
    form.appendChild(input);
    const send = node("button", chat.send_label || "Send");
    send.id = "collaboration-chat-send";
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
        fallbackMessage,
        {
          lockComposer: true,
          pendingAnnouncement: chat.send_pending_label || ""
        }
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
        item.tabIndex = -1;
        if (message.unread) item.setAttribute("data-unread", "true");
        const sender = node("strong");
        const senderText = node("bdi", message.sender || "");
        senderText.setAttribute("dir", "auto");
        sender.appendChild(senderText);
        item.appendChild(sender);
        item.appendChild(document.createTextNode(": "));
        const body = node("bdi", message.body || "");
        body.setAttribute("dir", "auto");
        item.appendChild(body);
        if (message.timestamp_text) {
          const timestampDetails = node("details");
          timestampDetails.setAttribute("data-message-timestamp", "true");
          const timestampSummary = node(
            "summary",
            chat.timestamp_label || "Message time"
          );
          timestampSummary.id = item.id + "-timestamp";
          timestampDetails.appendChild(timestampSummary);
          const timestamp = node("time", String(message.timestamp_text));
          timestamp.setAttribute("aria-live", "off");
          if (message.timestamp_datetime) {
            timestamp.setAttribute("datetime", String(message.timestamp_datetime));
          }
          timestampDetails.appendChild(timestamp);
          item.appendChild(timestampDetails);
        }
        if (message.retention_label) {
          const retentionDetails = node("details");
          retentionDetails.setAttribute("data-message-retention", "true");
          const retentionSummary = node(
            "summary",
            chat.retention_label || "Retention"
          );
          retentionSummary.id = item.id + "-retention";
          retentionDetails.appendChild(retentionSummary);
          const retention = node("span", String(message.retention_label));
          retention.setAttribute("aria-live", "off");
          retentionDetails.appendChild(retention);
          item.appendChild(retentionDetails);
        }
        if (message.can_hide && message.message_key) {
          const hide = node("button", chat.hide_label || "Hide message");
          hide.id = item.id + "-hide";
          hide.type = "button";
          hide.setAttribute(
            "aria-label",
            (chat.hide_label || "Hide message") + ": " +
              String(message.action_message || message.action_sender || message.sender || "")
          );
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
          mute.id = item.id + "-mute";
          mute.type = "button";
          mute.setAttribute(
            "aria-label",
            (chat.mute_sender_label || "Mute sender") + ": " +
              String(message.action_sender || message.sender || "")
          );
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
          allow.id = item.id + "-allow";
          allow.type = "button";
          allow.setAttribute(
            "aria-label",
            (chat.allow_sender_label || "Allow sender") + ": " +
              String(message.action_sender || message.sender || "")
          );
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
          remove.id = item.id + "-remove";
          remove.type = "button";
          remove.setAttribute(
            "aria-label",
            (chat.remove_sender_label || "Remove participant") + ": " +
              String(message.action_sender || message.sender || "")
          );
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
          block.id = item.id + "-block";
          block.type = "button";
          block.setAttribute(
            "aria-label",
            (chat.block_sender_label || "Remove and block participant") + ": " +
              String(message.action_sender || message.sender || "")
          );
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
    if (files.retention_policy_label) {
      const retentionPolicy = node("p", files.retention_policy_label);
      retentionPolicy.id = "collaboration-file-retention-policy";
      retentionPolicy.setAttribute("aria-live", "off");
      fileSection.appendChild(retentionPolicy);
    }
    const syncFiles = node("button", files.sync_label || "Refresh files");
    syncFiles.id = "collaboration-file-sync";
    syncFiles.type = "button";
    syncFiles.setAttribute("data-command", "collaboration.file.sync");
    syncFiles.addEventListener("click", function () {
      invokeCollaboration(
        invoke,
        "collaboration.file.sync",
        {},
        wrapper,
        announce,
        fallbackMessage,
        { pendingAnnouncement: files.sync_pending_label || "" }
      );
    });
    fileSection.appendChild(syncFiles);
    const choose = node("button", files.choose_upload_label || "Choose and send file");
    choose.id = "collaboration-file-choose";
    choose.type = "button";
    choose.disabled = !files.can_choose_upload;
    choose.setAttribute("data-command", "collaboration.file.choose_upload");
    choose.addEventListener("click", function () {
      invokeCollaboration(
        invoke,
        "collaboration.file.choose_upload",
        {},
        wrapper,
        announce,
        fallbackMessage,
        { pendingAnnouncement: files.choose_upload_pending_label || "" }
      );
    });
    fileSection.appendChild(choose);
    const transferProgress = node("div");
    transferProgress.id = "collaboration-file-transfer-progress";
    transferProgress.setAttribute("aria-live", "off");
    transferProgress.setAttribute(
      "aria-label",
      files.progress_label || "File transfer progress"
    );
    fileSection.appendChild(transferProgress);
    const olderFiles = node("button", files.older_label || "Older files");
    olderFiles.id = "collaboration-file-older";
    olderFiles.type = "button";
    olderFiles.disabled = !files.can_older;
    olderFiles.setAttribute("aria-describedby", "collaboration-file-page-status");
    olderFiles.setAttribute("data-command", "collaboration.file.older");
    olderFiles.addEventListener("click", function () {
      invokeCollaboration(invoke, "collaboration.file.older", {}, wrapper, announce, fallbackMessage);
    });
    fileSection.appendChild(olderFiles);
    const filePageStatus = node("span", files.page_label || "");
    filePageStatus.id = "collaboration-file-page-status";
    filePageStatus.setAttribute("aria-live", "off");
    fileSection.appendChild(filePageStatus);
    const newerFiles = node("button", files.newer_label || "Newer files");
    newerFiles.id = "collaboration-file-newer";
    newerFiles.type = "button";
    newerFiles.disabled = !files.can_newer;
    newerFiles.setAttribute("aria-describedby", "collaboration-file-page-status");
    newerFiles.setAttribute("data-command", "collaboration.file.newer");
    newerFiles.addEventListener("click", function () {
      invokeCollaboration(invoke, "collaboration.file.newer", {}, wrapper, announce, fallbackMessage);
    });
    fileSection.appendChild(newerFiles);

    const fileItems = Array.isArray(files.items) ? files.items : [];
    if (!fileItems.length) {
      fileSection.appendChild(node("p", files.empty_message || ""));
    } else {
      const list = node("ul");
      list.id = "collaboration-file-list";
      fileItems.forEach(function (file) {
        const item = node("li");
        item.id = String(file.dom_id || "");
        item.tabIndex = -1;
        const fileName = node("strong");
        const fileNameText = node("bdi", file.name || "");
        fileNameText.setAttribute("dir", "auto");
        fileName.appendChild(fileNameText);
        item.appendChild(fileName);
        if (file.sender) {
          item.appendChild(document.createTextNode(" — "));
          const fileSender = node("bdi", file.sender);
          fileSender.setAttribute("dir", "auto");
          item.appendChild(fileSender);
        }
        [
          file.size_label,
          file.type_label,
          file.status_label,
          file.scan_label,
          file.retention_label
        ].forEach(function (value) {
          if (!value) return;
          item.appendChild(document.createTextNode(" — "));
          item.appendChild(node("span", value));
        });
        if (file.can_save) {
          const save = node("button", files.save_label || "Save");
          save.id = item.id + "-save";
          save.type = "button";
          save.setAttribute(
            "aria-label",
            (files.save_label || "Save") + ": " + String(file.name || "")
          );
          save.setAttribute("data-command", "collaboration.file.save");
          save.addEventListener("click", function () {
            invokeCollaboration(
              invoke,
              "collaboration.file.save",
              { file_key: file.file_key },
              wrapper,
              announce,
              fallbackMessage,
              { pendingAnnouncement: files.save_pending_label || "" }
            );
          });
          item.appendChild(save);
        }
        if (file.can_open) {
          const open = node("button", files.open_label || "Open");
          open.id = item.id + "-open";
          open.type = "button";
          open.setAttribute(
            "aria-label",
            (files.open_label || "Open") + ": " + String(file.name || "")
          );
          open.setAttribute("data-command", "collaboration.file.open");
          open.addEventListener("click", function () {
            invokeCollaboration(
              invoke,
              "collaboration.file.open",
              { file_key: file.file_key },
              wrapper,
              announce,
              fallbackMessage,
              { pendingAnnouncement: files.open_pending_label || "" }
            );
          });
          item.appendChild(open);
        }
        if (file.can_retry) {
          const retry = node("button", files.retry_label || "Retry");
          retry.id = item.id + "-retry";
          retry.type = "button";
          retry.setAttribute(
            "aria-label",
            (files.retry_label || "Retry") + ": " + String(file.name || "")
          );
          retry.setAttribute("data-command", "collaboration.file.retry");
          retry.addEventListener("click", function () {
            invokeCollaboration(
              invoke,
              "collaboration.file.retry",
              { file_key: file.file_key },
              wrapper,
              announce,
              fallbackMessage,
              { pendingAnnouncement: files.retry_pending_label || "" }
            );
          });
          item.appendChild(retry);
        }
        if (file.can_cancel) {
          const cancel = node("button", files.cancel_label || "Cancel");
          cancel.id = item.id + "-cancel";
          cancel.type = "button";
          cancel.setAttribute(
            "aria-label",
            (files.cancel_label || "Cancel") + ": " + String(file.name || "")
          );
          cancel.setAttribute("data-command", "collaboration.file.cancel");
          cancel.addEventListener("click", function () {
            invokeCollaboration(
              invoke,
              "collaboration.file.cancel",
              { file_key: file.file_key },
              wrapper,
              announce,
              fallbackMessage,
              { pendingAnnouncement: files.cancel_pending_label || "" }
            );
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
