(() => {
  "use strict";

  const DATASETS = ["Overall", "QiskitHumanEval", "QiskitHumanEvalHard", "QuanBench44", "QuanBench117", "QCoder"];
  const METRICS = [
    { key: "pass_at_1", label: "Pass@1" },
    { key: "pass_at_3", label: "Pass@3" },
    { key: "pass_at_5", label: "Pass@5" },
  ];

  const state = {
    summary: [],
    details: null, // lazy-loaded
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
    const dsWrap = el("dataset-tabs");
    dsWrap.innerHTML = "";
    for (const ds of DATASETS) {
      const btn = document.createElement("button");
      btn.textContent = ds;
      btn.className = ds === state.dataset ? "active" : "";
      btn.addEventListener("click", () => {
        state.dataset = ds;
        state.expanded = null;
        renderTabs();
        renderBoard();
      });
      dsWrap.appendChild(btn);
    }

    const metWrap = el("metric-tabs");
    metWrap.innerHTML = "";
    for (const m of METRICS) {
      const btn = document.createElement("button");
      btn.textContent = m.label;
      btn.className = m.key === state.metric ? "active" : "";
      btn.addEventListener("click", () => {
        state.metric = m.key;
        renderTabs();
        renderBoard();
      });
      metWrap.appendChild(btn);
    }
  }

  function renderBoard() {
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

      const val = row[state.metric];
      const ciLo = row[`${state.metric}_ci_lo`];
      const ciHi = row[`${state.metric}_ci_hi`];
      const ciText = fmtCi(ciLo, ciHi);

      const barPct = maxVal > 0 ? (val / maxVal) * 100 : 0;
      const ciLeft = ciLo !== null && ciLo !== undefined && maxVal > 0 ? (ciLo / maxVal) * 100 : null;
      const ciWidth = ciLo !== null && ciHi !== undefined && ciHi !== null && maxVal > 0
        ? ((ciHi - ciLo) / maxVal) * 100
        : 0;

      tr.innerHTML = `
        <td class="rank-num">${i + 1}</td>
        <td class="model-name">${escapeHtml(row.model)}</td>
        <td class="metric-value">${fmtPct(val)}${ciText ? `<span class="metric-ci">${ciText}</span>` : ""}</td>
        <td>
          <div class="bar-track">
            ${ciLeft !== null ? `<div class="bar-ci" style="left:${ciLeft}%;width:${ciWidth}%"></div>` : ""}
            <div class="bar-fill" style="width:${barPct}%"></div>
          </div>
        </td>
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
    td.colSpan = 5;
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
    try {
      await loadSummary();
      renderBoard();
    } catch (e) {
      el("status").textContent = "Could not load leaderboard_summary.json. Has export_leaderboard.py been run?";
      console.error(e);
    }
  }

  init();
})();
