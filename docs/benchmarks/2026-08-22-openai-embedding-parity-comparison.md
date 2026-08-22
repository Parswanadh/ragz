# Four-way networking RAG retrieval comparison

Date: 2026-08-22

Primary evidence unit: unique 20-physical-PDF-page interval. Quality uses 12 answerable queries; abstention uses all 15 successful queries.

## Executive verdict

- AnythingLLM and RAGZ use the same OpenAI `text-embedding-3-small` model at 1,536 dimensions in this report.
- Quality leaders — Recall@5: AnythingLLM (0.7272); MRR@5: RAGZ single (0.8778); nDCG@5: AnythingLLM (0.7465).
- Median-latency leader: AnythingLLM (283.53 ms).
- The paired RAGZ multi-minus-single effect and query-bootstrap intervals are reported below without assuming the direction in advance.
- AnythingLLM native MiniLM was OOM-killed during serialized indexing.
- Onyx Standard was resource-gated before startup and receives no score.

| System | Status | Recall@5 | MRR@5 | nDCG@5 | Segment hit@5 | p50 ms | p95 ms |
|---|---|---:|---:|---:|---:|---:|---:|
| AnythingLLM OpenAI + LanceDB | completed | 0.7272 | 0.8611 | 0.7465 | 1.0000 | 283.53 | 400.28 |
| RAGZ single-query | completed | 0.6800 | 0.8778 | 0.7017 | 1.0000 | 374.84 | 542.51 |
| RAGZ multi-query | completed | 0.7244 | 0.8403 | 0.7295 | 1.0000 | 525.47 | 633.10 |
| Onyx v4.6.0 Standard | resource_gated | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable |

## Configuration and eligibility

| Variant | Retrieval configuration | Resource/result |
|---|---|---|
| AnythingLLM numeric | Native raw-text collector/chunker → OpenAI `text-embedding-3-small` → LanceDB | 2 CPU / 2 GiB; indexing 168755.17 ms; peak 463680307 bytes |
| AnythingLLM native MiniLM | Native raw-text collector/chunker → MiniLM → LanceDB | `failed` at `batched_native_indexing`; OOM flag `True` |
| RAGZ single | text-embedding-3-small (1536d) + BM25 → Qdrant RRF; one query | Completed |
| RAGZ multi | Same embedding/index; original + two fixed alternatives → Qdrant RRF | Completed |
| Onyx Standard | Native vector/keyword search | `resource_gated`: Docker RAM 3864363008 / required 10737418240 bytes |

## Abstention observations—not cross-system comparable

| Variant | Decision rule | Calibrated here? | Observed F1 |
|---|---|---|---:|
| AnythingLLM | Empty result only; similarity/score threshold `0.0` | No | 0.0000 |
| RAGZ single | Maximum dense cosine `< 0.0` | unthresholded OpenAI parity track aligned to AnythingLLM empty-result policy; not calibrated for abstention | 0.0000 |
| RAGZ multi | Maximum variant dense cosine `< 0.0` | unthresholded OpenAI parity track aligned to AnythingLLM empty-result policy; not calibrated for abstention | 0.0000 |
| Onyx | Unavailable—system not started | No | unavailable |

These values describe each configured product policy and must not be ranked as a fair abstention leaderboard.

## RAGZ paired effect

| Delta | Mean | 95% query-bootstrap CI |
|---|---:|---:|
| Recall@5 | 0.0444 | -0.0125 to 0.1111 |
| MRR@5 | -0.0375 | -0.1250 to 0.0125 |
| nDCG@5 | 0.0279 | -0.0109 to 0.0718 |

## Interpretation limits

- RAGZ multi-query uses two fixed alternatives, not live expansion.
- AnythingLLM and RAGZ use the same embedder model, but retain their native chunkers and retrieval engines; this is a model-parity product comparison, not an embedding-only ablation.
- AnythingLLM provider call/token counts and hosted embedding cost are not exposed by the pinned public API, so cost is unavailable rather than zero.
- Onyx receives no numeric score because its official Standard memory floor is unmet. Onyx Lite is not substituted because it omits the RAG index/workers.
- Exact page quality remains available only for RAGZ. A 20-page interval hit cannot be presented as an exact-page citation.
- Answer-quality comparison is unavailable: the query set has relevance pages but no reference-answer/atomic-claim rubric.
- p99 is descriptive because these cells have fewer than 100 observations per AnythingLLM condition.
- The historical AnythingLLM MiniLM OOM attempt used the pinned local v1.16.0 tag, but that runner did not enforce the digest at `docker run`; the successful numeric rerun executes the digest-qualified image reference.

Official Onyx resource guidance: <https://docs.onyx.app/deployment/getting_started/resourcing>

## Evidence

- RAGZ source runs: `ragz-networking-openai-parity-depth20-20260822-f341e45-r1`, `ragz-networking-openai-parity-depth20-20260822-f341e45-r2`.
- AnythingLLM numeric run: `anythingllm-networking-openai-depth50-20260822-ad70b7f-r6`.
- AnythingLLM MiniLM failure: `anythingllm-networking-serial-20260822-c060c46-r3`.
- Onyx preflight: `onyx-networking-preflight-20260822-2ed4bd0`.
- Privacy-safe raw copies: `docs/benchmarks/artifacts/raw/2026-08-22/`.
- Machine-readable aggregate: `docs/benchmarks/artifacts/2026-08-22-openai-embedding-parity-comparison.json`.

Temporary extracted textbook text is local-only and must be deleted after the comparison is built; committed raw copies contain no textbook text.
