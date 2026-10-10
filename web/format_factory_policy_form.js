"use strict";

/* Section 54 additive, keyboard-first policy collection UI; no model/network calls.
 * The trusted host must validate submitted objects against the canonical Python
 * FactoryJobPolicy and actual capability matrix before initiating any job.
 */
(function (global) {
  const CHOICES = Object.freeze([
    ["all", "Уся книга"],
    ["chapters", "Глави"],
    ["printed_pages", "Надруковані сторінки"],
    ["file_pages", "Сторінки файла"],
    ["positions", "Шахові позиції"],
    ["games", "Партії"],
    ["diagrams", "Діаграми"],
  ]);
  const FORMATS = Object.freeze([
    ["html", "Доступний HTML (прев’ю)", true],
    ["txt", "Текстовий TXT (можлива втрата структури)", true],
    ["epub3", "EPUB3 (у розробці)", false],
    ["tagged_pdf", "Доступний PDF (у розробці)", false],
    ["docx", "DOCX (у розробці)", false],
    ["pgn", "PGN (у розробці)", false],
    ["acsdb", "ACSDB (у розробці)", false],
  ]);

  function mountFactoryPolicyForm(host, options) {
    if (!host || !host.ownerDocument || !options || typeof options.onSubmit !== "function") {
      throw new TypeError("Trusted host and onSubmit callback required");
    }
    const prefix = String(options.prefix || "factory54");
    if (!/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(prefix)) {
      throw new TypeError("Invalid form identifier prefix");
    }
    const doc = host.ownerDocument;
    const form = doc.createElement("form");
    form.setAttribute("novalidate", "");
    const heading = doc.createElement("h2");
    heading.id = prefix + "-heading";
    heading.textContent = "Фабрика доступних шахових книг — політика завдання";
    form.setAttribute("aria-labelledby", heading.id);
    form.append(heading);
    function field(labelText, name, kind, config) {
      const wrap = doc.createElement("div");
      const label = doc.createElement("label");
      const input = doc.createElement(kind === "select" ? "select" : "input");
      input.id = prefix + "-" + name;
      input.name = name;
      if (kind !== "select") input.type = kind;
      if (config && config.required) input.required = true;
      label.htmlFor = input.id;
      label.textContent = labelText;
      wrap.append(label, input);
      form.append(wrap);
      return input;
    }
    const select = field("Обсяг обробки", "scope", "select");
    for (const [code, title] of CHOICES) {
      const option = doc.createElement("option");
      option.value = code;
      option.textContent = title;
      select.append(option);
    }
    select.value = "all";
    const ranges = field("Номери або діапазони через кому, наприклад 1-3,5,8-12", "ranges", "text");
    ranges.disabled = true;
    ranges.setAttribute("autocomplete", "off");
    const formatSet = doc.createElement("fieldset");
    const legend = doc.createElement("legend");
    legend.textContent = "Формати результатів";
    formatSet.append(legend);
    const formatInputs = [];
    for (const [code, title, supported] of FORMATS) {
      const label = doc.createElement("label");
      const input = doc.createElement("input");
      input.type = "checkbox";
      input.name = "format";
      input.value = code;
      input.id = prefix + "-format-" + code;
      input.disabled = !supported;
      input.checked = supported && code === "html";
      label.htmlFor = input.id;
      label.textContent = title;
      formatSet.append(input, label);
      formatInputs.push(input);
    }
    form.append(formatSet);
    const language = field("Мова результату (наприклад uk або en)", "language", "text", { required: true });
    language.value = options.defaultLanguage || "uk";
    const search = field("Дозволити пошук публічних допоміжних джерел", "external_search", "checkbox");
    const ai = field("Дозволити передавання обраного фрагмента зовнішній ШІ-моделі", "external_ai", "checkbox");
    const provider = field("Провайдер", "provider", "text");
    const model = field("Модель", "model", "text");
    const inputLimit = field("Максимум вхідних токенів за запуск", "max_input_tokens", "number");
    const outputLimit = field("Максимум вихідних токенів за запуск", "max_output_tokens", "number");
    inputLimit.min = outputLimit.min = "1";
    inputLimit.step = outputLimit.step = "1";
    inputLimit.setAttribute("inputmode", "numeric");
    outputLimit.setAttribute("inputmode", "numeric");
    function refresh() {
      const includeRanges = select.value !== "all";
      ranges.disabled = !includeRanges;
      ranges.required = includeRanges;
      for (const item of [provider, model, inputLimit, outputLimit]) {
        item.disabled = !ai.checked;
        item.required = ai.checked;
      }
    }
    select.addEventListener("change", refresh);
    ai.addEventListener("change", refresh);
    refresh();
    const status = doc.createElement("p");
    status.id = prefix + "-status";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    const submit = doc.createElement("button");
    submit.type = "submit";
    submit.textContent = "Підтвердити політику";
    form.append(status, submit);
    function validTokenCount(value) {
      return /^[1-9][0-9]*$/.test(value) && Number.isSafeInteger(Number(value));
    }
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      const outputs = formatInputs.filter(x => x.checked && !x.disabled).map(x => x.value);
      const hasRanges = select.value !== "all";
      if (!outputs.length || (hasRanges && !ranges.value.trim())) {
        status.textContent = "Оберіть формат і потрібні діапазони.";
        if (!outputs.length) formatInputs[0].focus(); else ranges.focus();
        return;
      }
      if (ai.checked && (!provider.value.trim() || !model.value.trim() ||
          !validTokenCount(inputLimit.value) || !validTokenCount(outputLimit.value))) {
        status.textContent = "Укажіть провайдера, модель та два додатні токенові ліміти.";
        provider.focus();
        return;
      }
      const policy = {
        selection: { kind: select.value, ranges: hasRanges ? ranges.value.trim() : "" },
        output_formats: outputs,
        output_language: language.value.trim(),
        allowed_external_search: search.checked,
        allowed_external_ai: ai.checked,
        provider_id: ai.checked ? provider.value.trim() : null,
        model_id: ai.checked ? model.value.trim() : null,
        max_input_tokens: ai.checked ? Number(inputLimit.value) : null,
        max_output_tokens: ai.checked ? Number(outputLimit.value) : null,
      };
      try {
        options.onSubmit(policy);
        status.textContent = "Політика передана для перевірки застосунком.";
      } catch (_error) {
        status.textContent = "Не вдалося передати політику застосунку.";
        submit.focus();
      }
    });
    host.replaceChildren(form);
    return { form, focus: () => select.focus() };
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { mountFactoryPolicyForm };
  else global.AccessibleChessFormatFactoryForm = { mountFactoryPolicyForm };
})(typeof window !== "undefined" ? window : this);
