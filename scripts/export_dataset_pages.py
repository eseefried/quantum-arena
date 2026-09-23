#!/usr/bin/env python3
"""Generate dataset reference pages from the local benchmark inventory."""
import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'leaderboard'
INVENTORY = [
    ('QiskitHumanEval', 'Qiskit HumanEval', 'Qiskit programming tasks', 'Pass@1 / 3 / 5',
     'Tasks ask models to generate Python code using Qiskit. Each problem includes a prompt and a reference solution, with saved attempts available in Arena’s Problem View.',
     'The standard set contains 151 problems. Category filters organize the saved tasks by quantum-programming skill. Scores summarize the recorded boolean evaluation verdicts.'),
    ('QiskitHumanEvalHard', 'Qiskit HumanEval Hard', 'Hard Qiskit programming set', 'Pass@1 / 3 / 5',
     'The hard set is presented separately from the standard Qiskit HumanEval set. It contains 151 problems with prompts, reference solutions, and saved model attempts.',
     'Use this dataset’s own scores and problem records to inspect performance. Its problem count does not imply identical prompts or difficulty to the standard set. Scores summarize recorded boolean evaluation verdicts.'),
    ('QuanBench44', 'QuanBench-44', 'Quantum circuit and algorithm tasks', 'Pass@1 / 3 / 5',
     'A 44-problem Qiskit benchmark with task prompts, reference implementations, and executable tests. The local metadata includes categories for exploring different programming skills.',
     'Tests are task-specific. For example, some circuit tasks compare output distributions with the reference circuit and check expected measurement outcomes. Arena summarizes the saved pass/fail verdicts.'),
    ('QuanBench117', 'QuanBench-117', 'Quantum circuit and algorithm tasks', 'Pass@1 / 3 / 5',
     'A 117-problem Qiskit benchmark, displayed as its own dataset. Problem View exposes the available prompts, reference implementations, and model outputs.',
     'Task-specific tests determine the recorded pass/fail outcomes. Category filters use the metadata supplied with the local benchmark files. This set is not combined with QuanBench-44 in its dataset view.'),
    ('QCoder', 'QCoder', 'Quantum coding with judge verdicts', 'Pass@1 / 3 / 5',
     'A 67-problem quantum coding dataset. Its saved evaluations use a Claude judge to assign pass/fail verdicts to model outputs.',
     'Judge versions differ across runs: older runs use claude-sonnet-4-20250514, while newer runs include claude-sonnet-4-6. These verdicts are binary, unlike QuantumBenchEval T3’s numerical rubric. Category and difficulty metadata are not available for this set.'),
    ('QuantumBenchEval', 'QuantumBenchEval', 'Six scientific quantum-computing topics', 'Pass@1 / 5; T3 rubric',
     'A 96-problem collection spanning six topics, with five requested samples per problem. The current collection contains one model, Gemini 3.6 Flash, and 480 sample records.',
     'T1, T2, T4, T5, and T6 use executable correctness checks and report pass@1 and pass@5. T3 reports a mean rubric score on a 0–10 scale, separately from pass rates. No combined score or comparative ranking is presented.'),
]


def page(title, subtitle, body):
    shell = (OUT / 'models.html').read_text().split('  <header class="page-header">')[0]
    shell = shell.replace('Quantum Arena — Models', 'Quantum Arena — ' + escape(title))
    shell = shell.replace('class="site-nav-link active" href="./models.html"', 'class="site-nav-link" href="./models.html"')
    shell = shell.replace('class="site-nav-link" href="./datasets.html"', 'class="site-nav-link active" href="./datasets.html"')
    return shell + f'<header class="page-header"><h1>{escape(title)}</h1><p class="subtitle">{escape(subtitle)}</p></header><main>{body}</main></body></html>\n'


def main():
    rows = []
    for key, title, focus, scoring, intro, evaluation in INVENTORY:
        if key == 'QuantumBenchEval':
            topics = [json.loads((ROOT / f'qbe_export/datasets/QuantumBenchEval_T{i}.json').read_text()) for i in range(1, 7)]
            count = sum(len(t['tasks']) for t in topics)
        else:
            content = json.loads((OUT / f'problem_content/{key}.json').read_text())
            count = len(content['tasks'])
        url = f'./dataset-{key}.html'
        rows.append(f'<tr><td class="model-name"><a href="{url}">{escape(title)}</a></td><td>{count}</td><td>5</td><td>{escape(scoring)}</td><td>{escape(focus)}</td></tr>')
        body = f'<p><a href="./datasets.html">← All datasets</a></p><section class="qbe-panel"><p>{escape(intro)}</p><dl class="qbe-statuses"><div><dt>Problems</dt><dd>{count}</dd></div><div><dt>Samples per problem</dt><dd>5</dd></div></dl><h2>What is evaluated</h2><p>{escape(evaluation)}</p>'
        if key == 'QuantumBenchEval':
            body += '<h2>Topics</h2><div class="table-scroll"><table class="board"><thead><tr><th>Topic</th><th>Problems</th><th>Scoring</th></tr></thead><tbody>'
            for i, topic in enumerate(topics, 1):
                body += f'<tr><td><a href="./index.html?collection=qbe&amp;topic=T{i}">{escape(topic["topic"])}</a></td><td>{len(topic["tasks"])}</td><td>{"Rubric score, 0–10" if i == 3 else "Pass@1 / 5"}</td></tr>'
            body += '</tbody></table></div><h2>Scoring and coverage</h2><p>T3 uses claude-sonnet-4-6 with the qbe-t3-rubric-v2 protocol. Its mean is 5.6744/10 across 43 scored samples; 32 truncated samples remain unscored. All 75 T3 sample records are present. Execution failures remain distinct from rubric scoring status.</p><h2>T1 scoring variants</h2><p>The original T1 tests require exact shots and optimizer_calls values that were not disclosed to candidates. The corrected replay replaces only these assertions with non-gating resource-closeness measurements, retaining other correctness checks. Arena displays the corrected replay scores, joined to the original prompts and generated code. Original results remain preserved in the source records.</p><p><a href="./index.html?collection=qbe">Explore QuantumBenchEval in Arena →</a></p>'
        else:
            body += '<h2>Reading the results</h2><p>Pass@k estimates the chance of obtaining at least one passing answer from k samples, averaged across problems. Arena displays pass@1, pass@3, and pass@5 from five recorded samples per problem. These are evaluation outcomes, not guarantees about code used elsewhere.</p><p>Select this dataset in Arena to compare model scores, or switch to Problem View to inspect individual attempts.</p><p><a href="./index.html">Open Arena →</a></p>'
        body += '</section>'
        (OUT / f'dataset-{key}.html').write_text(page(title, focus, body))
    table = '<section class="board-wrap table-scroll"><table class="board"><thead><tr><th>Dataset</th><th>Problems</th><th>Samples / problem</th><th>Metrics</th><th>Focus</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></section><p class="footnote">Select a dataset name to learn about its tasks and scoring. Counts describe the local benchmark inventory; model coverage is shown in Arena.</p>'
    (OUT / 'datasets.html').write_text(page('Datasets', 'Problem counts, task coverage, and evaluation methods', table))
    print('Generated dataset directory and six detail pages.')


if __name__ == '__main__':
    main()
