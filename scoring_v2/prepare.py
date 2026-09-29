"""Pre-declared minimal assertion deletion. Never changes source datasets or samples."""
import ast
import difflib
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
AUDIT = Path('/home/ejx/quantum/quantum-ai-assistants-benchmark/iclr/audit')
OUT = AUDIT / 'scoring_v2'
COST_TASKS = {'t2_0','t2_3','t2_8','t2_10','t2_11','t2_12','t2_13','t2_14'}
EXCLUDED = {
 't2_3': 'Disclosed QUBO has global minimum -49 with two circuits ({1,2}, {1,5}, or {1,6}), contradicting the stated exactly-three constraint and required optimum selection {1,3,5}.',
 't2_10': 'Disclosed QUBO has global minimum -101 at {3,4,6,7} (two targets per instrument), contradicting the exactly-three-per-instrument constraint and required selection {1,3,4,6,7,8}.',
 't2_14': 'Prompt defines feasible_objective_quality as achieved revenue / 47, while the disclosed constraints imply maximum 41 and the assertions demand achieved_revenue == 41 AND quality == 1.0.'}


def digest(path):
 return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def changed_test(task):
 source=task['test'];lines=source.splitlines(keepends=True);removed=[]
 for node in ast.walk(ast.parse(source)):
  if not isinstance(node,ast.Assert):continue
  expr=node.test
  remove=False
  if task['task_id'].startswith('t6_'):
   remove=any(isinstance(n,ast.Subscript) and isinstance(n.value,ast.Name) and n.value.id=='result' and isinstance(n.slice,ast.Constant) and n.slice.value=='reproducibility' for n in ast.walk(expr))
  elif task['task_id'] in COST_TASKS:
   remove=(isinstance(expr,ast.Compare) and len(expr.ops)==1 and isinstance(expr.ops[0],ast.Eq)
    and isinstance(expr.left,ast.Subscript) and isinstance(expr.left.value,ast.Name) and expr.left.value.id=='result'
    and isinstance(expr.left.slice,ast.Constant) and expr.left.slice.value=='evaluation_cost'
    and isinstance(expr.comparators[0],ast.Constant) and expr.comparators[0].value==2**task['num_variables'])
  if remove:
   removed.append(dict(line=node.lineno,end_line=node.end_lineno,assertion=ast.get_source_segment(source,node)))
 indices={i for r in removed for i in range(r['line']-1,r['end_line'])}
 result=''.join(s for i,s in enumerate(lines) if i not in indices)
 original_assertions=[ast.get_source_segment(source,n) for n in ast.walk(ast.parse(source)) if isinstance(n,ast.Assert) and n.lineno-1 not in indices]
 new_assertions=[ast.get_source_segment(result,n) for n in ast.walk(ast.parse(result)) if isinstance(n,ast.Assert)]
 assert original_assertions==new_assertions, task['task_id']
 # Stronger than assertion preservation: every surviving source line is byte-identical.
 assert result==''.join(line for i,line in enumerate(lines) if i not in indices)
 expected=1 if task['task_id'].startswith('t6_') or task['task_id'] in COST_TASKS else 0
 assert len(removed)==expected,task['task_id']
 return result,removed


