# RAGZ networking retrieval summary

- Mode: `reverse_q1_rerank-off_cache-warm`
- Queries: `24` × `5` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.451667`
- nDCG@5: `0.488982`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `16.711` / `19.655` / `21.091` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| vector_search | 11.067 | 10.889 | 12.542 | 65.2% |
| no_answer_probe | 7.132 | 7.007 | 8.425 | 42.0% |
| collection_ready | 2.138 | 2.002 | 2.934 | 12.6% |
| workspace_model_resolution | 1.163 | 1.048 | 1.729 | 6.9% |
| authorization_recheck | 0.920 | 0.827 | 1.281 | 5.4% |
| authorization_prefilter | 0.918 | 0.856 | 1.403 | 5.4% |
| sparse_embedding | 0.240 | 0.233 | 0.313 | 1.4% |
| database_release | 0.220 | 0.200 | 0.337 | 1.3% |
| candidate_decode | 0.042 | 0.036 | 0.065 | 0.3% |
| embedding_cache_lookup | 0.026 | 0.022 | 0.038 | 0.2% |
| dense_embedding | 0.010 | 0.009 | 0.015 | 0.1% |
| embedder_resolution | 0.008 | 0.007 | 0.013 | 0.0% |
| candidate_dedupe | 0.005 | 0.004 | 0.008 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
| embedding_usage_record | 0.000 | 0.000 | 0.001 | 0.0% |
| unattributed_runner | 0.000 | 0.000 | 0.000 | 0.0% |
