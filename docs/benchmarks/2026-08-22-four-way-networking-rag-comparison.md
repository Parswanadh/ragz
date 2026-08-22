# Four-way networking RAG retrieval comparison

Date: 2026-08-22

Primary evidence unit: unique 20-physical-PDF-page interval. Quality uses 12 answerable queries; abstention uses all 15 successful queries.

## Executive verdict

- AnythingLLM with OpenAI embeddings achieved the highest Recall@5, MRR@5 and nDCG@5 on the common interval evidence unit.
- RAGZ single-query was fastest. RAGZ multi-query increased mean Recall@5 but reduced MRR@5; all three interval-level bootstrap intervals cross zero.
- AnythingLLM native MiniLM was OOM-killed during serialized indexing.
- Onyx Standard was resource-gated before startup and receives no score.

| System | Status | Recall@5 | MRR@5 | nDCG@5 | Segment hit@5 | p50 ms | p95 ms |
|---|---|---:|---:|---:|---:|---:|---:|
| AnythingLLM OpenAI + LanceDB | completed | 0.7272 | 0.8611 | 0.7465 | 1.0000 | 283.53 | 400.28 |
| RAGZ single-query | completed | 0.4970 | 0.8009 | 0.5368 | 1.0000 | 28.00 | 31.69 |
| RAGZ multi-query | completed | 0.6045 | 0.7479 | 0.6146 | 0.9722 | 42.42 | 50.40 |
| Onyx v4.6.0 Standard | resource_gated | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable |

## Configuration and eligibility

| Variant | Retrieval configuration | Resource/result |
|---|---|---|
| AnythingLLM numeric | Native raw-text collector/chunker → OpenAI `text-embedding-3-small` → LanceDB | 2 CPU / 2 GiB; indexing 168755.17 ms; peak 463680307 bytes |
| AnythingLLM native MiniLM | Native raw-text collector/chunker → MiniLM → LanceDB | `failed` at `batched_native_indexing`; OOM flag `True` |
| RAGZ single | Hash dense + BM25 → Qdrant RRF; one query | Completed |
| RAGZ multi | Same index; original + two fixed alternatives → Qdrant RRF | Completed |
| Onyx Standard | Native vector/keyword search | `resource_gated`: Docker RAM 3864363008 / required 10737418240 bytes |

## Abstention observations—not cross-system comparable

| Variant | Decision rule | Calibrated here? | Observed F1 |
|---|---|---|---:|
| AnythingLLM | Empty result only; similarity/score threshold `0.0` | No | 0.0000 |
| RAGZ single | Maximum dense cosine `< 0.42` | Development sweep, not held out | 0.5000 |
| RAGZ multi | Maximum variant dense cosine `< 0.42` | Development sweep, not held out | 0.3333 |
| Onyx | Unavailable—system not started | No | unavailable |

These values describe each configured product policy and must not be ranked as a fair abstention leaderboard.

## RAGZ paired effect

| Delta | Mean | 95% query-bootstrap CI |
|---|---:|---:|
| Recall@5 | 0.1075 | -0.0049 to 0.2257 |
| MRR@5 | -0.0530 | -0.2106 to 0.0720 |
| nDCG@5 | 0.0779 | -0.0092 to 0.1748 |

## Interpretation limits

- RAGZ multi-query uses two fixed alternatives, not live expansion.
- AnythingLLM and RAGZ use different embedders/chunkers; this is a common-locator product comparison, not a controlled model ablation.
- AnythingLLM provider call/token counts and hosted embedding cost are not exposed by the pinned public API, so cost is unavailable rather than zero.
- Onyx receives no numeric score because its official Standard memory floor is unmet. Onyx Lite is not substituted because it omits the RAG index/workers.
- Exact page quality remains available only for RAGZ. A 20-page interval hit cannot be presented as an exact-page citation.
- Answer-quality comparison is unavailable: the query set has relevance pages but no reference-answer/atomic-claim rubric.
- p99 is descriptive because these cells have fewer than 100 observations per AnythingLLM condition.
- The historical AnythingLLM MiniLM OOM attempt used the pinned local v1.16.0 tag, but that runner did not enforce the digest at `docker run`; the successful numeric rerun executes the digest-qualified image reference.

Official Onyx resource guidance: <https://docs.onyx.app/deployment/getting_started/resourcing>

## Evidence

- RAGZ source runs: `ragz-networking-mq-segment-depth20-20260822-ad70b7f-r14`, `ragz-networking-mq-segment-depth20-20260822-ad70b7f-r15`.
- AnythingLLM numeric run: `anythingllm-networking-openai-depth50-20260822-ad70b7f-r6`.
- AnythingLLM MiniLM failure: `anythingllm-networking-serial-20260822-c060c46-r3`.
- Onyx preflight: `onyx-networking-preflight-20260822-2ed4bd0`.
- Privacy-safe raw copies: `docs/benchmarks/artifacts/raw/2026-08-22/`.
- Machine-readable aggregate: `docs/benchmarks/artifacts/2026-08-22-four-way-networking-rag.json`.

Temporary extracted textbook text and all scratch storage created by this campaign were deleted after execution.
