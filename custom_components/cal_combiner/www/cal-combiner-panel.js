class CalCombinerPanel extends HTMLElement {
  constructor() {
    super();
    // A real shadow root is required for the `:host` selector below (and for
    // our plain `button`/`input`/`select`/`h1`/`*` rules) to actually stay
    // scoped to this panel. Without one, that <style> tag is just a normal
    // light-DOM stylesheet: `:host` matches nothing (so our own sizing rules
    // silently no-op) while the generic tag/class selectors leak out and
    // apply to the rest of the Home Assistant UI.
    this.attachShadow({ mode: "open" });
    this._entries = [];
    this._calendars = [];
    this._initialized = false;
    this._activeTab = "calendars";
    this._activeCalendarKey = "__new__"; // entry_id, or "__new__" for the create-new sub-tab
    this._openFilters = {}; // "entryId::entityId" -> bool
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
      this._boot();
    }
  }

  get hass() {
    return this._hass;
  }

  async _boot() {
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; box-sizing: border-box; min-height: 100%; padding: 16px;
          max-width: 960px; margin: 0 auto;
          font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
        *, *::before, *::after { box-sizing: border-box; }
        h1 { font-size: 24px; font-weight: 400; color: var(--primary-text-color); margin: 4px 0 4px 0;
          display: flex; align-items: center; gap: 10px; }
        h1 ha-icon { --mdc-icon-size: 28px; color: var(--primary-color); }
        p.subtitle { color: var(--secondary-text-color); margin-top: 0; margin-bottom: 20px; }
        .cc-tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--divider-color, #ccc);
          margin-bottom: 20px; }
        .cc-tab { display: flex; align-items: center; gap: 6px; padding: 10px 18px; cursor: pointer;
          background: none; border: none; border-bottom: 2px solid transparent; font-size: 14px;
          font-weight: 500; color: var(--secondary-text-color); }
        .cc-tab.active { color: var(--primary-color); border-bottom-color: var(--primary-color); }
        .cc-tab ha-icon { --mdc-icon-size: 20px; }
        .cc-subtabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }
        .cc-subtab { display: flex; align-items: center; gap: 6px; padding: 6px 14px; cursor: pointer;
          background: var(--secondary-background-color, #eee); border: 1px solid transparent; border-radius: 999px;
          font-size: 13px; color: var(--primary-text-color); }
        .cc-subtab.active { background: var(--primary-color); color: var(--text-primary-color, white); }
        .cc-subtab-new { background: transparent; border: 1px dashed var(--divider-color, #ccc);
          color: var(--secondary-text-color); }
        .cc-subtab-new.active { background: var(--primary-color); color: var(--text-primary-color, white);
          border-style: solid; }
        .cc-subtab ha-icon { --mdc-icon-size: 16px; }
        .cc-render-error { color: var(--error-color, #db4437); background: rgba(219,68,55,0.08);
          border: 1px solid var(--error-color, #db4437); border-radius: 8px; padding: 12px; margin-bottom: 16px;
          font-size: 13px; white-space: pre-wrap; }
        .cc-card {
          background: var(--card-background-color, white);
          border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0,0,0,0.1));
          padding: 16px; margin-bottom: 16px; border: 1px solid var(--ha-card-border-color, transparent);
        }
        .cc-card-header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
        .cc-card-header ha-icon { --mdc-icon-size: 24px; color: var(--primary-color); flex-shrink: 0; }
        .cc-card-header img.cc-avatar { width: 28px; height: 28px; border-radius: 50%; object-fit: cover;
          flex-shrink: 0; }
        .cc-card-header input[type="text"].cc-name { font-size: 16px; font-weight: 500; flex: 1; }
        .cc-section-title { font-weight: 500; font-size: 13px; text-transform: uppercase;
          letter-spacing: .03em; color: var(--secondary-text-color); margin: 16px 0 6px 0; }
        .cc-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 8px; }
        input[type="text"], select {
          padding: 8px 10px; border-radius: 6px; min-width: 160px;
          border: 1px solid var(--divider-color, #ccc); background: var(--card-background-color);
          color: var(--primary-text-color); font-size: 14px; box-sizing: border-box;
        }
        input[type="text"] { flex: 1; }
        .cc-actions { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
        button {
          border: none; border-radius: 6px; padding: 8px 14px; font-size: 14px; cursor: pointer;
          background: var(--primary-color); color: var(--text-primary-color, white);
        }
        button.secondary { background: transparent; color: var(--primary-color);
          border: 1px solid var(--primary-color); }
        button.danger { background: var(--error-color, #db4437); color: white; }
        button:disabled { opacity: .4; cursor: default; }
        .cc-own-box { display: flex; align-items: center; gap: 8px; background: var(--secondary-background-color, #f4f4f4);
          border-radius: 8px; padding: 8px 10px; font-size: 13px; color: var(--secondary-text-color); }
        .cc-own-box ha-icon { --mdc-icon-size: 18px; color: var(--primary-color); }
        .cc-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
        .cc-chip { display: inline-flex; align-items: center; gap: 4px; background: var(--secondary-background-color, #eee);
          border-radius: 999px; padding: 4px 6px 4px 10px; font-size: 13px; color: var(--primary-text-color); }
        .cc-chip-remove { background: none; border: none; color: var(--secondary-text-color); cursor: pointer;
          font-size: 15px; line-height: 1; padding: 2px 4px; border-radius: 50%; }
        .cc-chip-remove:hover { background: rgba(0,0,0,0.1); }
        .cc-chip-empty { font-size: 13px; color: var(--secondary-text-color); font-style: italic; }
        .cc-icon-picker .cc-row ha-icon { --mdc-icon-size: 22px; color: var(--primary-text-color); }
        .cc-picture-preview { width: 40px; height: 40px; border-radius: 6px; object-fit: cover; display: none; }
        .cc-picture-status { display: block; font-size: 12px; color: var(--secondary-text-color); margin-top: 4px; }
        .cc-filter-box { border-top: 1px dashed var(--divider-color, #ccc); margin-top: 8px; padding-top: 8px; }
        .cc-filter-toggle { font-size: 13px; color: var(--primary-color); cursor: pointer; background: none;
          border: none; padding: 4px 0; text-align: left; }
        .cc-filter-fields { display: none; flex-direction: column; gap: 8px; margin-top: 8px; padding: 8px;
          background: var(--secondary-background-color, #f4f4f4); border-radius: 8px; }
        .cc-filter-fields.open { display: flex; }
        .cc-filter-fields label { font-size: 13px; color: var(--secondary-text-color); display: flex; align-items: center; gap: 6px; }
        .cc-feed-row { display: flex; gap: 6px; margin-top: 4px; align-items: center; }
        .cc-feed-row input { font-size: 12px; }
        .cc-caldav-field-label { font-size: 12px; color: var(--secondary-text-color); min-width: 130px; flex-shrink: 0; }
        .cc-source-block { border: 1px solid var(--divider-color, #eee); border-radius: 8px; padding: 8px; margin-bottom: 6px; }
        .cc-error { color: var(--error-color, #db4437); font-size: 13px; margin: 4px 0; }
        .cc-warning { color: var(--warning-color, #ff9800); font-size: 12px; margin: 4px 0; }
        .cc-new-card { border: 2px dashed var(--divider-color, #ccc); }
        .cc-log-list { display: flex; flex-direction: column; gap: 4px; max-height: 220px; overflow-y: auto; }
        .cc-log-row { display: flex; gap: 10px; font-size: 13px; padding: 4px 0;
          border-bottom: 1px solid var(--divider-color, #eee); }
        .cc-log-row:last-child { border-bottom: none; }
        .cc-log-time { color: var(--secondary-text-color); flex-shrink: 0; white-space: nowrap; }
        .cc-check-row { display: flex; align-items: center; gap: 8px; margin: 6px 0; font-size: 14px; }
      </style>
      <h1><ha-icon icon="mdi:calendar-sync"></ha-icon>Cal Combiner</h1>
      <p class="subtitle">Bygg och hantera dina sammanslagna kalendrar.</p>
      <div class="cc-tabs">
        <button class="cc-tab" data-tab="calendars"><ha-icon icon="mdi:calendar-multiple"></ha-icon>Kalendrar</button>
        <button class="cc-tab" data-tab="server"><ha-icon icon="mdi:server"></ha-icon>Server</button>
      </div>
      <div id="root">Laddar…</div>
    `;
    this.shadowRoot.querySelectorAll(".cc-tab").forEach((btn) => {
      btn.onclick = () => {
        this._activeTab = btn.dataset.tab;
        this._render();
      };
    });
    await this._reload();
  }

  async _reload() {
    const [entriesResp, calendarsResp] = await Promise.all([
      this._hass.callWS({ type: "cal_combiner/list_entries" }),
      this._hass.callWS({ type: "cal_combiner/list_calendars" }),
    ]);
    this._entries = entriesResp.entries;
    this._calendars = calendarsResp.calendars;
    this._render();
  }

  _calendarName(entityId) {
    const found = this._calendars.find((c) => c.entity_id === entityId);
    return found ? found.name : entityId;
  }

  _render() {
    this.shadowRoot.querySelectorAll(".cc-tab").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === this._activeTab);
    });

    const root = this.shadowRoot.querySelector("#root");
    root.innerHTML = "";

    if (this._activeTab === "calendars") {
      if (
        this._activeCalendarKey !== "__new__" &&
        !this._entries.find((e) => e.entry_id === this._activeCalendarKey)
      ) {
        this._activeCalendarKey = this._entries.length ? this._entries[0].entry_id : "__new__";
      }
      root.appendChild(
        this._renderSubTabs(this._entries, this._activeCalendarKey, (key) => {
          this._activeCalendarKey = key;
          this._render();
        })
      );
      if (this._activeCalendarKey === "__new__") {
        this._safeAppend(root, () => this._renderNewEntryCard(), "ny kalender");
      } else {
        const entry = this._entries.find((e) => e.entry_id === this._activeCalendarKey);
        this._safeAppend(root, () => this._renderEntryCard(entry), `kalendern "${entry.name}"`);
      }
    } else {
      this._safeAppend(root, () => this._renderServerTab(), "CalDAV-servern");
    }
  }

  // ---- shared building blocks ----

  /** Renders `build()` into `root`, or a visible error box instead of leaving the tab silently blank. */
  _safeAppend(root, build, context) {
    try {
      root.appendChild(build());
    } catch (err) {
      console.error(`Cal Combiner: kunde inte rita ${context}`, err);
      const box = document.createElement("div");
      box.className = "cc-render-error";
      box.textContent = `Kunde inte visa ${context}: ${err.message || err}\n(Se webbläsarens konsol för mer detaljer.)`;
      root.appendChild(box);
    }
  }

  _renderSubTabs(items, activeKey, onSelect) {
    const bar = document.createElement("div");
    bar.className = "cc-subtabs";
    items.forEach((item) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cc-subtab" + (item.entry_id === activeKey ? " active" : "");
      btn.textContent = item.name;
      btn.onclick = () => onSelect(item.entry_id);
      bar.appendChild(btn);
    });
    const newBtn = document.createElement("button");
    newBtn.type = "button";
    newBtn.className = "cc-subtab cc-subtab-new" + (activeKey === "__new__" ? " active" : "");
    newBtn.innerHTML = `<ha-icon icon="mdi:plus"></ha-icon>`;
    newBtn.onclick = () => onSelect("__new__");
    bar.appendChild(newBtn);
    return bar;
  }

  _buildIconPicker(value) {
    const wrap = document.createElement("div");
    wrap.className = "cc-icon-picker";
    let getValue;
    let usedPicker = false;
    if (customElements.get("ha-icon-picker")) {
      try {
        const picker = document.createElement("ha-icon-picker");
        picker.hass = this._hass;
        picker.label = "Ikon";
        picker.value = value || "";
        wrap.appendChild(picker);
        getValue = () => picker.value || "";
        usedPicker = true;
      } catch (err) {
        console.warn("Cal Combiner: ha-icon-picker gick inte att använda, faller tillbaka på textfält", err);
        wrap.innerHTML = "";
      }
    }
    if (!usedPicker) {
      const row = document.createElement("div");
      row.className = "cc-row";
      const icon = document.createElement("ha-icon");
      icon.setAttribute("icon", value || "mdi:help-circle-outline");
      const input = document.createElement("input");
      input.type = "text";
      input.placeholder = "mdi:calendar";
      input.value = value || "";
      input.oninput = () => icon.setAttribute("icon", input.value.trim() || "mdi:help-circle-outline");
      row.appendChild(icon);
      row.appendChild(input);
      wrap.appendChild(row);
      getValue = () => input.value.trim();
    }
    return { element: wrap, getValue };
  }

  // Uploads through Home Assistant's built-in image storage (the same
  // /api/image/upload + /api/image/serve mechanism used by e.g. the Person
  // and Area picture pickers), so images live in HA itself instead of a
  // pasted URL.
  _buildPicturePicker(value) {
    const state = { value: value || "" };
    const wrap = document.createElement("div");
    wrap.className = "cc-picture-picker";

    const row = document.createElement("div");
    row.className = "cc-row";

    const preview = document.createElement("img");
    preview.className = "cc-picture-preview";
    if (state.value) {
      preview.src = state.value;
      preview.style.display = "block";
    }

    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = "image/png,image/jpeg,image/gif";
    fileInput.style.display = "none";

    const uploadBtn = document.createElement("button");
    uploadBtn.type = "button";
    uploadBtn.className = "secondary";
    uploadBtn.textContent = state.value ? "Byt bild" : "Ladda upp bild";
    uploadBtn.onclick = () => fileInput.click();

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "secondary";
    removeBtn.textContent = "Ta bort bild";
    removeBtn.style.display = state.value ? "inline-block" : "none";

    const status = document.createElement("span");
    status.className = "cc-picture-status";

    const oldImageId = (url) => {
      const m = /^\/api\/image\/serve\/([^/]+)\/original$/.exec(url || "");
      return m ? m[1] : null;
    };

    const clear = async ({ deleteRemote } = {}) => {
      const previousId = deleteRemote ? oldImageId(state.value) : null;
      state.value = "";
      preview.removeAttribute("src");
      preview.style.display = "none";
      removeBtn.style.display = "none";
      uploadBtn.textContent = "Ladda upp bild";
      if (previousId) {
        try {
          await this._hass.callWS({ type: "image/delete", image_id: previousId });
        } catch (err) {
          // Non-critical cleanup; the reference is gone from our config either way.
          console.warn("Cal Combiner: kunde inte städa bort gammal bild", err);
        }
      }
    };

    removeBtn.onclick = () => clear({ deleteRemote: true });

    fileInput.onchange = async () => {
      const file = fileInput.files[0];
      if (!file) return;
      uploadBtn.disabled = true;
      removeBtn.disabled = true;
      status.textContent = "Laddar upp…";
      const previousId = oldImageId(state.value);
      try {
        const fd = new FormData();
        fd.append("file", file);
        const resp = await this._hass.fetchWithAuth("/api/image/upload", {
          method: "POST",
          body: fd,
        });
        if (!resp.ok) {
          throw new Error(resp.status === 413 ? "Bilden är för stor" : `Uppladdning misslyckades (${resp.status})`);
        }
        const item = await resp.json();
        state.value = `/api/image/serve/${item.id}/original`;
        preview.src = state.value;
        preview.style.display = "block";
        removeBtn.style.display = "inline-block";
        uploadBtn.textContent = "Byt bild";
        status.textContent = "";
        if (previousId) {
          try {
            await this._hass.callWS({ type: "image/delete", image_id: previousId });
          } catch (err) {
            console.warn("Cal Combiner: kunde inte städa bort gammal bild", err);
          }
        }
      } catch (err) {
        status.textContent = err.message || "Kunde inte ladda upp bilden";
      } finally {
        uploadBtn.disabled = false;
        removeBtn.disabled = false;
        fileInput.value = "";
      }
    };

    row.appendChild(preview);
    row.appendChild(uploadBtn);
    row.appendChild(removeBtn);
    row.appendChild(fileInput);
    wrap.appendChild(row);
    wrap.appendChild(status);

    return { element: wrap, getValue: () => state.value };
  }

  _buildSourcePicker(initialSelected) {
    const state = { selected: [...initialSelected] };
    const wrap = document.createElement("div");

    const chipsWrap = document.createElement("div");
    chipsWrap.className = "cc-chips";

    const pickRow = document.createElement("div");
    pickRow.className = "cc-row";
    const select = document.createElement("select");
    const addBtn = document.createElement("button");
    addBtn.type = "button";
    addBtn.className = "secondary";
    addBtn.textContent = "+ Lägg till";

    const renderChips = () => {
      chipsWrap.innerHTML = "";
      if (!state.selected.length) {
        const empty = document.createElement("span");
        empty.className = "cc-chip-empty";
        empty.textContent = "Inga källkalendrar tillagda ännu";
        chipsWrap.appendChild(empty);
      }
      state.selected.forEach((entityId) => {
        const chip = document.createElement("span");
        chip.className = "cc-chip";
        chip.append(this._calendarName(entityId));
        const rm = document.createElement("button");
        rm.type = "button";
        rm.className = "cc-chip-remove";
        rm.textContent = "×";
        rm.title = "Ta bort källa";
        rm.onclick = () => {
          state.selected = state.selected.filter((id) => id !== entityId);
          renderChips();
          renderSelect();
        };
        chip.appendChild(rm);
        chipsWrap.appendChild(chip);
      });
    };

    const renderSelect = () => {
      select.innerHTML = "";
      const options = this._calendars.filter((c) => !state.selected.includes(c.entity_id));
      if (!options.length) {
        const opt = document.createElement("option");
        opt.textContent = "Inga fler kalendrar att lägga till";
        opt.disabled = true;
        select.appendChild(opt);
        addBtn.disabled = true;
        return;
      }
      addBtn.disabled = false;
      options.forEach((cal) => {
        const opt = document.createElement("option");
        opt.value = cal.entity_id;
        opt.textContent = `${cal.name} (${cal.entity_id})`;
        select.appendChild(opt);
      });
    };

    addBtn.onclick = () => {
      if (select.value && !state.selected.includes(select.value)) {
        state.selected.push(select.value);
        renderChips();
        renderSelect();
      }
    };

    renderChips();
    renderSelect();
    pickRow.appendChild(select);
    pickRow.appendChild(addBtn);
    wrap.appendChild(chipsWrap);
    wrap.appendChild(pickRow);

    return { element: wrap, getSelected: () => state.selected };
  }

  _buildFilterFieldsControls(rule) {
    rule = rule || {};
    const wrap = document.createElement("div");
    wrap.className = "cc-filter-fields open";
    wrap.style.background = "transparent";
    wrap.style.padding = "0";

    const fieldSelect = document.createElement("select");
    ["any", "summary", "description", "location"].forEach((f) => {
      const opt = document.createElement("option");
      opt.value = f;
      opt.textContent = f === "any" ? "Titel + beskrivning + plats" : f;
      if ((rule.field || "any") === f) opt.selected = true;
      fieldSelect.appendChild(opt);
    });

    const includeInput = document.createElement("input");
    includeInput.type = "text";
    includeInput.placeholder = "Inkludera bara event som innehåller (t.ex. Zoo, Djurpark)";
    includeInput.value = (rule.include || []).join(", ");

    const excludeInput = document.createElement("input");
    excludeInput.type = "text";
    excludeInput.placeholder = "Uteslut event som innehåller (t.ex. Zoo, Privat)";
    excludeInput.value = (rule.exclude || []).join(", ");

    const regexLabel = document.createElement("label");
    const regexCb = document.createElement("input");
    regexCb.type = "checkbox";
    regexCb.checked = !!rule.use_regex;
    regexLabel.appendChild(regexCb);
    regexLabel.append(" Tolka orden som regex-mönster");

    const caseLabel = document.createElement("label");
    const caseCb = document.createElement("input");
    caseCb.type = "checkbox";
    caseCb.checked = !!rule.case_sensitive;
    caseLabel.appendChild(caseCb);
    caseLabel.append(" Skiftlägeskänslig");

    wrap.appendChild(fieldSelect);
    wrap.appendChild(includeInput);
    wrap.appendChild(excludeInput);
    wrap.appendChild(regexLabel);
    wrap.appendChild(caseLabel);

    return {
      element: wrap,
      getValues: () => ({
        field: fieldSelect.value,
        include: includeInput.value,
        exclude: excludeInput.value,
        use_regex: regexCb.checked,
        case_sensitive: caseCb.checked,
      }),
    };
  }

  _buildFeedBox(entry) {
    const box = document.createElement("div");
    if (!entry.feed_url) {
      const warn = document.createElement("div");
      warn.className = "cc-warning";
      warn.textContent =
        'Ingen "Home Assistant-URL" är konfigurerad (Inställningar → System → Nätverk), så länken kan inte visas fullständigt än.';
      box.appendChild(warn);
      return box;
    }

    const label = document.createElement("div");
    label.style.fontSize = "12px";
    label.style.color = "var(--secondary-text-color)";
    label.textContent = "Prenumerationslänk (lägg till i valfri kalenderapp via \"lägg till via URL\"):";
    box.appendChild(label);

    [
      { value: entry.feed_url, title: "https-länk" },
      { value: entry.feed_url_webcal, title: "webcal-länk (för appar som föredrar det schemat)" },
    ].forEach(({ value, title }) => {
      const row = document.createElement("div");
      row.className = "cc-feed-row";
      const input = document.createElement("input");
      input.type = "text";
      input.readOnly = true;
      input.value = value;
      input.title = title;
      input.onclick = () => input.select();
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "secondary";
      copyBtn.textContent = "Kopiera";
      copyBtn.onclick = async () => {
        try {
          await navigator.clipboard.writeText(value);
          copyBtn.textContent = "Kopierad!";
        } catch (err) {
          input.select();
          copyBtn.textContent = "Markerad";
        }
        setTimeout(() => (copyBtn.textContent = "Kopiera"), 1500);
      };
      row.appendChild(input);
      row.appendChild(copyBtn);
      box.appendChild(row);
    });

    return box;
  }

  _buildActivityLogBox(entryId) {
    const box = document.createElement("div");

    const title = document.createElement("div");
    title.className = "cc-section-title";
    title.textContent = "Senaste händelser";
    box.appendChild(title);

    const list = document.createElement("div");
    list.className = "cc-log-list";
    list.textContent = "Laddar…";
    box.appendChild(list);

    this._hass
      .callWS({ type: "cal_combiner/get_activity_log", entry_id: entryId })
      .then((resp) => {
        list.innerHTML = "";
        if (!resp.entries.length) {
          const empty = document.createElement("div");
          empty.className = "cc-chip-empty";
          empty.textContent = "Inga händelser ännu";
          list.appendChild(empty);
          return;
        }
        resp.entries.forEach((item) => {
          const row = document.createElement("div");
          row.className = "cc-log-row";
          const time = document.createElement("span");
          time.className = "cc-log-time";
          time.textContent = new Date(item.time).toLocaleString();
          const msg = document.createElement("span");
          msg.textContent = item.message;
          row.appendChild(time);
          row.appendChild(msg);
          list.appendChild(row);
        });
      })
      .catch((err) => {
        list.textContent = "Kunde inte hämta händelser";
        console.warn("Cal Combiner: kunde inte hämta aktivitetslogg", err);
      });

    return box;
  }

  _renderFilterBlock(entry, sourceEntityId) {
    const key = `${entry.entry_id}::${sourceEntityId}`;
    const box = document.createElement("div");
    box.className = "cc-source-block";

    const toggle = document.createElement("button");
    toggle.className = "cc-filter-toggle";
    const rule = (entry.filters || {})[sourceEntityId];
    toggle.textContent = `${this._calendarName(sourceEntityId)} ${rule ? "(filter aktivt)" : "(inget filter)"}`;
    box.appendChild(toggle);

    const filterControls = this._buildFilterFieldsControls(rule);
    filterControls.element.classList.toggle("open", !!this._openFilters[key]);
    filterControls.element.style.background = "";
    filterControls.element.style.padding = "";

    const actions = document.createElement("div");
    actions.className = "cc-actions";

    const saveBtn = document.createElement("button");
    saveBtn.textContent = "Spara filter";
    saveBtn.onclick = async () => {
      const values = filterControls.getValues();
      const include = values.include.split(",").map((s) => s.trim()).filter(Boolean);
      const exclude = values.exclude.split(",").map((s) => s.trim()).filter(Boolean);
      const filter =
        include.length || exclude.length
          ? { field: values.field, include, exclude, use_regex: values.use_regex, case_sensitive: values.case_sensitive }
          : null;
      await this._hass.callWS({
        type: "cal_combiner/update_filter",
        entry_id: entry.entry_id,
        source_entity_id: sourceEntityId,
        filter,
      });
      this._openFilters[key] = true;
      await this._reload();
    };

    const clearBtn = document.createElement("button");
    clearBtn.className = "secondary";
    clearBtn.textContent = "Ta bort filter";
    clearBtn.onclick = async () => {
      await this._hass.callWS({
        type: "cal_combiner/update_filter",
        entry_id: entry.entry_id,
        source_entity_id: sourceEntityId,
        filter: null,
      });
      await this._reload();
    };

    actions.appendChild(saveBtn);
    actions.appendChild(clearBtn);
    filterControls.element.appendChild(actions);

    toggle.onclick = () => {
      this._openFilters[key] = !this._openFilters[key];
      filterControls.element.classList.toggle("open", this._openFilters[key]);
    };

    box.appendChild(filterControls.element);
    return box;
  }

  // ---- calendars tab ----

  _renderEntryCard(entry) {
    const card = document.createElement("div");
    card.className = "cc-card";

    const header = document.createElement("div");
    header.className = "cc-card-header";
    const icon = document.createElement("ha-icon");
    icon.setAttribute("icon", entry.icon || "mdi:calendar-multiple");
    header.appendChild(icon);
    if (entry.picture) {
      const avatar = document.createElement("img");
      avatar.className = "cc-avatar";
      avatar.src = entry.picture;
      header.appendChild(avatar);
    }
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.className = "cc-name";
    nameInput.value = entry.name;
    header.appendChild(nameInput);
    card.appendChild(header);

    const ownBox = document.createElement("div");
    ownBox.className = "cc-own-box";
    ownBox.innerHTML = `<ha-icon icon="mdi:pencil-circle"></ha-icon>`;
    const ownText = document.createElement("span");
    ownText.textContent =
      "Nya event du lägger till här (eller via HA:s kalendervy) sparas direkt i den här kalendern.";
    ownBox.appendChild(ownText);
    card.appendChild(ownBox);

    const iconLabel = document.createElement("div");
    iconLabel.className = "cc-section-title";
    iconLabel.textContent = "Ikon";
    card.appendChild(iconLabel);
    const iconPicker = this._buildIconPicker(entry.icon);
    card.appendChild(iconPicker.element);

    const pictureLabel = document.createElement("div");
    pictureLabel.className = "cc-section-title";
    pictureLabel.textContent = "Bild";
    card.appendChild(pictureLabel);
    const picturePicker = this._buildPicturePicker(entry.picture);
    card.appendChild(picturePicker.element);

    const sourcesLabel = document.createElement("div");
    sourcesLabel.className = "cc-section-title";
    sourcesLabel.textContent = "Extra källkalendrar att slå ihop";
    card.appendChild(sourcesLabel);
    const sourcePicker = this._buildSourcePicker(entry.sources);
    card.appendChild(sourcePicker.element);

    const errorBox = document.createElement("div");
    errorBox.className = "cc-error";
    card.appendChild(errorBox);

    const actions = document.createElement("div");
    actions.className = "cc-actions";

    const saveBtn = document.createElement("button");
    saveBtn.textContent = "Spara";
    saveBtn.onclick = async () => {
      errorBox.textContent = "";
      try {
        await this._hass.callWS({
          type: "cal_combiner/update_entry",
          entry_id: entry.entry_id,
          name: nameInput.value || entry.name,
          sources: sourcePicker.getSelected(),
          icon: iconPicker.getValue(),
          picture: picturePicker.getValue(),
        });
        await this._reload();
      } catch (err) {
        errorBox.textContent = err.message || "Kunde inte spara ändringarna";
      }
    };

    const deleteBtn = document.createElement("button");
    deleteBtn.className = "danger";
    deleteBtn.textContent = "Ta bort kalender";
    deleteBtn.onclick = async () => {
      if (!confirm(`Ta bort "${entry.name}" och dess egen kalender? Detta går inte att ångra.`)) return;
      await this._hass.callWS({ type: "cal_combiner/delete_entry", entry_id: entry.entry_id });
      await this._reload();
    };

    actions.appendChild(saveBtn);
    actions.appendChild(deleteBtn);
    card.appendChild(actions);

    const filterHeader = document.createElement("div");
    filterHeader.className = "cc-section-title";
    filterHeader.textContent = "Filter per källa";
    card.appendChild(filterHeader);
    entry.sources.forEach((sourceId) => card.appendChild(this._renderFilterBlock(entry, sourceId)));

    const feedLabel = document.createElement("div");
    feedLabel.className = "cc-section-title";
    feedLabel.textContent = "Dela kalendern (prenumerera, read-only)";
    card.appendChild(feedLabel);
    card.appendChild(this._buildFeedBox(entry));

    const caldavHint = document.createElement("div");
    caldavHint.className = "cc-warning";
    caldavHint.textContent =
      'Vill du redigera event direkt i kalenderappen istället? Kryssa i den här kalendern under fliken "Server".';
    card.appendChild(caldavHint);

    card.appendChild(this._buildActivityLogBox(entry.entry_id));

    return card;
  }

  _renderNewEntryCard() {
    const card = document.createElement("div");
    card.className = "cc-card cc-new-card";

    const title = document.createElement("div");
    title.className = "cc-section-title";
    title.textContent = "Skapa ny sammanslagen kalender";
    card.appendChild(title);

    const nameRow = document.createElement("div");
    nameRow.className = "cc-row";
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.placeholder = "Namn, t.ex. Familj eller Jobb";
    nameRow.appendChild(nameInput);
    card.appendChild(nameRow);

    const iconLabel = document.createElement("div");
    iconLabel.className = "cc-section-title";
    iconLabel.textContent = "Ikon";
    card.appendChild(iconLabel);
    const iconPicker = this._buildIconPicker("");
    card.appendChild(iconPicker.element);

    const pictureLabel = document.createElement("div");
    pictureLabel.className = "cc-section-title";
    pictureLabel.textContent = "Bild";
    card.appendChild(pictureLabel);
    const picturePicker = this._buildPicturePicker("");
    card.appendChild(picturePicker.element);

    const sourcesLabel = document.createElement("div");
    sourcesLabel.className = "cc-section-title";
    sourcesLabel.textContent = "Extra källkalendrar (valfritt, går att lägga till senare)";
    card.appendChild(sourcesLabel);
    const sourcePicker = this._buildSourcePicker([]);
    card.appendChild(sourcePicker.element);

    const errorBox = document.createElement("div");
    errorBox.className = "cc-error";
    card.appendChild(errorBox);

    const createBtn = document.createElement("button");
    createBtn.textContent = "Skapa kalender";
    createBtn.onclick = async () => {
      errorBox.textContent = "";
      if (!nameInput.value.trim()) {
        errorBox.textContent = "Ange ett namn";
        return;
      }
      try {
        const result = await this._hass.callWS({
          type: "cal_combiner/create_entry",
          name: nameInput.value.trim(),
          sources: sourcePicker.getSelected(),
          icon: iconPicker.getValue(),
          picture: picturePicker.getValue(),
        });
        this._activeCalendarKey = result.entry_id;
        await this._reload();
      } catch (err) {
        errorBox.textContent = err.message || "Kunde inte skapa kalendern";
      }
    };
    card.appendChild(createBtn);

    return card;
  }

  // ---- server tab (shared CalDAV account) ----

  _renderServerTab() {
    const wrap = document.createElement("div");

    const card = document.createElement("div");
    card.className = "cc-card";

    const title = document.createElement("div");
    title.className = "cc-section-title";
    title.textContent = "CalDAV-konto (redigera direkt i kalenderappen)";
    card.appendChild(title);

    const info = document.createElement("p");
    info.className = "subtitle";
    info.style.marginBottom = "8px";
    info.textContent =
      'Lägg till ETT CalDAV-konto (Apple Kalender, Thunderbird, DAVx5 på Android) med uppgifterna nedan - varje kryssad kalender nedan dyker upp som en egen kalender i appen. Google Kalender saknar stöd för externa CalDAV-konton och kan bara prenumerera read-only (se varje kalenders "Dela kalendern"-länk under fliken Kalendrar).';
    card.appendChild(info);

    const fieldsBox = document.createElement("div");
    fieldsBox.textContent = "Laddar…";
    card.appendChild(fieldsBox);

    const calListLabel = document.createElement("div");
    calListLabel.className = "cc-section-title";
    calListLabel.textContent = "Kalendrar i CalDAV-kontot";
    card.appendChild(calListLabel);

    const calList = document.createElement("div");
    calList.textContent = "Laddar…";
    card.appendChild(calList);

    const errorBox = document.createElement("div");
    errorBox.className = "cc-error";
    card.appendChild(errorBox);

    const saveBtn = document.createElement("button");
    saveBtn.textContent = "Spara vilka kalendrar som ingår";
    saveBtn.style.display = "none";

    this._hass
      .callWS({ type: "cal_combiner/get_caldav_settings" })
      .then((resp) => {
        fieldsBox.innerHTML = "";
        if (!resp.server_url) {
          const warn = document.createElement("div");
          warn.className = "cc-warning";
          warn.textContent =
            'Ingen "Home Assistant-URL" är konfigurerad (Inställningar → System → Nätverk), så CalDAV-kontot kan inte visas fullständigt än.';
          fieldsBox.appendChild(warn);
        } else {
          [
            { value: resp.server_url, title: "Server-URL" },
            { value: "cal_combiner", title: "Användarnamn (valfritt värde)" },
            { value: resp.password, title: "Lösenord" },
          ].forEach(({ value, title }) => {
            const row = document.createElement("div");
            row.className = "cc-feed-row";
            const fieldLabel = document.createElement("span");
            fieldLabel.className = "cc-caldav-field-label";
            fieldLabel.textContent = title;
            const input = document.createElement("input");
            input.type = "text";
            input.readOnly = true;
            input.value = value;
            input.onclick = () => input.select();
            const copyBtn = document.createElement("button");
            copyBtn.type = "button";
            copyBtn.className = "secondary";
            copyBtn.textContent = "Kopiera";
            copyBtn.onclick = async () => {
              try {
                await navigator.clipboard.writeText(value);
                copyBtn.textContent = "Kopierad!";
              } catch (err) {
                input.select();
                copyBtn.textContent = "Markerad";
              }
              setTimeout(() => (copyBtn.textContent = "Kopiera"), 1500);
            };
            row.appendChild(fieldLabel);
            row.appendChild(input);
            row.appendChild(copyBtn);
            fieldsBox.appendChild(row);
          });
        }

        calList.innerHTML = "";
        if (!resp.calendars.length) {
          const empty = document.createElement("div");
          empty.className = "cc-chip-empty";
          empty.textContent = "Inga sammanslagna kalendrar skapade ännu";
          calList.appendChild(empty);
          return;
        }

        const checkboxes = [];
        resp.calendars.forEach((cal) => {
          const row = document.createElement("label");
          row.className = "cc-check-row";
          const cb = document.createElement("input");
          cb.type = "checkbox";
          cb.checked = resp.included.includes(cal.entry_id);
          cb.dataset.entryId = cal.entry_id;
          checkboxes.push(cb);
          row.appendChild(cb);
          row.append(cal.name);
          calList.appendChild(row);
        });

        saveBtn.style.display = "inline-block";
        saveBtn.onclick = async () => {
          errorBox.textContent = "";
          const included = checkboxes.filter((cb) => cb.checked).map((cb) => cb.dataset.entryId);
          try {
            await this._hass.callWS({ type: "cal_combiner/set_caldav_included", included });
            saveBtn.textContent = "Sparat!";
            setTimeout(() => (saveBtn.textContent = "Spara vilka kalendrar som ingår"), 1500);
          } catch (err) {
            errorBox.textContent = err.message || "Kunde inte spara";
          }
        };
      })
      .catch((err) => {
        fieldsBox.textContent = "Kunde inte hämta CalDAV-inställningar";
        calList.textContent = "";
        console.warn("Cal Combiner: kunde inte hämta CalDAV-inställningar", err);
      });

    card.appendChild(saveBtn);
    wrap.appendChild(card);
    return wrap;
  }
}

customElements.define("cal-combiner-panel", CalCombinerPanel);
