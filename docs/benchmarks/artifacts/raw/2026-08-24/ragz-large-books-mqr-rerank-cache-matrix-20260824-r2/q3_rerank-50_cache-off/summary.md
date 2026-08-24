# RAGZ networking retrieval summary

- Mode: `q3_rerank-50_cache-off`
- Queries: `24` × `1` repetitions
- Recall@5: `0.550000`
- MRR@5: `0.491667`
- nDCG@5: `0.506546`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `6685.868` / `6921.629` / `7223.215` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| rerank | 5540.220 | 5603.605 | 5787.378 | 83.0% |
| dense_embedding | 1095.275 | 999.954 | 1607.388 | 16.4% |
| vector_search | 24.430 | 23.673 | 28.063 | 0.4% |
| database_release | 6.690 | 0.835 | 17.285 | 0.1% |
| workspace_model_resolution | 3.337 | 2.965 | 4.983 | 0.0% |
| collection_ready | 2.891 | 3.023 | 3.779 | 0.0% |
| authorization_prefilter | 2.547 | 2.477 | 3.799 | 0.0% |
| authorization_recheck | 1.137 | 0.913 | 1.313 | 0.0% |
| unattributed_runner | 0.569 | 0.565 | 0.725 | 0.0% |
| sparse_embedding | 0.510 | 0.526 | 0.668 | 0.0% |
| query_expansion | 0.131 | 0.104 | 0.219 | 0.0% |
| candidate_decode | 0.126 | 0.112 | 0.189 | 0.0% |
| embedding_usage_record | 0.101 | 0.105 | 0.126 | 0.0% |
| candidate_dedupe | 0.023 | 0.024 | 0.033 | 0.0% |
| embedder_resolution | 0.010 | 0.008 | 0.016 | 0.0% |
| reranker_resolution | 0.002 | 0.002 | 0.002 | 0.0% |
| embedding_cache_lookup | 0.001 | 0.001 | 0.002 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
