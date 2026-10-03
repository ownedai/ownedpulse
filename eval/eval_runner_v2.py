#!/usr/bin/env python3
"""
eval_runner_v2.py
Runs the v2 question bank against the ownedpulse query API and scores
answers using multiple independent evaluator models.

Scoring approach:
  - Answer + retrieved sources passed to each evaluator (not blind)
  - Evaluators score on accuracy, completeness, and faithfulness
  - Each evaluator scores independently; results reported side by side
  - No clause citation required for score 3 unless question explicitly asks for it
  - Correct no_answer for out-of-scope questions scores 3

Evaluator models:
  - phi4:14b-q8_0   via Ollama        (baseline — generation model, not independent)
  - gpt-5.5         via OpenAI API    (independent)
  - deepseek-v4-pro via DeepSeek API  (independent, strict)
  - claude-sonnet-4-6 via Anthropic   (independent)

Input:  eval/questions_v2.json
Output: eval/results_v2_{timestamp}.json
        eval/report_v2_{timestamp}.txt

Usage:
  python eval_runner_v2.py [--questions questions_v2.json] [--limit N] [--models phi4,gpt,deepseek,claude]

Required .env keys:
  ANTHROPIC_API_KEY
  OPENAI_API_KEY
  DEEPSEEK_API_KEY
"""

import os
import json
import time
import argparse
import logging
import requests
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

# ownedpulse query API
OWNEDPULSE_API_URL = os.getenv("OWNEDPULSE_API_URL", "http://localhost:8001")
QUERY_ENDPOINT = f"{OWNEDPULSE_API_URL}/api/query"
QUERY_TIMEOUT = 120  # seconds

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")

# DeepSeek (OpenAI-compatible)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

# Ollama (local)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_EVAL_MODEL = os.getenv("OLLAMA_EVAL_MODEL", "phi4:14b-q8_0")

INPUT_PATH = Path(__file__).parent / "questions_v2.json"
OUTPUT_DIR = Path(__file__).parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring rubric (passed to every evaluator)
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
# Step 1: Query ownedpulse
# ---------------------------------------------------------------------------

