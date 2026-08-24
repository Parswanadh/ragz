# RAGZ networking retrieval summary

- Mode: `q1_rerank-off_cache-warm`
- Queries: `24` × `2` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.464167`
- nDCG@5: `0.498209`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `19.628` / `24.052` / `25.953` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| vector_search | 8.836 | 8.474 | 10.447 | 43.7% |
| no_answer_probe | 5.443 | 5.211 | 6.896 | 26.9% |
| collection_ready | 2.050 | 1.838 | 3.016 | 10.2% |
| workspace_model_resolution | 1.379 | 1.258 | 2.122 | 6.8% |
| authorization_prefilter | 0.986 | 0.886 | 1.524 | 4.9% |
| authorization_recheck | 0.762 | 0.664 | 1.224 | 3.8% |
| database_release | 0.247 | 0.206 | 0.490 | 1.2% |
| sparse_embedding | 0.225 | 0.220 | 0.294 | 1.1% |
| unattributed_runner | 0.199 | 0.189 | 0.276 | 1.0% |
| candidate_decode | 0.030 | 0.024 | 0.052 | 0.1% |
| dense_embedding | 0.014 | 0.011 | 0.022 | 0.1% |
| embedding_cache_lookup | 0.013 | 0.011 | 0.021 | 0.1% |
| embedder_resolution | 0.008 | 0.007 | 0.013 | 0.0% |
| candidate_dedupe | 0.006 | 0.005 | 0.010 | 0.0% |
| query_expansion | 0.000 | 0.000 | 0.001 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
| embedding_usage_record | 0.000 | 0.000 | 0.001 | 0.0% |
