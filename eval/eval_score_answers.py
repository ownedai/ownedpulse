#!/usr/bin/env python3
"""
eval_score_answers.py
Score model answers using the same evaluators (claude, gpt, deepseek, phi4)
and rubric as the phi4 evaluation run.

Instead of re-querying ownedpulse, this script:
  1. Parses chunks from generation_fixture.json (the [N] markers in llm_input.prompt)
  2. Parses cited [N] markers from the model's answer
  3. Builds source excerpts from the chunks the model actually cited
  4. Sends answer + cited sources to each evaluator for scoring

Output:
  eval/results_{prefix}_{timestamp}.json
  eval/report_{prefix}_{timestamp}.txt

Usage:
  python eval_score_answers.py --answers sonnet_answers.json --output-prefix sonnet
  python eval_score_answers.py --answers answers_llama4scout_20260613_xxx.json --output-prefix llama4scout
  python eval_score_answers.py --answers answers_llama4scout_20260613_xxx.json --output-prefix llama4scout --limit 5

Requires:
  ANTHROPIC_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY in .env
  Ollama running locally for phi4 evaluator
"""

import os
import re
import json
import time
import argparse
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_EVAL_MODEL = os.getenv("OLLAMA_EVAL_MODEL", "phi4:14b-q8_0")

EVAL_DIR = Path(__file__).parent
FIXTURE_PATH = EVAL_DIR / "generation_fixture.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring rubric (same as eval_runner_v2.py)
# ---------------------------------------------------------------------------

RUBRIC = """
SCORING RUBRIC — apply strictly and consistently:

Score 3 — Correct and complete
  The answer is substantively accurate and addresses all parts of the question.
  Contains no misleading statements. Retrieved sources support the answer.
  Clause citation is NOT required unless the question explicitly asks for a specific clause.
  For out-of-scope questions: correctly declining to answer scores 3.

Score 2 — Partially correct
  The answer is substantively accurate but incomplete.
  Omits material information that is present in the retrieved sources.
  OR: answers the question with minor inaccuracies that do not materially mislead.

Score 1 — Inadequate
  The answer is vague, tangentially relevant, or contains inaccuracies that would
  mislead a regulatory professional. Includes partial answers presented as complete
  without flagging the gap. Incorrect refusal to answer an in-scope question scores 1.

Score 0 — Wrong or harmful
  Factually incorrect. Hallucinates regulatory requirements not in the sources.
  Confidently answers a question that should have been declined.
  Claims a document says something it does not say.

SPECIAL CASES:
  - Correct no_answer for out-of-scope = Score 3
  - Partial answer without flagging incompleteness = Score 1 maximum
  - Answer faithful to sources but sources are incomplete = Score 2 (retrieval miss, not hallucination)

FAITHFULNESS (separate from score):
  Pass = answer makes no claims beyond what the retrieved sources contain
  Fail = answer contains claims not supported by any retrieved source
"""

EVALUATOR_SYSTEM = f"""You are an independent evaluator assessing answers from a pharmaceutical regulatory intelligence RAG system.

The system retrieves chunks from regulatory documents (EU GMP Annex 11, 21 CFR Part 11, ICH Q10, EMA Reflection Paper on AI, EU GMP Annex 15, EU GMP Annex 22, FDA Data Integrity Q&A) and generates answers using an LLM.

You will receive:
- The question asked
- The expected answer scope (what a correct answer must cover)
- The answer the system produced
- The retrieved source excerpts used to generate the answer

Your task: score the answer using the rubric below, then assess faithfulness.

{RUBRIC}

Output JSON only. No preamble, no markdown fences:
{{
  "score": 0-3,
  "faithfulness": "pass" | "fail",
  "reasoning": "two sentences maximum explaining the score"
}}"""


# ---------------------------------------------------------------------------
# Chunk parsing
# ---------------------------------------------------------------------------

CHUNK_MARKER_RE = re.compile(r'^\[(\d+)\] (.+)$')
CITATION_RE = re.compile(r'\[(\d+(?:,\d+)*)\]')


def parse_chunks(prompt: str) -> dict[int, dict]:
    """Parse chunks from a ownedpulse prompt. Returns {N: {header, text}}."""
    chunks = {}
    current_n = None
    current_header = None
    current_lines = []

    for line in prompt.split('\n'):
        m = CHUNK_MARKER_RE.match(line)
        if m:
            if current_n is not None:
                chunks[current_n] = {
                    "header": current_header,
                    "text": '\n'.join(current_lines).strip(),
                }
            current_n = int(m.group(1))
            current_header = m.group(2)
            current_lines = []
        elif current_n is not None:
            current_lines.append(line)

    if current_n is not None:
        chunks[current_n] = {
            "header": current_header,
            "text": '\n'.join(current_lines).strip(),
        }

    return chunks


