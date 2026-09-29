"""Summarize measured paired replays; do not conceal historical execution drift."""
import csv
import hashlib
import json
import math
import re
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from prepare import ROOT,HERE,OUT,digest


def write_csv(name,rows,fields=None):
    with (OUT/name).open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields or list(rows[0]));writer.writeheader();writer.writerows(rows)


def metric_estimates(counts,k):
    return np.array([1.0 if 5-c<k else 1.0-math.comb(5-c,k)/math.comb(5,k) for c in counts])


def estimate(rows,status_key,task_ids):
    counts=[]
    for tid in task_ids:
        task=[r for r in rows if r['task_id']==tid]
        assert len(task)==5 and {r['sample_index'] for r in task}==set(range(5))
        counts.append(sum(r[status_key]=='passed' for r in task))
    # Fixed task draws, reused for every model and metric on this task set.
    indices=np.random.default_rng(20260925).integers(0,len(task_ids),size=(10000,len(task_ids)))
    stats={}
    for k in (1,5):
        values=metric_estimates(counts,k)
        distribution=values[indices].mean(axis=1)
        lower,upper=np.percentile(distribution,[2.5,97.5],method='linear')
        stats.update({f'pass{k}':float(values.mean()),f'pass{k}_ci_lo':float(lower),f'pass{k}_ci_hi':float(upper)})
    return dict(n_tasks=len(task_ids),n_samples=5*len(task_ids),n_passed=sum(counts),**stats)


def historical_failure(source,removed_lines):
    record=json.loads((ROOT/source).read_text())
    tb=record.get('execution',{}).get('traceback','')
    frames=re.findall(r'File "([^"]+)", line (\d+)',tb)
    types=re.findall(r'^([\w.]+(?:Error|Exception|Interrupt|Exit))(?::|$)',tb,re.M)
    file,line=frames[-1] if frames else ('','')
    line=int(line) if line else ''
    exception=types[-1] if types else ''
    return exception,file,line,(exception=='TypeError' and file=='<dataset-test>' and line in removed_lines)


