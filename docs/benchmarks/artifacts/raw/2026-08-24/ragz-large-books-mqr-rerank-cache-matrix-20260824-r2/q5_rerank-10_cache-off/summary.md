# RAGZ networking retrieval summary

- Mode: `q5_rerank-10_cache-off`
- Queries: `24` × `1` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.495000`
- nDCG@5: `0.520232`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `6656.694` / `6759.733` / `6954.381` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| rerank | 5366.119 | 5579.718 | 5714.038 | 83.1% |
| dense_embedding | 1047.156 | 1032.006 | 1132.675 | 16.2% |
| vector_search | 31.283 | 30.513 | 37.809 | 0.5% |
| workspace_model_resolution | 3.403 | 3.417 | 4.650 | 0.1% |
| collection_ready | 2.797 | 2.662 | 3.752 | 0.0% |
| authorization_prefilter | 2.413 | 2.330 | 3.512 | 0.0% |
| authorization_recheck | 0.971 | 0.868 | 1.284 | 0.0% |
| database_release | 0.913 | 0.713 | 0.999 | 0.0% |
| sparse_embedding | 0.699 | 0.687 | 1.046 | 0.0% |
| unattributed_runner | 0.568 | 0.581 | 0.745 | 0.0% |
| query_expansion | 0.140 | 0.142 | 0.182 | 0.0% |
| embedding_usage_record | 0.094 | 0.092 | 0.131 | 0.0% |
| candidate_decode | 0.040 | 0.035 | 0.063 | 0.0% |
| embedder_resolution | 0.009 | 0.009 | 0.012 | 0.0% |
| candidate_dedupe | 0.007 | 0.007 | 0.011 | 0.0% |
| reranker_resolution | 0.002 | 0.002 | 0.002 | 0.0% |
| embedding_cache_lookup | 0.001 | 0.001 | 0.001 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
