/* Nook — представление. Знает только про window.pywebview.api и DOM. */
(() => {
  "use strict";

  // ---------------------------------------------------------------- утилиты
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  const svgIcon = (id) => {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", id);
    svg.appendChild(use);
    return svg;
  };

  const plural = (n, forms) => {
    const abs = Math.abs(n) % 100;
    const last = abs % 10;
    if (abs > 10 && abs < 20) return forms[2];
    if (last === 1) return forms[0];
    if (last >= 2 && last <= 4) return forms[1];
    return forms[2];
  };

  const baseName = (path) => String(path).split(/[\\/]/).pop() || String(path);

  const nowIso = () => new Date().toISOString();

  const debounce = (fn, ms) => {
    let timer = null;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
  };

  // ---------------------------------------------------------------- состояние
  const state = {
    items: [],
    selection: new Set(),
    tags: [],
    stats: { files: 0, tags: 0, bytes: 0, vault: "" },
    sort: null, // {key, dir}
    lastQuery: "",
    busy: false,
  };

  // ---------------------------------------------------------------- мост
  const bridge = () => (window.pywebview && window.pywebview.api) || null;

  const apiReady = new Promise((resolve) => {
    if (bridge()) return resolve(true);
    window.addEventListener("pywebviewready", () => resolve(true), { once: true });
    setTimeout(() => resolve(!!bridge()), 4000);
  });

  async function call(method, ...args) {
    const api = bridge();
    if (!api || typeof api[method] !== "function") {
      toast("Нет связи с Nook. Запустите приложение, а не файл в браузере.", "error");
      throw new Error(`no api.${method}`);
    }
    const result = await api[method](...args);
    if (result && result.ok === false && result.error) {
      toast(result.error, "error");
    }
    return result || {};
  }

  // ---------------------------------------------------------------- тосты
  const toastHost = $("#toasts");

  function toast(message, kind = "info", options = {}) {
    const node = el("div", `toast ${kind}`);
    const text = el("div", "toast-text", message);
    node.appendChild(text);
    if (options.action && typeof options.action.run === "function") {
      const button = el("button", "linklike", options.action.label || "Отменить");
      button.addEventListener("click", async () => {
        node.remove();
        await options.action.run();
      });
      node.appendChild(button);
    }
    toastHost.appendChild(node);
    const timeout = options.timeout ?? (options.action ? 8000 : 3800);
    setTimeout(() => {
      node.style.transition = "opacity .2s ease, transform .2s ease";
      node.style.opacity = "0";
      node.style.transform = "translateX(10px)";
      setTimeout(() => node.remove(), 220);
    }, timeout);
  }

  // ---------------------------------------------------------------- разбор запроса (только для подсказки)
  function parseQueryClient(raw) {
    const value = String(raw || "");
    const index = value.indexOf("\\");
    let head = index >= 0 ? value.slice(0, index) : value;
    let rest = index >= 0 ? value.slice(index + 1) : "";

    let ext = null;
    const extMatch = head.trimEnd().match(/\.([A-Za-z]{2,15})$/);
    if (extMatch) {
      ext = extMatch[1].toLowerCase();
      head = head.slice(0, head.length - extMatch[0].length);
    }

    const negTags = [];
    const tags = [];
    const dates = [];
    const negDates = [];

    for (const match of rest.matchAll(/(-?)\s*\[([^\]]*)\]/g)) {
      (match[1] ? negDates : dates).push(match[2].trim());
    }
    rest = rest.replace(/(-?)\s*\[([^\]]*)\]/g, " ");

    for (const match of rest.matchAll(/(-?)\s*[#№]([^\s[\]#№]+)/g)) {
      const name = match[2].toLowerCase().replace(/ё/g, "е");
      (match[1] ? negTags : tags).push(name);
    }
    rest = rest.replace(/(-?)\s*[#№]([^\s[\]#№]+)/g, " ");

    if (!ext) {
      const bareExt = rest.match(/(?:^|\s)\*?\.([A-Za-z]{2,15})(?=\s|$)/);
      if (bareExt) {
        ext = bareExt[1].toLowerCase();
        rest = rest.replace(bareExt[0], " ");
      }
    }

    const plainDate = /^(<=|>=|<|>)?(\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{4}-\d{2}-\d{2})$/;
    for (const token of rest.split(/\s+/)) {
      if (plainDate.test(token)) dates.push(token);
    }

    return { text: head.trim(), tags, negTags, dates, negDates, ext, hasParams: index >= 0 };
  }

  const queryInput = $("#query");
  const queryHint = $("#query-hint");
  const querySuggest = $("#query-suggest");

  function renderQueryHint() {
    queryHint.replaceChildren();
    const parsed = parseQueryClient(queryInput.value);
    if (!queryInput.value.trim()) {
      const hint = el("span", "hint-muted");
      hint.append("Слева — имя для нечёткого поиска, после ");
      hint.append(el("code", "", "\\"));
      hint.append(" — теги и даты.");
      queryHint.append(hint);
      return;
    }

    const chip = (label, value, kind = "") => {
      const node = el("span", `hint-chip ${kind}`);
      node.append(el("span", "", label));
      node.append(el("b", "", value));
      queryHint.append(node);
    };

    if (parsed.text) chip("имя", parsed.text);
    parsed.tags.forEach((tag) => chip("#", tag));
    parsed.negTags.forEach((tag) => chip("−#", tag, "neg"));
    parsed.dates.forEach((range) => chip("дата", range, "date"));
    parsed.negDates.forEach((range) => chip("−дата", range, "date neg"));
    if (parsed.ext) chip("тип", `.${parsed.ext}`, "ext");
    if (!parsed.text && !parsed.tags.length && !parsed.dates.length && !parsed.ext) {
      const hint = el("span", "hint-muted", "Пока нечего фильтровать");
      queryHint.append(hint);
    }
  }

  // ---------------------------------------------------------------- поиск
  const countNode = $("#count");
  const countLabel = $("#count-label");
  const timingNode = $("#timing");
  const rowsNode = $("#rows");
  const tableWrap = $("#table-wrap");
  const placeholder = $("#placeholder");
  const COMPACT_WIDTH = 900;

  /** В узком окне колонка «Изменён» убирается целиком (и <col>, и ячейки). */
  function isCompact() {
    return window.innerWidth < COMPACT_WIDTH;
  }

  function syncColumns() {
    const colgroup = $("colgroup");
    const col = document.getElementById("col-changed");
    const compact = isCompact();
    document.body.classList.toggle("compact", compact);
    if (!col || !colgroup) return;
    if (compact) {
      col.remove();
    } else if (!col.isConnected) {
      colgroup.insertBefore(col, colgroup.children[5] || null);
    }
  }
  const placeholderTitle = $("#placeholder-title");
  const placeholderText = $("#placeholder-text");

  function visibleItems() {
    if (!state.sort) return state.items;
    const { key, dir } = state.sort;
    const sign = dir === "asc" ? 1 : -1;
    const copy = state.items.slice();
    copy.sort((a, b) => {
      if (key === "size") return (a.size - b.size) * sign;
      if (key === "added") return a.added_at.localeCompare(b.added_at) * sign;
      if (key === "mtime") return (a.mtime_at || "").localeCompare(b.mtime_at || "") * sign;
      return a.name.localeCompare(b.name, "ru") * sign;
    });
    return copy;
  }

  function renderRows() {
    rowsNode.replaceChildren();
    const items = visibleItems();

    for (const item of items) {
      const tr = el("tr");
      tr.dataset.id = String(item.id);
      if (state.selection.has(item.id)) tr.classList.add("selected");

      // чекбокс
      const checkCell = el("td", "col-check");
      const check = document.createElement("input");
      check.type = "checkbox";
      check.checked = state.selection.has(item.id);
      check.setAttribute("aria-label", `Выбрать ${item.name}`);
      check.addEventListener("click", (event) => event.stopPropagation());
      check.addEventListener("change", () => {
        toggleSelection(item.id, check.checked);
        tr.classList.toggle("selected", check.checked);
      });
      checkCell.appendChild(check);

      // имя
      const nameCell = el("td", "col-name");
      const nameWrap = el("div", "name-cell");
      nameWrap.appendChild(el("span", "ext-badge", (item.ext || "?").slice(0, 4)));
      nameWrap.appendChild(el("span", "name-text", item.name));
      if (item.note) {
        const dot = el("span", "note-dot");
        dot.title = item.note;
        nameWrap.appendChild(dot);
      }
      nameCell.appendChild(nameWrap);

      // теги
      const tagsCell = el("td", "col-tags");
      const tagsWrap = el("div", "tags-cell");
      const tags = item.tags || [];
      const maxTags = isCompact() ? 1 : 3;
      tags.slice(0, maxTags).forEach((tag) => {
        const chip = el("button", "tag", `#${tag}`);
        chip.type = "button";
        chip.addEventListener("click", (event) => {
          event.stopPropagation();
          addTagToQuery(tag);
        });
        tagsWrap.appendChild(chip);
      });
      if (tags.length > maxTags) tagsWrap.appendChild(el("span", "tag-more", `+${tags.length - maxTags}`));
      if (!tags.length) tagsWrap.appendChild(el("span", "muted", "—"));
      tagsCell.appendChild(tagsWrap);

      const dateCell = el("td", "col-date muted", item.added_at_human.split(" ")[0]);
      const changedCell = el("td", "col-changed muted", item.mtime_at_human || "—");
      const sizeCell = el("td", "col-size muted", item.size_human);

      tr.title = [
        item.name,
        `Добавлен: ${item.added_at_human}`,
        item.mtime_at ? `Изменён: ${item.mtime_at.replace("T", " ").slice(0, 16)}` : "",
        item.created_at ? `Создан: ${item.created_at.replace("T", " ").slice(0, 16)}` : "",
        `Размер: ${item.size_human}`,
        item.tags.length ? `Теги: ${item.tags.map((tag) => `#${tag}`).join(" ")}` : "",
        item.note ? `Заметка: ${item.note}` : "",
      ]
        .filter(Boolean)
        .join("\n");

      // действия
      const actionsCell = el("td", "col-actions");
      const actions = el("div", "row-actions");
      actions.appendChild(
        iconButton("i-open", "Открыть", () => openFile(item.id)),
      );
      actions.appendChild(
        iconButton("i-folder", "Показать в проводнике", () => call("reveal_file", item.id)),
      );
      actions.appendChild(
        iconButton("i-trash", "В корзину", () => deleteFiles([item.id]), "danger"),
      );
      actionsCell.appendChild(actions);

      tr.append(
        ...[checkCell, nameCell, tagsCell, dateCell]
          .concat(isCompact() ? [] : [changedCell])
          .concat([sizeCell, actionsCell]),
      );
      tr.addEventListener("click", (event) => {
        if (event.target.closest("button, input, a")) return;
        toggleSelection(item.id);
        tr.classList.toggle("selected", state.selection.has(item.id));
        const box = $("input", checkCell);
        if (box) box.checked = state.selection.has(item.id);
      });
      tr.addEventListener("dblclick", (event) => {
        if (event.target.closest("button, input")) return;
        openFile(item.id);
      });

      rowsNode.appendChild(tr);
    }

    renderPlaceholder(items.length);
    $("#check-all").checked = items.length > 0 && items.every((item) => state.selection.has(item.id));
    renderBulkBar();
  }

  function iconButton(icon, title, handler, extraClass = "") {
    const button = el("button", `icon-btn ${extraClass}`);
    button.type = "button";
    button.title = title;
    button.appendChild(svgIcon(`#${icon}`));
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      handler();
    });
    return button;
  }

  function renderPlaceholder(shown) {
    const hasQuery = queryInput.value.trim().length > 0;
    placeholder.hidden = shown > 0;
    tableWrap.classList.toggle("is-empty", shown === 0);
    if (shown > 0) return;

    if (hasQuery) {
      placeholderTitle.textContent = "Ничего не нашлось";
      placeholderText.replaceChildren(
        "Попробуйте короче: две-три буквы работают лучше полного имени. ",
        "Фильтры — после ",
      );
      placeholderText.append(el("code", "", "\\"));
      placeholderText.append(", например ");
      placeholderText.append(el("code", "", "\\ #курсовая <12.04.2020"));
      return;
    }

    if (state.stats.files === 0) {
      placeholderTitle.textContent = "Зона пока пуста";
      placeholderText.textContent =
        "Перетащите файлы в окно или нажмите «Добавить файлы». Nook скопирует их в зону и запомнит имя — через полгода они найдутся за секунды.";
      return;
    }

    placeholderTitle.textContent = "Здесь пока тихо";
    placeholderText.textContent = "Начните печатать имя файла или тег.";
  }

  function renderCount(shown, total, took) {
    countNode.textContent = String(shown);
    countLabel.textContent = plural(shown, ["файл", "файла", "файлов"]);
    if (queryInput.value.trim() && total !== shown) {
      countLabel.textContent += ` из ${total}`;
    }
    timingNode.textContent = took !== undefined ? `${took.toFixed(1)} мс` : "";
  }

  function renderStatus() {
    const stats = state.stats || {};
    $("#status-files").textContent = `${stats.files || 0} ${plural(stats.files || 0, ["файл", "файла", "файлов"])}`;
    $("#status-tags").textContent = `${stats.tags || 0} ${plural(stats.tags || 0, ["тег", "тега", "тегов"])}`;
    $("#status-size").textContent = formatBytes(stats.bytes || 0);
    $("#status-vault").title = stats.vault || "";
  }

  function formatBytes(bytes) {
    const units = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
    let value = Number(bytes) || 0;
    let index = 0;
    while (value >= 1024 && index < units.length - 1) {
      value /= 1024;
      index += 1;
    }
    return index === 0 ? `${Math.round(value)} ${units[index]}` : `${value.toFixed(1)} ${units[index]}`;
  }

  // ---------------------------------------------------------------- выделение
  const bulkbar = $("#bulkbar");

  function toggleSelection(id, force) {
    const has = state.selection.has(id);
    const next = force === undefined ? !has : force;
    if (next) state.selection.add(id);
    else state.selection.delete(id);
    renderBulkBar();
    const row = rowsNode.querySelector(`tr[data-id="${id}"]`);
    if (row) {
      row.classList.toggle("selected", next);
      const box = $("input[type=checkbox]", row);
      if (box) box.checked = next;
    }
    $("#check-all").checked =
      state.items.length > 0 && state.items.every((item) => state.selection.has(item.id));
  }

  function clearSelection() {
    state.selection.clear();
    renderRows();
  }

  function selectedIds() {
    return Array.from(state.selection);
  }

  function renderBulkBar() {
    const count = state.selection.size;
    bulkbar.hidden = count === 0;
    $("#bulk-count").textContent = String(count);
  }

  // ---------------------------------------------------------------- поиск: запуск
  async function runSearch() {
    const raw = queryInput.value;
    const response = await call("search", raw, 400);
    if (!response || response.ok === false) return;
    state.items = response.items || [];
    state.stats = { ...state.stats, files: response.total ?? state.stats.files };
    // вычищаем выделение для исчезнувших файлов
    const alive = new Set(state.items.map((item) => item.id));
    for (const id of Array.from(state.selection)) if (!alive.has(id)) state.selection.delete(id);
    renderRows();
    renderCount(state.items.length, response.total ?? state.items.length, response.took_ms);
    renderStatus();
  }

  const scheduleSearch = debounce(() => {
    runSearch().catch(() => {});
  }, 70);

  // ---------------------------------------------------------------- теги в запросе
  function addTagToQuery(tag) {
    const parsed = parseQueryClient(queryInput.value);
    const params = [];
    parsed.tags.forEach((item) => params.push(`#${item}`));
    parsed.negTags.forEach((item) => params.push(`-#${item}`));
    parsed.dates.forEach((item) => params.push(`[${item}]`));
    if (!parsed.tags.includes(tag.toLowerCase())) params.push(`#${tag}`);
    queryInput.value = `${parsed.text} \\ ${params.join(" ")}`.trim();
    renderQueryHint();
    runSearch().catch(() => {});
    queryInput.focus();
  }

  // ---------------------------------------------------------------- автодополнение тегов в поиске
  const searchSuggest = {
    items: [],
    index: -1,
    open: false,
    timer: null,
  };

  function hideSearchSuggest() {
    searchSuggest.open = false;
    searchSuggest.items = [];
    searchSuggest.index = -1;
    querySuggest.hidden = true;
    querySuggest.replaceChildren();
  }

  function renderSearchSuggest() {
    querySuggest.replaceChildren();
    searchSuggest.items.forEach((item, index) => {
      const node = el("div", `suggest-item ${index === searchSuggest.index ? "active" : ""}`);
      node.append(el("span", "", `#${item.name}`));
      node.append(el("span", "count", String(item.count)));
      node.addEventListener("mousedown", (event) => {
        event.preventDefault();
        applySearchTag(item.name);
      });
      querySuggest.appendChild(node);
    });
    querySuggest.hidden = searchSuggest.items.length === 0;
    searchSuggest.open = !querySuggest.hidden;
  }

  function applySearchTag(name) {
    const value = queryInput.value;
    const caret = queryInput.selectionStart ?? value.length;
    const before = value.slice(0, caret);
    const after = value.slice(caret);
    const replaced = before.replace(/([#№])([^\s[\]#№\\]*)$/, (_match, hash, _prefix) => `${hash}${name} `);
    queryInput.value = replaced + after;
    queryInput.setSelectionRange(replaced.length, replaced.length);
    hideSearchSuggest();
    renderQueryHint();
    runSearch().catch(() => {});
  }

  const requestSuggest = debounce(async (prefix) => {
    try {
      const response = await call("tag_suggest", prefix, 8);
      const names = (response && response.tags) || [];
      if (!names.length) {
        hideSearchSuggest();
        return;
      }
      searchSuggest.items = names.map((name) => ({ name, count: "" }));
      searchSuggest.index = 0;
      renderSearchSuggest();
    } catch (_) {
      hideSearchSuggest();
    }
  }, 90);

  queryInput.addEventListener("input", () => {
    renderQueryHint();
    scheduleSearch();

    const before = queryInput.value.slice(0, queryInput.selectionStart ?? 0);
    const match = before.match(/([#№])([^\s[\]#№\\]*)$/);
    if (match) requestSuggest(match[2]);
    else hideSearchSuggest();
  });

  queryInput.addEventListener("keydown", (event) => {
    if (searchSuggest.open && searchSuggest.items.length) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const delta = event.key === "ArrowDown" ? 1 : -1;
        searchSuggest.index =
          (searchSuggest.index + delta + searchSuggest.items.length) % searchSuggest.items.length;
        renderSearchSuggest();
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        if (searchSuggest.index >= 0) {
          event.preventDefault();
          applySearchTag(searchSuggest.items[searchSuggest.index].name);
          return;
        }
      }
      if (event.key === "Escape") {
        hideSearchSuggest();
        return;
      }
    }

    if (event.key === "Enter") {
      event.preventDefault();
      const first = visibleItems()[0];
      if (first) openFile(first.id);
    }
    if (event.key === "Escape") {
      if (queryInput.value) {
        queryInput.value = "";
        renderQueryHint();
        runSearch().catch(() => {});
      } else {
        queryInput.blur();
      }
    }
  });

  queryInput.addEventListener("blur", () => setTimeout(hideSearchSuggest, 120));

  // ---------------------------------------------------------------- раскладка: № ( )
  function caretInParams() {
    const value = queryInput.value;
    const caret = queryInput.selectionStart ?? 0;
    const index = value.indexOf("\\");
    return index >= 0 && caret > index;
  }

  queryInput.addEventListener("beforeinput", (event) => {
    if (!event.data || event.data.length !== 1) return;
    if (!caretInParams()) return;
    const map = { "№": "#", "(": "[", ")": "]" };
    const replacement = map[event.data];
    if (!replacement) return;
    event.preventDefault();
    const value = queryInput.value;
    const start = queryInput.selectionStart ?? value.length;
    const end = queryInput.selectionEnd ?? start;
    queryInput.value = value.slice(0, start) + replacement + value.slice(end);
    queryInput.setSelectionRange(start + 1, start + 1);
    queryInput.dispatchEvent(new Event("input"));
  });

  // ---------------------------------------------------------------- действия с файлами
  async function openFile(id) {
    const response = await call("open_file", id);
    if (response.ok === false && !response.error) toast("Не удалось открыть файл", "error");
  }

  async function deleteFiles(ids) {
    if (!ids.length) return;
    const response = await call("delete_files", ids);
    if (!response || response.ok === false) return;
    const count = response.deleted || 0;
    ids.forEach((id) => state.selection.delete(id));
    toast(`В корзине: ${count} ${plural(count, ["файл", "файла", "файлов"])}`, "success", {
      action: {
        label: "Вернуть",
        run: async () => {
          await call("restore_files", ids);
          await refreshState();
        },
      },
    });
    await refreshState();
  }

  async function refreshState() {
    const response = await call("state");
    if (!response || response.ok === false) return;
    state.tags = response.tags || [];
    state.stats = response.stats || state.stats;
    renderStatus();
    await runSearch();
  }

  // ---------------------------------------------------------------- редактор тегов
  class TagBox {
    constructor(root, options = {}) {
      this.root = root;
      this.input = $("input[type=text]", root);
      this.suggest = options.suggest || $(".suggest", root);
      this.tags = [];
      this.items = [];
      this.index = -1;
      this.timer = null;
      this.preset = [];
      this.onlyPreset = false;
      this.navigated = false;
      this.onEmptyEnter = options.onEmptyEnter || null;

      this.input.addEventListener("keydown", (event) => this.onKeyDown(event));
      this.input.addEventListener("input", () => {
        this.navigated = false;
        this.onInput();
      });
      this.input.addEventListener("focus", () => {
        if (!this.input.value && this.preset.length) this.onInput();
      });
      this.input.addEventListener("blur", () => setTimeout(() => this.hideSuggest(), 120));
      root.addEventListener("mousedown", (event) => {
        if (event.target === root) {
          event.preventDefault();
          this.input.focus();
        }
      });
    }

    focus() {
      this.input.focus();
    }

    clear() {
      this.tags = [];
      this.input.value = "";
      this.render();
      this.hideSuggest();
    }

    set(values) {
      this.tags = Array.from(new Set((values || []).map((value) => String(value).trim()).filter(Boolean)));
      this.render();
    }

    setPreset(names, options = {}) {
      this.preset = (names || []).map((name) => String(name));
      // only — подсказывать строго из preset, без общих тегов зоны.
      this.onlyPreset = Boolean(options.only);
    }

    /** Если текст набран, но Enter не нажат — всё равно считаем его тегом. */
    commit() {
      const value = this.input.value.trim();
      if (value) this.add(value);
    }

    add(raw) {
      const name = String(raw || "")
        .trim()
        .replace(/^[#№]+/, "")
        .trim();
      if (!name) return;
      if (!this.tags.some((tag) => tag.toLowerCase() === name.toLowerCase())) this.tags.push(name);
      this.input.value = "";
      this.navigated = false;
      this.render();
      this.hideSuggest();
    }

    remove(name) {
      this.tags = this.tags.filter((tag) => tag !== name);
      this.render();
    }

    render() {
      $$(".chip", this.root).forEach((node) => node.remove());
      for (const tag of this.tags) {
        const chip = el("span", "chip", `#${tag}`);
        const button = el("button", "", "×");
        button.type = "button";
        button.title = "Убрать";
        button.addEventListener("click", () => this.remove(tag));
        chip.appendChild(button);
        this.root.insertBefore(chip, this.input);
      }
    }

    async onInput() {
      const value = this.input.value.trim();
      const prefix = value.replace(/^[#№]+/, "").toLowerCase();
      clearTimeout(this.timer);
      this.timer = setTimeout(async () => {
        // В режиме снятия тега — только теги выделенных файлов, без общей истории.
        const source = this.onlyPreset ? [] : ((await call("tag_suggest", prefix, 8)).tags || []);
        const seen = new Set();
        const merged = [];
        for (const name of [...source, ...this.preset]) {
          const key = String(name).toLowerCase();
          if (seen.has(key) || this.tags.some((tag) => tag.toLowerCase() === key)) continue;
          if (prefix && !key.includes(prefix)) continue;
          seen.add(key);
          merged.push(name);
        }
        this.items = merged.slice(0, 12);
        if (this.index >= this.items.length) this.index = this.items.length ? 0 : -1;
        this.renderSuggest();
      }, 110);
    }

    renderSuggest() {
      this.suggest.replaceChildren();
      this.items.forEach((name, index) => {
        const node = el("div", `suggest-item ${index === this.index ? "active" : ""}`);
        node.append(el("span", "", `#${name}`));
        node.addEventListener("mousedown", (event) => {
          event.preventDefault();
          this.add(name);
        });
        this.suggest.appendChild(node);
      });
      this.suggest.hidden = this.items.length === 0;
    }

    hideSuggest() {
      this.items = [];
      this.index = -1;
      this.suggest.hidden = true;
      this.suggest.replaceChildren();
    }

    onKeyDown(event) {
      if (event.key === "Enter") {
        event.preventDefault();
        const typed = this.input.value.trim();
        if (typed) {
          this.add(typed);
        } else if (this.navigated && this.items.length) {
          this.add(this.items[Math.max(0, this.index)]);
        } else if (typeof this.onEmptyEnter === "function") {
          this.onEmptyEnter();
        } else if (this.items.length) {
          this.add(this.items[Math.max(0, this.index)]);
        }
        return;
      }
      if (event.key === "Tab" && this.items.length) {
        event.preventDefault();
        this.add(this.items[Math.max(0, this.index)]);
        return;
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        if (!this.items.length) return;
        event.preventDefault();
        this.navigated = true;
        const delta = event.key === "ArrowDown" ? 1 : -1;
        this.index = (this.index + delta + this.items.length) % this.items.length;
        this.renderSuggest();
        return;
      }
      if (event.key === "Escape") {
        this.hideSuggest();
        return;
      }
      if (event.key === "Backspace" && !this.input.value && this.tags.length) {
        this.remove(this.tags[this.tags.length - 1]);
      }
    }
  }

  const addTagBox = new TagBox($("#add-tagbox"), {
    suggest: $("#add-tag-suggest"),
    onEmptyEnter: () => submitAdd(),
  });
  const bulkTagBox = new TagBox($("#bulk-tagbox"), {
    suggest: $("#bulk-tag-suggest"),
    onEmptyEnter: () => submitTags(),
  });

  // ---------------------------------------------------------------- модалка добавления
  const modalAdd = $("#modal-add");
  const addFilesList = $("#add-files");
  const addNote = $("#add-note");
  const addState = { paths: [] };

  function openAddDialog(paths) {
    addState.paths = paths.slice();
    addFilesList.replaceChildren();
    paths.forEach((path) => {
      const item = el("li");
      item.appendChild(svgIcon("#i-file"));
      item.appendChild(el("span", "", baseName(path)));
      addFilesList.appendChild(item);
    });
    $("#add-count").textContent = String(paths.length);
    $("#add-count-label").textContent = plural(paths.length, ["файл", "файла", "файлов"]);
    addTagBox.clear();
    addNote.value = "";
    openModal(modalAdd);
    setTimeout(() => addTagBox.focus(), 60);
  }

  async function submitAdd() {
    if (!addState.paths.length) return;
    addTagBox.commit();
    const tags = addTagBox.tags.slice();
    const button = $("#add-submit");
    button.disabled = true;
    button.textContent = "Добавляю…";
    try {
      const response = await call("add_paths", addState.paths, tags, addNote.value || null);
      const added = (response.added || []).length;
      (response.duplicates || []).slice(0, 3).forEach((message) => toast(message, "warn"));
      (response.errors || []).forEach((message) => toast(message, "error"));
      if (added) {
        toast(
          `Добавлено ${added} ${plural(added, ["файл", "файла", "файлов"])}${tags.length ? ` · #${tags.join(" #")}` : ""}`,
          "success",
        );
      } else if (!response.duplicates?.length && !response.errors?.length) {
        toast("Ничего не добавлено", "warn");
      }
      closeModal(modalAdd);
      await refreshState();
    } finally {
      button.disabled = false;
      button.textContent = "Добавить";
    }
  }

  // ---------------------------------------------------------------- модалка тегов
  const modalTag = $("#modal-tag");
  const tagState = { mode: "assign", ids: [] };

  async function openTagDialog(mode) {
    const ids = selectedIds();
    if (!ids.length) return;

    bulkTagBox.clear();
    bulkTagBox.setPreset([]);
    bulkTagBox.input.placeholder = "курсовая2024";

    if (mode === "remove") {
      // Только теги, которые реально висят на выделенных файлах.
      const response = await call("tags_for_files", ids);
      const names = (response.tags || []).map((item) => item.name);
      if (!names.length) {
        toast("У выбранных файлов нет тегов — снимать нечего", "warn");
        return;
      }
      bulkTagBox.setPreset(names, { only: true });
      bulkTagBox.input.placeholder = "тег на выделенных файлах";
    } else {
      bulkTagBox.setPreset([]);
    }

    tagState.mode = mode;
    tagState.ids = ids;
    $("#tag-title").textContent = mode === "remove" ? "Снять тег" : "Тег для выделенных";
    $("#tag-submit").textContent = mode === "remove" ? "Снять" : "Применить";
    $("#tag-count").textContent = String(ids.length);
    $("#tag-count-label").textContent = plural(ids.length, ["файл", "файла", "файлов"]);
    $("#modal-tag .sheet").classList.toggle("tag-sheet", true);

    openModal(modalTag);
    setTimeout(() => bulkTagBox.focus(), 60);
    if (mode === "remove") bulkTagBox.onInput();
  }

  async function submitTags() {
    bulkTagBox.commit();
    const tags = bulkTagBox.tags.slice();
    if (!tags.length) {
      toast("Введите хотя бы один тег", "warn");
      return;
    }
    const ids = tagState.ids;
    if (tagState.mode === "remove") {
      for (const tag of tags) await call("unassign_tag", ids, tag);
      toast(`Снято: ${tags.map((tag) => `#${tag}`).join(", ")}`, "success");
    } else {
      for (const tag of tags) await call("assign_tag", ids, tag);
      toast(`Теги: ${tags.map((tag) => `#${tag}`).join(", ")} — на ${ids.length} ${plural(ids.length, ["файл", "файла", "файлов"])}`, "success");
    }
    closeModal(modalTag);
    await refreshState();
  }

  // ---------------------------------------------------------------- модалки: механика
  function openModal(modal) {
    modal.hidden = false;
    const focusable = $("input, textarea, button", modal);
    if (focusable) setTimeout(() => focusable.focus(), 40);
  }

  function closeModal(modal) {
    modal.hidden = true;
  }

  $$("[data-close]").forEach((button) => {
    button.addEventListener("click", () => {
      const modal = document.getElementById(button.dataset.close);
      if (modal) closeModal(modal);
    });
  });

  // Клик мимо карточки её не закрывает: окно добавления может уйти за другое
  // окно при перетаскивании файлов, и возврат фокуса не должен терять выбор.
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      $$(".modal").forEach((modal) => {
        if (!modal.hidden) closeModal(modal);
      });
    }
    const isSearchKey = event.code === "KeyK" || (event.key || "").toLowerCase() === "k";
    if ((event.ctrlKey || event.metaKey) && isSearchKey) {
      event.preventDefault();
      queryInput.focus();
      queryInput.select();
    }
    const isFindKey = event.code === "KeyF" || (event.key || "").toLowerCase() === "f";
    if ((event.ctrlKey || event.metaKey) && isFindKey) {
      event.preventDefault();
      queryInput.focus();
      queryInput.select();
    }
  });

  $("#kbd-hint").addEventListener("click", () => {
    queryInput.focus();
    queryInput.select();
  });

  $("#add-submit").addEventListener("click", () => submitAdd());
  $("#tag-submit").addEventListener("click", () => submitTags());
  addNote.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") submitAdd();
  });

  // ---------------------------------------------------------------- кнопки
  $("#btn-add").addEventListener("click", async () => {
    const response = await call("pick_files");
    if (response && response.paths && response.paths.length) openAddDialog(response.paths);
  });

  $("#btn-export").addEventListener("click", async () => {
    const response = await call("export_zip");
    if (response && response.ok) toast(`Экспортировано: ${response.path}`, "success", { timeout: 6000 });
  });

  const openVault = async () => call("open_vault");
  $("#btn-vault").addEventListener("click", openVault);
  $("#status-vault").addEventListener("click", openVault);

  $("#check-all").addEventListener("change", (event) => {
    const on = event.target.checked;
    if (on) state.items.forEach((item) => state.selection.add(item.id));
    else state.selection.clear();
    renderRows();
  });

  $("#bulk-tag").addEventListener("click", () => openTagDialog("assign"));
  $("#bulk-untag").addEventListener("click", () => openTagDialog("remove"));
  $("#bulk-delete").addEventListener("click", () => deleteFiles(selectedIds()));
  $("#bulk-clear").addEventListener("click", () => clearSelection());

  // ---------------------------------------------------------------- сортировка
  $$("th.sortable").forEach((header) => {
    header.addEventListener("click", () => {
      const key = header.dataset.sort;
      if (state.sort && state.sort.key === key) {
        state.sort = state.sort.dir === "asc" ? { key, dir: "desc" } : null;
      } else {
        state.sort = { key, dir: key === "name" ? "asc" : "desc" };
      }
      $$("th.sortable .arrow").forEach((arrow) => (arrow.textContent = ""));
      if (state.sort) {
        const arrow = $(`[data-arrow="${key}"]`);
        if (arrow) arrow.textContent = state.sort.dir === "asc" ? "↑" : "↓";
      }
      renderRows();
    });
  });

  // ---------------------------------------------------------------- drag & drop
  const dropzone = $("#dropzone");
  let dragDepth = 0;

  function hasFiles(event) {
    const types = event.dataTransfer && event.dataTransfer.types;
    return types ? Array.from(types).includes("Files") : false;
  }

  window.addEventListener("dragenter", (event) => {
    if (!hasFiles(event)) return;
    dragDepth += 1;
    dropzone.hidden = false;
  });

  window.addEventListener("dragover", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });

  window.addEventListener("dragleave", (event) => {
    if (!hasFiles(event)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) dropzone.hidden = true;
  });

  window.addEventListener("drop", (event) => {
    event.preventDefault();
    dragDepth = 0;
    dropzone.hidden = true;
  });

  // пути приходят из Python (pywebview DOM drop)
  window.nook = {
    onDropped(paths) {
      if (!Array.isArray(paths) || !paths.length) return;
      openAddDialog(paths);
    },
  };

  // ---------------------------------------------------------------- старт
  syncColumns();
  renderQueryHint();

  window.addEventListener(
    "resize",
    debounce(() => {
      syncColumns();
      renderRows();
    }, 120),
  );

  apiReady.then(async (ready) => {
    if (!ready) {
      placeholder.hidden = false;
      placeholderTitle.textContent = "Нет связи с ядром Nook";
      placeholderText.textContent = "Это окно должно открываться из приложения Nook.";
      return;
    }
    try {
      await refreshState();
    } catch (error) {
      toast(`Ошибка запуска: ${error.message || error}`, "error");
    }
  });
})();
