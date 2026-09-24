import unittest
from pathlib import Path
from html.parser import HTMLParser
from export_quantumbencheval import metrics, check, topic_data, SOURCE, OUT


class PreviewTests(unittest.TestCase):
    def test_partial_and_infrastructure_are_not_failures(self):
        rows = [dict(task_id='a', sample_index=i, status='passed') for i in range(5)]
        rows += [dict(task_id='b', sample_index=0, status='passed')]
        rows += [dict(task_id='c', sample_index=i, status='evaluation_environment_failure') for i in range(5)]
        self.assertEqual(metrics(rows, ['a', 'b', 'c']), {'1': 1.0, '3': 1.0, '5': 1.0})

    def test_judged_never_becomes_pass(self):
        rows = [dict(task_id='a', sample_index=i, status='judged') for i in range(5)]
        self.assertEqual(metrics(rows, ['a']), {'1': None, '3': None, '5': None})

    def test_candidate_failures_remain_in_denominator(self):
        rows = [dict(task_id='a', sample_index=i, status='passed' if i == 0 else 'truncated') for i in range(5)]
        self.assertAlmostEqual(metrics(rows, ['a'])['1'], .2)
        self.assertEqual(metrics(rows, ['a'])['5'], 1)

    def test_summary_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            check(.2, .3, 'pass@1')

    def test_all_transferred_records_and_t3_coverage(self):
        topics = [topic_data(SOURCE / 'results/gemini36-flash', f'T{i}') for i in range(1, 7)]
        self.assertEqual(sum(t['samples'] for t in topics), 480)
        self.assertEqual(topics[2]['judged_samples'], 43)
        self.assertNotIn('pass_at_k', topics[2])
        self.assertAlmostEqual(topics[2]['mean_rubric_score'], 244/43)

    def test_integrated_export(self):
        import json
        data = json.loads((OUT / 'quantumbencheval.json').read_text())
        default = next(m for m in data['models'] if m['key'] == 'gemini36-flash')
        self.assertEqual(len(default['topics']), 6)
        t3 = default['topics'][2]
        self.assertEqual(len(json.loads((OUT / 'qbe_content/T3.json').read_text())['models']), len(data['models']))
        self.assertEqual(sum(t['judged_samples'] for t in t3['task_details']), 43)
        self.assertTrue(all(t['pass_at_k'] is None for t in t3['task_details']))
        self.assertEqual(len(t3['task_details']), 15)
        self.assertIn('collection-tabs', (OUT / 'index.html').read_text())
        self.assertIn('quantumbencheval.js', (OUT / 'index.html').read_text())
        for page in OUT.glob('quantumbencheval*.html'):
            self.assertIn('index.html?collection=qbe', page.read_text())


if __name__ == '__main__':
    unittest.main()