def parse_header(header: str) -> dict:
    """Parse chunk header like 'Title — Body, type, version, §clause (date)'."""
    parts = {}
    if ' — ' in header:
        parts['document_title'] = header.split(' — ')[0].strip()
        rest = header.split(' — ', 1)[1]
    else:
        parts['document_title'] = header
        rest = header

    clause_m = re.search(r'§(\S+)', rest)
    parts['clause_id'] = clause_m.group(1) if clause_m else None

    date_m = re.search(r'\((\d{4}-\d{2}-\d{2})\)', rest)
    parts['publication_date'] = date_m.group(1) if date_m else None

    parts['full_header'] = header
    return parts


def extract_cited_chunks(answer: str, chunk_map: dict[int, dict]) -> list[dict]:
    """Find [N] citations in answer and return cited chunk excerpts."""
    cited_nums = set()
    for m in CITATION_RE.finditer(answer):
        for num in m.group(1).split(','):
            cited_nums.add(int(num.strip()))

    sources = []
    for n in sorted(cited_nums):
        if n not in chunk_map:
            continue
        chunk = chunk_map[n]
        header_info = parse_header(chunk["header"])
        clause = header_info.get("clause_id")
        label = f"[{header_info['document_title']}]"
        if clause:
            label += f"[§{clause}]"
        text = chunk["text"][:500]
        sources.append(f"{label} {text}")

    return sources


def get_answer_text(entry: dict) -> str:
    """Extract answer text from an answers entry, handling different field names."""
    return (
        entry.get("answer_text")
        or entry.get("sonnet_answer")
        or entry.get("answer")
        or ""
    )


# ---------------------------------------------------------------------------
# Evaluator calls (same as eval_runner_v2.py)
# ---------------------------------------------------------------------------

def build_eval_prompt(question: str, expected_scope: str, answer: str, sources: list) -> str:
    sources_text = "\n\n".join(sources) if sources else "No sources retrieved."
    return f"""QUESTION:
{question}

EXPECTED ANSWER SCOPE:
{expected_scope}

SYSTEM ANSWER:
{answer if answer else "[No answer returned]"}

RETRIEVED SOURCES:
{sources_text}

Score this answer using the rubric. Output JSON only."""


def score_with_claude(client, question: str, expected_scope: str,
                      answer: str, sources: list) -> dict:
    prompt = build_eval_prompt(question, expected_scope, answer, sources)
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=EVALUATOR_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        log.warning(f"Claude evaluator error: {e}")
        return {"score": None, "faithfulness": None, "reasoning": f"evaluator error: {e}"}


def score_with_gpt(question: str, expected_scope: str,
                   answer: str, sources: list) -> dict:
    if not OPENAI_API_KEY:
        return {"score": None, "faithfulness": None, "reasoning": "OPENAI_API_KEY not set"}

    prompt = build_eval_prompt(question, expected_scope, answer, sources)
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": EVALUATOR_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 512,
    }
    try:
        resp = requests.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        log.warning(f"GPT evaluator error: {e}")
        return {"score": None, "faithfulness": None, "reasoning": f"evaluator error: {e}"}