def query_ownedpulse(question: str) -> dict:
    """Send question to ownedpulse query API. Returns full response dict."""
    payload = {"query": question}
    try:
        resp = requests.post(QUERY_ENDPOINT, json=payload, timeout=QUERY_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        return {"error": "timeout", "answer": None, "sources": []}
    except requests.exceptions.RequestException as e:
        return {"error": str(e), "answer": None, "sources": []}


def extract_answer_and_sources(api_response: dict) -> tuple:
    """Extract answer text and source excerpts from API response."""
    answer = api_response.get("answer") or api_response.get("response") or ""
    sources = api_response.get("sources") or api_response.get("citations") or []

    # Build source excerpts for evaluator context
    source_excerpts = []
    for s in sources[:8]:  # cap at 8 sources
        doc_id = s.get("document_id") or s.get("doc_id") or "unknown"
        clause = s.get("clause_id") or ""
        text = s.get("chunk_text") or s.get("text") or ""
        score = s.get("similarity_score") or s.get("score") or ""
        label = f"[{doc_id}]"
        if clause:
            label += f"[{clause}]"
        if score:
            label += f"[score:{score:.3f}]" if isinstance(score, float) else f"[score:{score}]"
        source_excerpts.append(f"{label} {text[:500]}")

    return answer, source_excerpts


# ---------------------------------------------------------------------------
# Step 2: Evaluator implementations
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
# Step 3: Run evaluation
# ---------------------------------------------------------------------------

def run_evaluation(questions: list, active_models: list,
                   claude_client=None) -> list:
    results = []

    for i, q in enumerate(questions):
        qid = q["question_id"]
        question_text = q["question_text"]
        log.info(f"[{i+1}/{len(questions)}] {qid} [{q['category']}] {question_text[:80]}...")

        # Query ownedpulse
        t0 = time.time()
        api_response = query_ownedpulse(question_text)
        query_time = round(time.time() - t0, 2)

        if api_response.get("error"):
            log.warning(f"  Query error: {api_response['error']}")

        answer, sources = extract_answer_and_sources(api_response)
        log.info(f"  Answer length: {len(answer)} chars | Sources: {len(sources)} | Time: {query_time}s")

        # Score with each active evaluator
        scores = {}

        if "claude" in active_models and claude_client:
            log.info("  Scoring with Claude...")
            scores["claude"] = score_with_claude(
                claude_client, question_text, q["expected_answer_scope"], answer, sources)
            log.info(f"  Claude: {scores['claude'].get('score')} | {scores['claude'].get('faithfulness')}")

        if "gpt" in active_models:
            log.info(f"  Scoring with {OPENAI_MODEL}...")
            scores["gpt"] = score_with_gpt(
                question_text, q["expected_answer_scope"], answer, sources)
            log.info(f"  GPT:    {scores['gpt'].get('score')} | {scores['gpt'].get('faithfulness')}")

        if "deepseek" in active_models:
            log.info("  Scoring with DeepSeek...")
            scores["deepseek"] = score_with_deepseek(
                question_text, q["expected_answer_scope"], answer, sources)
            log.info(f"  DeepSeek: {scores['deepseek'].get('score')} | {scores['deepseek'].get('faithfulness')}")

        if "phi4" in active_models:
            log.info("  Scoring with phi4...")
            scores["phi4"] = score_with_phi4(
                question_text, q["expected_answer_scope"], answer, sources)
            log.info(f"  phi4: {scores['phi4'].get('score')} | {scores['phi4'].get('faithfulness')}")

        results.append({
            "question_id": qid,
            "category": q["category"],
            "corpus_scope": q["corpus_scope"],
            "question_text": question_text,
            "primary_documents": q["primary_documents"],
            "expected_answer_scope": q["expected_answer_scope"],
            "answer": answer,
            "sources_retrieved": len(sources),
            "query_time_seconds": query_time,
            "api_error": api_response.get("error"),
            "scores": scores,
        })

        # Brief pause between questions to avoid overloading Ollama
        time.sleep(1)

    return results


# ---------------------------------------------------------------------------
# Step 4: Report
# ---------------------------------------------------------------------------

def compute_stats(results: list, model: str) -> dict:
    scored = [r for r in results if r["scores"].get(model, {}).get("score") is not None]
    if not scored:
        return {"n": 0, "mean": None, "pct": None, "by_category": {}}

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


def write_report(results: list, active_models: list, output_path: Path):
    lines = []
    lines.append("=" * 70)
    lines.append("OWNEDPULSE EVALUATION REPORT v2")
    lines.append(f"Generated: {datetime.utcnow().isoformat()}Z")
    lines.append(f"Questions:  {len(results)}")
    lines.append(f"Evaluators: {', '.join(active_models)}")
    lines.append("=" * 70)

    # Summary table per evaluator
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

    # Per-question detail
    lines.append("\n\nPER-QUESTION DETAIL\n")
    for r in results:
        lines.append(f"[{r['question_id']}][{r['category']}][{r['corpus_scope']}]")
        lines.append(f"  Q: {r['question_text'][:100]}")
        lines.append(f"  Sources retrieved: {r['sources_retrieved']} | Time: {r['query_time_seconds']}s")
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

    # Also print summary to console
    print("\n" + "\n".join(lines[:30]))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="OwnedPulse eval runner v2")
    parser.add_argument("--questions", default=str(INPUT_PATH))
    parser.add_argument("--limit", type=int, default=None,
                        help="Run only first N questions (for testing)")
    parser.add_argument("--models", default="claude,gpt,deepseek,phi4",
                        help="Comma-separated evaluator keys: claude,gpt,deepseek,phi4")
    args = parser.parse_args()

    active_models = [m.strip() for m in args.models.split(",")]
    log.info(f"Active evaluators: {active_models}")

    # Load questions
    questions_path = Path(args.questions)
    if not questions_path.exists():
        raise FileNotFoundError(f"Question bank not found: {questions_path}")
    data = json.loads(questions_path.read_text())
    questions = data["questions"]

    if args.limit:
        questions = questions[:args.limit]
        log.info(f"Limited to first {args.limit} questions")

    log.info(f"Loaded {len(questions)} questions from {questions_path.name}")

    # Init Claude client if needed
    claude_client = None
    if "claude" in active_models:
        if not ANTHROPIC_API_KEY:
            log.warning("ANTHROPIC_API_KEY not set — skipping Claude evaluator")
            active_models.remove("claude")
        else:
            claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Check GPT
    if "gpt" in active_models and not OPENAI_API_KEY:
        log.warning("OPENAI_API_KEY not set — skipping GPT evaluator")
        active_models.remove("gpt")

    # Check DeepSeek
    if "deepseek" in active_models and not DEEPSEEK_API_KEY:
        log.warning("DEEPSEEK_API_KEY not set — skipping DeepSeek evaluator")
        active_models.remove("deepseek")

    if not active_models:
        raise ValueError("No evaluators available. Check API keys.")

    # Verify ownedpulse API is reachable
    try:
        health = requests.get(f"{OWNEDPULSE_API_URL}/api/admin/health", timeout=10)
        log.info(f"ownedpulse API: {health.status_code}")
    except Exception as e:
        log.warning(f"ownedpulse API health check failed: {e} — continuing anyway")

    # Run
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    results_path = OUTPUT_DIR / f"results_v2_{timestamp}.json"
    report_path = OUTPUT_DIR / f"report_v2_{timestamp}.txt"

    log.info(f"Starting evaluation: {len(questions)} questions x {len(active_models)} evaluators")
    results = run_evaluation(questions, active_models, claude_client)

    # Save raw results
    output = {
        "version": "v2",
        "evaluated_at": datetime.utcnow().isoformat() + "Z",
        "question_bank": questions_path.name,
        "total_questions": len(results),
        "active_evaluators": active_models,
        "ownedpulse_api": OWNEDPULSE_API_URL,
        "results": results,
    }
    results_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    log.info(f"Results saved to: {results_path}")

    # Write report
    write_report(results, active_models, report_path)


if __name__ == "__main__":
    main()
