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

  function uiText(language, uk, en) {
    return language === "en" ? en : uk;
  }

  function safeId(value) {
    const token = String(value || "");
    return /^[A-Za-z0-9_-]{1,160}$/.test(token) ? token : "";
  }

  const MAX_DEVICE_ID_LENGTH = 512;
  const DEVICE_CONTROLS = Object.freeze([
    Object.freeze({ kind: "microphone", mediaKind: "audioinput" }),
    Object.freeze({ kind: "speaker", mediaKind: "audiooutput" }),
    Object.freeze({ kind: "camera", mediaKind: "videoinput" })
  ]);

  const selectedDeviceIds = Object.create(null);

  function safeDeviceId(value) {
    return typeof value === "string" &&
      value.length > 0 &&
      value.length <= MAX_DEVICE_ID_LENGTH &&
      !/[\u0000-\u001f\u007f]/.test(value) ? value : "";
  }

  function safeDeviceLabel(value, fallback) {
    const text = typeof value === "string" ? value.trim() : "";
    return text &&
      text.length <= 160 &&
      !/[\u0000-\u001f\u007f]/.test(text) ? text : fallback;
  }

  function deviceKindLabel(kind, language) {
    if (kind === "microphone") return uiText(language, "Мікрофон", "Microphone");
    if (kind === "speaker") return uiText(language, "Динаміки", "Speakers");
    return uiText(language, "Камера", "Camera");
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

  function actionButton(action, invoke, announce, root, language) {
    if (!action || typeof action !== "object") return null;
    const command = String(action.command || "");
    if (!/^media\.[a-z_]+$/.test(command)) return null;
    const button = node("button", action.label || "");
    button.type = "button";
    const id = safeId(action.id);
    if (id) button.id = id;
    button.addEventListener("click", function () {
      button.disabled = true;
      Promise.resolve().then(function () {
        return invoke(command, action.payload || {});
      }).then(function (result) {
        if (!result || typeof result !== "object") {
          throw new TypeError("classroom media result must be an object");
        }
        // Structured error events keep the current DOM. Re-enable before
        // applyEvent() so focus recovery can target the same native button.
        // Successful events may replace the button during applyEvent().
        if (button.isConnected) button.disabled = false;
        applyEvent(root, result, invoke, announce, language);
      }).catch(function () {
        if (button.isConnected) {
          button.disabled = false;
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
        if (button.isConnected) button.disabled = false;
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

  function renderDeviceControls(snapshot, invoke, announce, root, language) {
    if (!snapshot || snapshot.connected !== true) {
      DEVICE_CONTROLS.forEach(function (definition) {
        delete selectedDeviceIds[definition.kind];
      });
      return null;
    }

    const section = node("section");
    const heading = node(
      "h3",
      uiText(language, "Аудіо- й відеопристрої", "Audio and video devices")
    );
    heading.id = "classroom-media-devices-heading";
    heading.tabIndex = -1;
    section.setAttribute("aria-labelledby", heading.id);
    section.appendChild(heading);

    const status = node(
      "p",
      uiText(language, "Пошук доступних пристроїв…", "Finding available devices…")
    );
    status.id = "classroom-media-devices-status";
    status.setAttribute("aria-live", "off");
    section.appendChild(status);

    const controls = node("div");
    controls.id = "classroom-media-device-controls";
    section.appendChild(controls);

    const selectors = Object.create(null);

    function moveFocusBeforeDisable(select) {
      const owner = select && select.ownerDocument;
      if (
        owner &&
        owner.activeElement === select &&
        typeof heading.focus === "function"
      ) {
        heading.focus({ preventScroll: true });
      }
    }

    DEVICE_CONTROLS.forEach(function (definition) {
      const labelText = deviceKindLabel(definition.kind, language);
      const label = node("label", labelText);
      const select = node("select");
      select.id = "classroom-media-device-" + definition.kind;
      // Keep the placeholder focusable while enumeration is pending so a
      // post-mutation focus target survives the synchronous section rerender.
      select.disabled = false;
      label.setAttribute("for", select.id);

      const placeholder = node(
        "option",
        uiText(language, "Оберіть: ", "Choose: ") + labelText
      );
      placeholder.value = "";
      select.appendChild(placeholder);
      select.value = "";

      select.addEventListener("change", function () {
        const deviceId = safeDeviceId(select.value);
        if (!deviceId || select.disabled) return;
        select.disabled = true;
        Promise.resolve().then(function () {
          return invoke("media.recover_device", {
            kind: definition.kind,
            device_id: deviceId
          });
        }).then(function (result) {
          if (!result || typeof result !== "object") {
            throw new TypeError("classroom media result must be an object");
          }
          if (result.kind !== "error") {
            selectedDeviceIds[definition.kind] = deviceId;
          }
          if (select.isConnected) select.disabled = false;
          applyEvent(root, result, invoke, announce, language);
        }).catch(function () {
          if (select.isConnected) {
            select.disabled = false;
            if (typeof select.focus === "function") {
              select.focus({ preventScroll: true });
            }
          }
          announce(uiText(
            language,
            "Не вдалося змінити медіапристрій.",
            "Could not change media device."
          ));
        }).finally(function () {
          if (select.isConnected && select.children.length > 1) {
            select.disabled = false;
          }
        });
      });

      selectors[definition.kind] = select;
      controls.appendChild(label);
      controls.appendChild(select);
    });

    const mediaDevices = global.navigator && global.navigator.mediaDevices;
    if (!mediaDevices || typeof mediaDevices.enumerateDevices !== "function") {
      status.textContent = uiText(
        language,
        "Вибір пристроїв недоступний у цьому середовищі.",
        "Device selection is unavailable in this environment."
      );
      return section;
    }

    function renderChoices(devices) {
      DEVICE_CONTROLS.forEach(function (definition) {
        const select = selectors[definition.kind];
        const previous = safeDeviceId(selectedDeviceIds[definition.kind]);
        const labelText = deviceKindLabel(definition.kind, language);
        select.textContent = "";
        select.value = "";

        const placeholder = node(
          "option",
          uiText(language, "Оберіть: ", "Choose: ") + labelText
        );
        placeholder.value = "";
        select.appendChild(placeholder);

        let count = 0;
        let previousAvailable = false;
        devices.forEach(function (device) {
          if (!device || device.kind !== definition.mediaKind) return;
          const deviceId = safeDeviceId(device.deviceId);
          if (!deviceId) return;
          count += 1;
          const option = node(
            "option",
            safeDeviceLabel(
              device.label,
              labelText + " " + String(count)
            )
          );
          option.value = deviceId;
          select.appendChild(option);
          if (previous && previous === deviceId) previousAvailable = true;
        });

        if (count === 0) {
          delete selectedDeviceIds[definition.kind];
          moveFocusBeforeDisable(select);
          select.disabled = true;
          const missing = node(
            "option",
            uiText(language, "Пристроїв не знайдено", "No devices found")
          );
          missing.value = "";
          select.appendChild(missing);
        } else {
          select.disabled = false;
          if (previousAvailable) {
            select.value = previous;
          } else {
            delete selectedDeviceIds[definition.kind];
            select.value = "";
          }
        }
      });
      status.textContent = uiText(
        language,
        "Оберіть пристрій. Активний мікрофон або камера залишаться увімкненими лише за поточним дозволом заняття.",
        "Choose a device. An active microphone or camera stays published only under the current classroom permission."
      );
    }

    function refreshDevices(announceFailure) {
      refresh.disabled = true;
      return Promise.resolve().then(function () {
        return mediaDevices.enumerateDevices();
      }).then(function (devices) {
        if (!Array.isArray(devices)) {
          throw new TypeError("media device list must be an array");
        }
        renderChoices(devices);
      }).catch(function () {
        DEVICE_CONTROLS.forEach(function (definition) {
          const select = selectors[definition.kind];
          moveFocusBeforeDisable(select);
          select.disabled = true;
        });
        status.textContent = uiText(
          language,
          "Не вдалося отримати список медіапристроїв.",
          "Could not list media devices."
        );
        if (announceFailure) announce(status.textContent);
      }).finally(function () {
        if (refresh.isConnected) refresh.disabled = false;
      });
    }

    const refresh = node(
      "button",
      uiText(language, "Оновити список пристроїв", "Refresh device list")
    );
    refresh.type = "button";
    refresh.id = "classroom-media-device-refresh";
    refresh.addEventListener("click", function () {
      refreshDevices(true);
    });
    section.appendChild(refresh);
    refreshDevices(false);
    return section;
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

    if (!snapshot || typeof snapshot !== "object") {
      const recoveryRequired = availability &&
        typeof availability === "object" &&
        availability.recovery_required === true;
      section.appendChild(node("p", uiText(
        language,
        recoveryRequired
          ? "Керування медіа тимчасово недоступне. Шахова дошка й дані заняття залишаються доступними без відео."
          : "Медіазв’язок ще не налаштовано для цієї збірки. Шахова дошка й дані заняття залишаються доступними без відео.",
        recoveryRequired
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

    const devices = renderDeviceControls(snapshot, invoke, announce, root, language);
    if (devices) section.appendChild(devices);

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

  function applyEvent(root, result, invoke, announce, language) {
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
    apply: applyEvent
  });
})(window);
