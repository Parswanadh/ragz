# RAGZ large/1024 product benchmark analysis

This report is aggregate-only: it contains no prompts, answers, query text, or retrieved evidence.

## Run integrity

| Run | Order | Commit | Tracked diff | Dirty flag |
|---|---|---|---|---:|
| `ragz-networking-large1024-product-atomic-20260823-r1` | `single-first` | `e38b9f99ab5e1fa8c6590d6702c3387215bf6d6b` | `c9ab35ae572daca6f19af27d49571722ae076d480985e3d2b5864ac7bb776689` | `true` |
| `ragz-networking-large1024-product-atomic-20260823-r2` | `multi-first` | `e38b9f99ab5e1fa8c6590d6702c3387215bf6d6b` | `c9ab35ae572daca6f19af27d49571722ae076d480985e3d2b5864ac7bb776689` | `true` |

## Combined retrieval latency

| Mode | N | Mean ms | p50 ms | p95 ms | p99 ms |
|---|---:|---:|---:|---:|---:|
| Single | 210 | 368.64 | 380.68 | 461.58 | 669.35 |
| Multi | 210 | 451.04 | 481.92 | 532.77 | 554.07 |

## Atomic retrieval stages

| Stage | Single mean ms | Multi mean ms | Single share | Multi share |
|---|---:|---:|---:|---:|
| `dense_embedding` | 341.95 | 410.92 | 92.8% | 91.1% |
| `vector_search` | 8.76 | 14.99 | 2.4% | 3.3% |
| `no_answer_probe` | 5.62 | 11.37 | 1.5% | 2.5% |
| `authorization_prefilter` | 4.13 | 4.12 | 1.1% | 0.9% |
| `collection_ready` | 2.76 | 2.80 | 0.7% | 0.6% |
| `workspace_model_resolution` | 2.14 | 3.16 | 0.6% | 0.7% |
| `database_release` | 1.32 | 1.20 | 0.4% | 0.3% |
| `authorization_recheck` | 1.22 | 1.38 | 0.3% | 0.3% |
| `sparse_embedding` | 0.35 | 0.44 | 0.1% | 0.1% |
| `unattributed_runner` | 0.24 | 0.36 | 0.1% | 0.1% |
| `embedding_usage_record` | 0.10 | 0.10 | 0.0% | 0.0% |
| `candidate_decode` | 0.03 | 0.03 | 0.0% | 0.0% |
| `embedder_resolution` | 0.01 | 0.01 | 0.0% | 0.0% |
| `candidate_dedupe` | 0.01 | 0.01 | 0.0% | 0.0% |
| `query_expansion` | 0.00 | 0.14 | 0.0% | 0.0% |

## Paired multi-minus-single bootstrap

Bootstrap resampling is over the 15 query-level paired means (12 for retrieval quality), with 10,000 samples and seed 42.

| Metric | Paired queries | Mean delta | 95% CI |
|---|---:|---:|---:|
| Latency ms | 15 | 82.4025 | [70.2094, 95.0211] |
| Recall@5 | 12 | -0.0151 | [-0.0685, 0.0400] |
| MRR@5 | 12 | 0.0556 | [0.0000, 0.1528] |
| nDCG@5 | 12 | 0.0045 | [-0.0786, 0.0891] |

## Combined index-stage totals

| Stage | Combined ms | Share |
|---|---:|---:|
| `chunk` | 263.68 | 0.0% |
| `dense_embedding` | 498549.99 | 90.2% |
| `parse` | 35337.84 | 6.4% |
| `qdrant_upsert` | 15322.78 | 2.8% |
| `sparse_embedding` | 3006.23 | 0.5% |

## Prior small/1536 track (descriptive only)

The prior pair is shown only as context; its denominator is 15 queries × 3 repetitions × 2 orderings = 90 observations per mode.

| Mode | N | Answerable N | Mean ms | p50 ms | p95 ms | p99 ms |
|---|---:|---:|---:|---:|---:|---:|
| Single | 90 | 72 | 377.35 | 388.76 | 451.07 | 466.93 |
| Multi | 90 | 72 | 485.47 | 507.26 | 553.17 | 568.25 |

## Interpretation

The dominant retrieval stage is the one with the largest mean share above; stage closure is validated per row. Fixed local alternatives make query expansion near-zero and are not a live Luna expansion measurement. The historical small/1536 comparison is not a controlled ranking because it has a different model, dimension, repetition count, and commit.
