# RAGZ networking retrieval summary

- Mode: `single`
- Queries: `15` × `7` repetitions
- Recall@5: `0.257317`
- MRR@5: `0.861111`
- nDCG@5: `0.556765`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `391.046` / `447.990` / `508.508` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 358.530 | 363.967 | 419.341 | 93.0% |
| vector_search | 8.764 | 8.530 | 12.968 | 2.3% |
| no_answer_probe | 5.608 | 5.629 | 6.914 | 1.5% |
| authorization_prefilter | 4.285 | 4.306 | 5.793 | 1.1% |
| collection_ready | 2.809 | 2.727 | 3.565 | 0.7% |
| workspace_model_resolution | 2.142 | 2.110 | 3.131 | 0.6% |
| database_release | 1.390 | 1.352 | 1.862 | 0.4% |
| authorization_recheck | 1.225 | 1.238 | 1.581 | 0.3% |
| sparse_embedding | 0.378 | 0.372 | 0.523 | 0.1% |
| unattributed_runner | 0.248 | 0.252 | 0.316 | 0.1% |
| embedding_usage_record | 0.111 | 0.122 | 0.144 | 0.0% |
| candidate_decode | 0.031 | 0.033 | 0.042 | 0.0% |
| embedder_resolution | 0.009 | 0.009 | 0.014 | 0.0% |
| candidate_dedupe | 0.006 | 0.006 | 0.009 | 0.0% |
| query_expansion | 0.000 | 0.000 | 0.001 | 0.0% |
