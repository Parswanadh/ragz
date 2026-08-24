# RAGZ networking retrieval summary

- Mode: `forward_q3_rerank-off_cache-warm`
- Queries: `24` × `5` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.447500`
- nDCG@5: `0.485516`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `32.546` / `36.607` / `41.287` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| vector_search | 25.982 | 25.729 | 29.429 | 79.1% |
| no_answer_probe | 13.004 | 12.837 | 14.757 | 39.6% |
| collection_ready | 2.155 | 2.070 | 2.973 | 6.6% |
| workspace_model_resolution | 1.693 | 1.493 | 2.497 | 5.2% |
| authorization_prefilter | 0.980 | 0.889 | 1.490 | 3.0% |
| authorization_recheck | 0.928 | 0.834 | 1.261 | 2.8% |
| sparse_embedding | 0.334 | 0.319 | 0.443 | 1.0% |
| database_release | 0.223 | 0.191 | 0.366 | 0.7% |
| candidate_decode | 0.042 | 0.036 | 0.064 | 0.1% |
| embedding_cache_lookup | 0.040 | 0.036 | 0.060 | 0.1% |
| query_expansion | 0.029 | 0.025 | 0.044 | 0.1% |
| dense_embedding | 0.015 | 0.013 | 0.025 | 0.0% |
| embedder_resolution | 0.008 | 0.007 | 0.011 | 0.0% |
| candidate_dedupe | 0.006 | 0.005 | 0.008 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
| embedding_usage_record | 0.000 | 0.000 | 0.001 | 0.0% |
| unattributed_runner | 0.000 | 0.000 | 0.000 | 0.0% |
