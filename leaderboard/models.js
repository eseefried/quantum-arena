(() => {
  "use strict";

  // Best-effort public specs for each model's provider/openness/parameter
  // count. Fine-tuned or custom variants built on a base model are marked
  // "(fine-tuned)"; anything genuinely unknown (a custom RAG pipeline, an
  // unconfirmed base model) is left as "—" rather than guessed.
  // Hugging Face model cards verified 2026-09-09; counts use published model sizes.
  const MODEL_META = {
    "GPT-5": { provider: "OpenAI", open: false, parameters: "Undisclosed" },
    "Claude Opus 4.6": { provider: "Anthropic", open: false, parameters: "Undisclosed" },
    "Gemini 3 Flash": { provider: "Google DeepMind", open: false, parameters: "Undisclosed" },
    "Gemini 2.0 Flash": { provider: "Google DeepMind", open: false, parameters: "Undisclosed" },
    "Gemma-3-4B-IT": { provider: "Google DeepMind", open: true, parameters: "4B", huggingFace: "google/gemma-3-4b-it" },
    "LLaMA-3.1-8B": { provider: "Meta", open: true, parameters: "8B", huggingFace: "meta-llama/Llama-3.1-8B" },
    "LLaMA-3.2-3B-Instruct": { provider: "Meta", open: true, parameters: "3B", huggingFace: "meta-llama/Llama-3.2-3B-Instruct" },
    "LLaMA-4-Scout-17B": { provider: "Meta", open: true, parameters: "17B active / 109B total (MoE)" },
    "Mistral-7B-Instruct-v0.3": { provider: "Mistral AI", open: true, parameters: "7B", huggingFace: "mistralai/Mistral-7B-Instruct-v0.3" },
    "Mistral-3.2-24B-Qiskit": { provider: "Mistral AI (fine-tuned)", open: true, parameters: "24B", huggingFace: "Qiskit/mistral-small-3.2-24b-qiskit" },
    "Mistral3-Qiskit": { provider: "Mistral AI (fine-tuned)", open: true, parameters: "24B (default)", huggingFace: "Qiskit/mistral-small-3.2-24b-qiskit", linkLabel: "Default model" },
    "Qwen2.5-Coder-Qiskit": { provider: "Alibaba (fine-tuned)", open: true, parameters: "14.7B (default)", huggingFace: "Qiskit/Qwen2.5-Coder-14B-Qiskit", linkLabel: "Default model" },
    "Qwen2.5-Coder-14B-Qiskit": { provider: "Alibaba (fine-tuned)", open: true, parameters: "14.7B", huggingFace: "Qiskit/Qwen2.5-Coder-14B-Qiskit" },
    "Granite-8B-Qiskit": { provider: "IBM (fine-tuned)", open: true, parameters: "8B", huggingFace: "Qiskit/granite-8b-qiskit" },
    "Granite-3.2-8B-Qiskit": { provider: "IBM (fine-tuned)", open: true, parameters: "8B", huggingFace: "Qiskit/granite-3.2-8b-qiskit" },
    "Quantum RAG": { provider: "Custom (Granite + retrieval)", open: true, parameters: "8B generator (default)", huggingFace: "Qiskit/granite-3.2-8b-qiskit", linkLabel: "Default generator" },
  };

  const DEFAULT_META = { provider: "—", open: null, parameters: "—" };

  const el = (id) => document.getElementById(id);

  function fmtOpen(open) {
    if (open === true) return "Yes";
    if (open === false) return "No";
    return "—";
  }

  // Same task-weighted average across datasets as the Arena page's "Overall"
  // tab, so Rank here matches what you'd see there by default.
  function overallPassAt1(summary) {
    const byModel = new Map();
    for (const row of summary) {
      if (!byModel.has(row.model)) byModel.set(row.model, []);
      byModel.get(row.model).push(row);
    }
    const out = [];
    for (const [model, rows] of byModel) {
      let wsum = 0, vsum = 0;
      let lastRun = "";
      for (const r of rows) {
        if (r.pass_at_1 !== null && r.pass_at_1 !== undefined) {
          wsum += r.n_tasks;
          vsum += r.pass_at_1 * r.n_tasks;
        }
        if (r.last_run > lastRun) lastRun = r.last_run;
      }
      out.push({
        model,
        pass_at_1: wsum > 0 ? vsum / wsum : null,
        last_run: lastRun,
      });
    }
    return out;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function render(rows) {
    const body = el("models-body");

    if (rows.length === 0) {
      el("status").hidden = false;
      el("status").textContent = "No results yet.";
      el("models-board").hidden = true;
      return;
    }
    el("status").hidden = true;
    el("models-board").hidden = false;

    body.innerHTML = rows
      .map((row, i) => {
        const meta = MODEL_META[row.model] || DEFAULT_META;
        return `
          <tr>
            <td class="rank-num">${i + 1}</td>
            <td class="model-name">${escapeHtml(row.model)}</td>
            <td>${escapeHtml(meta.provider)}</td>
            <td class="col-date">${escapeHtml(row.last_run || "—")}</td>
            <td class="col-open">${fmtOpen(meta.open)}</td>
            <td class="col-params">${escapeHtml(meta.parameters)}</td>
            <td class="col-source">${meta.huggingFace
              ? `<a class="model-source-link" href="https://huggingface.co/${escapeHtml(meta.huggingFace)}" target="_blank" rel="noopener noreferrer" aria-label="${escapeHtml(row.model)} on Hugging Face (opens in a new tab)">${escapeHtml(meta.linkLabel || "Model card")} ↗</a>`
              : "—"}</td>
          </tr>
        `;
      })
      .join("");
  }

  async function init() {
    try {
      const res = await fetch("./leaderboard_summary.json");
      const summary = await res.json();
      const rows = overallPassAt1(summary)
        .filter((r) => r.pass_at_1 !== null)
        .sort((a, b) => b.pass_at_1 - a.pass_at_1);
      render(rows);
    } catch (e) {
      el("status").textContent = "Could not load model results. Please refresh the page to try again.";
      console.error(e);
    }
  }

  init();
})();
