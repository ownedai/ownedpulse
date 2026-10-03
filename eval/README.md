# Evaluation

This directory contains the evaluation set, rubric, scoring scripts and result files behind the Evaluation section of the main README.

## Reproduce the README tables

```bash
python3 eval/summarise.py
```

Standard library only; no API keys or running services needed. Scores are 0–3 per question; percentage = mean score / 3 × 100.

## Contents

| File | What it is |
|---|---|
| `questions_v2.json` | Question bank: 51 questions in categories A, B, C. 50 were scored; Q052 was added after the scored runs and has not been scored. |
| `eval_runner_v2.py` | Runs the questions and collects judge scores. Contains the scoring rubric (`RUBRIC`). |
| `eval_score_answers.py` | Scores a frozen set of answers with the judge models. Reads `generation_fixture.json`. |
| `eval_score_sonnet.py` | Scoring script used for the Claude Sonnet 4.6 generation run. |
| `generation_fixture.json` | Frozen baseline: for each of the 50 questions, the retrieved context passed to the model and the phi4:14b-q8_0 answer that was scored. The comparison models received the same retrieved context. |
| `results_v2_20260613_160027.json` | Scores, phi4:14b-q8_0 (baseline) |
| `results_llama4scout_20260614_063214.json` | Scores, Llama 4 Scout |
| `results_qwen25_72b_20260614_072311.json` | Scores, Qwen2.5-72B |
| `results_gptoss20b_20260614_074613.json` | Scores, GPT-OSS-20B |
| `results_gptoss120b_20260614_065717.json` | Scores, GPT-OSS-120B |
| `results_sonnet_20260613_201401.json` | Scores, Claude Sonnet 4.6 |
| `summarise.py` | Recomputes every number in the README evaluation tables from the result files. |

## Notes

- Judges: Claude Sonnet 4.6, GPT-4.1, DeepSeek V4 Pro. The result files also contain a phi4 self-score; it is shown by `summarise.py` but excluded from all means because the generation model is not an independent judge.
- DeepSeek returned usable scores for 49 of 50 questions in most runs (48 for Qwen2.5-72B); its percentages use that denominator.
- Re-running the judges needs `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `DEEPSEEK_API_KEY` in the environment. Only public-corpus questions, retrieved public text and generated answers are sent to the hosted judge models.
- Answers for the comparison models were generated through hosted APIs from the frozen retrieved context. The generation scripts are not included.
