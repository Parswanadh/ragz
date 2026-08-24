# RAGZ networking retrieval summary

- Mode: `reverse_q3_rerank-off_cache-off`
- Queries: `24` × `5` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.447500`
- nDCG@5: `0.485516`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `1436.563` / `1639.763` / `1751.687` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 1327.536 | 1397.261 | 1602.487 | 97.2% |
| vector_search | 27.483 | 26.505 | 33.301 | 2.0% |
| no_answer_probe | 14.565 | 13.823 | 19.513 | 1.1% |
| authorization_prefilter | 2.756 | 2.591 | 4.594 | 0.2% |
| collection_ready | 2.242 | 2.098 | 3.125 | 0.2% |
| workspace_model_resolution | 1.828 | 1.548 | 2.801 | 0.1% |
| authorization_recheck | 1.040 | 1.000 | 1.380 | 0.1% |
| database_release | 0.942 | 0.894 | 1.451 | 0.1% |
| sparse_embedding | 0.545 | 0.544 | 0.780 | 0.0% |
| embedding_usage_record | 0.105 | 0.106 | 0.137 | 0.0% |
| candidate_decode | 0.046 | 0.037 | 0.065 | 0.0% |
| query_expansion | 0.024 | 0.024 | 0.037 | 0.0% |
| embedder_resolution | 0.008 | 0.007 | 0.012 | 0.0% |
| candidate_dedupe | 0.006 | 0.005 | 0.009 | 0.0% |
| embedding_cache_lookup | 0.002 | 0.002 | 0.003 | 0.0% |
| embedding_cache_store | 0.001 | 0.001 | 0.001 | 0.0% |
| unattributed_runner | 0.000 | 0.000 | 0.000 | 0.0% |
