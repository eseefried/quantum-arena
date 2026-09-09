(() => {
  "use strict";

  const DATASETS = ["Overall", "QiskitHumanEval", "QiskitHumanEvalHard", "QuanBench44", "QuanBench117", "QCoder"];
  const METRICS = [
    { key: "pass_at_1", label: "Pass@1" },
    { key: "pass_at_3", label: "Pass@3" },
    { key: "pass_at_5", label: "Pass@5" },
  ];

  const VIEWS = [
    { key: "leaderboard", label: "Leaderboard" },
    { key: "problems", label: "Problem View" },
  ];

  // Display-only relabeling — filtering still runs on the real dataset/category
  // values (DATASETS entries, and the category strings in leaderboard_details.json).
  const DATASET_LABELS = {
    QiskitHumanEval: "Qiskit HumanEval",
    QiskitHumanEvalHard: "Qiskit HumanEval Hard",
    QuanBench44: "QuanBench-44",
    QuanBench117: "QuanBench-117",
  };

  const CATEGORY_LABELS = {
    "Advanced Circuit Manipulation": "Circuit Manipulation",
    "Algorithm Implementation": "Algorithms",
    "Backend and Runtime": "Backend / Runtime",
    "Gate Operations and Manipulation": "Gate Operations",
    "Quantum Circuit Generation": "Circuit Generation",
    "Quantum Circuit Serialization": "Serialization",
    "Quantum Information": "Quantum Information",
    "Simulation and Execution": "Simulation / Execution",
    "State Preparation and Analysis": "State Preparation",
    "Visualization and Post-Processing": "Visualization",
    Uncategorized: "Other",
  };

  const datasetLabel = (ds) => DATASET_LABELS[ds] || ds;
  const categoryLabel = (cat) => CATEGORY_LABELS[cat] || cat;

  const state = {
    summary: [],
    details: null, // lazy-loaded
    view: "leaderboard",
    dataset: "Overall",
    category: "All",
    metric: "pass_at_1",
    selected: null,
    attempt: 0,
    content: new Map(),
    expanded: null, // model name currently expanded
  };

  const el = (id) => document.getElementById(id);

  function fmtPct(v) {
    return v === null || v === undefined ? "—" : (v * 100).toFixed(1) + "%";
  }

  function fmtCi(lo, hi) {
    if (lo === null || lo === undefined || hi === null || hi === undefined) return "";
    return `${(lo * 100).toFixed(1)}–${(hi * 100).toFixed(1)}%`;
  }

  // ---- data loading ----

  async function loadSummary() {
    const res = await fetch("./leaderboard_summary.json");
    state.summary = await res.json();
  }

  async function loadDetails() {
    if (state.details) return state.details;
    const res = await fetch("./leaderboard_details.json");
    state.details = await res.json();
    return state.details;
  }

  // ---- aggregation ----

  function overallRows() {
    const byModel = new Map();
    for (const row of state.summary) {
      if (!byModel.has(row.model)) byModel.set(row.model, []);
      byModel.get(row.model).push(row);
    }
    const out = [];
    for (const [model, rows] of byModel) {
      out.push({
        model,
        dataset: "Overall",
        n_tasks: sum(rows.map((r) => r.n_tasks)),
        ...weightedMetric(rows, "pass_at_1"),
        ...weightedMetric(rows, "pass_at_3"),
        ...weightedMetric(rows, "pass_at_5"),
      });
    }
    return out;
  }

  // Combining datasets' pass@k is a simple task-weighted average; combining
  // their confidence intervals is not, so Overall never shows a CI band.
  function weightedMetric(rows, key) {
    let wsum = 0, vsum = 0;
    for (const r of rows) {
      if (r[key] === null || r[key] === undefined) continue;
      wsum += r.n_tasks;
      vsum += r[key] * r.n_tasks;
    }
    return {
      [key]: wsum > 0 ? vsum / wsum : null,
      [`${key}_ci_lo`]: null,
      [`${key}_ci_hi`]: null,
    };
  }

  function sum(arr) {
    return arr.reduce((a, b) => a + b, 0);
  }

  // Category isn't part of leaderboard_summary.json (it's a per-task
  // attribute), so any category filter other than "All" is aggregated here
  // from leaderboard_details.json instead of the precomputed summary — same
  // averaging the export script uses, just without confidence intervals
  // (those are only computed for whole datasets).
  function aggregateDetailRows(rows) {
    const byModel = new Map();
    for (const r of rows) {
      if (!byModel.has(r.model)) byModel.set(r.model, { n: 0, sum1: 0, sum3: 0, n3: 0, sum5: 0, n5: 0 });
      const a = byModel.get(r.model);
      a.n += 1;
      a.sum1 += r.pass_at_1;
      if (r.pass_at_3 !== null && r.pass_at_3 !== undefined) {
        a.sum3 += r.pass_at_3;
        a.n3 += 1;
      }
      if (r.pass_at_5 !== null && r.pass_at_5 !== undefined) {
        a.sum5 += r.pass_at_5;
        a.n5 += 1;
      }
    }
    const out = new Map();
    for (const [model, a] of byModel) {
      out.set(model, {
        n_tasks: a.n,
        pass_at_1: a.n > 0 ? a.sum1 / a.n : null,
        pass_at_3: a.n3 > 0 ? a.sum3 / a.n3 : null,
        pass_at_5: a.n5 > 0 ? a.sum5 / a.n5 : null,
      });
    }
    return out;
  }

  function detailRowsFor(dataset, category) {
    let rows = state.details || [];
    if (dataset !== "Overall") rows = rows.filter((r) => r.dataset === dataset);
    if (category !== "All") rows = rows.filter((r) => r.category === category);
    return rows;
  }

  function categoriesForDataset(dataset) {
    if (!state.details) return [];
    const rows = dataset === "Overall" ? state.details : state.details.filter((r) => r.dataset === dataset);
    return [...new Set(rows.map((r) => r.category))].sort();
  }

  function rowsForCurrentDataset() {
    if (state.category !== "All") {
      const agg = aggregateDetailRows(detailRowsFor(state.dataset, state.category));
      return [...agg.entries()].map(([model, a]) => ({
        model,
        n_tasks: a.n_tasks,
        pass_at_1: a.pass_at_1,
        pass_at_1_ci_lo: null,
        pass_at_1_ci_hi: null,
        pass_at_3: a.pass_at_3,
        pass_at_3_ci_lo: null,
        pass_at_3_ci_hi: null,
        pass_at_5: a.pass_at_5,
        pass_at_5_ci_lo: null,
        pass_at_5_ci_hi: null,
      }));
    }
    if (state.dataset === "Overall") return overallRows();
    return state.summary.filter((r) => r.dataset === state.dataset);
  }

  // ---- rendering ----

  function renderTabs() {
    const viewWrap = el("view-tabs");
    viewWrap.innerHTML = "";
    for (const v of VIEWS) {
      const btn = document.createElement("button");
      btn.textContent = v.label;
      btn.className = v.key === state.view ? "active" : "";
      btn.addEventListener("click", () => {
        state.view = v.key;
        state.expanded = null;
        renderTabs();
        renderCurrentView();
      });
      viewWrap.appendChild(btn);
    }

    // The per-problem grid only makes sense within a single dataset, since
    // task IDs/columns don't line up across datasets the way they do for a
    // task-weighted "Overall" average.
    const dsList = state.view === "problems" ? DATASETS.filter((d) => d !== "Overall") : DATASETS;
    if (state.view === "problems" && state.dataset === "Overall") {
      state.dataset = dsList[0];
    }

    const dsWrap = el("dataset-tabs");
    dsWrap.innerHTML = "";
    for (const ds of dsList) {
      const btn = document.createElement("button");
      btn.textContent = datasetLabel(ds);
      btn.className = ds === state.dataset ? "active" : "";
      btn.addEventListener("click", () => {
        state.dataset = ds;
        state.category = "All";
        state.expanded = null;
        renderTabs();
        renderCurrentView();
      });
      dsWrap.appendChild(btn);
    }

    const catOptions = ["All", ...categoriesForDataset(state.dataset)];
    if (!catOptions.includes(state.category)) state.category = "All";

    const menu = el("category-menu");
    menu.innerHTML = catOptions
      .map((cat) => {
        const label = cat === "All" ? "All" : categoryLabel(cat);
        const selected = cat === state.category;
        return `<li class="dropdown-option${selected ? " selected" : ""}" role="option" tabindex="0" aria-selected="${selected}" data-value="${escapeHtml(cat)}">${escapeHtml(label)}</li>`;
      })
      .join("");
    el("category-toggle-label").textContent = state.category === "All" ? "All" : categoryLabel(state.category);
  }

  function closeCategoryMenu() {
    el("category-menu").hidden = true;
    el("category-toggle").setAttribute("aria-expanded", "false");
  }

  function openCategoryMenu() {
    el("category-menu").hidden = false;
    el("category-toggle").setAttribute("aria-expanded", "true");
  }

  function selectCategory(cat) {
    state.category = cat;
    state.expanded = null;
    closeCategoryMenu();
    renderTabs();
    renderCurrentView();
  }

  // Toggle button + option list are static/rebuilt-in-place like the other
  // dropdowns on this page, so delegated listeners bound once in init()
  // keep working across every re-render.
  function bindCategoryDropdown() {
    const toggle = el("category-toggle");
    const menu = el("category-menu");

    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      if (menu.hidden) openCategoryMenu();
      else closeCategoryMenu();
    });

    menu.addEventListener("click", (e) => {
      const opt = e.target.closest(".dropdown-option");
      if (opt) selectCategory(opt.dataset.value);
    });

    menu.addEventListener("keydown", (e) => {
      const opt = e.target.closest(".dropdown-option");
      if (opt && (e.key === "Enter" || e.key === " ")) {
        e.preventDefault();
        selectCategory(opt.dataset.value);
      }
    });

    document.addEventListener("click", (e) => {
      if (!el("category-dropdown").contains(e.target)) closeCategoryMenu();
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !menu.hidden) {
        closeCategoryMenu();
        toggle.focus();
      }
    });
  }

  // Both tables' Pass@1/3/5 headers double as sort/rank controls and (in the
  // problem grid) pick which metric colors the cells. #board's header is
  // static and #problem-head is only ever rebuilt via innerHTML on the same
  // <tr>, so one delegated listener per container survives every re-render.
  function bindSortableHeader(container) {
    container.addEventListener("click", (e) => {
      const th = e.target.closest(".sortable");
      if (!th) return;
      state.metric = th.dataset.metric;
      renderCurrentView();
    });
  }

  function syncSortableHeaders(container) {
    container.querySelectorAll(".sortable").forEach((th) => {
      th.classList.toggle("active", th.dataset.metric === state.metric);
    });
  }

  function renderCurrentView() {
    const isProblems = state.view === "problems";
    el("problem-detail").hidden = true;
    el("leaderboard-footnote").hidden = isProblems;
    el("problem-footnote").hidden = !isProblems;
    if (isProblems) {
      el("board").hidden = true;
      renderProblemView();
    } else {
      el("problem-wrap").hidden = true;
      renderBoard();
    }
  }

  // Renders one Pass@k cell; the currently-ranked-by metric also gets the
  // bar-track visualization so it's obvious which column is driving order.
  function renderMetricCell(row, metricKey, maxVal) {
    const isActive = metricKey === state.metric;
    const val = row[metricKey];
    if (val === null || val === undefined) {
      return `<td class="metric-value${isActive ? " metric-active" : ""}">—</td>`;
    }

    const ciLo = row[`${metricKey}_ci_lo`];
    const ciHi = row[`${metricKey}_ci_hi`];
    const ciText = fmtCi(ciLo, ciHi);

    let bar = "";
    if (isActive) {
      const barPct = maxVal > 0 ? (val / maxVal) * 100 : 0;
      const ciLeft = ciLo !== null && ciLo !== undefined && maxVal > 0 ? (ciLo / maxVal) * 100 : null;
      const ciWidth = ciLo !== null && ciHi !== undefined && ciHi !== null && maxVal > 0
        ? ((ciHi - ciLo) / maxVal) * 100
        : 0;
      bar = `
        <div class="bar-track">
          ${ciLeft !== null ? `<div class="bar-ci" style="left:${ciLeft}%;width:${ciWidth}%"></div>` : ""}
          <div class="bar-fill" style="width:${barPct}%"></div>
        </div>`;
    }

    return `
      <td class="metric-value${isActive ? " metric-active" : ""}">
        ${fmtPct(val)}${ciText ? `<span class="metric-ci">${ciText}</span>` : ""}
        ${bar}
      </td>
    `;
  }

  function renderBoard() {
    syncSortableHeaders(el("board-head"));

    const rows = rowsForCurrentDataset()
      .filter((r) => r[state.metric] !== null && r[state.metric] !== undefined)
      .sort((a, b) => b[state.metric] - a[state.metric]);

    const body = el("board-body");
    body.innerHTML = "";

    if (rows.length === 0) {
      el("status").hidden = false;
      el("status").textContent = "No results for this metric/dataset/category combination yet.";
      el("board").hidden = true;
      return;
    }
    el("status").hidden = true;
    el("board").hidden = false;

    const maxVal = Math.max(...rows.map((r) => r[state.metric]));

    rows.forEach((row, i) => {
      const tr = document.createElement("tr");
      tr.className = "row";

      tr.innerHTML = `
        <td class="rank-num">${i + 1}</td>
        <td class="model-name">${escapeHtml(row.model)}</td>
        ${METRICS.map((m) => renderMetricCell(row, m.key, maxVal)).join("")}
        <td class="col-n">${row.n_tasks}</td>
      `;

      tr.addEventListener("click", () => toggleDetail(row.model, tr));
      body.appendChild(tr);

      if (state.expanded === row.model) {
        body.appendChild(buildDetailRow(row.model));
        loadDetailBreakdown(row.model);
      }
    });
  }

  function toggleDetail(model, tr) {
    state.expanded = state.expanded === model ? null : model;
    renderBoard();
  }

  function buildDetailRow(model) {
    const tr = document.createElement("tr");
    tr.className = "detail-row";
    const td = document.createElement("td");
    td.colSpan = 6;
    td.innerHTML = `<div class="detail-loading" data-model="${escapeHtml(model)}">Loading category breakdown…</div>`;
    tr.appendChild(td);
    return tr;
  }

  async function loadDetailBreakdown(model) {
    const details = await loadDetails();
    if (state.expanded !== model) return; // user moved on before this resolved

    const datasetFilter = state.dataset === "Overall" ? null : state.dataset;
    const rows = details.filter(
      (r) =>
        r.model === model &&
        (datasetFilter === null || r.dataset === datasetFilter) &&
        (state.category === "All" || r.category === state.category)
    );

    const byCat = new Map();
    for (const r of rows) {
      const key = `${datasetFilter ? "" : datasetLabel(r.dataset) + " / "}${categoryLabel(r.category)}`;
      if (!byCat.has(key)) byCat.set(key, { n: 0, passed: 0, sum1: 0 });
      const c = byCat.get(key);
      c.n += 1;
      c.sum1 += r.pass_at_1;
    }

    const container = document.querySelector(`.detail-loading[data-model="${cssEscape(model)}"]`);
    if (!container) return;

    if (byCat.size === 0) {
      container.textContent = "No per-category data available for this dataset.";
      return;
    }

    const entries = [...byCat.entries()].sort((a, b) => b[1].sum1 / b[1].n - a[1].sum1 / a[1].n);
    const table = document.createElement("table");
    table.className = "detail-table";
    table.innerHTML = `
      <thead><tr><th>Category</th><th>Pass@1</th><th>Tasks</th></tr></thead>
      <tbody>
        ${entries
          .map(
            ([cat, c]) => `<tr><td>${escapeHtml(cat)}</td><td>${fmtPct(c.sum1 / c.n)}</td><td>${c.n}</td></tr>`
          )
          .join("")}
      </tbody>
    `;
    container.replaceWith(table);
  }

  // ---- problem view ----

  // Splits into alternating digit/non-digit runs so "qiskitHumanEval/9" sorts
  // before "qiskitHumanEval/10", and QCoder's mixed alnum IDs still get a
  // stable, sensible order.
  function naturalCompare(a, b) {
    const pa = a.match(/(\d+|\D+)/g) || [];
    const pb = b.match(/(\d+|\D+)/g) || [];
    const len = Math.max(pa.length, pb.length);
    for (let i = 0; i < len; i++) {
      const x = pa[i] ?? "";
      const y = pb[i] ?? "";
      if (x === y) continue;
      const xNum = /^\d+$/.test(x);
      const yNum = /^\d+$/.test(y);
      if (xNum && yNum) {
        const diff = parseInt(x, 10) - parseInt(y, 10);
        if (diff !== 0) return diff;
      } else if (x < y) {
        return -1;
      } else {
        return 1;
      }
    }
    return 0;
  }

  // Red -> yellow -> green, matching the pass rate for one problem.
  function heatColor(v) {
    const stops = [
      [0, [248, 113, 113]],
      [0.5, [250, 204, 21]],
      [1, [74, 222, 128]],
    ];
    const clamped = Math.max(0, Math.min(1, v));
    let [loStop, hiStop] = [stops[0], stops[1]];
    for (let i = 0; i < stops.length - 1; i++) {
      if (clamped >= stops[i][0] && clamped <= stops[i + 1][0]) {
        [loStop, hiStop] = [stops[i], stops[i + 1]];
        break;
      }
    }
    const span = hiStop[0] - loStop[0] || 1;
    const t = (clamped - loStop[0]) / span;
    const rgb = loStop[1].map((c, i) => Math.round(c + (hiStop[1][i] - c) * t));
    return `rgb(${rgb.join(",")})`;
  }

  async function renderProblemView() {
    el("status").hidden = true;

    let details;
    try {
      details = await loadDetails();
    } catch (e) {
      el("problem-wrap").hidden = true;
      el("status").hidden = false;
      el("status").textContent = "Could not load leaderboard_details.json.";
      console.error(e);
      return;
    }
    if (state.view !== "problems") return; // user switched views before this resolved

    const dataset = state.dataset;
    const rows = detailRowsFor(dataset, state.category);
    if (rows.length === 0) {
      el("problem-wrap").hidden = true;
      el("status").hidden = false;
      el("status").textContent = "No per-problem results for this dataset/category yet.";
      return;
    }

    const taskIds = [...new Set(rows.map((r) => r.task_id))].sort(naturalCompare);

    const byModel = new Map();
    for (const r of rows) {
      if (!byModel.has(r.model)) byModel.set(r.model, new Map());
      byModel.get(r.model).set(r.task_id, r[state.metric]);
    }

    // Aggregated from the same (dataset + category)-filtered rows as the grid
    // itself, so the Pass@k columns always match what the cells show.
    const aggByModel = aggregateDetailRows(rows);

    const modelRows = [...byModel.entries()].map(([model, cells]) => {
      const a = aggByModel.get(model);
      return {
        model,
        cells,
        sortVal: a ? a[state.metric] : null,
        pass_at_1: a ? a.pass_at_1 : null,
        pass_at_3: a ? a.pass_at_3 : null,
        pass_at_5: a ? a.pass_at_5 : null,
      };
    });
    modelRows.sort((a, b) => (b.sortVal ?? -1) - (a.sortVal ?? -1));

    const head = el("problem-head");
    head.innerHTML = `
      <th class="col-model problem-sticky">Model Name</th>
      ${METRICS.map((m) => `<th class="col-metric sortable" data-metric="${m.key}">${m.label}</th>`).join("")}
      ${taskIds.map((tid, i) => `<th class="col-task" title="${escapeHtml(tid)}">${i + 1}</th>`).join("")}
    `;
    syncSortableHeaders(head);

    const body = el("problem-body");
    body.innerHTML = modelRows
      .map((row) => {
        const cells = taskIds
          .map((tid) => {
            const v = row.cells.get(tid);
            if (v === null || v === undefined) {
              return `<td class="cell-task cell-empty" title="${escapeHtml(tid)}: no data"></td>`;
            }
            return `<td class="cell-task"><button type="button" class="problem-cell" style="background:${heatColor(v)}" data-model="${escapeHtml(row.model)}" data-task="${escapeHtml(tid)}" title="${escapeHtml(tid)}: ${fmtPct(v)}" aria-label="${escapeHtml(row.model)}, ${escapeHtml(tid)}, ${state.metric.replaceAll('_', ' ')}: ${fmtPct(v)}" aria-controls="problem-detail" aria-pressed="false"></button></td>`;
          })
          .join("");
        const metricCells = METRICS.map(
          (m) => `<td class="metric-value${m.key === state.metric ? " metric-active" : ""}">${fmtPct(row[m.key])}</td>`
        ).join("");
        return `
          <tr>
            <td class="model-name problem-sticky">${escapeHtml(row.model)}</td>
            ${metricCells}
            ${cells}
          </tr>
        `;
      })
      .join("");

    el("problem-wrap").hidden = false;
    if (state.selected && !rows.some((r) => r.dataset === state.selected.dataset && r.model === state.selected.model && r.task_id === state.selected.task_id)) state.selected = null;
    renderProblemDetail();
  }

  async function selectProblem(model, task) {
    state.selected = detailRowsFor(state.dataset, state.category).find((r) => r.model === model && r.task_id === task);
    state.attempt = 0;
    const dataset = state.dataset;
    if (!state.content.has(dataset)) {
      const request = fetch(`./problem_content/${encodeURIComponent(dataset)}.json`)
        .then((res) => { if (!res.ok) throw new Error("Content unavailable"); return res.json(); });
      state.content.set(dataset, request);
      renderProblemDetail();
      try { state.content.set(dataset, await request); }
      catch { state.content.delete(dataset); }
    }
    renderProblemDetail();
  }

  function renderProblemDetail() {
    const panel = el("problem-detail");
    panel.hidden = state.view !== "problems" || el("problem-wrap").hidden;
    document.querySelectorAll(".problem-cell").forEach((button) => {
      button.setAttribute("aria-pressed", String(!!state.selected && button.dataset.model === state.selected.model && button.dataset.task === state.selected.task_id));
    });
    const row = state.selected;
    if (!row) {
      panel.innerHTML = '<p class="inspection-placeholder">Select a problem cell to inspect the prompt, reference solution, and model outputs.</p>';
      return;
    }
    const content = state.content.get(row.dataset);
    const task = content?.tasks?.[row.task_id] || row;
    const attempts = content?.models?.[row.model]?.[row.task_id] || row.attempts || [];
    const attempt = attempts[state.attempt] || {};
    const status = (a) => a.passed === true ? ["correct", "✓ Correct"] : a.passed === false ? ["incorrect", "× Incorrect"] : ["unknown", "— Unavailable"];
    const [tone, label] = status(attempt);
    const tasks = [...new Set(detailRowsFor(row.dataset, state.category).map((r) => r.task_id))].sort(naturalCompare);
    const index = tasks.indexOf(row.task_id);
    const available = detailRowsFor(row.dataset, state.category).filter((r) => r.model === row.model && r[state.metric] != null).map((r) => r.task_id).sort(naturalCompare);
    const position = available.indexOf(row.task_id);
    const code = (value, fallback) => `<pre class="inspection-code" tabindex="0"><code>${escapeHtml(value || fallback)}</code></pre>`;
    panel.innerHTML = `
      <header class="inspection-header">
        <div><h2 id="inspection-title">Problem ${index + 1}</h2>
          <div class="inspection-chips">${[datasetLabel(row.dataset), row.task_id, row.category && categoryLabel(row.category), row.difficulty].filter(Boolean).map((v) => `<span>${escapeHtml(v)}</span>`).join("")}</div>
          <p>Selected from: <strong>${escapeHtml(row.model)}</strong></p>
          <p>Result: ${row.n_passed ?? "—"} of ${row.n_samples ?? "—"} attempts passed · ${METRICS.find((m) => m.key === state.metric).label}: ${fmtPct(row[state.metric])}</p>
        </div>
        <nav class="problem-navigation" aria-label="Problem navigation">
          <button type="button" data-step="-1" ${position <= 0 ? "disabled" : ""}>← Previous problem</button>
          <span>Problem ${index + 1} of ${tasks.length}</span>
          <button type="button" data-step="1" ${position < 0 || position >= available.length - 1 ? "disabled" : ""}>Next problem →</button>
        </nav>
      </header>
      <div class="inspection-columns">
        <section class="inspection-card"><h3>Problem Prompt</h3><pre class="inspection-prompt" tabindex="0">${escapeHtml(task.prompt || "Problem prompt unavailable.")}</pre></section>
        <section class="inspection-card"><h3>Canonical Solution <small>Python</small></h3>${code(task.canonical_solution, "Canonical solution unavailable.")}</section>
        <section class="inspection-card"><h3>Model Outputs</h3>
          <div class="attempt-tabs" role="tablist" aria-label="Model attempts">${Array.from({length: 5}, (_, i) => {
            const [t, l] = status(attempts[i] || {});
            return `<button type="button" role="tab" id="attempt-tab-${i}" aria-controls="attempt-output" aria-selected="${i === state.attempt}" tabindex="${i === state.attempt ? 0 : -1}" data-attempt="${i}" class="${t}">Attempt ${i + 1}<span>${l}</span></button>`;
          }).join("")}</div>
          <div id="attempt-output" role="tabpanel" aria-labelledby="attempt-tab-${state.attempt}" tabindex="0" class="attempt-output ${tone}">
            ${code(attempt.code || attempt.output, "No output available for this attempt.")}
            <p class="evaluation-result">${label}: ${attempt.runtime_error ? "Execution error" : attempt.syntax_valid === false ? "Syntax error" : attempt.passed === true ? "Passed evaluation" : attempt.passed === false ? "Failed evaluation" : "Evaluation unavailable"}</p>
            ${attempt.logs ? `<details><summary>Evaluation details</summary>${code(attempt.logs, "")}</details>` : ""}
          </div>
        </section>
      </div>
      <div class="inspection-summary ${tone}" role="status">${attempt.passed === true ? "✓ This model’s attempt correctly solves the problem." : attempt.passed === false ? "× This model’s attempt does not solve the problem. The generated output failed evaluation." : content instanceof Promise ? "Loading problem content…" : "Evaluation data is unavailable for this attempt."}</div>`;
    panel.querySelectorAll("[data-step]").forEach((button) => button.addEventListener("click", () => {
      selectProblem(row.model, available[position + Number(button.dataset.step)]);
      (panel.querySelector(`[data-step="${button.dataset.step}"]:not(:disabled)`) || panel.querySelector('[data-step]:not(:disabled)'))?.focus();
    }));
    const activate = (i) => {
      state.attempt = i;
      renderProblemDetail();
      el(`attempt-tab-${i}`).focus();
    };
    panel.querySelectorAll("[data-attempt]").forEach((button) => {
      button.addEventListener("click", () => activate(Number(button.dataset.attempt)));
      button.addEventListener("keydown", (event) => {
        const next = {ArrowRight: (state.attempt + 1) % 5, ArrowLeft: (state.attempt + 4) % 5, Home: 0, End: 4}[event.key];
        if (next !== undefined) { event.preventDefault(); activate(next); }
      });
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function cssEscape(s) {
    return String(s).replace(/"/g, '\\"');
  }

  // ---- init ----

  async function init() {
    renderTabs();
    bindSortableHeader(el("board-head"));
    bindSortableHeader(el("problem-head"));
    bindCategoryDropdown();
    el("problem-body").addEventListener("click", (event) => {
      const button = event.target.closest(".problem-cell");
      if (button) selectProblem(button.dataset.model, button.dataset.task);
    });
    try {
      // Details are loaded eagerly (not just on row-expand) because the
      // Category dropdown and any category-filtered view need them up front.
      await Promise.all([loadSummary(), loadDetails()]);
      renderTabs();
      renderCurrentView();
    } catch (e) {
      el("status").textContent = "Could not load leaderboard_summary.json. Has export_leaderboard.py been run?";
      console.error(e);
    }
  }

  init();
})();
