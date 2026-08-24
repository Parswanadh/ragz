# RAGZ networking retrieval summary

- Mode: `forward_q1_rerank-off_cache-off`
- Queries: `24` × `5` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.451667`
- nDCG@5: `0.488982`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `716.311` / `823.185` / `925.305` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 675.461 | 693.753 | 799.810 | 96.7% |
| vector_search | 13.156 | 12.669 | 16.260 | 1.9% |
| no_answer_probe | 8.454 | 8.147 | 11.462 | 1.2% |
| authorization_prefilter | 3.114 | 2.895 | 5.277 | 0.4% |
| collection_ready | 2.309 | 2.199 | 3.308 | 0.3% |
| workspace_model_resolution | 1.387 | 1.328 | 2.172 | 0.2% |
| database_release | 1.180 | 1.118 | 1.750 | 0.2% |
| authorization_recheck | 1.081 | 1.010 | 1.531 | 0.2% |
| sparse_embedding | 0.471 | 0.461 | 0.671 | 0.1% |
| embedding_usage_record | 0.106 | 0.112 | 0.139 | 0.0% |
| candidate_decode | 0.049 | 0.045 | 0.072 | 0.0% |
| embedder_resolution | 0.008 | 0.007 | 0.012 | 0.0% |
| candidate_dedupe | 0.006 | 0.006 | 0.009 | 0.0% |
| embedding_cache_lookup | 0.001 | 0.001 | 0.002 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
| unattributed_runner | 0.000 | 0.000 | 0.000 | 0.0% |
