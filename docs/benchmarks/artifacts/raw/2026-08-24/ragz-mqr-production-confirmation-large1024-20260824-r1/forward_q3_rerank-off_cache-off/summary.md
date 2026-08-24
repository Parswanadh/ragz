# RAGZ networking retrieval summary

- Mode: `forward_q3_rerank-off_cache-off`
- Queries: `24` × `5` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.447500`
- nDCG@5: `0.485516`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `1443.110` / `1638.158` / `1654.029` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 1365.827 | 1403.450 | 1602.332 | 97.2% |
| vector_search | 28.372 | 27.993 | 33.826 | 2.0% |
| no_answer_probe | 14.680 | 14.000 | 19.451 | 1.0% |
| authorization_prefilter | 2.958 | 2.779 | 4.937 | 0.2% |
| collection_ready | 2.362 | 2.297 | 3.277 | 0.2% |
| workspace_model_resolution | 1.774 | 1.540 | 2.804 | 0.1% |
| database_release | 1.113 | 0.934 | 1.459 | 0.1% |
| authorization_recheck | 1.028 | 0.970 | 1.433 | 0.1% |
| sparse_embedding | 0.602 | 0.581 | 0.833 | 0.0% |
| embedding_usage_record | 0.104 | 0.105 | 0.133 | 0.0% |
| candidate_decode | 0.044 | 0.036 | 0.065 | 0.0% |
| query_expansion | 0.024 | 0.024 | 0.034 | 0.0% |
| embedder_resolution | 0.008 | 0.007 | 0.012 | 0.0% |
| candidate_dedupe | 0.006 | 0.005 | 0.009 | 0.0% |
| embedding_cache_lookup | 0.002 | 0.002 | 0.003 | 0.0% |
| embedding_cache_store | 0.001 | 0.001 | 0.001 | 0.0% |
| unattributed_runner | 0.000 | 0.000 | 0.000 | 0.0% |
