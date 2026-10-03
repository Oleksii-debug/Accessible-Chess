(function (global) {
  "use strict";

  let providerRuntime = null;

  function requireFunction(value, name) {
    if (typeof value !== "function") throw new TypeError(name + " must be a function");
    return value;
  }

  function mediaProviderRuntime(invoke) {
    if (providerRuntime) return providerRuntime;
    const module = global.AccessibleChessClassroomMediaProviderRuntime;
    if (!module || typeof module.ClassroomMediaProviderRuntime !== "function") {
      throw new TypeError("classroom media provider runtime is unavailable");
    }
    providerRuntime = new module.ClassroomMediaProviderRuntime({ invoke: invoke });
    return providerRuntime;
  }

  function providerTransactionId(result) {
    const payload = result && typeof result === "object" &&
      result.payload && typeof result.payload === "object"
      ? result.payload
      : {};
    const value = payload.transaction_id;
    return typeof value === "string" &&
      /^(?:host|session)-[0-9a-f]{32}$/.test(value)
      ? value
      : "";
  }

  function retireUnstartedProvider(result, invoke) {
    const transactionId = providerTransactionId(result);
    if (!transactionId) {
      return Promise.reject(new TypeError("classroom media transaction is invalid"));
    }
    return Promise.resolve().then(function () {
      return invoke(
        "media.provider_not_started",
        { transaction_id: transactionId }
      );
    });
  }

  function settleProviderEvent(result, invoke) {
    if (!result || typeof result !== "object") {
      return Promise.reject(new TypeError("classroom media result must be an object"));
    }
    if (result.kind !== "provider-dispatch") return Promise.resolve(result);
    let settlement;
    try {
      settlement = mediaProviderRuntime(invoke).settle(result);
    } catch (_error) {
      return retireUnstartedProvider(result, invoke);
    }
    return Promise.resolve(settlement).catch(function () {
      // A rejected runtime before it can establish/retire the provider boundary
      // must not strand the canonical Python lease. Runtime-internal
      // post-boundary failures return a recovery terminal instead of rejecting.
      return retireUnstartedProvider(result, invoke);
    });
  }

  function node(tag, text) {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function uiText(language, uk, en) {
    return language === "en" ? en : uk;
  }

  function safeId(value) {
    const token = String(value || "");
    return /^[A-Za-z0-9_-]{1,160}$/.test(token) ? token : "";
  }

  function focusById(root, id) {
    const targetId = safeId(id);
    if (!targetId) return;
    const candidates = root.querySelectorAll("[id]");
    for (let index = 0; index < candidates.length; index += 1) {
      const candidate = candidates[index];
      if (candidate.id === targetId && typeof candidate.focus === "function") {
        candidate.focus({ preventScroll: true });
        return;
      }
    }
  }

  function setMediaActionButtonsDisabled(root, disabled) {
    if (!root || typeof root.querySelector !== "function") return;
    const section = root.querySelector("#classroom-media-section");
    if (!section || typeof section.querySelectorAll !== "function") return;
    const buttons = section.querySelectorAll("button");
    for (let index = 0; index < buttons.length; index += 1) {
      buttons[index].disabled = disabled === true;
    }
  }

  function actionButton(action, invoke, announce, root, language) {
    if (!action || typeof action !== "object") return null;
    const command = String(action.command || "");
    if (!/^media\.[a-z_]+$/.test(command)) return null;
    const button = node("button", action.label || "");
    button.type = "button";
    const id = safeId(action.id);
    if (id) button.id = id;
    button.addEventListener("click", function () {
      // The Python provider arbiter owns one global mutation lease. Mirror that
      // contract in the accessible DOM so keyboard/screen-reader users cannot
      // activate a second media action that is guaranteed to be rejected while
      // the first provider transaction is still settling.
      setMediaActionButtonsDisabled(root, true);
      Promise.resolve().then(function () {
        return invoke(command, action.payload || {});
      }).then(function (result) {
        // Keep the initiating native button disabled across the complete
        // provider transaction, including moderation chunk chains. Re-enable
        // only after a terminal event exists so duplicate click/retry cannot
        // race the sole global provider lease.
        return settleProviderEvent(result, invoke).then(function (terminal) {
          setMediaActionButtonsDisabled(root, false);
          applyTerminalEvent(root, terminal, invoke, announce, language);
          return terminal;
        });
      }).catch(function () {
        setMediaActionButtonsDisabled(root, false);
        if (button.isConnected) {
          if (typeof button.focus === "function") {
            button.focus({ preventScroll: true });
          }
        }
        announce(uiText(
          language,
          "Не вдалося змінити стан медіа.",
          "Could not change media state."
        ));
      }).finally(function () {
        setMediaActionButtonsDisabled(root, false);
      });
    });
    return button;
  }

  function appendActions(host, actions, invoke, announce, root, language) {
    const list = Array.isArray(actions) ? actions : [];
    list.forEach(function (action) {
      const button = actionButton(action, invoke, announce, root, language);
      if (button) host.appendChild(button);
    });
  }

  function renderParticipant(item, invoke, announce, root, language) {
    const row = node("li");
    const id = safeId(item && item.dom_id);
    if (id) {
      row.id = id;
      // Programmatic recovery target only; do not add every participant row
      // to the normal Tab order.
      row.tabIndex = -1;
    }
    const heading = node("h3", item && item.label || "");
    row.appendChild(heading);
    row.appendChild(node("p", item && item.summary || ""));
    appendActions(row, item && item.actions, invoke, announce, root, language);
    return row;
  }

  function renderSection(snapshot, invoke, announce, root, language, availability) {
    const section = node("section");
    section.id = "classroom-media-section";
    section.setAttribute("aria-labelledby", "classroom-media-heading");

    const documentState = snapshot && typeof snapshot === "object"
      ? (snapshot.document || {})
      : {};
    const heading = node(
      "h2",
      documentState.heading || uiText(language, "Аудіо та відео заняття", "Lesson audio and video")
    );
    heading.id = "classroom-media-heading";
    // Programmatic recovery target only; normal heading navigation remains
    // semantic and this does not add the heading to the Tab order.
    heading.tabIndex = -1;
    section.appendChild(heading);

    const recoveryRequired = availability &&
      typeof availability === "object" &&
      availability.recovery_required === true;
    const transactionActive = availability &&
      typeof availability === "object" &&
      availability.transaction_active === true;
    if (
      !snapshot ||
      typeof snapshot !== "object" ||
      recoveryRequired ||
      transactionActive
    ) {
      section.appendChild(node("p", uiText(
        language,
        transactionActive
          ? "Оновлення медіа виконується. Керування тимчасово недоступне до завершення операції."
          : recoveryRequired
            ? "Керування медіа тимчасово недоступне. Шахова дошка й дані заняття залишаються доступними без відео."
            : "Медіазв’язок ще не налаштовано для цієї збірки. Шахова дошка й дані заняття залишаються доступними без відео.",
        transactionActive
          ? "A media update is in progress. Controls are temporarily unavailable until it completes."
          : recoveryRequired
            ? "Media controls are temporarily unavailable. The chess board and lesson data remain available without video."
            : "Realtime media is not configured for this build yet. The chess board and lesson data remain available without video."
      )));
      return section;
    }

    const connection = node("p", snapshot.connection_text || "");
    connection.id = "classroom-media-connection";
    connection.setAttribute("aria-live", "off");
    section.appendChild(connection);

    const own = snapshot.own && typeof snapshot.own === "object" ? snapshot.own : null;
    if (own) {
      const ownSection = node("section");
      const ownHeading = node("h3", snapshot.own_heading || "");
      ownHeading.id = "classroom-media-own-heading";
      ownSection.setAttribute("aria-labelledby", ownHeading.id);
      ownSection.appendChild(ownHeading);
      ownSection.appendChild(node("p", own.summary || ""));
      appendActions(ownSection, own.actions, invoke, announce, root, language);
      section.appendChild(ownSection);
    }

    const participants = Array.isArray(snapshot.participants) ? snapshot.participants : [];
    const participantSection = node("section");
    const participantHeading = node("h3", snapshot.participants_heading || "");
    participantHeading.id = "classroom-media-participants-heading";
    participantSection.setAttribute("aria-labelledby", participantHeading.id);
    participantSection.appendChild(participantHeading);
    const list = node("ul");
    participants.forEach(function (item) {
      list.appendChild(renderParticipant(item || {}, invoke, announce, root, language));
    });
    participantSection.appendChild(list);
    section.appendChild(participantSection);

    const allActions = Array.isArray(snapshot.all_student_actions)
      ? snapshot.all_student_actions
      : [];
    if (allActions.length) {
      const moderation = node("section");
      const moderationHeading = node("h3", snapshot.teacher_controls_heading || "");
      moderationHeading.id = "classroom-media-teacher-controls-heading";
      moderation.setAttribute("aria-labelledby", moderationHeading.id);
      moderation.appendChild(moderationHeading);
      appendActions(moderation, allActions, invoke, announce, root, language);
      section.appendChild(moderation);
    }
    return section;
  }

  function applyTerminalEvent(root, result, invoke, announce, language) {
    if (!root || !result || typeof result !== "object") return;
    const payload = result.payload && typeof result.payload === "object" ? result.payload : {};
    if (Object.prototype.hasOwnProperty.call(payload, "snapshot")) {
      const current = root.querySelector("#classroom-media-section");
      if (current && typeof current.replaceWith === "function") {
        current.replaceWith(renderSection(
          payload.snapshot,
          invoke,
          announce,
          root,
          language,
          { recovery_required: payload.recovery_required === true }
        ));
      }
    }
    if (payload.announcement) announce(String(payload.announcement));
    if (result.kind === "error" && payload.message) announce(String(payload.message));
    focusById(root, payload.focus_target || "");
  }

  function applyEvent(root, result, invoke, announce, language) {
    return settleProviderEvent(result, invoke).then(function (terminal) {
      applyTerminalEvent(root, terminal, invoke, announce, language);
      return terminal;
    });
  }

  function executeProvider(result, invoke) {
    requireFunction(invoke, "classroom media invoke");
    return settleProviderEvent(result, invoke);
  }

  function mount(root, snapshot, invoke, announce, language, availability) {
    if (!root || typeof root.appendChild !== "function") {
      throw new TypeError("classroom media root must support appendChild");
    }
    requireFunction(invoke, "classroom media invoke");
    announce = announce == null ? function () {} : requireFunction(announce, "classroom media announce");
    const existing = root.querySelector("#classroom-media-section");
    const section = renderSection(
      snapshot,
      invoke,
      announce,
      root,
      language === "en" ? "en" : "uk",
      availability || null
    );
    if (existing && typeof existing.replaceWith === "function") {
      existing.replaceWith(section);
    } else {
      const main = root.querySelector("main");
      (main || root).appendChild(section);
    }
  }

  global.AccessibleChessClassroomMediaSurface = Object.freeze({
    mount: mount,
    apply: applyEvent,
    executeProvider: executeProvider
  });
})(window);
