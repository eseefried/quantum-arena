"""Evaluate two untouched test scripts against ONE execution of saved candidate code.

Runtime output is not normalized. The original scorer's import classification is reused.
Only the entry point is memoized; recursive calls execute normally while it is active.
"""
import importlib.util
import json
import sys
import traceback
from pathlib import Path

spec=importlib.util.spec_from_file_location('qbe_original_child',Path(__file__).with_name('original_child.py'))
original=importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)


def outcome(exc,phase):
    if isinstance(exc,(ImportError,ModuleNotFoundError)):
        if phase=='candidate' or original.raised_by_candidate(exc):
            status,kind,module=original.classify_import(exc)
        else:
            status,kind,module='evaluation_environment_failure','dataset_test_import',getattr(exc,'name','') or ''
        return dict(status=status,import_kind=kind,module=module,error=str(exc),phase=phase,traceback=traceback.format_exc())
    return dict(status='incorrect' if isinstance(exc,AssertionError) else 'candidate_error',
                error=str(exc),phase=phase,traceback=traceback.format_exc())


def main():
    request=json.loads(Path(sys.argv[1]).read_text());result_path=Path(sys.argv[2])
    namespace={'__name__':'__candidate__'}
    original.write_marker(str(result_path),'candidate')
    try:
        exec(compile(request['code'],'<candidate>','exec'),namespace)
    except BaseException as exc:
        result=outcome(exc,'candidate')
        result_path.write_text(json.dumps(dict(original=result,v2=result,entry_calls=0)))
        return
    entry=request['entry_point'];actual=namespace.get(entry);cache={};active=False;calls=0
    if actual is not None:
        def invoke(*args,**kwargs):
            nonlocal active,calls
            if active:
                return actual(*args,**kwargs)
            if 'exception' in cache:
                raise cache['exception']
            if 'value' in cache:
                return cache['value']
            calls+=1;active=True
            try:
                cache['value']=actual(*args,**kwargs)
            except BaseException as exc:
                cache['exception']=exc
                raise
            finally:
                active=False
            return cache['value']
        namespace[entry]=invoke
    results={}
    for variant in ('original','v2'):
        original.write_marker(str(result_path),'dataset_test_'+variant)
        try:
            # The namespace is shared exactly as in the supplied evaluator. The test
            # never mutates the returned object; both variants bind result afresh.
            exec(compile(request[variant+'_test'],'<dataset-test>','exec'),namespace)
            results[variant]={'status':'passed'}
        except BaseException as exc:
            results[variant]=outcome(exc,'dataset_test')
    assert calls<=1
    results['entry_calls']=calls
    if 'value' in cache:
        results['returned_type']=type(cache['value']).__name__
        try:results['returned_repr']=repr(cache['value'])[:64000]
        except BaseException:results['returned_repr']='<repr unavailable>'
    result_path.write_text(json.dumps(results,allow_nan=False))

if __name__=='__main__':main()
