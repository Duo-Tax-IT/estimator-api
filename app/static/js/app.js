
    // ============================== CORE: dom refs, shared state, money + live room-scaling ==============================
    const $ = (id) => document.getElementById(id);
    const qEl = $("q"), sugEl = $("suggestions"), statusEl = $("status"),
          errorEl = $("error"), resultEl = $("result");

    let debounce;
    let activeQuery = "";
    let lastSelected = null;  // the picked suggestion, for the prompt-preview panel
    let lastVersion = "v1";   // which pipeline produced the shown result, for the prompt preview
    let lastResultData = null;  // the last rendered result dict, for live room-scale re-render

    // Money helpers (module-scope so totals can be recomputed live).
    const parseMoney = (s) => Number(String(s ?? "").replace(/[$,]/g, "")) || 0;
    const fmtMoney = (n) => "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    // Live room-scale multipliers from the settings inputs (blank = omitted),
    // and the multiplier that applies to a given renovation row by its RoomType.
    const roomScale = () => {
      const m = {};
      for (const [room, id] of [["bathroom", "scaleBathroom"], ["kitchen", "scaleKitchen"]]) {
        const v = $(id).value.trim();
        if (v !== "") m[room] = Number(v);
      }
      return m;
    };
    // A renovation's room type — from the backend `RoomType` when present, else
    // derived from its top-level group so live scaling works without a re-run
    // (and on older results). Kitchen variants + bathroom roll up to one type.
    const ROOM_OF_ROOT = {
      "Bathroom": "bathroom", "Bathroom - Additional Items": "bathroom",
      "Kitchen - House": "kitchen", "Kitchen - Apartment": "kitchen", "Kitchen - Additional Items": "kitchen",
      "Built-in Wardrobes": "bedroom",
    };
    const roomTypeOf = (r) =>
      r.RoomType || ROOM_OF_ROOT[(r.groupPath && r.groupPath.length) ? r.groupPath[0] : (r.parentName || r.Name || "")] || null;
    // The property attribute auto-scaling counts each room type by (mirrors the
    // backend: bathrooms→baths, bedrooms→beds; kitchens never auto-scale).
    const ROOM_COUNT_ATTR = { bathroom: "baths", bedroom: "beds" };
    const autoRooms = () => $("scaleAuto").checked;
    // A row's multiplier: a manual ×N wins; else, with "all rooms renovated" on,
    // the property's room count for that type; otherwise ×1.
    const liveCount = (r) => {
      const type = roomTypeOf(r);
      const manual = roomScale()[type];
      if (manual != null) return manual;
      const attr = autoRooms() && type ? ROOM_COUNT_ATTR[type] : null;
      const prop = lastResultData && lastResultData.Property;
      if (attr && prop) return Math.max(Number(prop[attr]) || 1, 1);
      return 1;
    };

    // Re-render the shown result from the stored data + current multipliers — no refetch.
    for (const id of ["scaleBathroom", "scaleKitchen"]) {
      $(id).addEventListener("input", () => {
        if (lastResultData && lastSelected) renderResult(lastSelected, lastResultData, lastVersion);
      });
    }
    $("scaleAuto").addEventListener("change", () => {
      if (lastResultData && lastSelected) renderResult(lastSelected, lastResultData, lastVersion);
    });

    $("overrideToggle").addEventListener("change", (e) => {
      $("overrideFields").hidden = !e.target.checked;
    });

    // Live dd/mm/yyyy formatter: keep digits only, insert slashes, and expand a
    // 2-digit year (>=50 -> 19xx, else 20xx) once day+month+yy are in.
    const expandYear = (yy) => String(+yy >= 50 ? 1900 + +yy : 2000 + +yy);

    // ============================== REQUEST INPUTS: date, override, auth header, body, prompt preview ==============================
    function formatDateInput(value) {
      const n = value.replace(/\D/g, "").slice(0, 8);
      let out = n.slice(0, 2);
      if (n.length >= 3) out += "/" + n.slice(2, 4);
      if (n.length >= 5) out += "/" + (n.length === 6 ? expandYear(n.slice(4)) : n.slice(4));
      return out;
    }

    // dd/mm/yyyy -> yyyy-mm-dd (what the backend's settlementDate expects);
    // "" until a complete date is entered.
    function settlementIso() {
      const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec($("settlementDate").value.trim());
      return m ? `${m[3]}-${m[2]}-${m[1]}` : "";
    }

    $("settlementDate").addEventListener("input", (e) => {
      e.target.value = formatDateInput(e.target.value);
    });

    // Build the property override from the ticked fields. Only non-empty fields
    // are sent, under rpdata's own keys, so the model sees the same shape it
    // would from a fetched property. Returns null when override is off/blank.
    function buildOverride() {
      if (!$("overrideToggle").checked) return null;
      const map = { beds: "ovBeds", baths: "ovBaths", carSpaces: "ovCarSpaces", yearBuilt: "ovYearBuilt" };
      const property = {};
      for (const [key, id] of Object.entries(map)) {
        const v = $(id).value.trim();
        if (v !== "") property[key] = v;
      }
      return Object.keys(property).length ? property : null;
    }

    // Shared by /estimate and /debug/prompt — the secret-sauce header is only
    // sent when the API requires one.
    function authHeaders() {
      const headers = { "Content-Type": "application/json" };
      const key = $("apiKey").value.trim();
      if (key) headers["secret-sauce"] = key;
      return headers;
    }

    // The EstimateRequest body for a picked suggestion, from the current form.
    function buildBody(s) {
      const body = { rpId: String(s.suggestionId) };
      if (s.suggestion) body.address = s.suggestion;
      const override = buildOverride();
      if (override) body.property = override;
      const model = $("model").value.trim();
      if (model) body.model = model;
      const effort = $("reasoningEffort").value;
      if (effort) body.reasoningEffort = effort;
      const temp = $("temperature").value.trim();
      if (temp !== "") body.temperature = Number(temp);
      const label = $("label").value.trim();
      if (label) body.label = label;
      const settlement = settlementIso();
      if (settlement) body.settlementDate = settlement;
      // Room-scaling config (pricing-only; kept out of the prompt). Manual
      // multipliers + the auto "all rooms renovated" flag. Applied live client-side too.
      const scale = roomScale();
      const config = {};
      if (Object.keys(scale).length) config.roomScale = scale;
      if (autoRooms()) config.assumeAllRoomsRenovated = true;
      if (Object.keys(config).length) body.config = config;
      return body;
    }

    // Fetch the assembled prompt (template + injected input) for the selection.
    // Lazy: runs when the panel is opened, so settings changes are reflected.
    async function previewPrompt() {
      if (!lastSelected) return;
      const pre = $("promptText");
      pre.textContent = "Loading…";
      try {
        const resp = await fetch(lastVersion === "v2" ? "/debug/prompt/v2" : "/debug/prompt", {
          method: "POST",
          headers: authHeaders(),
          body: JSON.stringify(buildBody(lastSelected)),
        });
        const text = await resp.text();
        pre.textContent = resp.ok ? text : `Error (${resp.status}): ${text}`;
      } catch (e) {
        pre.textContent = e.message;
      }
    }
    $("promptWrap").addEventListener("toggle", (e) => { if (e.target.open) previewPrompt(); });

    function showStatus(msg) {
      statusEl.innerHTML = msg ? `<span class="spinner"></span><span>${msg}</span>` : "";
      statusEl.hidden = !msg;
    }
    function showError(msg) {
      errorEl.textContent = msg || "";
      errorEl.hidden = !msg;
    }

    // ============================== ADDRESS SEARCH ==============================
    function clearSuggestions() { sugEl.innerHTML = ""; sugEl.hidden = true; }
    function setSearching(on) { $("searchSpin").hidden = !on; }

    qEl.addEventListener("input", () => {
      const q = qEl.value.trim();
      activeQuery = q;
      clearTimeout(debounce);
      showError("");
      if (q.length < 3) { setSearching(false); clearSuggestions(); return; }
      // Immediate feedback while the debounce + request are in flight.
      setSearching(true);
      sugEl.innerHTML = `<div class="hint">Searching…</div>`;
      sugEl.hidden = false;
      debounce = setTimeout(() => runSearch(q), 300);
    });

    async function runSearch(q) {
      try {
        const resp = await fetch(`/search?q=${encodeURIComponent(q)}`);
        if (q !== activeQuery) return; // a newer keystroke won
        if (!resp.ok) throw new Error((await resp.json()).detail || `Search failed (${resp.status})`);
        const { suggestions } = await resp.json();
        renderSuggestions(suggestions || []);
      } catch (e) {
        clearSuggestions();
        showError(e.message);
      } finally {
        if (q === activeQuery) setSearching(false);
      }
    }

    function renderSuggestions(items) {
      if (!items.length) {
        sugEl.innerHTML = `<div class="empty">No matching addresses.</div>`;
        sugEl.hidden = false;
        return;
      }
      sugEl.innerHTML = "";
      for (const s of items) {
        const div = document.createElement("div");
        div.className = "item";
        const badge = s.isUnit ? "Unit" : (s.suggestionType || "address");
        div.innerHTML = `<span class="addr"></span><span class="badge"></span>`;
        div.querySelector(".addr").textContent = s.suggestion;
        div.querySelector(".badge").textContent = badge;
        div.addEventListener("click", () => selectSuggestion(s));
        sugEl.appendChild(div);
      }
      sugEl.hidden = false;
    }

    // Mark a property as picked: show it, enable the run buttons, load photos.
    // Running is a separate step (the Run v1 / Run v2 buttons).
    function markSelected(s) {
      lastSelected = s;
      $("picked").innerHTML = `Selected <strong></strong> &nbsp;·&nbsp; rp_id ${s.suggestionId} — choose a version to run`;
      $("picked").querySelector("strong").textContent = s.suggestion;
      $("picked").hidden = false;
      $("runV1").disabled = false;
      $("runV2").disabled = false;
    }

    function selectSuggestion(s) {
      clearSuggestions();
      qEl.value = s.suggestion;
      activeQuery = s.suggestion;
      resultEl.classList.remove("show");
      showError("");
      showStatus("");
      markSelected(s);
      // Photos load now so they're ready before/while running.
      loadPhotos(s.suggestionId);
    }

    // Run the picked property through a pipeline. `version` only picks the
    // endpoint ("v1" -> /estimate, "v2" -> /estimate/v2); the body is identical.

    // ============================== ESTIMATE: run + render result + renovations table ==============================
    async function runEstimate(version) {
      if (!lastSelected) return;
      const s = lastSelected;
      resultEl.classList.remove("show");
      showError("");
      showStatus("Thinking…");
      try {
        const resp = await fetch(version === "v2" ? "/estimate/v2" : "/estimate", {
          method: "POST",
          headers: authHeaders(),
          body: JSON.stringify(buildBody(s)),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || `Estimate failed (${resp.status})`);
        lastResultData = data;  // stored so room-scale edits re-render without a refetch
        renderResult(s, data, version);
        loadRuns(s.suggestionId);  // refresh the saved-runs panel (incl. this run)
      } catch (e) {
        showError(e.message);
      } finally {
        showStatus("");
      }
    }
    $("runV1").addEventListener("click", () => runEstimate("v1"));
    $("runV2").addEventListener("click", () => runEstimate("v2"));

    function renderResult(s, data, version) {
      // Fall back to detecting the pipeline from the payload (v2 carries Stages).
      const ver = version || (data.Stages ? "v2" : "v1");
      lastVersion = ver;  // so the prompt-preview panel fetches the matching pipeline's prompt
      $("selected").innerHTML = `Showing estimate for <strong></strong> &nbsp;·&nbsp; rp_id ${s.suggestionId} &nbsp;·&nbsp; ${ver}`;
      $("selected").querySelector("strong").textContent = s.suggestion;

      // Totals are computed client-side from each row's base cost × its live
      // room multiplier, so the room-scale inputs update them instantly.
      const renos = data["Renovations"] || [];
      $("total").textContent = fmtMoney(renos.reduce((t, r) => t + parseMoney(r.FinalCost) * liveCount(r), 0));
      const hasOwnerSplit = data["Previous Owner Total"] != null;
      $("ownerTotals").hidden = !hasOwnerSplit;
      if (hasOwnerSplit) {
        const owner = (name) => fmtMoney(renos
          .filter((r) => r.Owner === name)
          .reduce((t, r) => t + parseMoney(r.FinalCost) * liveCount(r), 0));
        $("prevOwnerTotal").textContent = owner("Previous Owner");
        $("currOwnerTotal").textContent = owner("Current Owner");
      }

      const summary = data["Summary Description"] || "";
      $("summary").textContent = summary;
      $("summaryWrap").hidden = !summary;

      const debug = { Property: data.Property ?? null, GFA: data.GFA ?? null };
      $("debugJson").textContent = JSON.stringify(debug, null, 2);
      $("debugWrap").hidden = false;

      // Collapse so the prompt re-fetches (with current settings) when re-opened.
      $("promptWrap").open = false;
      $("promptWrap").hidden = false;

      // v2 returns per-stage outputs for debugging; v1 has none.
      if (data.Stages) {
        $("stagesJson").textContent = JSON.stringify(data.Stages, null, 2);
        $("stagesWrap").open = false;
        $("stagesWrap").hidden = false;
      } else {
        $("stagesWrap").hidden = true;
      }

      $("tableWrap").innerHTML = renovationsTableHtml(renos);
      $("disclaimer").textContent = data["Disclaimer"] || "";
      resultEl.classList.add("show");
    }

    // Renovations as a grouped table (by parent). Shared by the result view and
    // the run-details modal. Empty list renders a friendly "none" message.
    function renovationsTableHtml(renos) {
      if (!renos.length) {
        return `<div class="none">No depreciable renovations were detected from the property's photos.</div>`;
      }
      const pad = (d) => `style="padding-left:${14 + d * 20}px"`;
      // Full ancestor path per row (root → immediate parent); older runs only
      // carry parentName, so fall back to a single level.
      const pathOf = (r) => (r.groupPath && r.groupPath.length) ? r.groupPath : (r.parentName ? [r.parentName] : []);

      // Cost of every group's whole subtree, keyed by its joined path.
      const sub = {};
      for (const r of renos) {
        const p = pathOf(r), c = parseMoney(r.FinalCost);
        for (let d = 0; d < p.length; d++) {
          const k = p.slice(0, d + 1).join(" › ");
          sub[k] = (sub[k] || 0) + c;
        }
      }
      // Live room scaling: the manual multiplier for a row's RoomType (from the
      // settings inputs). Line items stay one room's worth; the ×N shows on the
      // top-level group (or inline for a flat item) and the subtotal/total reflect it.
      const rootCount = {};
      for (const r of renos) {
        const n = liveCount(r);
        if (n !== 1) {
          const root = pathOf(r).length ? pathOf(r)[0] : (r.Name ?? "");
          rootCount[root] = { count: n, of: roomTypeOf(r) || "" };
        }
      }
      const badge = (root) => rootCount[root]
        ? ` <span class="help">× ${rootCount[root].count} ${escapeHtml(rootCount[root].of)}</span>` : "";

      // Walk in order, opening a nested header each time the path deepens/changes.
      const rows = [];
      let last = [];
      for (const r of renos) {
        const p = pathOf(r);
        let common = 0;
        while (common < p.length && common < last.length && p[common] === last[common]) common++;
        for (let d = common; d < p.length; d++) {
          const key = p.slice(0, d + 1).join(" › ");
          const anc = p.slice(0, d).join(" › ");  // groups this header sits inside
          const cnt = d === 0 && rootCount[p[0]] ? rootCount[p[0]].count : 1;  // scale top level only
          rows.push(
            `<tr class="group" data-gk="${escapeHtml(key)}" data-anc="${escapeHtml(anc)}" onclick="toggleRenoGroup(this)">` +
            `<td class="gname" colspan="6" ${pad(d)}>${escapeHtml(p[d])}${d === 0 ? badge(p[0]) : ""}</td>` +
            `<td class="num">${fmtMoney(sub[key] * cnt)}</td></tr>`
          );
        }
        last = p;
        // A flat (ungrouped) row scales inline, since it has no header to carry the ×count.
        const n = liveCount(r);
        const flatScaled = p.length === 0 && n !== 1;
        rows.push(
          `<tr class="gitem" data-anc="${escapeHtml(p.join(" › "))}">` +
          `<td ${pad(p.length)}>${escapeHtml(r.Name ?? "")}${flatScaled ? badge(r.Name ?? "") : ""}</td>` +
          `<td>${escapeHtml(r.Year ?? "")}</td>` +
          `<td>${escapeHtml(r.Owner ?? "")}</td>` +
          `<td class="num">${escapeHtml(String(r.Quantity ?? ""))}</td>` +
          `<td>${escapeHtml(r.Unit ?? "")}</td>` +
          `<td class="num">${escapeHtml(r.DefaultRate ?? "")}</td>` +
          `<td class="num">${flatScaled ? fmtMoney(parseMoney(r.FinalCost) * n) : escapeHtml(r.FinalCost ?? "")}</td></tr>`
        );
      }
      return `
        <table>
          <thead>
            <tr>
              <th>Renovation</th><th>Year</th><th>Owner</th>
              <th class="num">Qty</th><th>Unit</th>
              <th class="num">Rate</th><th class="num">Cost</th>
            </tr>
          </thead>
          <tbody>${rows.join("")}</tbody>
        </table>`;
    }

    // Collapse/expand a group's whole subtree. Visibility is recomputed from the
    // set of collapsed groups, so nested collapse/expand can't drift out of sync:
    // a row hides when any collapsed group is one of its ancestors.
    function toggleRenoGroup(row) {
      row.classList.toggle("collapsed");
      const table = row.closest("table");
      const collapsed = [...table.querySelectorAll("tr.group.collapsed")].map((g) => g.dataset.gk);
      const hidden = (anc) => collapsed.some((k) => anc === k || anc.startsWith(k + " › "));
      table.querySelectorAll("tr.group, tr.gitem")
        .forEach((tr) => { tr.hidden = hidden(tr.dataset.anc || ""); });
    }

    // ---- Saved runs (version comparison) ----

    // ============================== HISTORY & SAVED RUNS: runs table, history view, run modal, compare ==============================
    async function loadRuns(rpId) {
      try {
        const resp = await fetch(`/runs?rpId=${encodeURIComponent(rpId)}`);
        if (!resp.ok) return; // non-fatal
        const { runs } = await resp.json();
        renderRuns(runs || []);
      } catch { /* non-fatal */ }
    }

    function runsTableHtml(runs) {
      const rows = runs.map((r) => {
        const resp = r.response || {};
        const renos = resp.Renovations || [];
        const names = renos.map((x) => x.Name).filter(Boolean).join(", ");
        const settings = [r.reasoning_effort, r.temperature != null ? `temp ${r.temperature}` : ""]
          .filter(Boolean).join(" · ");
        const when = (r.created_at || "").replace("T", " ").slice(0, 16);
        return `
          <tr style="cursor:pointer" title="Open run details" onclick="openRunDetails(${r.id})">
            <td>${escapeHtml(when)}</td>
            <td>${escapeHtml(r.label || "—")}</td>
            <td>${escapeHtml(r.model || "")}</td>
            <td>${escapeHtml(settings)}</td>
            <td class="num">${escapeHtml(resp["Renovations Total"] || "")}</td>
            <td>${renos.length}<div class="help">${escapeHtml(names)}</div></td>
          </tr>`;
      }).join("");
      return `
        <table>
          <thead><tr>
            <th>When</th><th>Label</th><th>Model</th><th>Settings</th>
            <th class="num">Total</th><th>Items</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>`;
    }

    let savedRuns = [];
    function renderRuns(runs) {
      savedRuns = runs;
      if (!runs.length) { $("runsWrap").hidden = true; return; }
      $("runsBody").innerHTML = runsTableHtml(runs);
      $("runsWrap").hidden = false;
    }

    // ---- History view (all saved runs; filter by property id) ----
    async function loadHistory() {
      const rpId = $("histFilter").value.trim();
      const url = rpId ? `/runs?rpId=${encodeURIComponent(rpId)}` : "/runs";
      $("historyBody").innerHTML = `<div class="none">Loading…</div>`;
      try {
        const { runs } = await (await fetch(url)).json();
        renderHistory(runs || []);
      } catch {
        $("historyBody").innerHTML = `<div class="none">Could not load runs.</div>`;
      }
    }

    let historyRuns = [];
    function renderHistory(runs) {
      historyRuns = runs;
      $("compareBody").innerHTML = "";
      if (!runs.length) { $("historyBody").innerHTML = `<div class="none">No saved runs yet.</div>`; return; }
      $("historyBody").innerHTML = runs.map((r) => {
        const resp = r.response || {};
        const renos = resp.Renovations || [];
        const settings = [r.reasoning_effort, r.temperature != null ? `temp ${r.temperature}` : ""]
          .filter(Boolean).join(" · ");
        const when = (r.created_at || "").replace("T", " ").slice(0, 16);
        const head = [when, r.address || `rp ${r.rp_id ?? ""}`, r.label || "—", r.model || "", settings, resp["Renovations Total"] || ""]
          .filter(Boolean).map(escapeHtml).join(" · ");
        const items = renos.map((x) =>
          `${escapeHtml(x.Name ?? "")} <span class="help">(${escapeHtml(String(x.Year ?? ""))}, ` +
          `${escapeHtml(String(x.Quantity ?? ""))} ${escapeHtml(x.Unit ?? "")}, ${escapeHtml(x.FinalCost ?? "")})</span>`
        ).join("<br>");
        return `
          <details class="hist-item">
            <summary><input type="checkbox" class="cmp" value="${r.id}" onclick="event.stopPropagation()" />${head} <span class="help">(${renos.length} items)</span> <button class="tab" onclick="event.stopPropagation(); openRunDetails(${r.id})">Details</button> <button class="tab" onclick="event.stopPropagation(); openRun(${r.id})">Open</button> <a class="tab" href="/photos/download?rpId=${encodeURIComponent(r.rp_id)}" onclick="event.stopPropagation()">Photos</a></summary>
            <div class="meta" style="margin-top:8px"><strong>Summary:</strong> ${escapeHtml(resp["Summary Description"] || "—")}</div>
            <div class="meta" style="margin-top:8px">${items || "<span class='help'>No items</span>"}</div>
          </details>`;
      }).join("");
    }

    // Re-open a saved run in the Estimate view — no model call, photos re-fetched by rp_id.
    function openRun(id) {
      const run = historyRuns.find((r) => r.id === id);
      if (!run) return;
      showTab("estimate");
      const s = { suggestion: run.address || `rp_id ${run.rp_id}`, suggestionId: run.rp_id };
      markSelected(s);
      loadPhotos(run.rp_id);
      lastResultData = run.response || {};  // enable live room-scale re-render
      renderResult(s, lastResultData);
      loadRuns(run.rp_id);
    }

    // ---- Run details modal (full record for one saved run) ----
    function findRun(id) { return [...historyRuns, ...savedRuns].find((r) => r.id === id); }

    function kvHtml(rows) {
      return `<div class="kv">` + rows.map(([k, v]) =>
        `<span class="k">${escapeHtml(k)}</span><span class="v">${escapeHtml(String(v))}</span>`).join("") + `</div>`;
    }

    function openRunDetails(id) {
      const run = findRun(id);
      if (!run) return;
      const r = run.response || {}, u = r.Usage;
      const meta = [
        ["When", (run.created_at || "").replace("T", " ").slice(0, 19)],
        ["Address", run.address || `rp_id ${run.rp_id}`],
        ["Property id", run.rp_id],
        ["Model", run.model || "—"],
        ["Reasoning effort", run.reasoning_effort || "—"],
        ["Temperature", run.temperature != null ? run.temperature : "—"],
        ["Label", run.label || "—"],
      ];
      const usage = (u && u.total_tokens)
        ? [["Tokens (prompt / completion / total)", `${u.prompt_tokens} / ${u.completion_tokens} / ${u.total_tokens}`],
           ["Cost (USD)", `$${Number(u.cost).toFixed(4)}`]]
        : [["Usage", "— (run predates token tracking)"]];
      const ownerSplit = r["Previous Owner Total"] != null
        ? `<div class="totalcard"><span class="label">Previous Owner</span><span class="amount">${escapeHtml(r["Previous Owner Total"])}</span>` +
          `<span class="label">Current Owner</span><span class="amount">${escapeHtml(r["Current Owner Total"])}</span></div>` : "";
      const summary = r["Summary Description"] || "";
      const debug = JSON.stringify({ Property: r.Property ?? null, GFA: r.GFA ?? null }, null, 2);
      $("runModalBody").innerHTML = `
        <h3>Run details</h3>
        ${kvHtml(meta)}
        ${kvHtml(usage)}
        <div class="totalcard"><span class="label">Renovations Total</span>` +
          `<span class="amount">${escapeHtml(r["Renovations Total"] || "$0.00")}</span></div>
        ${ownerSplit}
        ${renovationsTableHtml(r.Renovations || [])}
        ${summary ? `<div class="summary" style="margin-top:18px"><div class="label">Summary</div><div>${escapeHtml(summary)}</div></div>` : ""}
        <details class="summary" style="margin-top:14px"><summary class="label" style="cursor:pointer">Property &amp; GFA</summary><pre>${escapeHtml(debug)}</pre></details>
        ${run.prompt ? `<details class="summary" style="margin-top:14px"><summary class="label" style="cursor:pointer">Prompt sent to AI</summary><pre>${escapeHtml(run.prompt)}</pre></details>` : ""}
        ${r["Disclaimer"] ? `<div class="disclaimer">${escapeHtml(r["Disclaimer"])}</div>` : ""}`;
      $("runModal").hidden = false;
    }

    function closeRunModal() { $("runModal").hidden = true; }
    $("runModalClose").addEventListener("click", closeRunModal);
    $("runModal").addEventListener("click", (e) => { if (e.target.id === "runModal") closeRunModal(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeRunModal(); });

    // Tick 2+ runs → a matrix of items (rows) × runs (cols) with diffs highlighted.
    function selectedRuns() {
      const ids = [...document.querySelectorAll(".cmp:checked")].map((c) => Number(c.value));
      return historyRuns.filter((r) => ids.includes(r.id));
    }

    let compareRuns = [];
    function renderCompare(runs) { compareRuns = runs; drawCompare(); }

    function drawCompare() {
      const runs = compareRuns;
      if (runs.length < 2) { $("compareBody").innerHTML = `<div class="none">Tick 2+ runs to compare.</div>`; return; }
      const keys = [], seen = {};
      const maps = runs.map((r) => {
        const m = {};
        ((r.response && r.response.Renovations) || []).forEach((it) => {
          const k = it._id || it.Name;
          m[k] = it;
          if (!seen[k]) { seen[k] = true; keys.push(k); }
        });
        return m;
      });
      const diffOnly = $("diffOnly").checked;
      const colHead = runs.map((r) =>
        `<th class="num">${escapeHtml(r.label || (r.created_at || "").slice(5, 16))}</th>`).join("");
      const totalRow = `<tr><td><strong>Total</strong></td>${runs.map((r) =>
        `<td class="num"><strong>${escapeHtml(((r.response || {})["Renovations Total"]) || "")}</strong></td>`).join("")}</tr>`;
      let diffs = 0;
      const rows = keys.map((k) => {
        const item = maps.find((m) => m[k])[k];
        const costs = maps.map((m) => (m[k] ? (m[k].FinalCost ?? "") : null));
        const same = costs.every((c) => c === costs[0]);
        if (!same) diffs++;
        if (diffOnly && same) return "";
        const cells = maps.map((m) =>
          `<td class="num">${m[k] ? escapeHtml(String(m[k].FinalCost ?? "")) : "—"}</td>`).join("");
        return `<tr class="${same ? "" : "diff"}"><td>${escapeHtml(item.Name || k)}</td>${cells}</tr>`;
      }).join("");
      const note = `<div class="help" style="margin-bottom:8px">${diffs} of ${keys.length} items differ${diffOnly ? " · showing differences only" : ""}</div>`;
      $("compareBody").innerHTML = note + `
        <table style="margin-bottom:18px">
          <thead><tr><th>Item</th>${colHead}</tr></thead>
          <tbody>${totalRow}${rows}</tbody>
        </table>`;
    }
    $("histCompare").addEventListener("click", () => renderCompare(selectedRuns()));
    $("diffOnly").addEventListener("change", drawCompare);


    // ============================== TABS ==============================
    function showTab(which) {
      const hist = which === "history";
      $("estimateView").hidden = hist;
      $("historyView").hidden = !hist;
      $("tabEstimate").classList.toggle("active", !hist);
      $("tabHistory").classList.toggle("active", hist);
      if (hist) loadHistory();
    }
    $("tabEstimate").addEventListener("click", () => showTab("estimate"));
    $("tabHistory").addEventListener("click", () => showTab("history"));
    $("histRefresh").addEventListener("click", loadHistory);
    $("histFilter").addEventListener("change", loadHistory);

    // ---- Photo carousel ----
    let carouselPhotos = [], carouselIndex = 0;


    // ============================== PHOTOS: carousel + grid ==============================
    async function loadPhotos(rpId) {
      $("carousel").hidden = true;
      carouselPhotos = []; carouselIndex = 0;
      try {
        const resp = await fetch(`/photos?rpId=${encodeURIComponent(rpId)}`);
        if (!resp.ok) return; // non-fatal: the estimate still renders
        const { photos } = await resp.json();
        if (!photos || !photos.length) return;
        carouselPhotos = photos;
        $("downloadPhotos").href = `/photos/download?rpId=${encodeURIComponent(rpId)}`;
        renderCarousel();
      } catch { /* non-fatal */ }
    }

    function renderCarousel() {
      $("track").innerHTML = carouselPhotos.map((p) =>
        `<div class="slide"><img loading="lazy" alt="Property photo" src="${escapeHtml(p.url)}" /></div>`
      ).join("");
      const multi = carouselPhotos.length > 1;
      $("prevBtn").hidden = !multi;
      $("nextBtn").hidden = !multi;

      const thumbs = $("thumbs");
      thumbs.hidden = !multi;
      thumbs.innerHTML = multi
        ? carouselPhotos.map((p, i) =>
            `<img loading="lazy" alt="Photo ${i + 1}" data-index="${i}" src="${escapeHtml(p.url)}" />`
          ).join("")
        : "";

      // Reset the (lazy) "view all" grid for the new set of photos.
      $("viewAllPhotos").hidden = !multi;
      $("viewAllPhotos").textContent = "View all";
      $("photoGrid").hidden = true;
      $("photoGrid").innerHTML = "";

      carouselIndex = 0;
      updateCarousel();
      $("carousel").hidden = false;
    }

    // A numbered grid of every photo, for verifying a candidate's "Photo N" refs.
    function renderPhotoGrid() {
      $("photoGrid").innerHTML = carouselPhotos.map((p, i) =>
        `<figure data-index="${i}">` +
        `<img loading="lazy" alt="Photo ${i + 1}" src="${escapeHtml(p.url)}" />` +
        `<figcaption>Photo ${i + 1}</figcaption>` +
        (p.date ? `<span class="pdate">${escapeHtml(p.date)}</span>` : "") +
        `</figure>`
      ).join("");
    }

    $("viewAllPhotos").addEventListener("click", (e) => {
      e.preventDefault();
      const grid = $("photoGrid");
      const show = grid.hidden;
      if (show && !grid.innerHTML) renderPhotoGrid();
      grid.hidden = !show;
      $("viewAllPhotos").textContent = show ? "Hide all" : "View all";
    });

    // Click a grid photo → jump the carousel to it.
    $("photoGrid").addEventListener("click", (e) => {
      const fig = e.target.closest("figure");
      if (!fig) return;
      carouselIndex = Number(fig.dataset.index);
      updateCarousel();
      $("carousel").scrollIntoView({ behavior: "smooth", block: "start" });
    });

    function updateCarousel() {
      $("track").style.transform = `translateX(-${carouselIndex * 100}%)`;
      const p = carouselPhotos[carouselIndex];
      $("carouselCounter").textContent = `${carouselIndex + 1} / ${carouselPhotos.length}`;
      $("carouselDate").textContent = p && p.date ? p.date : "";

      const thumbs = $("thumbs").children;
      for (let i = 0; i < thumbs.length; i++) {
        const active = i === carouselIndex;
        thumbs[i].classList.toggle("active", active);
        if (active) thumbs[i].scrollIntoView({ block: "nearest", inline: "nearest" });
      }
    }

    $("thumbs").addEventListener("click", (e) => {
      const idx = e.target.dataset && e.target.dataset.index;
      if (idx === undefined) return;
      carouselIndex = Number(idx);
      updateCarousel();
    });

    function moveCarousel(delta) {
      const n = carouselPhotos.length;
      if (!n) return;
      carouselIndex = (carouselIndex + delta + n) % n;
      updateCarousel();
    }
    $("prevBtn").addEventListener("click", () => moveCarousel(-1));
    $("nextBtn").addEventListener("click", () => moveCarousel(1));


    // ============================== UTILITIES ==============================
    function escapeHtml(str) {
      return String(str).replace(/[&<>"']/g, (c) => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
      ));
    }

    // Dismiss the suggestions dropdown when clicking outside the search box.
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".search")) clearSuggestions();
    });
