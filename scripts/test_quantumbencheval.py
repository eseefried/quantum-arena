import unittest
from pathlib import Path
from html.parser import HTMLParser
from export_quantumbencheval import metrics, check, topic_data, SOURCE, OUT


class PreviewTests(unittest.TestCase):
    def test_partial_and_infrastructure_are_not_failures(self):
        rows = [dict(task_id='a', sample_index=i, status='passed') for i in range(5)]
        rows += [dict(task_id='b', sample_index=0, status='passed')]
        rows += [dict(task_id='c', sample_index=i, status='evaluation_environment_failure') for i in range(5)]
        self.assertEqual(metrics(rows, ['a', 'b', 'c']), {'1': 1.0, '5': 1.0})

    def test_judged_never_becomes_pass(self):
        rows = [dict(task_id='a', sample_index=i, status='judged') for i in range(5)]
        self.assertEqual(metrics(rows, ['a']), {'1': None, '5': None})

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

    def test_generated_pages_and_links(self):
        class Links(HTMLParser):
            def handle_starttag(self, tag, attrs):
                for key, value in attrs:
                    if key in ('href', 'src') and value.startswith('./'):
                        assert (OUT / value).exists(), value
        for page in OUT.glob('quantumbencheval*.html'):
            html = page.read_text()
            Links().feed(html)
            self.assertIn('Preview', html)
            self.assertNotIn('col-rank', html)
        t3 = (OUT / 'quantumbencheval-T3.html').read_text()
        self.assertNotIn('Pass@', t3)
        self.assertIn('43/75 samples scored', t3)
        self.assertIn('claude-sonnet-4-6', t3)


if __name__ == '__main__':
    unittest.main()
