# RAGZ networking retrieval summary

- Mode: `q5_rerank-20_cache-off`
- Queries: `24` × `1` repetitions
- Recall@5: `0.500000`
- MRR@5: `0.450000`
- nDCG@5: `0.463093`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `6674.858` / `17564.829` / `22448.893` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| rerank | 6371.371 | 5584.907 | 16477.288 | 85.2% |
| dense_embedding | 1058.174 | 1039.373 | 1152.488 | 14.1% |
| vector_search | 35.314 | 34.895 | 40.706 | 0.5% |
| workspace_model_resolution | 3.811 | 3.572 | 5.596 | 0.1% |
| collection_ready | 3.315 | 3.375 | 4.056 | 0.0% |
| authorization_prefilter | 2.921 | 2.678 | 5.651 | 0.0% |
| authorization_recheck | 1.466 | 1.137 | 1.466 | 0.0% |
| database_release | 1.455 | 0.833 | 1.328 | 0.0% |
| sparse_embedding | 0.738 | 0.757 | 1.121 | 0.0% |
| unattributed_runner | 0.647 | 0.645 | 0.800 | 0.0% |
| candidate_decode | 0.328 | 0.070 | 0.110 | 0.0% |
| query_expansion | 0.159 | 0.163 | 0.246 | 0.0% |
| embedding_usage_record | 0.093 | 0.091 | 0.115 | 0.0% |
| candidate_dedupe | 0.014 | 0.012 | 0.020 | 0.0% |
| embedder_resolution | 0.011 | 0.011 | 0.018 | 0.0% |
| reranker_resolution | 0.002 | 0.002 | 0.003 | 0.0% |
| embedding_cache_lookup | 0.001 | 0.001 | 0.002 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.000 | 0.0% |