def prepare():
 OUT.mkdir(parents=True,exist_ok=True)
 (HERE/'datasets').mkdir(exist_ok=True)
 changes=[];diff=[]
 for topic in ('T2','T6'):
  path=ROOT/'qbe_export/datasets'/f'QuantumBenchEval_{topic}.json'
  data=json.loads(path.read_text())
  for task in data['tasks']:
   old=task['test'];new,removed=changed_test(task)
   task['test']=new
   for r in removed:changes.append(dict(task_id=task['task_id'],**r))
   diff.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile=f'original/{task["task_id"]}.py',tofile=f'scoring_v2/{task["task_id"]}.py'))
  (HERE/'datasets'/path.name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
 assert len(changes)==25
 (AUDIT/'qbe_t2_t6_changes.diff').write_text(''.join(diff))
 original_child=ROOT/'qbe_export/qbe/eval_child_v2.py'
 (HERE/'original_child.py').write_bytes(original_child.read_bytes())
 assert digest(HERE/'original_child.py')==digest(original_child)
 source_paths=[*sorted((ROOT/'qbe_export/results').glob('*/T[26]/samples/*.json')),
               *sorted((ROOT/'qbe_export/results').glob('*/T[26]/plan.json')),
               *sorted((ROOT/'qbe_export/results').glob('*/T[26]/summary.json')),
               *sorted((ROOT/'qbe_export/qbe').glob('*.py')),
               *sorted((ROOT/'qbe_export/datasets').glob('*.json'))]
 manifest={str(p.relative_to(ROOT)):digest(p) for p in source_paths}
 protocol={
  'declared_at_utc':datetime.now(timezone.utc).isoformat(),
  'scope':'Minimal sensitivity analysis, T2/T6 only. No generation, judge calls, normalization, tie-break changes, or Step 3 tightening.',
  'changes':changes,'excluded_t2_tasks':EXCLUDED,
  'primary_groups':{'T2 original':15,'T2 v2':12,'T6 original':17,'T6 v2':17},
  'original_baseline':'Historical saved sample statuses; generation failures keep their recorded unsuccessful statuses.',
  'v2_outcomes':'Replay saved code once; apply original and v2 tests to the same returned value. Use measured v2 outcomes without retries or historical-pass overrides. Historical-to-v2 and paired-original-to-v2 flips are both reported; any historical drift is explicit, never silently coerced to zero.',
  'generation_policy':'empty_output/truncated/incomplete_output remain terminal unsuccessful without execution, matching original runner policy.',
  'pairing':'Memoize exactly one entry-point invocation, including exceptions, and reuse its return in both otherwise unchanged test scripts. No normalization of the returned object. Test statements other than the 25 deletions remain byte-identical.',
  'timeouts_seconds':{'T2':60,'T6':150},
  'reference_policy':'Execute every T2/T6 canonical solution under both original and v2 assertions on paired runtime output, including excluded T2 tasks; report each outcome without changing solutions.',
  'excluded_policy':'Replay excluded T2 tasks for diagnostics but never include their samples in T2 v2 metrics or included-sample flips.',
  'statistics':{'samples_per_task':5,'pass_at_k':'mean over tasks of 1 - C(n-c,k)/C(n,k); n=5, k=1,5',
    'bootstrap_replicates':10000,'seed':20260925,'unit':'task, with replacement; each resampled task retains all 5 slots',
    'ci':'two-sided percentile 95%, NumPy percentile method=linear; identical draws across models within a task set',
    'infrastructure_policy':'Any evaluation_environment_failure blocks final scored summaries; never count infrastructure failure as unsuccessful.'},
  'no_pass_to_fail_policy':'Check measured included-sample historical flips and paired-runtime flips independently; if nonzero, report failure of the requested check instead of altering outcomes.',
  'source_sha256':manifest}
 target=OUT/'protocol.json'
 if target.exists():raise RuntimeError('Protocol already exists: do not overwrite a pre-declaration after execution.')
 target.write_text(json.dumps(protocol,indent=2)+'\n')
 (OUT/'PROTOCOL.md').write_text('''# Pre-declared minimal QBE sensitivity analysis

T6: remove only reproducibility assertions (17). T2: remove only exact 2^n evaluation-cost assertions (8).
Exclude t2_3, t2_10, t2_14 from T2 v2, but report their diagnostic replays and reference checks separately.
Every other test statement is preserved byte-for-byte. No selection normalization, tie-break changes, or metric normalization.

Historical original scores come from saved statuses. Execute saved code once per eligible sample, memoizing the entry-point return;
original and v2 tests see that same return. Report v2 replay results without retries or pass overrides. Also report paired original
results to separate assertion effects from historical execution drift. A historical pass-to-fail result, if observed, is reported honestly.
Generation-terminal failures keep their original unsuccessful status. No model generation or judge calls.

Run all 32 reference solutions, including exclusions, through original and v2 checks. Use original timeouts: T2 60s, T6 150s.
Pass@1/5: unbiased per-task estimator with n=5, task mean. CIs: 10,000 task bootstrap draws, seed 20260925,
percentile 2.5/97.5 with linear interpolation; same draws across models on the same task set. No within-task sample bootstrap.
No infrastructure-failure scores. Verify input hashes after execution. Paper, figures, leaderboard and other topics stay untouched.

See protocol.json for the exact deleted assertion text, exclusions, timestamp and input hashes.
''')
 print(f'Pre-declared {len(changes)} deletions; protocol at {target}')

if __name__=='__main__':prepare()
