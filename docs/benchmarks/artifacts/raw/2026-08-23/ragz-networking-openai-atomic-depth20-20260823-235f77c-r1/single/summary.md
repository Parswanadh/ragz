# RAGZ networking retrieval summary

- Mode: `single`
- Queries: `15` × `3` repetitions
- Recall@20: `0.446140`
- MRR@20: `0.808333`
- nDCG@20: `0.501608`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `379.570` / `442.745` / `459.124` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 335.391 | 343.420 | 410.032 | 90.5% |
| vector_search | 12.597 | 12.218 | 15.958 | 3.4% |
| no_answer_probe | 7.335 | 7.250 | 8.574 | 2.0% |
| authorization_prefilter | 4.600 | 4.624 | 5.788 | 1.2% |
| collection_ready | 3.405 | 3.318 | 4.206 | 0.9% |
| workspace_model_resolution | 2.554 | 2.570 | 3.111 | 0.7% |
| authorization_recheck | 2.246 | 1.568 | 6.793 | 0.6% |
| database_release | 1.465 | 1.343 | 1.814 | 0.4% |
| sparse_embedding | 0.363 | 0.355 | 0.524 | 0.1% |
| unattributed_runner | 0.322 | 0.335 | 0.400 | 0.1% |
| embedding_usage_record | 0.109 | 0.096 | 0.150 | 0.0% |
| candidate_decode | 0.074 | 0.082 | 0.099 | 0.0% |
| candidate_dedupe | 0.018 | 0.020 | 0.024 | 0.0% |
| embedder_resolution | 0.012 | 0.011 | 0.018 | 0.0% |
| query_expansion | 0.000 | 0.001 | 0.001 | 0.0% |
