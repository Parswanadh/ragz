# RAGZ networking retrieval summary

- Mode: `q3_rerank-off_cache-off`
- Queries: `24` × `1` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.464167`
- nDCG@5: `0.497423`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `942.009` / `1128.783` / `1132.931` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 891.449 | 894.993 | 1077.628 | 94.8% |
| vector_search | 23.787 | 23.426 | 27.308 | 2.5% |
| no_answer_probe | 13.020 | 12.283 | 15.495 | 1.4% |
| authorization_prefilter | 3.754 | 3.401 | 5.469 | 0.4% |
| collection_ready | 2.975 | 2.916 | 3.652 | 0.3% |
| workspace_model_resolution | 2.500 | 2.639 | 3.005 | 0.3% |
| authorization_recheck | 1.169 | 1.099 | 1.645 | 0.1% |
| sparse_embedding | 0.706 | 0.688 | 0.930 | 0.1% |
| database_release | 0.678 | 0.697 | 0.866 | 0.1% |
| unattributed_runner | 0.457 | 0.459 | 0.565 | 0.0% |
| query_expansion | 0.172 | 0.173 | 0.210 | 0.0% |
| embedding_usage_record | 0.106 | 0.113 | 0.132 | 0.0% |
| candidate_decode | 0.033 | 0.026 | 0.055 | 0.0% |
| embedder_resolution | 0.012 | 0.011 | 0.018 | 0.0% |
| candidate_dedupe | 0.007 | 0.007 | 0.010 | 0.0% |
| embedding_cache_lookup | 0.001 | 0.001 | 0.002 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
