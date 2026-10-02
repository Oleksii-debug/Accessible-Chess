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

  let soundDispatchCounter = 1000000000;

  function announce(message, explicitAction) {
    if (!message) return;
    const textValue = String(message).slice(0, 300);
    if (
      explicitAction &&
      global.AccessibleChessP0Runtime &&
      typeof global.AccessibleChessP0Runtime.exposeAnnouncement === "function"
    ) {
      soundDispatchCounter += 1;
      global.AccessibleChessP0Runtime.exposeAnnouncement(textValue, soundDispatchCounter);
      return;
    }
    if (typeof global.announce === "function") {
      global.announce(textValue);
      return;
    }
    if (!live) return;
    live.textContent = "";
    global.setTimeout(function () {
      live.textContent = textValue;
    }, 20);
  }

  function setStatus(message) {
    const next = String(message || "");
    if (status.textContent !== next) status.textContent = next;
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
  masterVolume.step = "1";
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

  const packHeading = documentRef.createElement("h3");
  packHeading.id = "sound-packs-heading";
  root.appendChild(packHeading);
  const packStatus = documentRef.createElement("p");
  packStatus.id = "sound-packs-status";
  root.appendChild(packStatus);
  const packList = documentRef.createElement("div");
  packList.id = "sound-packs-list";
  packList.setAttribute("aria-labelledby", packHeading.id);
  root.appendChild(packList);

  heading.parentNode.appendChild(root);

  let currentSnapshot = null;
  let busy = false;
  let eventControls = [];
  let packControls = [];

  function writesBlocked() {
    return !!(currentSnapshot && currentSnapshot.writes_blocked === true);
  }

  function setBusy(value) {
    busy = !!value;
    root.setAttribute("aria-busy", busy ? "true" : "false");
    masterEnabled.disabled = busy || writesBlocked();
    masterVolume.disabled = busy || writesBlocked();
    eventControls.forEach(function (entry) {
      entry.control.disabled = busy || (writesBlocked() && entry.mutation);
    });
    packControls.forEach(function (entry) {
      entry.control.disabled = busy || (writesBlocked() && entry.mutation);
    });
  }

  function restoreFocus(id, fallbackId) {
    const target = (id && documentRef.getElementById(id)) ||
      (fallbackId && documentRef.getElementById(fallbackId));
    if (target && typeof target.focus === "function") target.focus();
  }

  function clampVolume(value) {
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed < 0 || parsed > 100) return null;
    return parsed;
  }

  function restoreConfirmedSnapshot() {
    if (currentSnapshot && typeof currentSnapshot === "object") render(currentSnapshot);
  }

  function invoke(command, payload, restoreFocusFallbackId) {
    const active = documentRef.activeElement;
    const restoreFocusId = active && typeof active.id === "string" ? active.id : "";
    const bridge = api();
    if (busy || !bridge || typeof bridge.sound_settings_command !== "function") {
      restoreConfirmedSnapshot();
      announce(text("Налаштування звуку недоступні.", "Sound settings are unavailable."), true);
      return Promise.resolve(false);
    }
    setBusy(true);
    return bridge.sound_settings_command(command, payload || {}).then(function (result) {
      if (!result || result.ok !== true || !result.snapshot) {
        restoreConfirmedSnapshot();
        announce(result && result.message ? result.message :
          text("Не вдалося застосувати налаштування звуку.", "Sound settings could not be applied."), true);
        return false;
      }
      currentSnapshot = result.snapshot;
      render(currentSnapshot);
      announce(result.message || "", true);
      return true;
    }, function () {
      restoreConfirmedSnapshot();
      announce(text("Не вдалося застосувати налаштування звуку.", "Sound settings could not be applied."), true);
      return false;
    }).finally(function () {
      setBusy(false);
      restoreFocus(restoreFocusId, restoreFocusFallbackId);
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
    eventControls.push({control: enabled, mutation: true});

    const volumeLabel = documentRef.createElement("label");
    volumeLabel.setAttribute("for", "sound-event-" + safeId + "-volume");
    volumeLabel.textContent = text("Гучність, відсотків", "Volume, percent");
    const volume = documentRef.createElement("input");
    volume.type = "number";
    volume.id = "sound-event-" + safeId + "-volume";
    volume.min = "0";
    volume.max = "100";
    volume.step = "1";
    volume.inputMode = "numeric";
    volume.value = String(item.volume_percent);
    volume.disabled = writesBlocked || busy;
    volume.addEventListener("change", function () {
      const value = clampVolume(volume.value);
      if (value === null) {
        volume.value = String(item.volume_percent);
        announce(text("Гучність має бути від 0 до 100.", "Volume must be from 0 to 100."), true);
        return;
      }
      invoke("set_event", {event_id: eventId, volume_percent: value});
    });
    group.appendChild(volumeLabel);
    group.appendChild(volume);
    eventControls.push({control: volume, mutation: true});

    const preview = documentRef.createElement("button");
    preview.type = "button";
    preview.id = "sound-event-" + safeId + "-preview";
    preview.textContent = text("Прослухати", "Preview");
    preview.disabled = busy;
    preview.addEventListener("click", function () {
      invoke("preview", {event_id: eventId});
    });
    group.appendChild(preview);
    eventControls.push({control: preview, mutation: false});

    const effective = documentRef.createElement("span");
    effective.id = "sound-event-" + safeId + "-effective";
    effective.textContent = " " + text("Ефективна гучність: ", "Effective volume: ") +
      String(item.effective_volume) + "%";
    group.appendChild(effective);
    return group;
  }

  function packRow(item, writesBlocked) {
    const packId = String(item.pack_id || "");
    const safeId = packId.replace(/[^a-z0-9_-]/g, "-");
    const group = documentRef.createElement("fieldset");
    group.className = "sound-pack";
    group.id = "sound-pack-" + safeId;
    group.tabIndex = -1;
    const groupLegend = documentRef.createElement("legend");
    groupLegend.textContent = String(item.title || packId);
    group.appendChild(groupLegend);

    const metadata = documentRef.createElement("p");
    metadata.id = "sound-pack-" + safeId + "-metadata";
    const installed = item.installed_version == null
      ? text("не встановлено", "not installed")
      : text("встановлено ", "installed ") + String(item.installed_version);
    metadata.textContent =
      text("Версія ", "Version ") + String(item.version || "") + ". " +
      text("Автор: ", "Author: ") + String(item.author || "") + ". " +
      text("Ліцензія: ", "License: ") + String(item.license_id || "") + ". " +
      installed + ".";
    group.appendChild(metadata);

    if (item.active === true) {
      const active = documentRef.createElement("p");
      active.id = "sound-pack-" + safeId + "-active";
      active.textContent = text("Активний набір.", "Active pack.");
      group.appendChild(active);
    }

    if (item.installed_version != null && item.active !== true) {
      const select = documentRef.createElement("button");
      select.type = "button";
      select.id = "sound-pack-" + safeId + "-select";
      select.textContent = text("Використовувати", "Use this pack");
      select.disabled = writesBlocked || busy;
      select.addEventListener("click", function () {
        invoke("select_pack", {pack_id: packId}, group.id);
      });
      group.appendChild(select);
      packControls.push({control: select, mutation: true});
    }

    if (item.can_install === true) {
      const install = documentRef.createElement("button");
      install.type = "button";
      install.id = "sound-pack-" + safeId + "-install";
      install.textContent = item.installed_version == null
        ? text("Установити й використовувати", "Install and use")
        : text("Оновити й використовувати", "Update and use");
      install.disabled = writesBlocked || busy;
      install.addEventListener("click", function () {
        invoke("install_pack", {pack_id: packId, activate: true}, group.id);
      });
      group.appendChild(install);
      packControls.push({control: install, mutation: true});
    }

    if (item.can_uninstall === true) {
      const uninstall = documentRef.createElement("button");
      uninstall.type = "button";
      uninstall.id = "sound-pack-" + safeId + "-uninstall";
      uninstall.textContent = text("Видалити", "Remove");
      uninstall.disabled = writesBlocked || busy;
      uninstall.addEventListener("click", function () {
        invoke("uninstall_pack", {pack_id: packId}, group.id);
      });
      group.appendChild(uninstall);
      packControls.push({control: uninstall, mutation: true});
    }
    return group;
  }

  function render(snapshot) {
    legend.textContent = text("Звуки", "Sounds");
    masterEnabledLabel.textContent = text("Увімкнути звуки", "Enable sounds");
    masterVolumeLabel.textContent = text("Загальна гучність, відсотків", "Master volume, percent");
    eventHeading.textContent = text("Події", "Events");
    packHeading.textContent = text("Набори звуків", "Sound packs");

    if (!snapshot || typeof snapshot !== "object") {
      setStatus(text("Завантаження налаштувань звуку.", "Loading sound settings."));
      masterEnabled.disabled = true;
      masterVolume.disabled = true;
      eventList.replaceChildren();
      packList.replaceChildren();
      packStatus.textContent = "";
      return;
    }

    const writesBlocked = snapshot.writes_blocked === true;
    setStatus(writesBlocked
      ? text(
          "Цей профіль створено новішою версією. Зміни заблоковано, щоб не пошкодити дані.",
          "This profile was created by a newer version. Changes are blocked to protect the data."
        )
      : text(
          "Активний набір: " + String(snapshot.active_pack_id || "classic") + ".",
          "Active pack: " + String(snapshot.active_pack_id || "classic") + "."
        ));
    masterEnabled.checked = snapshot.master_enabled === true;
    masterEnabled.disabled = writesBlocked || busy;
    masterVolume.value = String(snapshot.master_volume_percent);
    masterVolume.disabled = writesBlocked || busy;

    eventControls = [];
    const fragment = documentRef.createDocumentFragment();
    const events = Array.isArray(snapshot.events) ? snapshot.events : [];
    events.forEach(function (item) {
      if (item && typeof item === "object") fragment.appendChild(eventRow(item, writesBlocked));
    });
    eventList.replaceChildren(fragment);

    packControls = [];
    const packFragment = documentRef.createDocumentFragment();
    const packs = Array.isArray(snapshot.packs) ? snapshot.packs : [];
    packs.forEach(function (item) {
      if (item && typeof item === "object") packFragment.appendChild(packRow(item, writesBlocked));
    });
    packList.replaceChildren(packFragment);
    packStatus.textContent = packs.length === 0
      ? text(
          "Каталог наборів звуків не налаштовано.",
          "No sound-pack catalog is configured."
        )
      : text(
          "Доступні набори: " + String(packs.length) + ".",
          "Available packs: " + String(packs.length) + "."
        );
  }

  masterEnabled.addEventListener("change", function () {
    invoke("set_master", {enabled: masterEnabled.checked});
  });

  masterVolume.addEventListener("change", function () {
    const value = clampVolume(masterVolume.value);
    if (value === null) {
      if (currentSnapshot) masterVolume.value = String(currentSnapshot.master_volume_percent);
      announce(text("Гучність має бути від 0 до 100.", "Volume must be from 0 to 100."), true);
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
        setStatus(result && result.message ? result.message :
          text("Налаштування звуку недоступні.", "Sound settings are unavailable."));
        return false;
      }
      currentSnapshot = result.snapshot;
      render(currentSnapshot);
      return true;
    }, function () {
      setStatus(text("Налаштування звуку недоступні.", "Sound settings are unavailable."));
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
