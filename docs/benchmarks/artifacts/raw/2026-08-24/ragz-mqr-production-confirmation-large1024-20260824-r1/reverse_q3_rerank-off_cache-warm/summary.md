# RAGZ networking retrieval summary

- Mode: `reverse_q3_rerank-off_cache-warm`
- Queries: `24` × `5` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.447500`
- nDCG@5: `0.485516`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `34.204` / `39.840` / `42.533` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| vector_search | 27.200 | 26.858 | 31.084 | 78.5% |
| no_answer_probe | 13.632 | 13.460 | 16.329 | 39.3% |
| collection_ready | 2.393 | 2.301 | 3.180 | 6.9% |
| workspace_model_resolution | 1.814 | 1.665 | 2.550 | 5.2% |
| authorization_prefilter | 1.066 | 0.950 | 1.626 | 3.1% |
| authorization_recheck | 0.989 | 0.925 | 1.379 | 2.9% |
| sparse_embedding | 0.367 | 0.355 | 0.511 | 1.1% |
| database_release | 0.238 | 0.211 | 0.367 | 0.7% |
| candidate_decode | 0.046 | 0.042 | 0.065 | 0.1% |
| embedding_cache_lookup | 0.045 | 0.040 | 0.068 | 0.1% |
| query_expansion | 0.033 | 0.029 | 0.045 | 0.1% |
| dense_embedding | 0.017 | 0.015 | 0.026 | 0.0% |
| embedder_resolution | 0.009 | 0.008 | 0.013 | 0.0% |
| candidate_dedupe | 0.006 | 0.006 | 0.009 | 0.0% |
| embedding_cache_store | 0.001 | 0.001 | 0.001 | 0.0% |
| embedding_usage_record | 0.000 | 0.000 | 0.001 | 0.0% |
| unattributed_runner | 0.000 | 0.000 | 0.000 | 0.0% |
