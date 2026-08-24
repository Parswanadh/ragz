# RAGZ networking retrieval summary

- Mode: `q5_rerank-50_cache-off`
- Queries: `24` × `1` repetitions
- Recall@5: `0.500000`
- MRR@5: `0.475000`
- nDCG@5: `0.481546`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `6672.711` / `7113.620` / `9045.022` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| rerank | 5506.107 | 5560.089 | 6004.207 | 82.5% |
| dense_embedding | 1120.134 | 1065.421 | 1336.997 | 16.8% |
| vector_search | 36.407 | 35.629 | 41.487 | 0.5% |
| workspace_model_resolution | 3.407 | 3.389 | 4.758 | 0.1% |
| collection_ready | 3.161 | 3.372 | 4.244 | 0.0% |
| authorization_prefilter | 2.685 | 2.470 | 4.169 | 0.0% |
| database_release | 1.758 | 0.681 | 9.967 | 0.0% |
| authorization_recheck | 1.210 | 0.911 | 1.542 | 0.0% |
| sparse_embedding | 0.805 | 0.802 | 1.147 | 0.0% |
| unattributed_runner | 0.684 | 0.651 | 0.848 | 0.0% |
| query_expansion | 0.148 | 0.145 | 0.220 | 0.0% |
| candidate_decode | 0.139 | 0.115 | 0.261 | 0.0% |
| embedding_usage_record | 0.097 | 0.095 | 0.125 | 0.0% |
| candidate_dedupe | 0.027 | 0.024 | 0.046 | 0.0% |
| embedder_resolution | 0.010 | 0.010 | 0.016 | 0.0% |
| reranker_resolution | 0.002 | 0.002 | 0.003 | 0.0% |
| embedding_cache_lookup | 0.001 | 0.001 | 0.002 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
