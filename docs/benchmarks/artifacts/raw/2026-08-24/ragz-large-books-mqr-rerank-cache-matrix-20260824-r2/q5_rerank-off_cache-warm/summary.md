# RAGZ networking retrieval summary

- Mode: `q5_rerank-off_cache-warm`
- Queries: `24` × `1` repetitions
- Recall@5: `0.550000`
- MRR@5: `0.458333`
- nDCG@5: `0.481546`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `54.495` / `59.912` / `61.064` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| vector_search | 32.152 | 31.815 | 34.594 | 58.7% |
| no_answer_probe | 15.581 | 15.461 | 18.016 | 28.4% |
| collection_ready | 1.911 | 1.809 | 2.453 | 3.5% |
| workspace_model_resolution | 1.822 | 1.807 | 2.037 | 3.3% |
| authorization_prefilter | 1.148 | 1.044 | 1.694 | 2.1% |
| authorization_recheck | 0.958 | 0.821 | 1.421 | 1.7% |
| sparse_embedding | 0.480 | 0.438 | 0.682 | 0.9% |
| unattributed_runner | 0.312 | 0.286 | 0.416 | 0.6% |
| database_release | 0.215 | 0.186 | 0.346 | 0.4% |
| query_expansion | 0.113 | 0.102 | 0.183 | 0.2% |
| embedding_cache_lookup | 0.031 | 0.028 | 0.048 | 0.1% |
| candidate_decode | 0.028 | 0.025 | 0.047 | 0.1% |
| dense_embedding | 0.014 | 0.012 | 0.021 | 0.0% |
| embedder_resolution | 0.008 | 0.007 | 0.011 | 0.0% |
| candidate_dedupe | 0.006 | 0.006 | 0.010 | 0.0% |
| embedding_usage_record | 0.000 | 0.000 | 0.000 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.000 | 0.0% |
