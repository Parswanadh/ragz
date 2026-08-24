# RAGZ networking retrieval summary

- Mode: `q1_rerank-20_cache-off`
- Queries: `24` × `1` repetitions
- Recall@5: `0.500000`
- MRR@5: `0.450000`
- nDCG@5: `0.463093`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `6655.768` / `6933.561` / `6957.908` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| rerank | 5898.217 | 5916.045 | 6113.824 | 88.2% |
| dense_embedding | 762.335 | 724.701 | 819.099 | 11.4% |
| vector_search | 11.695 | 11.241 | 13.735 | 0.2% |
| collection_ready | 3.017 | 2.480 | 4.308 | 0.0% |
| workspace_model_resolution | 2.971 | 2.926 | 3.940 | 0.0% |
| authorization_prefilter | 2.900 | 2.759 | 4.977 | 0.0% |
| database_release | 1.431 | 0.746 | 1.252 | 0.0% |
| authorization_recheck | 0.976 | 0.930 | 1.333 | 0.0% |
| unattributed_runner | 0.454 | 0.446 | 0.589 | 0.0% |
| sparse_embedding | 0.437 | 0.444 | 0.607 | 0.0% |
| embedding_usage_record | 0.111 | 0.119 | 0.146 | 0.0% |
| candidate_decode | 0.073 | 0.073 | 0.115 | 0.0% |
| candidate_dedupe | 0.014 | 0.015 | 0.018 | 0.0% |
| embedder_resolution | 0.010 | 0.008 | 0.019 | 0.0% |
| reranker_resolution | 0.002 | 0.002 | 0.003 | 0.0% |
| embedding_cache_lookup | 0.001 | 0.001 | 0.002 | 0.0% |
| query_expansion | 0.000 | 0.000 | 0.001 | 0.0% |
| embedding_cache_store | 0.000 | 0.001 | 0.001 | 0.0% |
