# ownedpulse

Sovereign regulatory intelligence for pharmaceutical and life sciences teams.

ownedpulse is a private, on-premises RAG (Retrieval-Augmented Generation) system over public regulatory documents from EMA, FDA, and ICH. It runs entirely on your infrastructure. No data leaves your network.

---

## What It Does

ownedpulse answers regulatory questions by retrieving and synthesising content from a curated corpus of public guidance documents. Every answer is traceable to the exact source chunk, document version, and ingestion event that produced it.

Typical queries:

- Compare Annex 11 and 21 CFR Part 11 requirements for audit trails
- What does ICH Q9(R1) say about risk acceptability criteria?
- Summarise recent EMA press releases on GMP enforcement

---

## Who It Is For

Regulatory Affairs and QA professionals who need fast, sourced answers across multiple regulatory frameworks — without sending documents to a cloud service.

This is a portfolio demonstration system. The target deployment context is organisations operating under GxP obligations (EU GMP, FDA cGMP, ICH guidelines) where data sovereignty is a compliance requirement, not a preference.

---

## Intended Use Boundary

**ownedpulse is not a GxP Document Management System.** It does not replace Documentum, Veeva Vault, or equivalent validated DMS platforms.

The current corpus contains public regulatory documents only. It does not process internal SOPs, deviations, batch records, or any organisation-specific GxP records.

**Outputs require human review before use in any GxP decision.** The system is advisory. It does not make autonomous decisions in regulated processes.

This system has not been validated under GAMP 5 / CSA methodology. It is a portfolio and operational demonstration artefact. Organisations deploying this system in a GxP context are responsible for their own validation and qualification activities.

GAMP 5 category assessment: Category 5 (Bespoke/Custom Software), risk classification LOW-MEDIUM (advisory function, no direct GxP process impact). 

---

## Corpus

Public regulatory documents from:

- **EMA** — Scientific Guidelines, Regulatory Guidance
- **FDA** — Drugs guidance, Press Releases
- **ICH** — Guidelines via JSON API

The corpus is defined in `corpus_manifest.json`. Extension beyond the declared scope is a change control event.

---

## Architecture

```
Fetch (Python scrapers) → Chunk (Docling) → Embed (Ollama) → Store (Qdrant)
                                                                      ↓
                                              Query API (FastAPI) ← Retrieve
                                                      ↓
                                          Generate (Ollama / phi4)
                                                      ↓
                                         Response + provenance metadata
```

| Component | Technology |
|-----------|-----------|
| API | FastAPI |
| UI | React + Vite + Tailwind |
| Vector store | Qdrant |
| Database | PostgreSQL |
| Generation model | phi4:14b-q8_0 via Ollama |
| Embedding model | mxbai-embed-large (1024-dim, cosine) |
| Observability | Langfuse |
| PDF parsing | Docling |
| Deployment | Docker Compose |

**Retrieval is deterministic.** Query expansion runs at temperature=0.0. The same query returns the same sources on repeated runs.

**Every chunk carries a deterministic ID**: MD5(doc_id | version | chunk_index) → UUID. Chunk provenance is traceable to the ingestion event via PostgreSQL trace tables.

**Observability**: all query traces are captured in Langfuse, including sub-queries, retrieved chunk IDs, similarity scores, and the prompt template version used.

**Requirements**: NVIDIA GPU w/ ≥24GB VRAM recommended (phi4:14b-q8_0 + mxbai-embed-large via Ollama). CPU-only inference possible but not benchmarked; expect significantly slower generation.

---

## Ingestion

After ingestion, check logs for any lines starting with `WARNING: char_offset`. These indicate chunks where offset anchor matching failed due to source text formatting. Affected chunks are still ingested and searchable. To inspect, query the PostgreSQL chunks table for rows where `char_offset_end - char_offset_start < 50` for the affected document_id. Re-ingest the document after resolving the source text formatting issue.

---

## Evaluation

A structured evaluation was conducted using 50 questions across three categories, designed to reflect real regulatory work tasks rather than system testing scenarios. Reference hardware used for eval numbers was RTX 3090 24GB.

**Question categories:**
- A — Core lookup: single document, specific requirement
- B — Cross-framework: synthesis across multiple regulatory bodies
- C — Boundary/scope: correct system behaviour at corpus edges

Answers were scored by three independent evaluator models (Claude Sonnet 4.6, GPT-4.1, DeepSeek V4 Pro) against a defined rubric. Score 0–3 per question; clause citation not required unless explicitly asked. Correct declination of out-of-scope questions scores 3.

**Results with phi4:14b-q8_0 as generation model (current hardware):**

| Evaluator | Overall | Cat A | Cat B | Cat C |
|-----------|---------|-------|-------|-------|
| Claude Sonnet 4.6 | 71.3% | 88.9% | 61.3% | 70.0% |
| GPT-4.1 | 75.3% | 88.9% | 68.0% | 73.3% |
| DeepSeek V4 Pro | 61.9% | 82.2% | 45.3% | 74.1% |
| **Independent avg** | **69.5%** | **86.7%** | **58.2%** | **72.5%** |

DeepSeek applies stricter faithfulness criteria than the other evaluators — this is a known methodological difference documented in `eval/`. The independent average of Claude and GPT-4.1 is 73.3% overall.

**Generation model comparison — same retrieval context, different models:**

The retrieval pipeline was held constant. Each generation model received identical retrieved chunks per question. This isolates generation quality from retrieval quality.

| Generation model | Independent avg | Cat B |
|-----------------|-----------------|-------|
| phi4:14b (local, current hardware) | 69.5% | 58.2% |
| Llama 4 Scout (open-weight) | 65.5% | 62.7% |
| Qwen2.5-72B (open-weight) | 68.3% | 61.9% |
| GPT-OSS-20B (open-weight, Apache 2.0) | 66.7% | 60.0% |
| GPT-OSS-120B (open-weight, Apache 2.0) | **76.2%** | **76.4%** |
| Claude Sonnet 4.6 (API, cloud) | **87.7%** | **85.5%** |

**What this means for deployment:**

The architecture is model-agnostic. Quality scales with generation model capability. On current hardware (single consumer GPU), the system scores 69.5%. With a moderate hardware investment running GPT-OSS-120B — an Apache 2.0 open-weight model deployable entirely on-premises — this rises to 76.2%. The cloud API reference ceiling is 87.7% with Claude Sonnet 4.6, but sovereignty is not maintained.

Category B (cross-framework synthesis) shows the largest model-dependent spread — 58% to 85%. This is the most commercially valuable query type and the primary area where hardware investment returns measurable quality gains.

All open-weight models in the comparison are deployable on private infrastructure under permissive licences. No query data leaves the network in any on-premises configuration.

Evaluation scripts and full per-question results: `eval/`

---

## Traceability Design

Each query response surfaces:

- Chunk ID, document ID, document version, clause ID
- Similarity score per retrieved chunk
- Prompt template version (hash)
- Embedding model and chunker version
- Ingestion timestamp and source hash
- Supersede status of the source document

This metadata is designed to feed a validation package for organisations deploying the system under Annex 11 or 21 CFR Part 11 requirements. Langfuse traces constitute the query audit log.

---

## Status

Active development. 

---

## License

See `LICENSE`.

---

## About

Built by [ownedai](https://ownedai.dev) — private AI infrastructure for regulated industries.
