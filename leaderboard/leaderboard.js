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

  const state = {
    summary: [],
    details: null, // lazy-loaded
    view: "leaderboard",
    dataset: "Overall",
    metric: "pass_at_1",
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

  function rowsForCurrentDataset() {
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
      btn.textContent = ds;
      btn.className = ds === state.dataset ? "active" : "";
      btn.addEventListener("click", () => {
        state.dataset = ds;
        state.expanded = null;
        renderTabs();
        renderCurrentView();
      });
      dsWrap.appendChild(btn);
    }
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
      el("status").textContent = "No results for this metric on this dataset yet.";
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
      (r) => r.model === model && (datasetFilter === null || r.dataset === datasetFilter)
    );

    const byCat = new Map();
    for (const r of rows) {
      const key = `${datasetFilter ? "" : r.dataset + " / "}${r.category}`;
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
    const rows = details.filter((r) => r.dataset === dataset);
    if (rows.length === 0) {
      el("problem-wrap").hidden = true;
      el("status").hidden = false;
      el("status").textContent = "No per-problem results for this dataset yet.";
      return;
    }

    const taskIds = [...new Set(rows.map((r) => r.task_id))].sort(naturalCompare);

    const byModel = new Map();
    for (const r of rows) {
      if (!byModel.has(r.model)) byModel.set(r.model, new Map());
      byModel.get(r.model).set(r.task_id, r[state.metric]);
    }

    const summaryByModel = new Map(state.summary.filter((r) => r.dataset === dataset).map((r) => [r.model, r]));

    const modelRows = [...byModel.entries()].map(([model, cells]) => {
      const s = summaryByModel.get(model);
      return {
        model,
        cells,
        sortVal: s ? s[state.metric] : null,
        pass_at_1: s ? s.pass_at_1 : null,
        pass_at_3: s ? s.pass_at_3 : null,
        pass_at_5: s ? s.pass_at_5 : null,
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
            return `<td class="cell-task" style="background:${heatColor(v)}" title="${escapeHtml(tid)}: ${fmtPct(v)}"></td>`;
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
    try {
      await loadSummary();
      renderCurrentView();
    } catch (e) {
      el("status").textContent = "Could not load leaderboard_summary.json. Has export_leaderboard.py been run?";
      console.error(e);
    }
  }

  init();
})();
