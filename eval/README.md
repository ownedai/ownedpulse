# Evaluation

_Stub — full text to follow._

## Contents

| File | Role |
|---|---|
| `questions_v2.json` | Question bank: 51 questions across categories A (core lookup), B (cross-framework), C (boundary/scope) |
| `generation_fixture.json` | Frozen baseline run — the 50 questions with the exact retrieved context and phi4:14b-q8_0 answer each was scored against. |
| `eval_runner_v2.py` | Runs the question bank against the query API and scores each answer with four evaluator models. Holds the scoring rubric. |
| `eval_score_answers.py` | Scores externally generated answers (OpenRouter models) with the same evaluators and rubric. Reads `generation_fixture.json` for the retrieved context. |
| `eval_score_sonnet.py` | Scores Claude Sonnet answers with the same evaluators and rubric. |
| `summarise.py` | Recomputes every percentage quoted in the README from the six result files below. |
| `results_v2_20260613_160027.json` | Baseline run — ownedpulse with phi4:14b-q8_0 as the generation model. |
| `results_llama4scout_20260614_063214.json` | Generation model comparison — Llama 4 Scout. |
| `results_qwen25_72b_20260614_072311.json` | Generation model comparison — Qwen2.5-72B. |
| `results_gptoss20b_20260614_074613.json` | Generation model comparison — GPT-OSS-20B. |
| `results_gptoss120b_20260614_065717.json` | Generation model comparison — GPT-OSS-120B. |
| `results_sonnet_20260613_201401.json` | Generation model comparison — Claude Sonnet 4.6 (cloud reference). |

Each `results_*.json` holds per-question answers, retrieved sources, and one
score plus a faithfulness verdict per evaluator. Percentages in the README are
recomputed from these files; the evaluator averages are derived from the three
independent evaluators (claude, gpt, deepseek) — `phi4` scores in the same
files are the generation model's self-assessment and are not part of any
independent average.

Running the scripts requires `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and
`DEEPSEEK_API_KEY` in the environment (see `.env.example`). No keys are
stored in this directory.