def main():
    protocol=json.loads((OUT/'protocol.json').read_text())
    raw=[json.loads(p.read_text()) for p in sorted((OUT/'raw/samples').glob('*/*.json'))]
    refs=[json.loads(p.read_text()) for p in sorted((OUT/'raw/references/reference').glob('*.json'))]
    expected=[p for p in protocol['source_sha256'] if '/samples/' in p]
    assert len(raw)==len(expected)==1600 and {r['source'] for r in raw}==set(expected), 'Incomplete replay'
    assert len(refs)==32
    assert all(digest(ROOT/p)==sha for p,sha in protocol['source_sha256'].items()),'Source hashes changed'
    assert not any(r[v]['status']=='evaluation_environment_failure' for r in raw+refs for v in ('original','v2')),'Infrastructure failures cannot be scored'
    removed=defaultdict(set)
    for change in protocol['changes']:
        removed[change['task_id']].update(range(change['line'],change['end_line']+1))
    samples=[]
    for r in raw:
        orig=r['historical_status'];paired=r['original']['status'];v2=r['v2']['status'];included=r['included_v2']
        exception,file,line,is_repro_type=historical_failure(r['source'],removed[r['task_id']])
        paired_tb=r['original'].get('traceback','')
        paired_frames=re.findall(r'File "([^"]+)", line (\d+)',paired_tb)
        paired_types=re.findall(r'^([\w.]+(?:Error|Exception|Interrupt|Exit))(?::|$)',paired_tb,re.M)
        paired_file,paired_line=paired_frames[-1] if paired_frames else ('','')
        paired_line=int(paired_line) if paired_line else ''
        paired_exception=paired_types[-1] if paired_types else ''
        removed_text=next((c['assertion'] for c in protocol['changes'] if c['task_id']==r['task_id'] and paired_file=='<dataset-test>' and c['line']<=paired_line<=c['end_line']), '') if paired_line else ''
        historical_flip=(orig=='passed')!=(v2=='passed')
        paired_flip=(paired=='passed')!=(v2=='passed')
        if not included:reason='Excluded from T2 v2: '+protocol['excluded_t2_tasks'][r['task_id']]
        elif historical_flip:
            if orig=='passed':reason='Historical pass -> replay failure; inspect original replay and logs for execution drift. No v2 pass override applied.'
            elif paired_flip:reason='Deletion effect reproduced on paired output; historical first failure recorded separately.'
            else:reason='Historical fail -> replay pass without a paired assertion flip; execution drift, not attributable solely to deleted assertion.'
        elif paired_flip:reason='Paired deletion effect; historical pass/fail unchanged.'
        else:reason='No pass/fail change.'
        samples.append(dict(model=r['model'],topic=r['topic'],task_id=r['task_id'],sample_id=r['sample_id'],sample_index=r['sample_index'],
          included_v2=included,outcome_orig=orig,outcome_original_replay=paired,outcome_v2=v2,
          flip_historical_to_v2=historical_flip if included else False,flip_paired_to_v2=paired_flip if included else False,
          original_first_exception=exception,original_first_failure_file=file,original_first_failure_line=line,
          first_failure_was_reproducibility_typeerror=is_repro_type if r['topic']=='T6' else False,
          paired_first_exception=paired_exception,paired_first_failure_line=paired_line,paired_removed_assertion=removed_text,
          reason=reason,source=r['source']))
    write_csv('qbe_sample_outcomes.csv',samples)
    flips=[r for r in samples if r['included_v2'] and (r['flip_historical_to_v2'] or r['flip_paired_to_v2'])]
    write_csv('qbe_flips.csv',flips,list(samples[0]))
    write_csv('qbe_excluded_t2_samples.csv',[r for r in samples if not r['included_v2']],list(samples[0]))
    excluded=[dict(task_id=tid,contradiction=reason) for tid,reason in protocol['excluded_t2_tasks'].items()]
    write_csv('qbe_excluded_tasks.csv',excluded)
    reference_rows=[dict(task_id=r['task_id'],topic=r['topic'],included_v2=r['included_v2'],
                        outcome_original=r['original']['status'],outcome_v2=r['v2']['status'],
                        original_error=r['original'].get('error',''),v2_error=r['v2'].get('error',''),
                        entry_calls=r.get('entry_calls'),elapsed_seconds=r.get('elapsed_seconds')) for r in refs]
    write_csv('qbe_reference_checks.csv',reference_rows)
    historical_regressions=[r for r in samples if r['included_v2'] and r['outcome_orig']=='passed' and r['outcome_v2']!='passed']
    paired_regressions=[r for r in samples if r['included_v2'] and r['outcome_original_replay']=='passed' and r['outcome_v2']!='passed']
    drift=[r for r in samples if (r['outcome_orig']=='passed')!=(r['outcome_original_replay']=='passed')]
    write_csv('qbe_historical_execution_drift.csv',drift,list(samples[0]))
    models=sorted({r['model'] for r in samples})
    scores=[];runtime_scores=[];type_flips=[]
    for model in models:
        for topic in ('T2','T6'):
            subset=[r for r in samples if r['model']==model and r['topic']==topic]
            original_tasks=sorted({r['task_id'] for r in subset},key=lambda s:int(s.split('_')[1]))
            included_tasks=[t for t in original_tasks if t not in protocol['excluded_t2_tasks']]
            for variant,status,tasks in [('original','outcome_orig',original_tasks),('v2','outcome_v2',included_tasks)]:
                scores.append(dict(model=model,topic=topic,variant=variant,**estimate(subset,status,tasks)))
            for variant,status in [('original_replay','outcome_original_replay'),('v2_replay','outcome_v2'),('historical_original_matched','outcome_orig')]:
                runtime_scores.append(dict(model=model,topic=topic,variant=variant,**estimate(subset,status,included_tasks)))
        rows=[r for r in samples if r['model']==model and r['topic']=='T6']
        type_flips.append(dict(model=model,original_first_reproducibility_typeerrors=sum(r['first_failure_was_reproducibility_typeerror'] for r in rows),
                              historical_fail_to_v2_pass=sum(r['outcome_orig']!='passed' and r['outcome_v2']=='passed' for r in rows),
                              of_these_first_reproducibility_typeerror=sum(r['outcome_orig']!='passed' and r['outcome_v2']=='passed' and r['first_failure_was_reproducibility_typeerror'] for r in rows),
                              paired_fail_to_v2_pass=sum(r['outcome_original_replay']!='passed' and r['outcome_v2']=='passed' for r in rows),
                              historical_pass_to_v2_fail=sum(r['outcome_orig']=='passed' and r['outcome_v2']!='passed' for r in rows)))
    write_csv('qbe_rescore.csv',scores)
    write_csv('qbe_paired_sensitivity.csv',runtime_scores)
    write_csv('qbe_t6_typeerror_flips.csv',type_flips)
    checks=dict(samples=1600,references=32,reference_original_passes=sum(r['outcome_original']=='passed' for r in reference_rows),
      reference_v2_passes=sum(r['outcome_v2']=='passed' for r in reference_rows),
      historical_pass_to_fail=len(historical_regressions),paired_pass_to_fail=len(paired_regressions),
      historical_execution_pass_fail_drift=len(drift),
      t6_original_first_reproducibility_typeerrors=sum(r['original_first_reproducibility_typeerrors'] for r in type_flips),
      t6_fail_to_pass_from_original_reproducibility_typeerror=sum(r['of_these_first_reproducibility_typeerror'] for r in type_flips),
      included_samples=1450,excluded_t2_samples=150,original_source_hashes_unchanged=True,
      bootstrap_replicates=10000,seed=20260925)
    (OUT/'verification.json').write_text(json.dumps(checks,indent=2))
    assert len(scores)==40
    report='''# Minimal QBE sensitivity rescore

Only the pre-declared changes were made: delete T6 reproducibility assertions and T2 exact
evaluation-cost assertions; exclude t2_3/t2_10/t2_14 from T2 v2. All other test statements,
selection encodings, t2_6 tie-break, and model code remain unchanged. No regeneration or judge calls.

Original columns use historical saved outcomes. V2 columns use paired runtime replay of saved code.
Each replay evaluates original and v2 tests against one memoized function return; see the paired
sensitivity CSV for comparisons unaffected by differing simulator draws within the pair.
Evaluation dependencies match recorded versions; original platform was aarch64, replay x86_64.
Time limits are unchanged (T2 60s, T6 150s); generation-terminal failures remain unsuccessful.

| Model | T2 orig (15), pass@1 / @5 | T2 v2 (12), pass@1 / @5 | T6 orig (17), pass@1 / @5 | T6 v2 (17), pass@1 / @5 |
|---|---:|---:|---:|---:|
'''
    for model in models:
        groups={(r['topic'],r['variant']):r for r in scores if r['model']==model}
        cells=[f'{groups[key]["pass1"]*100:.2f}% / {groups[key]["pass5"]*100:.2f}%' for key in [('T2','original'),('T2','v2'),('T6','original'),('T6','v2')]]
        report+='| '+model+' | '+' | '.join(cells)+' |\n'
    report+=f'''\n**Reference checks:** {checks['reference_original_passes']}/32 original and {checks['reference_v2_passes']}/32 v2 pass; per-task results are in `qbe_reference_checks.csv`.
**Pass→fail checks:** {len(paired_regressions)} on paired runtime outputs; {len(historical_regressions)} comparing historical saved passes with v2 replay.
There are {len(drift)} historical-original versus replay-original pass/fail differences (see `qbe_historical_execution_drift.csv`).
T6: {checks['t6_fail_to_pass_from_original_reproducibility_typeerror']} fail→pass flips come from the {checks['t6_original_first_reproducibility_typeerrors']} samples whose historical first failure was the reproducibility TypeError.

**Intervals:** `qbe_rescore.csv` contains all four requested groups with pass@1/@5 and 95% CIs.
Unbiased per-task pass@k uses n=5. CIs use 10,000 task-bootstrap draws, seed 20260925,
percentile [2.5,97.5], linear interpolation; five sample slots stay together. Identical draws
are used across models within each task set. T2 original versus v2 also changes the task population;
`qbe_paired_sensitivity.csv` includes the matched 12-task baseline to separate that effect.

**Exclusions:** t2_3 and t2_10 disclose QUBOs whose minima violate stated slot constraints;
t2_14 specifies revenue/47 while its constraints cap revenue at 41 and tests require quality 1.
Full contradictions and all 150 excluded diagnostic outcomes are reported separately.

All 1,600 source sample hashes and original dataset/evaluator hashes verified unchanged.
`qbe_sample_outcomes.csv` records every slot; `qbe_flips.csv` lists historical or paired pass/fail flips.
Raw paired logs, pre-declaration, environment and evaluator manifests are retained in this directory.
'''
    if historical_regressions:
        report+='\n**Requested historical zero-pass→fail check did not pass.** These measured regressions have not been overwritten. The paired zero-regression check distinguishes deletion effects from historical runtime drift. The single regression is gemini31-pro/t6_8.3: approximation_ratio=0.5646258503401361 fails the unchanged line-16 quality assertion under both original and v2.\n'
    (OUT/'REPORT.md').write_text(report)
    print(json.dumps(checks,indent=2))
    print(report)
    if paired_regressions:raise SystemExit('BUG: paired pass->fail despite only assertion deletion')

if __name__=='__main__':main()
