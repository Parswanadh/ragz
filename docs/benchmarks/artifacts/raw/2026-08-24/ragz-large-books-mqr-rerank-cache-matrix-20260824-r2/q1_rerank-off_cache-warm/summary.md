# RAGZ networking retrieval summary

- Mode: `q1_rerank-off_cache-warm`
- Queries: `24` × `1` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.436667`
- nDCG@5: `0.476778`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `18.403` / `21.378` / `23.990` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| vector_search | 8.579 | 8.351 | 10.016 | 45.1% |
| no_answer_probe | 5.020 | 4.905 | 5.966 | 26.4% |
| collection_ready | 1.916 | 1.664 | 2.588 | 10.1% |
| workspace_model_resolution | 1.232 | 1.129 | 1.801 | 6.5% |
| authorization_prefilter | 0.874 | 0.827 | 1.285 | 4.6% |
| authorization_recheck | 0.679 | 0.635 | 1.013 | 3.6% |
| sparse_embedding | 0.232 | 0.216 | 0.312 | 1.2% |
| database_release | 0.222 | 0.175 | 0.407 | 1.2% |
| unattributed_runner | 0.182 | 0.180 | 0.228 | 1.0% |
| candidate_decode | 0.027 | 0.022 | 0.042 | 0.1% |
| dense_embedding | 0.015 | 0.012 | 0.022 | 0.1% |
| embedding_cache_lookup | 0.013 | 0.010 | 0.019 | 0.1% |
| embedder_resolution | 0.008 | 0.007 | 0.012 | 0.0% |
| candidate_dedupe | 0.005 | 0.004 | 0.008 | 0.0% |
| query_expansion | 0.000 | 0.000 | 0.001 | 0.0% |
| embedding_usage_record | 0.000 | 0.000 | 0.001 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
