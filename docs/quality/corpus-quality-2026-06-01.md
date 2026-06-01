# Corpus Quality Report — 2026-06-01


## 1. Corpus Completeness

**Operator:** G-T4 automated check
**Started:** 2026-06-01 19:40:18 UTC
**Expected docs:** 1382
**Expected min chunks:** 20000
- **Total documents in registry:** 1382
- **Expected:** 1382
✅ **Total document count**: PASS — 1382 docs in registry

**Documents per agency:**
  - FDA: 1014
  - EMA: 211
  - ICH: 157
✅ **Agency distribution**: PASS — all agencies present

**Zero-chunk document check:**
✅ **Zero-chunk documents**: PASS — every indexed doc has >=1 Qdrant chunk

- **Qdrant points:** 22074
✅ **Minimum chunk count**: PASS — 22074 chunks >= 20000 expected


## 2. Chunk Quality

Analysing 22074 chunks from Qdrant...

**Chunk character length distribution:**
| Metric | Value |
|---|---|
| Count | 22074 |
| Mean | 972 |
| Min | 2 |
| Max | 2532 |
| P5 | 116 |
⚠️ **Short chunks (<50 chars)**: WARN — 317 chunks flagged — samples: ['ILEA\nEFNS', ' justifications will be considered.', 'International Programme for Chemical Safety.']
⚠️ **HTML/XML artefacts in chunk text**: WARN — 845 chunks — samples: ['<h1>FDA ORIG approval — OMEPRAZOLE AND SODIUM BICARBONATE (NOVITIUM PHARMA)</h1>', '<h1>FDA ORIG approval — FOSTER AND THRIVE ALLERGY AND CONGESTION D (L PERRIGO CO', '<h1>FDA SUPPL approval — DEXMEDETOMIDINE (HQ SPCLT PHARMA)</h1>\n<p><b>Applicatio']

**Overall clause_id coverage:** 16.2% (18509/22074 null)

**Documents below 80% clause_id coverage (excluding known gaps):**
| Document ID | Coverage | Total chunks | Null |
|---|---|---|---|
| ICH-Q9 | 0% | 88 | 88 |
| ICH-Q9-R1 | 0% | 111 | 111 |
| ema_reg_guidance-amended-biologics-working-party-vaccines-c609e95f0ed5 | 0% | 15 | 15 |
| ema_reg_guidance-annex-european-commission-guideline-exci-612b6434d3d4 | 0% | 42 | 42 |
| ema_reg_guidance-concept-paper-development-guideline-demo-53e392a51985 | 0% | 14 | 14 |
| ema_reg_guidance-development-guideline-safety-nanoparticl-03c61b474230 | 0% | 14 | 14 |
| ema_reg_guidance-efficacy-target-animal-safety-data-requi-a4ffca06b237 | 0% | 28 | 28 |
| ema_reg_guidance-guidance-details-classification-variatio-e0f00d5520b0 | 0% | 114 | 114 |
| ema_reg_guidance-guideline-assessment-reporting-mechanist-7628d6d85113 | 0% | 12 | 12 |
| ema_reg_guidance-guideline-evaluation-benefit-risk-balanc-4af3c70c4ee8 | 0% | 16 | 16 |
⚠️ **clause_id coverage**: WARN — 344 docs below 80% threshold


## 3. Metadata Completeness

Scanning 22074 chunk payloads for null rates...

**Scanned:** 22074 chunks

**Mandatory fields (must be 0% null):**
  - `trace_id`: 0 null (0.00%) — PASS
  - `document_id`: 0 null (0.00%) — PASS
  - `chunk_id`: 0 null (0.00%) — PASS
  - `document_title`: 0 null (0.00%) — PASS
  - `issuing_body`: 0 null (0.00%) — PASS
  - `document_type`: 0 null (0.00%) — PASS
  - `embedding_model`: 0 null (0.00%) — PASS
✅ **Mandatory metadata completeness**: PASS — all mandatory fields 0% null across all chunks

**Advisory fields (reported, not gating):**
  - `clause_id`: 21845 null (98.96%)
  - `source_fetched_at`: 247 null (1.12%)
  - `source_url`: 0 null (0.00%)
  - `publication_date`: 815 null (3.69%)
✅ **Advisory metadata completeness**: PASS — advisory null rates reported above


## 4. Supersede Chain Integrity

**Document families:** 1
✅ **Multiple active versions per family**: PASS — each family has exactly one current version
⚠️ **Families with no current version**: WARN — 1 families have 0 current docs
✅ **Orphaned family references**: PASS — all families have >=2 documents


## 5. Trace Coverage

**Qdrant points:** 22074
✅ **Null trace_id on chunks**: PASS — 0/22074 chunks missing trace_id

✅ **Chunk trace_id → ingestion_doc**: PASS — all 1382 trace_ids resolve to ingestion_doc
✅ **ingestion_doc.trace_id → run_log**: PASS — all 1382 ingestion_doc trace_ids resolve to run_log
✅ **Failed document spans**: PASS — 0 failed
⚠️ **Wipe completeness**: WARN — no wipe timestamp file at /tmp/g3_wipe_timestamp.txt — cannot verify

**Trace ID uniqueness:** 1382 unique trace_ids across 22074 chunks


## 6. Embedding Sanity

  - **Annex 11** (EU-GMP-Annex11...): 2/6 same-doc neighbours — FLAG
  - **ICH Q9(R1)** (ich_guidelines-q10-20guideline-pdf-3f3fd...): 0/6 same-doc neighbours — FLAG
  - **FDA guidance** (ich_guidelines-ich-e6-28r3-29-step4-fina...): 6/6 same-doc neighbours — OK
✅ **Embedding neighbour sanity**: PASS — spot-checks completed (see details above)

✅ **Near-zero embedding vectors**: PASS — no vectors with norm < 0.01


---

**Run date:** 2026-06-01 19:40:18 UTC
**Duration:** 232.0s
**Checks:** 19 total (14 pass, 5 warn, 0 fail)
**Verdict:** GREEN