def score_with_deepseek(question: str, expected_scope: str,
                         answer: str, sources: list) -> dict:
    if not DEEPSEEK_API_KEY:
        return {"score": None, "faithfulness": None, "reasoning": "DEEPSEEK_API_KEY not set"}

    prompt = build_eval_prompt(question, expected_scope, answer, sources)
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": EVALUATOR_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 4096,
    }
    try:
        resp = requests.post(
            f"{DEEPSEEK_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        log.warning(f"DeepSeek evaluator error: {e}")
        return {"score": None, "faithfulness": None, "reasoning": f"evaluator error: {e}"}


def score_with_phi4(question: str, expected_scope: str,
                    answer: str, sources: list) -> dict:
    prompt = build_eval_prompt(question, expected_scope, answer, sources)
    payload = {
        "model": OLLAMA_EVAL_MODEL,
        "prompt": f"{EVALUATOR_SYSTEM}\n\n{prompt}",
        "stream": False,
        "options": {"temperature": 0.0},
    }
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        log.warning(f"phi4 evaluator error: {e}")
        return {"score": None, "faithfulness": None, "reasoning": f"evaluator error: {e}"}


# ---------------------------------------------------------------------------
# Run evaluation
# ---------------------------------------------------------------------------

def run_evaluation(fixture: dict, answers_data: dict,
                   active_models: list, claude_client=None) -> list:
    results = []

    answers_by_id = {q["question_id"]: q for q in answers_data["questions"]}
    model_name = answers_data.get("model", "unknown")

    questions = fixture["questions"]

    for i, fq in enumerate(questions):
        qid = fq["question_id"]
        question_text = fq["question_text"]
        entry = answers_by_id.get(qid)
        if not entry:
            log.warning(f"[{i+1}/{len(questions)}] {qid} — no answer found, skipping")
            continue

        log.info(f"[{i+1}/{len(questions)}] {qid} [{fq['category']}] {question_text[:80]}...")

        prompt = fq["llm_input"]["prompt"]
        chunk_map = parse_chunks(prompt)

        answer = get_answer_text(entry)
        if entry.get("api_error"):
            log.warning(f"  Answer had API error: {entry['api_error']}")

        cited_sources = extract_cited_chunks(answer, chunk_map)
        log.info(f"  Answer: {len(answer)} chars | Cited sources: {len(cited_sources)}")

        scores = {}

        if "claude" in active_models and claude_client:
            log.info("  Scoring with Claude...")
            scores["claude"] = score_with_claude(
                claude_client, question_text, fq["expected_answer_scope"],
                answer, cited_sources)
            log.info(f"  Claude: {scores['claude'].get('score')} | {scores['claude'].get('faithfulness')}")

        if "gpt" in active_models:
            log.info(f"  Scoring with {OPENAI_MODEL}...")
            scores["gpt"] = score_with_gpt(
                question_text, fq["expected_answer_scope"],
                answer, cited_sources)
            log.info(f"  GPT:    {scores['gpt'].get('score')} | {scores['gpt'].get('faithfulness')}")

        if "deepseek" in active_models:
            log.info("  Scoring with DeepSeek...")
            scores["deepseek"] = score_with_deepseek(
                question_text, fq["expected_answer_scope"],
                answer, cited_sources)
            log.info(f"  DeepSeek: {scores['deepseek'].get('score')} | {scores['deepseek'].get('faithfulness')}")

        if "phi4" in active_models:
            log.info("  Scoring with phi4...")
            scores["phi4"] = score_with_phi4(
                question_text, fq["expected_answer_scope"],
                answer, cited_sources)
            log.info(f"  phi4: {scores['phi4'].get('score')} | {scores['phi4'].get('faithfulness')}")

        results.append({
            "question_id": qid,
            "category": fq["category"],
            "corpus_scope": fq.get("corpus_scope", ""),
            "question_text": question_text,
            "primary_documents": fq.get("primary_documents", []),
            "expected_answer_scope": fq.get("expected_answer_scope", ""),
            "answer": answer,
            "sources_retrieved": len(cited_sources),
            "query_time_seconds": entry.get("query_time_seconds"),
            "api_error": entry.get("api_error"),
            "scores": scores,
        })

        time.sleep(1)

    return results


# ---------------------------------------------------------------------------
# Report (same as eval_runner_v2.py)
# ---------------------------------------------------------------------------

def compute_stats(results: list, model: str) -> dict:
    scored = [r for r in results if r["scores"].get(model, {}).get("score") is not None]
    if not scored:
        return {"n": 0, "mean": None, "pct": None, "by_category": {}, "faithfulness_fails": 0}

    total = sum(r["scores"][model]["score"] for r in scored)
    mean = total / len(scored)
    pct = round((mean / 3.0) * 100, 1)

    by_cat = {}
    for cat in ["A", "B", "C"]:
        cat_scored = [r for r in scored if r["category"] == cat]
        if cat_scored:
            cat_total = sum(r["scores"][model]["score"] for r in cat_scored)
            cat_mean = cat_total / len(cat_scored)
            by_cat[cat] = {
                "n": len(cat_scored),
                "mean": round(cat_mean, 2),
                "pct": round((cat_mean / 3.0) * 100, 1),
            }

    faithfulness_fails = [
        r for r in scored
        if r["scores"][model].get("faithfulness") == "fail"
    ]

    return {
        "n": len(scored),
        "mean": round(mean, 2),
        "pct": pct,
        "by_category": by_cat,
        "faithfulness_fails": len(faithfulness_fails),
    }


def write_report(results: list, active_models: list, model_name: str, output_path: Path):
    lines = []
    lines.append("=" * 70)
    lines.append(f"OWNEDPULSE EVALUATION REPORT v2 — {model_name.upper()} ANSWERS")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Questions:  {len(results)}")
    lines.append(f"Evaluators: {', '.join(active_models)}")
    lines.append("=" * 70)

    lines.append("\nSUMMARY BY EVALUATOR\n")
    header = f"{'Evaluator':<12} {'N':>4} {'Overall':>8} {'Cat A':>7} {'Cat B':>7} {'Cat C':>7} {'Faith Fail':>10}"
    lines.append(header)
    lines.append("-" * len(header))

    for model in active_models:
        stats = compute_stats(results, model)
        if stats["n"] == 0:
            lines.append(f"{model:<12} {'N/A':>4}")
            continue
        cat_a = stats["by_category"].get("A", {})
        cat_b = stats["by_category"].get("B", {})
        cat_c = stats["by_category"].get("C", {})
        lines.append(
            f"{model:<12} {stats['n']:>4} "
            f"{stats['pct']:>7.1f}% "
            f"{cat_a.get('pct', 0):>6.1f}% "
            f"{cat_b.get('pct', 0):>6.1f}% "
            f"{cat_c.get('pct', 0):>6.1f}% "
            f"{stats['faithfulness_fails']:>10}"
        )

    lines.append("\n\nPER-QUESTION DETAIL\n")
    for r in results:
        lines.append(f"[{r['question_id']}][{r['category']}][{r['corpus_scope']}]")
        lines.append(f"  Q: {r['question_text'][:100]}")
        lines.append(f"  Sources cited: {r['sources_retrieved']}")
        if r.get("api_error"):
            lines.append(f"  ERROR: {r['api_error']}")
        for model in active_models:
            s = r["scores"].get(model, {})
            score = s.get("score")
            faith = s.get("faithfulness", "-")
            reason = s.get("reasoning", "")
            lines.append(f"  {model:<12}: {score}/3 | faith={faith} | {reason[:80]}")
        lines.append("")

    report_text = "\n".join(lines)
    output_path.write_text(report_text)
    log.info(f"Report written to: {output_path}")

    print("\n" + "\n".join(lines[:30]))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Score model answers against evaluators")
    parser.add_argument("--answers", required=True,
                        help="Path to answers JSON file (e.g. sonnet_answers.json, answers_llama4scout_*.json)")
    parser.add_argument("--output-prefix", required=True,
                        help="Prefix for output files (e.g. sonnet, llama4scout, gptoss120b)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Run only first N questions (for testing)")
    parser.add_argument("--models", default="claude,gpt,deepseek,phi4",
                        help="Comma-separated evaluator keys: claude,gpt,deepseek,phi4")
    args = parser.parse_args()

    active_models = [m.strip() for m in args.models.split(",")]
    log.info(f"Active evaluators: {active_models}")

    answers_path = Path(args.answers)
    if not answers_path.exists():
        raise FileNotFoundError(f"Answers file not found: {answers_path}")

    # Load fixture (chunks)
    fixture = json.loads(FIXTURE_PATH.read_text())
    log.info(f"Loaded fixture: {fixture['total_questions']} questions")

    # Load answers
    answers_data = json.loads(answers_path.read_text())
    log.info(f"Loaded answers: {answers_data['total_questions']} questions (model: {answers_data.get('model', '?')})")

    if args.limit:
        fixture["questions"] = fixture["questions"][:args.limit]
        log.info(f"Limited to first {args.limit} questions")

    # Init Claude client
    claude_client = None
    if "claude" in active_models:
        if not ANTHROPIC_API_KEY:
            log.warning("ANTHROPIC_API_KEY not set — skipping Claude evaluator")
            active_models.remove("claude")
        else:
            claude_client = anthropic.Anthropic(
                api_key=ANTHROPIC_API_KEY,
                base_url="https://api.anthropic.com",
            )

    if "gpt" in active_models and not OPENAI_API_KEY:
        log.warning("OPENAI_API_KEY not set — skipping GPT evaluator")
        active_models.remove("gpt")

    if "deepseek" in active_models and not DEEPSEEK_API_KEY:
        log.warning("DEEPSEEK_API_KEY not set — skipping DeepSeek evaluator")
        active_models.remove("deepseek")

    if not active_models:
        raise ValueError("No evaluators available. Check API keys.")

    # Run
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    prefix = args.output_prefix
    results_path = EVAL_DIR / f"results_{prefix}_{timestamp}.json"
    report_path = EVAL_DIR / f"report_{prefix}_{timestamp}.txt"

    log.info(f"Starting evaluation: {len(fixture['questions'])} questions x {len(active_models)} evaluators")
    results = run_evaluation(fixture, answers_data, active_models, claude_client)

    model_name = answers_data.get("model", prefix)

    # Save results
    output = {
        "version": "v2",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "model_scored": model_name,
        "fixture_source": "generation_fixture.json",
        "answers_source": str(answers_path.name),
        "total_questions": len(results),
        "active_evaluators": active_models,
        "results": results,
    }
    results_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    log.info(f"Results saved to: {results_path}")

    # Write report
    write_report(results, active_models, model_name, report_path)


if __name__ == "__main__":
    main()
