#!/usr/bin/env python3
"""
summarise.py — recompute the evaluation numbers quoted in the README.

Reads the six scored result files sitting next to this script and prints, for
each, the per-evaluator score percentage overall and per category, followed by
the two judge averages the README cites. No dependencies beyond the standard
library.

Usage:
    python3 eval/summarise.py
"""

import json
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent

# Label -> result file. Order matches the README tables.
RUNS = [
    ("phi4:14b-q8_0 (baseline)", "results_v2_20260613_160027.json"),
    ("Llama 4 Scout",            "results_llama4scout_20260614_063214.json"),
    ("Qwen2.5-72B",              "results_qwen25_72b_20260614_072311.json"),
    ("GPT-OSS-20B",              "results_gptoss20b_20260614_074613.json"),
    ("GPT-OSS-120B",             "results_gptoss120b_20260614_065717.json"),
    ("Claude Sonnet 4.6",        "results_sonnet_20260613_201401.json"),
]

EVALUATORS = ["claude", "gpt", "deepseek", "phi4"]
CATEGORIES = ["A", "B", "C"]

THREE_JUDGES = ["claude", "gpt", "deepseek"]
TWO_JUDGES = ["claude", "gpt"]


def pct(scores):
    """Mean score as a percentage of the 3-point scale, or None if no scores."""
    return round(sum(scores) / len(scores) / 3 * 100, 1) if scores else None


def collect(doc):
    """{evaluator: {'ALL': [...], 'A': [...], 'B': [...], 'C': [...]}}"""
    out = {ev: {k: [] for k in ["ALL"] + CATEGORIES} for ev in EVALUATORS}
    for r in doc["results"]:
        cat = r.get("category")
        for ev, entry in (r.get("scores") or {}).items():
            if ev not in out or not isinstance(entry, dict):
                continue
            score = entry.get("score")
            if score is None or score < 0:
                continue
            out[ev]["ALL"].append(score)
            if cat in out[ev]:
                out[ev][cat].append(score)
    return out


def mean_of(buckets, judges, key):
    """Mean of the given judges' percentages for one bucket key."""
    vals = [pct(buckets[j][key]) for j in judges if pct(buckets[j][key]) is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def fmt(value):
    return "n/a" if value is None else f"{value:.1f}%"


def report(label, doc):
    buckets = collect(doc)
    print("=" * 68)
    print(f"{label}   [{doc.get('total_questions', len(doc['results']))} questions]")
    print("=" * 68)
    header = f"{'Evaluator':<10} {'n':>4} {'Overall':>9} {'A':>8} {'B':>8} {'C':>8}"
    print(header)
    print("-" * len(header))
    for ev in EVALUATORS:
        b = buckets[ev]
        print(f"{ev:<10} {len(b['ALL']):>4} {fmt(pct(b['ALL'])):>9} "
              f"{fmt(pct(b['A'])):>8} {fmt(pct(b['B'])):>8} {fmt(pct(b['C'])):>8}")

    print()
    for name, judges in (("Mean of 3 judges (Claude, GPT-4.1, DeepSeek)", THREE_JUDGES),
                         ("Mean of 2 judges (Claude, GPT-4.1)", TWO_JUDGES)):
        print(f"{name}")
        print(f"  Overall {fmt(mean_of(buckets, judges, 'ALL'))}   "
              f"A {fmt(mean_of(buckets, judges, 'A'))}   "
              f"B {fmt(mean_of(buckets, judges, 'B'))}   "
              f"C {fmt(mean_of(buckets, judges, 'C'))}")
    print()


def main():
    for label_, filename in RUNS:
        path = EVAL_DIR / filename
        if not path.exists():
            print(f"MISSING: {filename}\n")
            continue
        report(label_, json.loads(path.read_text()))


if __name__ == "__main__":
    main()
