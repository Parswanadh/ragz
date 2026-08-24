# RAGZ networking retrieval summary

- Mode: `q3_rerank-20_cache-off`
- Queries: `24` × `1` repetitions
- Recall@5: `0.500000`
- MRR@5: `0.450000`
- nDCG@5: `0.463093`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `6655.840` / `6857.064` / `6943.209` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| rerank | 5569.961 | 5592.011 | 5842.688 | 83.5% |
| dense_embedding | 1061.773 | 1026.112 | 1218.194 | 15.9% |
| vector_search | 23.598 | 23.539 | 27.172 | 0.4% |
| workspace_model_resolution | 3.854 | 3.854 | 5.744 | 0.1% |
| collection_ready | 3.284 | 3.251 | 4.516 | 0.0% |
| authorization_prefilter | 3.037 | 3.047 | 4.647 | 0.0% |
| database_release | 1.445 | 0.757 | 1.287 | 0.0% |
| authorization_recheck | 1.051 | 1.060 | 1.438 | 0.0% |
| sparse_embedding | 0.612 | 0.602 | 0.808 | 0.0% |
| unattributed_runner | 0.568 | 0.575 | 0.697 | 0.0% |
| candidate_decode | 0.328 | 0.059 | 0.116 | 0.0% |
| query_expansion | 0.170 | 0.170 | 0.289 | 0.0% |
| embedding_usage_record | 0.103 | 0.099 | 0.132 | 0.0% |
| candidate_dedupe | 0.014 | 0.013 | 0.019 | 0.0% |
| embedder_resolution | 0.010 | 0.011 | 0.014 | 0.0% |
| reranker_resolution | 0.002 | 0.002 | 0.003 | 0.0% |
| embedding_cache_lookup | 0.001 | 0.001 | 0.002 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
