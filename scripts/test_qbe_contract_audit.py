import ast
import unittest
from audit_qbe_contracts import classify, first_failure, read, SOURCE
from qbe_contract_enumeration import enumerate_task


class ContractAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = {t['task_id']: t for topic in ('T2', 'T6')
                     for t in read(SOURCE / 'datasets' / f'QuantumBenchEval_{topic}.json')['tasks']}

    def test_augmented_objective_field_is_disclosed(self):
        t=self.tasks['t2_0']
        a=next(a for a in ast.walk(ast.parse(t['test'])) if isinstance(a,ast.Assert) and 'achieved_priority' in ast.unparse(a))
        self.assertEqual(classify(t,a,enumerate_task(t))[0], 'SPECIFIED')

    def test_tie_does_not_require_reference_choice(self):
        result=enumerate_task(self.tasks['t2_6'])
        self.assertEqual(result['optimum'],23)
        self.assertEqual(len(result['optimal_selections']),4)

    def test_actual_manufacturing_optimum(self):
        result=enumerate_task(self.tasks['t2_14'])
        self.assertEqual(result['optimum'],41)
        self.assertEqual(result['optimal_selections'],[[1,2,3,5,7,8,9,10]])

    def test_inner_candidate_error_not_charged_to_dataset_assertion(self):
        r={'status':'candidate_error','execution':{'traceback':'Traceback (most recent call last):\n  File "<dataset-test>", line 7, in <module>\n  File "<candidate>", line 18, in f\nKeyError: missing\n'}}
        result=first_failure(r,self.tasks['t2_0'])
        self.assertEqual(result['first_assertion_line'],'')
        self.assertEqual(result['dataset_call_line'],7)
        self.assertEqual(result['exception'],'KeyError')

    def test_direct_dataset_keyerror_is_attributed(self):
        r={'status':'candidate_error','execution':{'traceback':'Traceback (most recent call last):\n  File "<dataset-test>", line 7, in <module>\nKeyError: achieved_priority\n'}}
        self.assertEqual(first_failure(r,self.tasks['t2_0'])['first_assertion_line'],7)

    def test_multiline_assertion_is_attributed(self):
        r={'status':'incorrect','execution':{'traceback':'Traceback (most recent call last):\n  File "<dataset-test>", line 17, in <module>\nAssertionError: quality\n'}}
        self.assertEqual(first_failure(r,self.tasks['t6_0'])['first_assertion_line'],16)

    def test_requested_astra_example(self):
        r=read(SOURCE/'results/astra/T6/samples/t6_0.0.json')
        result=first_failure(r,self.tasks['t6_0'])
        self.assertEqual((result['exception'],result['first_assertion_line']),('TypeError',27))

    def test_threshold_explicit_only_in_late_t6_prompts(self):
        for tid,expected in [('t6_0','UNDISCLOSED'),('t6_15','SPECIFIED'),('t6_16','SPECIFIED')]:
            t=self.tasks[tid]
            a=next(a for a in ast.walk(ast.parse(t['test'])) if isinstance(a,ast.Assert) and 'result["approximation_ratio"]' in ast.get_source_segment(t['test'],a))
            self.assertEqual(classify(t,a,None)[0],expected)


if __name__=='__main__':
    unittest.main()
