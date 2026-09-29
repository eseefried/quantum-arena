import ast
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from prepare import ROOT,HERE,COST_TASKS,changed_test


class ScoringTests(unittest.TestCase):
    def test_exactly_the_declared_deletions(self):
        counts={'T2':0,'T6':0}
        for topic in counts:
            for task in json.loads((ROOT/f'qbe_export/datasets/QuantumBenchEval_{topic}.json').read_text())['tasks']:
                test,removed=changed_test(task);counts[topic]+=len(removed)
                self.assertEqual(test,next(t['test'] for t in json.loads((HERE/f'datasets/QuantumBenchEval_{topic}.json').read_text())['tasks'] if t['task_id']==task['task_id']))
                if task['task_id']=='t2_6':self.assertEqual(test,task['test'])
                if topic=='T6':
                    self.assertIn('assert result["approximation_ratio"]',test)
                    self.assertIn('assert 0.0 <= result["balance_constraint_score"] <= 1.0',test)
        self.assertEqual(counts,{'T2':8,'T6':17})

    def test_pair_reuses_output_and_can_reach_later_assertion(self):
        request={'code':'calls = 0\ndef f():\n global calls\n calls += 1\n assert calls == 1\n return {"evaluation_cost": 99, "selected_jobs": [2,3]}',
                 'entry_point':'f','original_test':'result=f()\nassert result["evaluation_cost"]==16\nassert set(result["selected_jobs"])=={2,3}\n',
                 'v2_test':'result=f()\nassert set(result["selected_jobs"])=={2,3}\n'}
        with tempfile.TemporaryDirectory() as tmp:
            req=Path(tmp)/'req.json';out=Path(tmp)/'out.json';req.write_text(json.dumps(request))
            subprocess.run([sys.executable,'-I',str(HERE/'paired_child.py'),str(req),str(out)],check=True)
            result=json.loads(out.read_text())
        self.assertEqual(result['entry_calls'],1)
        self.assertEqual(result['original']['status'],'incorrect')
        self.assertEqual(result['v2']['status'],'passed')

    def test_unbiased_estimator(self):
        from summarize import metric_estimates
        self.assertEqual(metric_estimates([0,1,5],5).tolist(),[0.,1.,1.])
        for actual,expected in zip(metric_estimates([0,1,5],1),[0.,.2,1.]):self.assertAlmostEqual(actual,expected)

    def test_bootstrap_keeps_task_clusters(self):
        from summarize import estimate
        rows=[dict(task_id=t,sample_index=i,status='passed' if t=='a' else 'incorrect') for t in ('a','b') for i in range(5)]
        result=estimate(rows,'status',['a','b'])
        self.assertEqual(result['pass1'],.5)
        self.assertEqual(result['pass1_ci_lo'],0.)
        self.assertEqual(result['pass1_ci_hi'],1.)
        self.assertEqual(result,estimate(rows,'status',['a','b']))

if __name__=='__main__':unittest.main()
