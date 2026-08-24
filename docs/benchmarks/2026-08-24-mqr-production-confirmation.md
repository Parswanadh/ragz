# MQR production-change confirmation

Date: 2026-08-24  
Production commit under measurement: `abe6bd10`  
Analyzer commit: `431ca272`

## Verdict

The production changes preserve the selected default and strengthen the cache
decision:

- Keep Q1/MQR-off as the default.
- Q3 preserved Recall@5 but did not improve MRR or nDCG.
- Q3 added `656.50 ms` mean on cache-off requests and `16.83 ms` on warm hits.
- The production query-vector cache reduced Q1 mean from `728.49` to `16.93 ms`
  (`43.03x`) and Q3 from `1,385.00` to `33.76 ms` (`41.03x`).
- Cache-off and cache-warm quality is exactly equal inside each query-count cell.
- All eight conditions completed with zero errors and exact cache counters.

This confirms that enabling the bounded production cache does not change the
measured rankings, while unconditional MQR still has no quality justification
on this corpus.

## Protocol

| Field | Value |
|---|---|
| Corpus | `large-books-v1`, three PDFs, 4,412 pages |
| Chunks | 18,734 |
| Queries | 24: 20 answerable, four off-corpus |
| Embedding | OpenAI `text-embedding-3-large`, 1,024 dimensions |
| Index embedding | 587 calls, 6,541,213 tokens |
| Conditions | Q1/Q3 × cache-off/warm × forward/reverse |
| Per condition/order | two warmups plus five scored repetitions |
| Retrieval observations | 960 |
| Answerable quality observations | 800 |
| Total logical retrieval calls | 1,344 |
| Reranker | disabled |
| Expansion | fixed private alternatives; live LLM variance excluded |
| Errors | zero |

The original query embedding starts concurrently with query expansion in
production. The fixed expander returns immediately here so the run measures the
retrieval/cache changes without mixing in a fresh Luna response.

## Results

| Cell | Recall@5 | MRR@5 | nDCG@5 | Mean | p50 | p95 |
|---|---:|---:|---:|---:|---:|---:|
| Q1 cache-off | **0.6000** | **0.4517** | **0.4890** | 728.49 ms | 718.45 ms | 913.52 ms |
| Q1 cache-warm | **0.6000** | **0.4517** | **0.4890** | **16.93 ms** | **16.68 ms** | **19.68 ms** |
| Q3 cache-off | **0.6000** | 0.4475 | 0.4855 | 1,385.00 ms | 1,440.66 ms | 1,639.51 ms |
| Q3 cache-warm | **0.6000** | 0.4475 | 0.4855 | **33.76 ms** | **33.16 ms** | **39.33 ms** |

Paired Q3-minus-Q1 results:

- Recall: `0.0000`, with every one of 200 answerable pairs tied.
- MRR: `-0.00417`; bootstrap CI95 `[-0.02833, 0.02042]`.
- nDCG: `-0.00347`; bootstrap CI95 `[-0.02150, 0.01480]`.
- Cache-off latency: `+656.50 ms`; CI95 `[623.75, 687.95]`.
- Cache-warm latency: `+16.83 ms`; CI95 `[16.41, 17.26]`.

No quality delta supports making MQR unconditional. The latency deltas are
large and consistently positive.

## Atomic latency

### Q1 cache-off

| Stage | Mean | p95 |
|---|---:|---:|
| Dense embedding | 705.28 ms | 889.87 ms |
| Vector search/RRF | 13.18 ms | 16.68 ms |
| Dense no-answer probe | 8.51 ms | 12.04 ms |
| ACL prefilter | 3.12 ms | 5.86 ms |
| Request total | **728.49 ms** | **913.52 ms** |

### Q1 cache-warm

| Stage | Mean | p95 |
|---|---:|---:|
| Embedding-cache lookup | 0.025 ms | 0.038 ms |
| Dense embedding (no provider call) | 0.010 ms | 0.015 ms |
| Vector search/RRF | 11.08 ms | 12.99 ms |
| Dense no-answer probe | 7.19 ms | 8.55 ms |
| Request total | **16.93 ms** | **19.68 ms** |

Vector search and the no-answer probe execute concurrently. The authoritative
request total therefore uses their observed overlap; they must not be added as
serial stages. The parallel critical group is their maximum, saving about the
probe duration versus the former serial schedule.

## Ranking stability

- Q3: 48/48 order/query groups were byte-stable across five repetitions.
- Q1: 33/48 groups were stable; 15 changed the final candidate set/order despite
  deterministic secondary tie sorting.

The remaining Q1 variation is upstream of the tie sorter: fresh hosted
embeddings and approximate candidate-boundary behavior can change which tied
candidate reaches the returned set. Stable sorting fixes equal-score ordering
for a given candidate set; it cannot make different provider vectors or
different approximate candidate sets identical. Warm-cache quality nevertheless
matched cache-off in aggregate exactly.

## Live expansion boundary

The fresh low-reasoning 24-query expansion pass completed 24/24 on the first
attempt with zero fallback lanes:

- mean `3,163.02 ms`;
- p50 `2,754.28 ms`;
- p95 `4,876.80 ms`; and
- usage-derived cost `$0.006254`.

The production deadline is 3,000 ms. It deliberately accepts the faster cold
expansions and returns Q1 for the slower tail; repeated queries use the
prompt/model/count-versioned expansion cache. This prevents a 4.9-second p95
expansion from becoming mandatory retrieval latency.

A separate live cache pass expanded all 24 queries cold and then immediately
warm in the same process. Cold mean/p50/p95 was
`3,229.59 / 3,071.06 / 4,573.67 ms`; warm mean/p50/p95 was
`0.023 / 0.017 / 0.047 ms`. All 24 warm results exactly matched their cold
alternatives, with zero warm provider calls and zero warm provider tokens.

## Evidence

- Machine analysis:
  `docs/benchmarks/artifacts/2026-08-24-mqr-production-confirmation.json`
- Generated table:
  `docs/benchmarks/artifacts/2026-08-24-mqr-production-confirmation.md`
- Raw retrieval run:
  `docs/benchmarks/artifacts/raw/2026-08-24/ragz-mqr-production-confirmation-large1024-20260824-r1/`
- Expansion evidence:
  `docs/benchmarks/artifacts/raw/2026-08-24/ragz-mqr-production-confirmation-expansions-20260824/`
- Live expansion-cache evidence:
  `docs/benchmarks/artifacts/raw/2026-08-25/query-expansion-cache-live-smoke-20260825.json`
