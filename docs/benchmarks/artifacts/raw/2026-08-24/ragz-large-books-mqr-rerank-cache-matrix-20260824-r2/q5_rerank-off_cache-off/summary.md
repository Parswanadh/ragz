# RAGZ networking retrieval summary

- Mode: `q5_rerank-off_cache-off`
- Queries: `24` × `1` repetitions
- Recall@5: `0.550000`
- MRR@5: `0.458333`
- nDCG@5: `0.481546`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `832.911` / `1205.026` / `1270.445` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 868.417 | 770.282 | 1142.119 | 93.5% |
| vector_search | 33.278 | 32.875 | 36.872 | 3.6% |
| no_answer_probe | 16.388 | 16.065 | 21.151 | 1.8% |
| authorization_prefilter | 3.177 | 3.157 | 5.024 | 0.3% |
| collection_ready | 2.225 | 2.192 | 2.898 | 0.2% |
| workspace_model_resolution | 2.046 | 1.786 | 2.882 | 0.2% |
| authorization_recheck | 1.072 | 0.999 | 1.560 | 0.1% |
| sparse_embedding | 0.797 | 0.804 | 1.048 | 0.1% |
| database_release | 0.716 | 0.720 | 0.944 | 0.1% |
| unattributed_runner | 0.444 | 0.408 | 0.612 | 0.0% |
| query_expansion | 0.131 | 0.104 | 0.185 | 0.0% |
| embedding_usage_record | 0.101 | 0.090 | 0.136 | 0.0% |
| candidate_decode | 0.032 | 0.026 | 0.045 | 0.0% |
| embedder_resolution | 0.009 | 0.007 | 0.013 | 0.0% |
| candidate_dedupe | 0.006 | 0.006 | 0.009 | 0.0% |
| embedding_cache_lookup | 0.001 | 0.001 | 0.002 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
