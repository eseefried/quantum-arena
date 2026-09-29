#!/usr/bin/env python3
"""Replay saved T2/T6 outputs; no generation adapters or judge APIs imported."""
import argparse
import concurrent.futures
import hashlib
import importlib.metadata
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from prepare import ROOT,HERE,OUT,digest

PYTHON=Path('/tmp/qbe-scoring-v2-env/bin/python')
TERMINAL_GENERATION={'empty_output','truncated','incomplete_output'}
PACKAGES=['numpy','scipy','networkx','qiskit','qiskit-aer','qiskit-algorithms','qiskit-optimization','pennylane','dimod','dwave-neal']


def environment():
    versions={name:importlib.metadata.version(name) for name in PACKAGES}
    expected={'numpy':'2.5.3','scipy':'1.18.1','networkx':'3.6.1','qiskit':'1.4.5','qiskit-aer':'0.17.2',
              'qiskit-algorithms':'0.3.1','qiskit-optimization':'0.6.1','pennylane':'0.45.1','dimod':'0.12.22','dwave-neal':'0.6.0'}
    assert versions==expected,(versions,expected)
    for name in ['numpy','scipy','networkx','qiskit','qiskit_aer','qiskit_algorithms','qiskit_optimization','pennylane','dimod','neal']:
        __import__(name)
    return dict(python=sys.version,executable=sys.executable,platform=platform.platform(),packages=versions,
                all_packages={d.metadata['Name']:d.version for d in importlib.metadata.distributions()},
                original_platform='Linux aarch64; current replay is x86_64. Package versions match; platform/compiler and CPU performance may differ.')


def execute(request,timeout):
    start=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='qbe-v2-replay-') as tmp:
        folder=Path(tmp);req=folder/'request.json';result=folder/'result.json';req.write_text(json.dumps(request))
        env={k:os.environ[k] for k in ('PATH','LANG','LD_LIBRARY_PATH') if k in os.environ}
        env.update(HOME=tmp,CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
        with (folder/'stdout').open('w+') as out,(folder/'stderr').open('w+') as err:
            proc=subprocess.Popen([str(PYTHON),'-I',str(HERE/'paired_child.py'),str(req),str(result)],cwd=tmp,env=env,stdout=out,stderr=err,start_new_session=True)
            timed_out=False
            try:proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out=True
                os.killpg(proc.pid,signal.SIGKILL);proc.wait()
            finally:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            out.seek(0);err.seek(0);logs=dict(stdout=out.read(64000),stderr=err.read(64000),returncode=proc.returncode,elapsed_seconds=time.monotonic()-start)
        parsed=json.loads(result.read_text()) if result.exists() else {}
        if timed_out:
            failure=dict(status='evaluation_timeout',timeout_seconds=timeout,phase=parsed.get('phase'))
            return dict(original=failure,v2=failure,**logs)
        if proc.returncode!=0 or 'original' not in parsed or 'v2' not in parsed:
            status='evaluation_crash' if proc.returncode<0 and parsed.get('status')=='in_progress' else 'evaluation_environment_failure'
            failure=dict(status=status,phase=parsed.get('phase'),error='Replay process did not complete paired outcomes')
            return dict(original=failure,v2=failure,**logs)
        return dict(**parsed,**logs)


def task_key(x):
    a,b=x.split('_');return a,int(b)


def run_one(job):
    path,metadata,request,timeout=job
    if path.exists():
        cached=json.loads(path.read_text())
        assert cached['request_sha256']==metadata['request_sha256']
        return cached
    if metadata.get('historical_status') in TERMINAL_GENERATION:
        res={'original':{'status':metadata['historical_status']},'v2':{'status':metadata['historical_status']},'entry_calls':0,'generation_terminal_preserved':True}
    else:
        res=execute(request,timeout)
    record=dict(**metadata,**res)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2));temp.replace(path)
    return record


def main():
    ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['references','samples']);ap.add_argument('--workers',type=int,default=12);args=ap.parse_args()
    protocol=json.loads((OUT/'protocol.json').read_text())
    env=environment();(OUT/'environment.json').write_text(json.dumps(env,indent=2))
    originals={};variants={}
    for topic in ('T2','T6'):
        original_path=ROOT/'qbe_export/datasets'/f'QuantumBenchEval_{topic}.json'
        assert digest(original_path)==protocol['source_sha256'][str(original_path.relative_to(ROOT))]
        originals.update({t['task_id']:t for t in json.loads(original_path.read_text())['tasks']})
        variants.update({t['task_id']:t for t in json.loads((HERE/'datasets'/original_path.name).read_text())['tasks']})
    evaluator_hashes={p.name:digest(p) for p in (HERE/'paired_child.py',HERE/'original_child.py',HERE/'run.py')}
    frozen=OUT/'evaluator_manifest.json'
    if frozen.exists():assert json.loads(frozen.read_text())==evaluator_hashes,'Evaluator changed after first execution'
    else:frozen.write_text(json.dumps(evaluator_hashes,indent=2))
    jobs=[]
    for tid in sorted(originals,key=task_key):
        topic=tid.split('_')[0].upper();task=originals[tid]
        if args.stage=='references':
            records=[('reference',None,dict(generation={'code':task['canonical_solution']}))]
        else:
            records=[]
            for path in sorted((ROOT/'qbe_export/results').glob(f'*/{topic}/samples/{tid}.*.json')):
                relative=str(path.relative_to(ROOT));assert digest(path)==protocol['source_sha256'][relative]
                records.append((path.parts[-4],path,json.loads(path.read_text())))
        for model,source,r in records:
            request=dict(code=r.get('generation',{}).get('code') or '',entry_point=task['entry_point'],original_test=task['test'],v2_test=variants[tid]['test'])
            sample_id=f'{tid}.{r["sample_index"]}' if source else tid
            sha=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
            metadata=dict(model=model,topic=topic,task_id=tid,sample_id=sample_id,sample_index=r.get('sample_index'),
                          historical_status=r.get('status'),included_v2=tid not in protocol['excluded_t2_tasks'],
                          source=str(source.relative_to(ROOT)) if source else f'qbe_export/datasets/QuantumBenchEval_{topic}.json:canonical_solution:{tid}',request_sha256=sha)
            path=OUT/'raw'/args.stage/model/(sample_id+'.json');path.parent.mkdir(parents=True,exist_ok=True)
            jobs.append((path,metadata,request,protocol['timeouts_seconds'][topic]))
    print(f'{args.stage}: {len(jobs)} paired evaluations, {args.workers} workers; matching dependency versions.',flush=True)
    counts={};infra=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(run_one,job) for job in jobs]
        for index,future in enumerate(concurrent.futures.as_completed(futures),1):
            record=future.result();key=record['v2']['status'];counts[key]=counts.get(key,0)+1
            if any(record[v]['status']=='evaluation_environment_failure' for v in ('original','v2')):infra.append(record['source'])
            if args.stage=='references' or index%25==0 or index==len(jobs):
                print(f'{index}/{len(jobs)} {record["model"]} {record["sample_id"]}: historical={record["historical_status"]} original={record["original"]["status"]} v2={key}; totals={counts}',flush=True)
    assert all(digest(ROOT/path)==sha for path,sha in protocol['source_sha256'].items()),'Original input changed'
    print(f'Completed {args.stage}. Infrastructure failures: {len(infra)}. Source hashes unchanged.',flush=True)
    if infra:
        (OUT/f'{args.stage}_infrastructure_failures.json').write_text(json.dumps(infra,indent=2))
        raise SystemExit(2)

if __name__=='__main__':main()
