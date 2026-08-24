# RAGZ networking retrieval summary

- Mode: `q1_rerank-50_cache-off`
- Queries: `24` × `1` repetitions
- Recall@5: `0.550000`
- MRR@5: `0.491667`
- nDCG@5: `0.506546`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `6659.861` / `8444.586` / `9668.733` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| rerank | 5839.573 | 5900.526 | 7585.530 | 87.7% |
| dense_embedding | 792.503 | 758.864 | 978.976 | 11.9% |
| vector_search | 14.018 | 13.923 | 17.794 | 0.2% |
| workspace_model_resolution | 2.873 | 2.999 | 3.555 | 0.0% |
| database_release | 2.826 | 0.818 | 16.714 | 0.0% |
| collection_ready | 2.723 | 2.590 | 3.761 | 0.0% |
| authorization_prefilter | 2.428 | 2.269 | 3.624 | 0.0% |
| authorization_recheck | 0.943 | 0.872 | 1.250 | 0.0% |
| unattributed_runner | 0.472 | 0.475 | 0.579 | 0.0% |
| sparse_embedding | 0.413 | 0.407 | 0.632 | 0.0% |
| candidate_decode | 0.396 | 0.129 | 0.309 | 0.0% |
| embedding_usage_record | 0.111 | 0.115 | 0.152 | 0.0% |
| candidate_dedupe | 0.026 | 0.025 | 0.040 | 0.0% |
| embedder_resolution | 0.010 | 0.009 | 0.015 | 0.0% |
| reranker_resolution | 0.002 | 0.002 | 0.002 | 0.0% |
| embedding_cache_lookup | 0.001 | 0.001 | 0.002 | 0.0% |
| query_expansion | 0.000 | 0.000 | 0.001 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
