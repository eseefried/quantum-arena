(() => {
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pct = v => v == null ? '—' : `${(v*100).toFixed(2)}%`;
  const score = v => v == null ? '—' : Number(v.toFixed(2)).toString();
  const code = v => `<pre class="inspection-code" tabindex="0"><code>${esc(typeof v === 'string' ? v : JSON.stringify(v, null, 2))}</code></pre>`;
  function heatColor(value) {
    const v = Math.max(0, Math.min(1, value));
    const stops = [[248,113,113], [250,204,21], [74,222,128]];
    const index = v < .5 ? 0 : 1, t = v < .5 ? v*2 : (v-.5)*2;
    return `rgb(${stops[index].map((c,i) => Math.round(c+(stops[index+1][i]-c)*t)).join(',')})`;
  }
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
        loading ||= fetch('./quantumbencheval.json?v=multi-model-1').then(r => { if (!r.ok) throw Error('QBE export unavailable'); return r.json(); });
        payload = await loading;
      }
    } catch (error) {
      loading = null;
      if (state.collection === 'qbe') el('status').textContent = 'Could not load QuantumBenchEval. Run python3 scripts/export_quantumbencheval.py.';
      return;
    }
    if (state.collection !== 'qbe') return;
    const models = payload.models || [{key: 'gemini36-flash', topics: payload.topics, corrected: payload.corrected}];
    const active = models.find(m => m.key === state.qbeModel) || models[0];
    state.qbeModel = active.key;
    const data = active.topics.find(t => t.topic === state.topic) || active.topics[0];
    const rubric = data.topic === 'T3';
    const corrected = data.topic === 'T1';
    const result = corrected ? active.corrected : data;
    const tasks = data.task_details;
    const metric = state.metric === 'pass_at_5' ? '5' : '1';
    const taskValue = t => rubric ? t.mean_rubric_score : (corrected ? t.corrected_pass_at_k : t.pass_at_k)[metric];
    const notes = el('qbe-notes');
    notes.innerHTML = `<h2>${esc(data.title)}${corrected ? ' · corrected scoring' : ''}</h2>${data.samples < data.expected_samples ? '<p class="footnote">Incomplete recorded coverage.</p>' : ''}`;
    notes.innerHTML += `<p class="footnote">T1 uses corrected tests; original outcomes are retained in sample details. T2 evaluation_cost and T6 reproducibility scoring issues remain uncorrected. T3 is a rubric score, not a pass rate.</p>`;
    el('status').hidden = true;
    const headers = rubric ? '<th>Mean rubric score</th><th>Scale</th><th>Judge</th>' : '<th class="sortable" data-metric="pass_at_1">Pass@1</th><th class="sortable" data-metric="pass_at_5">Pass@5</th>';
    if (state.view === 'leaderboard') {
      el('board-head').innerHTML = `<th>Model</th>${headers}<th>Tasks</th><th>Samples${rubric ? ' / scored' : ''}</th>`;
      const tableRows = models.map(m => {
        const t=m.topics.find(t=>t.topic===data.topic), r=corrected?m.corrected:t;
        const value=rubric?t.mean_rubric_score:r.pass_at_k[metric];
        const values=rubric?`<td>${score(t.mean_rubric_score)}</td><td>0–${esc(t.rubric_maximum.join('/'))}</td><td>${esc(t.judge.model)}</td>`:`<td>${pct(r.pass_at_k['1'])}</td><td>${pct(r.pass_at_k['5'])}</td>`;
        return {value,html:`<tr><td>${esc(t.identity)}</td>${values}<td>${t.recorded_tasks}/${t.tasks}</td><td>${t.samples}/${t.expected_samples}${rubric?` · ${t.judged_samples} scored`:''}</td></tr>`};
      }).sort((a,b)=>(b.value??-1)-(a.value??-1));
      el('board-body').innerHTML = tableRows.map(r=>r.html).join('');
      el('board').hidden = false;
      return;
    }
    el('problem-head').innerHTML = `<th class="problem-sticky">Model</th>${headers}${tasks.map((t,i) => `<th class="col-task" title="${esc(t.task_id)}">${i+1}</th>`).join('')}`;
    const problemRows = models.map(m => {
      const topic = m.topics.find(t => t.topic === data.topic);
      const summary = corrected ? m.corrected : topic;
      const value = rubric ? topic.mean_rubric_score : summary.pass_at_k[metric];
      const cells = rubric ? `<td>${score(topic.mean_rubric_score)}</td><td>0–${esc(topic.rubric_maximum.join('/'))}</td><td>${esc(topic.judge.model)}</td>` : `<td>${pct(summary.pass_at_k['1'])}</td><td>${pct(summary.pass_at_k['5'])}</td>`;
      const byId = new Map(topic.task_details.map(t => [t.task_id, t]));
      const html = `<tr><td class="model-name problem-sticky">${esc(topic.identity)}</td>${cells}${tasks.map(column => {
        const t = byId.get(column.task_id);
        const value = t ? taskValue(t) : null;
        const label = rubric ? `${score(value)} / ${topic.rubric_maximum.join('/')} · ${t?.judged_samples ?? 0}/5 scored` : pct(value);
        const background = value == null ? 'var(--accent-soft)' : heatColor(rubric ? value / topic.rubric_maximum[0] : value);
        return `<td class="cell-task"><button class="problem-cell" style="background:${background}" data-qbe-model="${esc(m.key)}" data-qbe-task="${esc(column.task_id)}" title="${esc(topic.identity)} · ${esc(column.task_id)}: ${label}" aria-label="${esc(topic.identity)} · ${esc(column.task_id)}: ${label}" aria-controls="problem-detail" aria-pressed="${state.qbeModel === m.key && state.selected === column.task_id}">${rubric ? score(value) : ''}</button></td>`;
      }).join('')}</tr>`;
      return {value, html};
    }).sort((a,b) => (b.value ?? -1) - (a.value ?? -1));
    el('problem-body').innerHTML = problemRows.map(r => r.html).join('');
    el('problem-wrap').hidden = false;
    el('problem-body').querySelectorAll('[data-qbe-task]').forEach(b => b.onclick = () => { state.qbeModel = b.dataset.qbeModel; state.selected = b.dataset.qbeTask; state.attempt = 0; refresh(); });
    const panel = el('problem-detail'); panel.hidden = false;
    const task = tasks.find(t => t.task_id === state.selected);
    if (!task) { panel.innerHTML = '<p class="inspection-placeholder">Select a problem cell to inspect its prompt, reference solution, and sample outputs.</p>'; return; }
    const rows = data.rows.filter(r => r.task_id === task.task_id).sort((a,b) => a.sample_index-b.sample_index);
    const attempt = rows.find(r => r.sample_index === state.attempt);
    const replay = corrected ? attempt?.corrected_evaluation : null;
    const presentation = r => {
      if (rubric) {
        if (r?.status !== 'judged' || !r.judge) return {tone:'unknown', style:'', label:'Unscored'};
        const hue = Math.max(0, Math.min(1, r.judge.total/r.judge.max_total))*120;
        return {tone:'rubric-score', style:`--score-hue:${hue}`, label:`${score(r.judge.total)} / ${r.judge.max_total}`};
      }
      const status = corrected ? r?.corrected_evaluation?.graded_status : r?.status;
      if (!status || status === 'evaluation_environment_failure') return {tone:'unknown', style:'', label:'— Unavailable'};
      return status === 'passed' ? {tone:'correct', style:'', label:'✓ Correct'} : {tone:'incorrect', style:'', label:'× Incorrect'};
    };
    const selected = presentation(attempt);
    const index = tasks.indexOf(task);
    panel.innerHTML = `<header class="inspection-header"><div><h2>Problem ${index+1}</h2><div class="inspection-chips"><span>${esc(task.task_id)}</span><span>${esc(data.topic)}</span><span>${esc(data.identity)}</span></div><p>${task.sample_count}/5 sample records${rubric ? ` · ${task.judged_samples}/5 rubric scores · mean ${score(task.mean_rubric_score)} / ${data.rubric_maximum.join('/')}` : ` · Pass@${metric}: ${pct(taskValue(task))}`}</p></div><nav class="problem-navigation"><button data-step="-1" ${index===0?'disabled':''}>← Previous problem</button><button data-step="1" ${index===tasks.length-1?'disabled':''}>Next problem →</button></nav></header><div class="inspection-columns"><section class="inspection-card"><h3>Problem Prompt</h3><pre class="inspection-prompt">${esc(attempt?.prompt || task.prompt)}</pre></section><section class="inspection-card"><h3>Canonical Solution</h3>${code(task.canonical_solution)}</section><section class="inspection-card"><h3>Model Outputs</h3><div class="attempt-tabs" role="tablist" aria-label="Model attempts">${Array.from({length:5},(_,i) => { const r=rows.find(r=>r.sample_index===i), display=presentation(r); return `<button id="qbe-attempt-${i}" role="tab" aria-controls="qbe-attempt-output" class="${display.tone}" style="${display.style}" data-attempt="${i}" aria-selected="${i===state.attempt}">Attempt ${i+1}<span>${esc(display.label)}</span></button>`; }).join('')}</div><div id="qbe-attempt-output" role="tabpanel" aria-labelledby="qbe-attempt-${state.attempt}" class="attempt-output ${selected.tone}" style="${selected.style}">${code(attempt?.generation?.code || attempt?.completion?.raw_text || 'No output available.')}<p class="evaluation-result">${esc(selected.label)}</p><details><summary>Evaluation details${rubric ? ' and rubric' : ''}</summary>${code(corrected ? {status:replay?.graded_status, metrics:replay?.metrics} : {status:attempt?.status, execution:attempt?.execution, judge:attempt?.judge})}</details></div></section></div>`;
    panel.querySelectorAll('[data-attempt]').forEach(b => b.onclick = () => { state.attempt=Number(b.dataset.attempt); refresh(); });
    panel.querySelectorAll('[data-step]').forEach(b => b.onclick = () => { state.selected=tasks[index+Number(b.dataset.step)].task_id; state.attempt=0; refresh(); });
  };
})();
