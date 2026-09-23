(() => {
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pct = v => v == null ? '—' : `${(v*100).toFixed(2)}%`;
  const score = v => v == null ? '—' : v.toFixed(4);
  const code = v => `<pre class="inspection-code" tabindex="0"><code>${esc(typeof v === 'string' ? v : JSON.stringify(v, null, 2))}</code></pre>`;
  const histogram = (title, counts) => `<h3>${title}</h3><dl class="qbe-statuses">${Object.entries(counts).map(([k,v]) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join('')}</dl>`;
  let payload, loading;
  window.renderQBE = async (state, refresh) => {
    el('board').hidden = true;
    el('problem-wrap').hidden = true;
    el('problem-detail').hidden = true;
    el('leaderboard-footnote').hidden = true;
    el('problem-footnote').hidden = true;
    el('status').hidden = false;
    el('status').textContent = 'Loading QuantumBenchEval…';
    try {
      if (!payload) {
        loading ||= fetch('./quantumbencheval.json').then(r => { if (!r.ok) throw Error('QBE export unavailable'); return r.json(); });
        payload = await loading;
      }
    } catch (error) {
      loading = null;
      if (state.collection === 'qbe') el('status').textContent = 'Could not load QuantumBenchEval. Run python3 scripts/export_quantumbencheval.py.';
      return;
    }
    if (state.collection !== 'qbe') return;
    const data = payload.topics.find(t => t.topic === state.topic) || payload.topics[0];
    const rubric = data.topic === 'T3';
    const corrected = data.topic === 'T1' && state.variant === 'corrected';
    const result = corrected ? payload.corrected : data;
    const tasks = data.task_details;
    const metric = state.metric === 'pass_at_5' ? '5' : '1';
    const taskValue = t => rubric ? t.mean_rubric_score : (corrected ? t.corrected_pass_at_k : t.pass_at_k)[metric];
    const notes = el('qbe-notes');
    notes.innerHTML = `<h2>${esc(data.title)}</h2><p class="footnote">Preview · one available model · no comparative ranking or combined score. ${data.recorded_tasks}/${data.tasks} tasks · ${data.samples}/${data.expected_samples} sample records · ${data.complete_tasks}/${data.tasks} tasks with all five slots. ${data.samples < data.expected_samples ? '<strong>Incomplete recorded coverage.</strong>' : 'Complete recorded coverage.'}</p>`;
    if (data.topic === 'T1') {
      notes.innerHTML += `<div class="segmented" id="qbe-variant"><button data-variant="original" class="${corrected ? '' : 'active'}">Original T1</button><button data-variant="corrected" class="${corrected ? 'active' : ''}">Corrected T1 replay</button></div><p class="qbe-notice"><strong>Original T1 has a known test limitation:</strong> exact shots/optimizer_calls values were never disclosed to candidates. The corrected variant replays the same generated code, replacing only those assertions with non-gating closeness ratios. Original scores and statuses remain separate.</p>`;
      notes.querySelectorAll('[data-variant]').forEach(b => b.onclick = () => { state.variant = b.dataset.variant; refresh(); });
    }
    if (rubric) notes.innerHTML += `<p class="qbe-notice"><strong>Incomplete rubric coverage: ${data.judged_samples}/${data.expected_samples} samples scored.</strong> Mean over judged samples only; unjudged samples are excluded, not assigned zero. “Judged” never means passed. Scale: 0–${esc(data.rubric_maximum.join('/'))}. Judge: ${esc(data.judge.model)} (${esc(data.judge.protocol)}). Energy accuracy is checked deterministically against executed output.</p>`;
    else notes.innerHTML += '<p class="footnote">Pass@k is task-averaged over fully recorded, scorable tasks. Candidate failures remain unsuccessful; infrastructure failures are unscored. Select a metric heading to color the problem grid.</p>';
    notes.innerHTML += `<details><summary>Sample statuses and verification</summary>${histogram(corrected ? 'Corrected replay statuses' : 'Sample statuses', result.counts)}${histogram('Original execution outcomes', data.execution_status_counts)}${histogram('Unsupported imports', data.unsupported_import_modules)}<p>Verified against all saved sample records${corrected ? ' and corrected replay rows' : ''}.</p></details>`;
    el('status').hidden = true;
    const headers = rubric ? '<th>Mean rubric score</th><th>Scale</th><th>Judge</th>' : '<th class="sortable" data-metric="pass_at_1">Pass@1</th><th class="sortable" data-metric="pass_at_5">Pass@5</th>';
    const cells = rubric ? `<td>${score(data.mean_rubric_score)}</td><td>0–${esc(data.rubric_maximum.join('/'))}</td><td>${esc(data.judge.model)}</td>` : `<td class="metric-value">${pct(result.pass_at_k['1'])}</td><td class="metric-value">${pct(result.pass_at_k['5'])}</td>`;
    const model = `<td class="model-name">Gemini 3.6 Flash${corrected ? '<small> · corrected T1</small>' : ''}</td>`;
    if (state.view === 'leaderboard') {
      el('board-head').innerHTML = `<th>Model</th>${headers}<th>Tasks</th><th>Samples${rubric ? ' / scored' : ''}</th>`;
      el('board-body').innerHTML = `<tr>${model}${cells}<td>${data.recorded_tasks}/${data.tasks}</td><td>${data.samples}/${data.expected_samples}${rubric ? ` · ${data.judged_samples} scored` : ''}</td></tr>`;
      el('board').hidden = false;
      return;
    }
    el('problem-head').innerHTML = `<th class="problem-sticky">Model</th>${headers}${tasks.map((t,i) => `<th class="col-task" title="${esc(t.task_id)}">${i+1}</th>`).join('')}`;
    el('problem-body').innerHTML = `<tr>${model}${cells}${tasks.map(t => {
      const value = taskValue(t);
      const label = rubric ? `${score(value)} / ${data.rubric_maximum.join('/')} · ${t.judged_samples}/5 scored` : pct(value);
      // Rubric cells use neutral styling, never a pass-rate heatmap.
      const background = rubric || value == null ? 'var(--accent-soft)' : `hsl(${value*120} 70% 70%)`;
      return `<td class="cell-task"><button class="problem-cell" style="background:${background}" data-qbe-task="${esc(t.task_id)}" title="${esc(t.task_id)}: ${label}" aria-label="${esc(t.task_id)}: ${label}" aria-controls="problem-detail" aria-pressed="${state.selected === t.task_id}">${rubric ? score(value) : ''}</button></td>`;
    }).join('')}</tr>`;
    el('problem-wrap').hidden = false;
    el('problem-body').querySelectorAll('[data-qbe-task]').forEach(b => b.onclick = () => { state.selected = b.dataset.qbeTask; state.attempt = 0; refresh(); });
    const panel = el('problem-detail'); panel.hidden = false;
    const task = tasks.find(t => t.task_id === state.selected);
    if (!task) { panel.innerHTML = '<p class="inspection-placeholder">Select a problem cell to inspect its prompt, reference solution, and sample outputs.</p>'; return; }
    const rows = data.rows.filter(r => r.task_id === task.task_id).sort((a,b) => a.sample_index-b.sample_index);
    const attempt = rows.find(r => r.sample_index === state.attempt);
    const replay = corrected ? payload.corrected.rows.find(r => r.task_id === task.task_id && r.sample_index === state.attempt) : null;
    const index = tasks.indexOf(task);
    panel.innerHTML = `<header class="inspection-header"><div><h2>Problem ${index+1}</h2><div class="inspection-chips"><span>${esc(task.task_id)}</span><span>${esc(data.topic)}</span></div><p>${task.sample_count}/5 sample records${rubric ? ` · ${task.judged_samples}/5 rubric scores · mean ${score(task.mean_rubric_score)} / ${data.rubric_maximum.join('/')}` : ` · Pass@${metric}: ${pct(taskValue(task))}`}</p></div><nav class="problem-navigation"><button data-step="-1" ${index===0?'disabled':''}>← Previous problem</button><button data-step="1" ${index===tasks.length-1?'disabled':''}>Next problem →</button></nav></header><div class="inspection-columns"><section class="inspection-card"><h3>Problem Prompt</h3><pre class="inspection-prompt">${esc(task.prompt)}</pre></section><section class="inspection-card"><h3>Canonical Solution</h3>${code(task.canonical_solution)}</section><section class="inspection-card"><h3>Model Outputs</h3><div class="attempt-tabs">${Array.from({length:5},(_,i) => { const r=rows.find(r=>r.sample_index===i); return `<button data-attempt="${i}" aria-pressed="${i===state.attempt}">Attempt ${i+1}<span>${esc(r?.status || 'missing')}</span></button>`; }).join('')}</div><p>Original status: <strong>${esc(attempt?.status || 'missing')}</strong> · Execution: ${esc(attempt?.execution?.status || 'not_executed')}${replay ? ` · Corrected status: <strong>${esc(replay.graded_status)}</strong>` : ''}</p>${rubric && attempt?.judge ? `<p>Rubric: ${attempt.judge.total} / ${attempt.judge.max_total} · Judge: ${esc(attempt.judge.judge.model)}</p>` : ''}${code(attempt?.generation?.code || attempt?.completion?.raw_text || 'No output available.')}<details><summary>Evaluation details${rubric ? ' and rubric' : ''}</summary>${code({execution:attempt?.execution, judge:attempt?.judge, corrected:replay})}</details></section></div>`;
    panel.querySelectorAll('[data-attempt]').forEach(b => b.onclick = () => { state.attempt=Number(b.dataset.attempt); refresh(); });
    panel.querySelectorAll('[data-step]').forEach(b => b.onclick = () => { state.selected=tasks[index+Number(b.dataset.step)].task_id; state.attempt=0; refresh(); });
  };
})();
