# RAGZ atomic retrieval latency analysis

Date: 2026-08-23

## Verdict

- Single-query mean/p50/p95: `377.35` / `388.76` / `451.07` ms.
- Multi-query mean/p50/p95: `485.47` / `507.26` / `553.17` ms.
- Dense OpenAI embedding accounts for `90.9%` of single and `89.0%` of multi mean latency.
- Removing dense-provider time leaves `34.48` ms single and `53.52` ms multi—the same tens-of-milliseconds range as the hash track, but about 25% higher.
- Multi adds `108.12` ms mean latency; dense embedding explains `82.4%` of that delta.

## Atomic stage means

| Stage | Single ms | Multi ms | Delta ms | Multi share |
|---|---:|---:|---:|---:|
| `dense_embedding` | 342.87 | 431.95 | 89.08 | 89.0% |
| `vector_search` | 12.50 | 24.28 | 11.78 | 5.0% |
| `no_answer_probe` | 7.31 | 14.03 | 6.73 | 2.9% |
| `authorization_prefilter` | 4.50 | 4.49 | -0.01 | 0.9% |
| `collection_ready` | 3.25 | 3.20 | -0.05 | 0.7% |
| `workspace_model_resolution` | 2.52 | 3.39 | 0.88 | 0.7% |
| `authorization_recheck` | 2.07 | 1.50 | -0.58 | 0.3% |
| `database_release` | 1.41 | 1.34 | -0.07 | 0.3% |
| `sparse_embedding` | 0.39 | 0.46 | 0.07 | 0.1% |
| `unattributed_runner` | 0.32 | 0.46 | 0.15 | 0.1% |
| `embedding_usage_record` | 0.11 | 0.11 | -0.01 | 0.0% |
| `query_expansion` | 0.00 | 0.16 | 0.16 | 0.0% |
| `candidate_decode` | 0.07 | 0.08 | 0.01 | 0.0% |
| `candidate_dedupe` | 0.02 | 0.02 | 0.00 | 0.0% |
| `embedder_resolution` | 0.01 | 0.01 | -0.00 | 0.0% |

## Embedding endpoint probe

Synthetic content, two warmups and ten scored repetitions per condition; a new HTTP client was created per request to match the RAGZ embedder lifecycle.

| Path | Mean ms | p50 ms | p95 ms |
|---|---:|---:|---:|
| Direct OpenAI · 1 input | 408.00 | 379.16 | 579.21 |
| LiteLLM → OpenAI · 1 input | 350.86 | 344.62 | 416.18 |
| Direct OpenAI · 3 inputs | 462.29 | 460.80 | 486.49 |
| LiteLLM → OpenAI · 3 inputs | 373.04 | 429.99 | 496.59 |

The LiteLLM and direct paths differed by `57.14` ms for one input and `89.25` ms for three inputs in this small diagnostic. Both paths remained hundreds of milliseconds; the provider/network path dominates, and these unpaired samples do not prove a fixed proxy speedup or penalty.

## Why the earlier report showed about 50 ms

The historical baseline used `deterministic-hash-1024` with no provider call: single mean/p50/p95 `27.56` / `28.00` / `31.69` ms; multi `42.99` / `42.42` / `50.40` ms. The OpenAI residuals are in the same tens-of-milliseconds range but are `25.1%` and `24.5%` higher than the hash means. They retain a different vector width/provider-backed index and are not a controlled hash counterfactual.

## AGNO boundary

AGNO does not participate in these measurements. `rag_agno` is a separate application with separate PostgreSQL/Qdrant instances and a separate benchmark. Its architecture has its own atomic timing contract, but no AGNO timing row is included here. A separately source-bound model/corpus/prompt lock is required before a cross-system latency score is valid.

## Limits

- Timings are wall clock, so they include async scheduling and network wait.
- Fixed alternatives make query-expansion time effectively zero; live LLM expansion would add a separate generation call.
- The endpoint probe has ten observations per condition and is diagnostic, not a provider SLA.
- Repeated-query embedding caches were intentionally disabled.
