# RAGZ networking retrieval summary

- Mode: `single`
- Queries: `15` × `3` repetitions
- Recall@20: `0.446140`
- MRR@20: `0.808333`
- nDCG@20: `0.501727`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `399.360` / `455.126` / `479.233` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 350.350 | 361.773 | 425.320 | 91.2% |
| vector_search | 12.411 | 12.406 | 14.933 | 3.2% |
| no_answer_probe | 7.281 | 6.953 | 8.654 | 1.9% |
| authorization_prefilter | 4.402 | 4.433 | 5.952 | 1.1% |
| collection_ready | 3.086 | 3.104 | 3.590 | 0.8% |
| workspace_model_resolution | 2.482 | 2.400 | 3.148 | 0.6% |
| authorization_recheck | 1.900 | 1.443 | 5.767 | 0.5% |
| database_release | 1.351 | 1.353 | 1.613 | 0.4% |
| sparse_embedding | 0.419 | 0.350 | 0.527 | 0.1% |
| unattributed_runner | 0.312 | 0.315 | 0.386 | 0.1% |
| embedding_usage_record | 0.113 | 0.102 | 0.143 | 0.0% |
| candidate_decode | 0.071 | 0.081 | 0.096 | 0.0% |
| candidate_dedupe | 0.018 | 0.020 | 0.025 | 0.0% |
| embedder_resolution | 0.011 | 0.010 | 0.017 | 0.0% |
| query_expansion | 0.000 | 0.001 | 0.001 | 0.0% |
