#!/usr/bin/env python3
"""Export experiment results into static JSON for the leaderboard site.

Reads data/results/**/results_*.json (produced by the benchmark framework)
and data/benchmarks/*.json(l) (task metadata: category/difficulty), and
writes leaderboard/leaderboard_summary.json + leaderboard/leaderboard_details.json.

All pass@k math is computed here, in Python, using the same numbers the
benchmark run itself produced (pass_at_k.per_task) wherever available. The
JS on the site only sorts/filters/renders these precomputed numbers.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_ROOT = REPO_ROOT / "data" / "results"
BENCHMARKS_ROOT = REPO_ROOT / "data" / "benchmarks"
OUT_DIR = REPO_ROOT / "leaderboard"
CI_PATH = RESULTS_ROOT / "confidence_intervals.json"

# dataset label -> key used inside confidence_intervals.json
DATASET_CI_KEY = {
    "QiskitHumanEval": "qiskit_humaneval_standard",
    "QiskitHumanEvalHard": "qiskit_humaneval_hard",
    "QuanBench44": "quanbench-44",
    "QuanBench117": "quanbench-117",
    "QCoder": "qcoder_claude_judge",
}

# raw "assistant" field (lowercased) -> display name shown on the site.
# Kept explicit rather than auto-derived: several raw ids are ambiguous or
# inconsistent across scripts (e.g. "mistral3" vs "mistral-small-3.2-24b-qiskit"
# are DIFFERENT recorded runs, not the same model under two names).
MODEL_DISPLAY_NAMES = {
    "gpt-5": "GPT-5",
    "claude-opus-4-6": "Claude Opus 4.6",
    "gemini-3-flash-preview": "Gemini 3 Flash",
    "gemini-2.0-flash": "Gemini 2.0 Flash",
    "google/gemma-3-4b-it": "Gemma-3-4B-IT",
    "meta-llama/llama-3.1-8b": "LLaMA-3.1-8B",
    "meta-llama/llama-3.2-3b-instruct": "LLaMA-3.2-3B-Instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct": "LLaMA-4-Scout-17B",
    "mistralai/mistral-7b-instruct-v0.3": "Mistral-7B-Instruct-v0.3",
    "mistral-small-3.2-24b-qiskit": "Mistral-3.2-24B-Qiskit",
    "mistral3": "Mistral3-Qiskit",
    "qwen": "Qwen2.5-Coder-Qiskit",
    "qwen2.5-coder-14b-qiskit": "Qwen2.5-Coder-14B-Qiskit",
    "qiskit/granite-8b-qiskit": "Granite-8B-Qiskit",
    "qiskit/granite-3.2-8b-qiskit": "Granite-3.2-8B-Qiskit",
    "quantum-rag": "Quantum RAG",
}

TS_RE = re.compile(r"(\d{8}_\d{6})")


def clean_model_name(raw: str) -> str:
    key = (raw or "").strip().lower()
    if key in MODEL_DISPLAY_NAMES:
        return MODEL_DISPLAY_NAMES[key]
    return raw.split("/")[-1]


def parse_timestamp(path: Path) -> str:
    m = TS_RE.search(path.name)
    return m.group(1) if m else ""


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def extract_samples(data: dict) -> dict[str, list[dict]]:
    """Normalize the two result-file schemas into {task_id: [sample, ...]}."""
    if isinstance(data.get("raw_task_results"), dict):
        return data["raw_task_results"]
    if isinstance(data.get("results"), list):
        out: dict[str, list[dict]] = {}
        for entry in data["results"]:
            tid = entry.get("task_id")
            if tid is not None:
                out[str(tid)] = entry.get("results", [])
        return out
    return {}


def resolve_dataset_label(path: Path, data: dict, samples: dict) -> Optional[str]:
    benchmark = data.get("benchmark")
    if benchmark == "qiskit_humaneval_standard":
        return "QiskitHumanEval"
    if benchmark == "qiskit_humaneval_hard":
        return "QiskitHumanEvalHard"
    if benchmark == "quanbench":
        name = path.name
        if "-44" in name:
            return "QuanBench44"
        if "-117" in name:
            return "QuanBench117"
        n = len(samples)
        if n == 44:
            return "QuanBench44"
        if n == 117:
            return "QuanBench117"
        return None
    if "qcoder" in str(path).lower():
        return "QCoder"
    return None


def load_task_metadata() -> dict[tuple[str, str], dict]:
    """(dataset_label, task_id) -> {category, difficulty}."""
    lookup: dict[tuple[str, str], dict] = {}

    def add(dataset_label: str, items: list[dict]) -> None:
        for item in items:
            tid = str(item.get("task_id", ""))
            lookup[(dataset_label, tid)] = {
                "category": item.get("category") or "Uncategorized",
                "difficulty": item.get("difficulty_scale") or item.get("difficulty") or "",
            }

    add("QiskitHumanEval", load_json(BENCHMARKS_ROOT / "dataset_qiskit_test_human_eval_categorized.json"))
    add("QiskitHumanEvalHard", load_json(BENCHMARKS_ROOT / "dataset_qiskit_test_human_eval_hard.json"))
    add("QuanBench44", load_jsonl(BENCHMARKS_ROOT / "QuanBench44_categorized.jsonl"))
    add("QuanBench117", load_jsonl(BENCHMARKS_ROOT / "QuanBench117_categorized.jsonl"))
    # QCoder ships no local task metadata; those rows fall back to "Uncategorized".
    return lookup


def format_run_date(ts: str) -> str:
    """'20260329_120510' -> '2026-03-29' (used as the Models page's Rank Date)."""
    if len(ts) < 8:
        return ""
    return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"


def collect_latest_result_files() -> tuple[dict[tuple[str, str], tuple[str, Path, dict, dict]], list[tuple[str, str]]]:
    """One (timestamp, path, data, samples) per (model, dataset), keeping the newest run."""
    best: dict[tuple[str, str], tuple[str, Path, dict, dict]] = {}
    skipped: list[tuple[str, str]] = []

    for path in sorted(RESULTS_ROOT.rglob("results_*.json")):
        try:
            data = load_json(path)
        except Exception as e:
            skipped.append((str(path), f"unreadable: {e}"))
            continue

        samples = extract_samples(data)
        dataset_label = resolve_dataset_label(path, data, samples)
        if dataset_label is None:
            skipped.append((str(path), "could not resolve dataset label"))
            continue

        raw_assistant = data.get("assistant") or ""
        model = clean_model_name(raw_assistant)

        key = (model, dataset_label)
        ts = parse_timestamp(path)
        if key not in best or ts > best[key][0]:
            best[key] = (ts, path, data, samples)

    return {k: (v[0], v[1], v[2], v[3]) for k, v in best.items()}, skipped


def main() -> None:
    task_lookup = load_task_metadata()
    ci_data = load_json(CI_PATH) if CI_PATH.exists() else {}

    best_files, skipped = collect_latest_result_files()

    model_last_run: dict[str, str] = {}

    detail_rows: list[dict] = []
    for (model, dataset_label), (ts, path, data, samples) in best_files.items():
        if ts > model_last_run.get(model, ""):
            model_last_run[model] = ts

        per_task_pak = ((data.get("pass_at_k") or {}).get("per_task")) or {}

        for task_id, task_samples in samples.items():
            if not isinstance(task_samples, list):
                continue
            n_total = len(task_samples)
            n_passed = sum(1 for s in task_samples if isinstance(s, dict) and s.get("passed") is True)
            n_syntax_err = sum(1 for s in task_samples if isinstance(s, dict) and s.get("syntax_valid") is False)
            n_runtime_err = sum(1 for s in task_samples if isinstance(s, dict) and s.get("runtime_error") is True)

            tinfo = task_lookup.get((dataset_label, str(task_id)), {})
            tpak = per_task_pak.get(task_id) or per_task_pak.get(str(task_id)) or {}

            detail_rows.append({
                "model": model,
                "dataset": dataset_label,
                "task_id": str(task_id),
                "category": tinfo.get("category", "Uncategorized"),
                "difficulty": tinfo.get("difficulty", ""),
                "n_samples": n_total,
                "n_passed": n_passed,
                "n_syntax_err": n_syntax_err,
                "n_runtime_err": n_runtime_err,
                "pass_at_1": tpak.get("1", (n_passed / n_total) if n_total else 0.0),
                "pass_at_3": tpak.get("3"),
                "pass_at_5": tpak.get("5"),
            })

    # Aggregate per (model, dataset) from the detail rows themselves, so the
    # summary numbers are always consistent with what the drill-down shows.
    agg: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"n": 0, "sum1": 0.0, "sum3": 0.0, "n3": 0, "sum5": 0.0, "n5": 0}
    )
    for row in detail_rows:
        a = agg[(row["model"], row["dataset"])]
        a["n"] += 1
        a["sum1"] += row["pass_at_1"]
        if row["pass_at_3"] is not None:
            a["sum3"] += row["pass_at_3"]
            a["n3"] += 1
        if row["pass_at_5"] is not None:
            a["sum5"] += row["pass_at_5"]
            a["n5"] += 1

    summary_rows: list[dict] = []
    for (model, dataset_label), a in agg.items():
        ci_key = DATASET_CI_KEY.get(dataset_label)
        ci_entry = (ci_data.get(model) or {}).get(ci_key, {}) if ci_key else {}

        def ci_bounds(k: str) -> tuple[Optional[float], Optional[float]]:
            c = ci_entry.get(k)
            return (c.get("ci_lo"), c.get("ci_hi")) if c else (None, None)

        lo1, hi1 = ci_bounds("1")
        lo3, hi3 = ci_bounds("3")
        lo5, hi5 = ci_bounds("5")

        summary_rows.append({
            "model": model,
            "dataset": dataset_label,
            "last_run": format_run_date(model_last_run.get(model, "")),
            "n_tasks": a["n"],
            "pass_at_1": a["sum1"] / a["n"] if a["n"] else None,
            "pass_at_1_ci_lo": lo1,
            "pass_at_1_ci_hi": hi1,
            "pass_at_3": a["sum3"] / a["n3"] if a["n3"] else None,
            "pass_at_3_ci_lo": lo3,
            "pass_at_3_ci_hi": hi3,
            "pass_at_5": a["sum5"] / a["n5"] if a["n5"] else None,
            "pass_at_5_ci_lo": lo5,
            "pass_at_5_ci_hi": hi5,
        })

    summary_rows.sort(key=lambda r: (r["dataset"], -(r["pass_at_1"] or 0)))
    detail_rows.sort(key=lambda r: (r["dataset"], r["model"], r["task_id"]))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "leaderboard_summary.json").write_text(json.dumps(summary_rows, indent=2))
    (OUT_DIR / "leaderboard_details.json").write_text(json.dumps(detail_rows, indent=2))

    print(f"Wrote {len(summary_rows)} summary rows and {len(detail_rows)} detail rows "
          f"from {len(best_files)} result files ({len(set(m for m, _ in best_files))} models).")
    if skipped:
        print(f"Skipped {len(skipped)} file(s):", file=sys.stderr)
        for p, reason in skipped:
            print(f"  {p}: {reason}", file=sys.stderr)


if __name__ == "__main__":
    main()
