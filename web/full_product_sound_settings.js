(function (global) {
  "use strict";

  if (global.__accessibleChessSoundSettingsInstalled) return;
  global.__accessibleChessSoundSettingsInstalled = true;

  const documentRef = global.document;
  const heading = documentRef.getElementById("h-settings");
  const live = documentRef.getElementById("live");
  if (!heading || !heading.parentNode) return;

  function api() {
    return global.pywebview && global.pywebview.api;
  }

  function language() {
    return documentRef.documentElement.lang === "en" ? "en" : "uk";
  }

  function text(uk, en) {
    return language() === "en" ? en : uk;
  }

  function announce(message) {
    if (!live || !message) return;
    live.textContent = "";
    global.setTimeout(function () {
      live.textContent = String(message).slice(0, 300);
    }, 20);
  }

  const root = documentRef.createElement("fieldset");
  root.id = "sound-profile-settings";
  root.setAttribute("aria-busy", "false");
  const legend = documentRef.createElement("legend");
  legend.id = "sound-profile-settings-heading";
  root.appendChild(legend);

  const status = documentRef.createElement("p");
  status.id = "sound-profile-settings-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  root.appendChild(status);

  const masterEnabled = documentRef.createElement("input");
  masterEnabled.type = "checkbox";
  masterEnabled.id = "sound-master-enabled";
  const masterEnabledLabel = documentRef.createElement("label");
  masterEnabledLabel.setAttribute("for", masterEnabled.id);
  root.appendChild(masterEnabled);
  root.appendChild(masterEnabledLabel);

  const masterVolumeLabel = documentRef.createElement("label");
  masterVolumeLabel.setAttribute("for", "sound-master-volume");
  const masterVolume = documentRef.createElement("input");
  masterVolume.type = "number";
  masterVolume.id = "sound-master-volume";
  masterVolume.min = "0";
  masterVolume.max = "100";
  masterVolume.step = "5";
  masterVolume.inputMode = "numeric";
  root.appendChild(masterVolumeLabel);
  root.appendChild(masterVolume);

  const eventHeading = documentRef.createElement("h3");
  eventHeading.id = "sound-events-heading";
  root.appendChild(eventHeading);
  const eventList = documentRef.createElement("div");
  eventList.id = "sound-events-list";
  eventList.setAttribute("aria-labelledby", eventHeading.id);
  root.appendChild(eventList);

  heading.parentNode.appendChild(root);

  let currentSnapshot = null;
  let busy = false;

  function setBusy(value) {
    busy = !!value;
    root.setAttribute("aria-busy", busy ? "true" : "false");
    render(currentSnapshot);
  }

  function clampVolume(value) {
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed < 0 || parsed > 100) return null;
    return parsed;
  }

  function invoke(command, payload) {
    const bridge = api();
    if (busy || !bridge || typeof bridge.sound_settings_command !== "function") {
      announce(text("Налаштування звуку недоступні.", "Sound settings are unavailable."));
      return Promise.resolve(false);
    }
    setBusy(true);
    return bridge.sound_settings_command(command, payload || {}).then(function (result) {
      if (!result || result.ok !== true || !result.snapshot) {
        announce(result && result.message ? result.message :
          text("Не вдалося застосувати налаштування звуку.", "Sound settings could not be applied."));
        return false;
      }
      currentSnapshot = result.snapshot;
      render(currentSnapshot);
      announce(result.message || "");
      return true;
    }, function () {
      announce(text("Не вдалося застосувати налаштування звуку.", "Sound settings could not be applied."));
      return false;
    }).finally(function () {
      setBusy(false);
    });
  }

  function eventRow(item, writesBlocked) {
    const eventId = String(item.event_id || "");
    const safeId = eventId.replace(/[^a-z0-9_-]/g, "-");
    const group = documentRef.createElement("fieldset");
    group.className = "sound-event";
    const groupLegend = documentRef.createElement("legend");
    groupLegend.textContent = String(item.label || eventId);
    group.appendChild(groupLegend);

    const enabled = documentRef.createElement("input");
    enabled.type = "checkbox";
    enabled.id = "sound-event-" + safeId + "-enabled";
    enabled.checked = item.enabled === true;
    enabled.disabled = writesBlocked || busy;
    const enabledLabel = documentRef.createElement("label");
    enabledLabel.setAttribute("for", enabled.id);
    enabledLabel.textContent = text("Увімкнено", "Enabled");
    enabled.addEventListener("change", function () {
      invoke("set_event", {event_id: eventId, enabled: enabled.checked});
    });
    group.appendChild(enabled);
    group.appendChild(enabledLabel);

    const volumeLabel = documentRef.createElement("label");
    volumeLabel.setAttribute("for", "sound-event-" + safeId + "-volume");
    volumeLabel.textContent = text("Гучність, відсотків", "Volume, percent");
    const volume = documentRef.createElement("input");
    volume.type = "number";
    volume.id = "sound-event-" + safeId + "-volume";
    volume.min = "0";
    volume.max = "100";
    volume.step = "5";
    volume.inputMode = "numeric";
    volume.value = String(item.volume_percent);
    volume.disabled = writesBlocked || busy;
    volume.addEventListener("change", function () {
      const value = clampVolume(volume.value);
      if (value === null) {
        volume.value = String(item.volume_percent);
        announce(text("Гучність має бути від 0 до 100.", "Volume must be from 0 to 100."));
        return;
      }
      invoke("set_event", {event_id: eventId, volume_percent: value});
    });
    group.appendChild(volumeLabel);
    group.appendChild(volume);

    const preview = documentRef.createElement("button");
    preview.type = "button";
    preview.id = "sound-event-" + safeId + "-preview";
    preview.textContent = text("Прослухати", "Preview");
    preview.disabled = busy;
    preview.addEventListener("click", function () {
      invoke("preview", {event_id: eventId});
    });
    group.appendChild(preview);

    const effective = documentRef.createElement("span");
    effective.id = "sound-event-" + safeId + "-effective";
    effective.textContent = " " + text("Ефективна гучність: ", "Effective volume: ") +
      String(item.effective_volume) + "%";
    group.appendChild(effective);
    return group;
  }

  function render(snapshot) {
    legend.textContent = text("Звуки", "Sounds");
    masterEnabledLabel.textContent = text("Увімкнути звуки", "Enable sounds");
    masterVolumeLabel.textContent = text("Загальна гучність, відсотків", "Master volume, percent");
    eventHeading.textContent = text("Події", "Events");

    if (!snapshot || typeof snapshot !== "object") {
      status.textContent = text("Завантаження налаштувань звуку.", "Loading sound settings.");
      masterEnabled.disabled = true;
      masterVolume.disabled = true;
      eventList.replaceChildren();
      return;
    }

    const writesBlocked = snapshot.writes_blocked === true;
    status.textContent = writesBlocked
      ? text(
          "Цей профіль створено новішою версією. Зміни заблоковано, щоб не пошкодити дані.",
          "This profile was created by a newer version. Changes are blocked to protect the data."
        )
      : text(
          "Активний набір: " + String(snapshot.active_pack_id || "classic") + ".",
          "Active pack: " + String(snapshot.active_pack_id || "classic") + "."
        );
    masterEnabled.checked = snapshot.master_enabled === true;
    masterEnabled.disabled = writesBlocked || busy;
    masterVolume.value = String(snapshot.master_volume_percent);
    masterVolume.disabled = writesBlocked || busy;

    const fragment = documentRef.createDocumentFragment();
    const events = Array.isArray(snapshot.events) ? snapshot.events : [];
    events.forEach(function (item) {
      if (item && typeof item === "object") fragment.appendChild(eventRow(item, writesBlocked));
    });
    eventList.replaceChildren(fragment);
  }

  masterEnabled.addEventListener("change", function () {
    invoke("set_master", {enabled: masterEnabled.checked});
  });

  masterVolume.addEventListener("change", function () {
    const value = clampVolume(masterVolume.value);
    if (value === null) {
      if (currentSnapshot) masterVolume.value = String(currentSnapshot.master_volume_percent);
      announce(text("Гучність має бути від 0 до 100.", "Volume must be from 0 to 100."));
      return;
    }
    invoke("set_master", {volume_percent: value});
  });

  function refresh() {
    const bridge = api();
    if (!bridge || typeof bridge.sound_settings_snapshot !== "function") {
      render(null);
      return Promise.resolve(false);
    }
    return bridge.sound_settings_snapshot().then(function (result) {
      if (!result || result.ok !== true || !result.snapshot) {
        status.textContent = result && result.message ? result.message :
          text("Налаштування звуку недоступні.", "Sound settings are unavailable.");
        return false;
      }
      currentSnapshot = result.snapshot;
      render(currentSnapshot);
      return true;
    }, function () {
      status.textContent = text("Налаштування звуку недоступні.", "Sound settings are unavailable.");
      return false;
    });
  }

  if (global.MutationObserver) {
    new global.MutationObserver(function (records) {
      if (records.some(function (record) { return record.attributeName === "lang"; })) refresh();
    }).observe(documentRef.documentElement, {attributes: true, attributeFilter: ["lang"]});
  }

  global.AccessibleChessSoundSettingsSurface = Object.freeze({refresh: refresh});
  render(null);
  refresh();
})(window);
