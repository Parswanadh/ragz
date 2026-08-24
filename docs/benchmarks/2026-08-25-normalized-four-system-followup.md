# Normalized open-source RAG follow-up

Date: 2026-08-25  
Status: RAGZ and AnythingLLM common-corpus complete; RAGFlow source-bound;
Onyx eligible but protocol-gated

## Common protocol

| Field | Value |
|---|---|
| Source corpus | `large-books-v1`, three PDFs, 4,412 pages |
| Evaluation unit | common 20-page interval |
| Queries | 24: 20 answerable, four off-corpus |
| Embedding | OpenAI `text-embedding-3-large`, 1,024 dimensions |
| Final retrieval | top five |
| RAGZ repetitions | five in forward and reverse order |
| AnythingLLM repetitions | five after two warmups |
| Reranker | disabled |

AnythingLLM indexed the 222 common intervals directly. RAGZ retained its native
18,734 heading chunks and mapped retrieved physical pages to the same intervals
after retrieval. This is a shared scoring unit, not identical chunking; the
direct interval index structurally favors AnythingLLM on evidence alignment.

## Common-corpus result

| System | Recall@5 | MRR@5 | nDCG@5 | p50 | p95 |
|---|---:|---:|---:|---:|---:|
| RAGZ Q1 cache-off | **0.8250** | **0.6583** | **0.7002** | 718.45 ms | 913.52 ms |
| RAGZ Q3 cache-off | 0.8000 | **0.6792** | **0.7096** | 1,440.66 ms | 1,639.51 ms |
| AnythingLLM large/1,024 | 0.8000 | 0.6517 | 0.6890 | **306.93 ms** | **354.01 ms** |

Interpretation:

- Q1 RAGZ has the best recall and slightly better MRR/nDCG than AnythingLLM.
- Q3 trades `-0.025` recall for higher MRR/nDCG and roughly doubles Q1 latency;
  it remains unsuitable as a global default.
- AnythingLLM is about `2.34x` faster at p50 and `2.58x` faster at p95 than
  cache-off RAGZ because its dense-only LanceDB path is shorter.
- Production RAGZ warm-cache p50 is `16.68 ms`, but it is not placed in the
  cache-off leaderboard because AnythingLLM did not expose an equivalent cache
  control.

AnythingLLM indexed 21,505 vectors in `236.92 s`, peaked at `691,535,872`
bytes, and completed 120 zero-error retrieval/latency observations, including
100 answerable quality observations. RAGZ's confirmation
indexed 18,734 chunks; its sequential index atomic total was about `1,297.78 s`,
dominated by hosted embedding. This ingestion comparison is native-path
descriptive, not a chunk-count-normalized throughput result.

## Invalid AnythingLLM attempts retained

The exact-page attempt r1 returned 120 empty retrieval rows in approximately
2 ms each. It is invalid, not “Recall 0”: AnythingLLM's update endpoint swallowed
per-document embedding failures while returning HTTP 200, leaving the namespace
empty. The runner now requires vector count to cover every input document.

The first corrected network attempt was stopped early after proving a direct
page index would require 4,412 serial document embedding operations. The final
run uses the established 20-page common unit, reducing this structural overhead
without changing corpus, queries, model, dimension or top five.

## RAGFlow boundary

RAGFlow v0.27.0 has a completed API-only cloud-model result on Open Manuals with
large/1,024 embeddings: Recall/MRR/nDCG `0.9833/0.9750/0.9772`. It is not in the
table above because the corpus and qrels differ.

The current automated RAGFlow runner requires a pre-seeded, exactly
22-document Open Manuals dataset and validates that denominator in code. No
reproducible large-books ingestion adapter exists on this branch. A manual
database/API setup would violate the campaign's provenance and recovery gates,
so the large-books row is `protocol_gated/not_executed`, not zero.

## Onyx boundary

Onyx v4.6.0 Standard passes the native Docker resource preflight (22 CPUs,
16.25 GB RAM and sufficient disk) but has no frozen large-books hosted-model
adapter or matching evidence export. Starting its official stack without those
contracts would consume its 10-GB resource envelope without producing a valid
row. Its canonical machine status is `eligible_not_executed`; the reason is a
protocol gate, and no numeric score is emitted.

## Evidence

- Machine comparison:
  `docs/benchmarks/artifacts/2026-08-25-large-books-open-source-followup.json`
- Generated table:
  `docs/benchmarks/artifacts/2026-08-25-large-books-open-source-followup.md`
- AnythingLLM valid run:
  `docs/benchmarks/artifacts/raw/2026-08-25/anythingllm-large-books-20page-large1024-20260825-r3/`
- AnythingLLM invalid empty-namespace run:
  `docs/benchmarks/artifacts/raw/2026-08-25/anythingllm-large-books-page-large1024-20260825-r1/`
- RAGZ confirmation:
  `docs/benchmarks/artifacts/raw/2026-08-24/ragz-mqr-production-confirmation-large1024-20260824-r1/`
- RAGFlow source-bound result:
  `docs/benchmarks/artifacts/raw/2026-08-23/ragflow-open-manuals-large1024-retrieval-20260823-r3/`
- Onyx resource preflight:
  `docs/benchmarks/artifacts/raw/2026-08-24/onyx-native-daemon-preflight-20260824/`
