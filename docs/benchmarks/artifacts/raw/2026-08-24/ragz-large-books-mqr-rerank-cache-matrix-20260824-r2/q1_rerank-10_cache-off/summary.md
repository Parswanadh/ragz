# RAGZ networking retrieval summary

- Mode: `q1_rerank-10_cache-off`
- Queries: `24` × `1` repetitions
- Recall@5: `0.450000`
- MRR@5: `0.425000`
- nDCG@5: `0.431546`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `6656.597` / `6802.601` / `6828.842` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| rerank | 5670.085 | 5905.821 | 6021.558 | 87.9% |
| dense_embedding | 755.128 | 726.497 | 817.325 | 11.7% |
| vector_search | 11.146 | 10.840 | 13.040 | 0.2% |
| authorization_prefilter | 3.782 | 2.729 | 4.813 | 0.1% |
| collection_ready | 3.068 | 3.063 | 4.126 | 0.0% |
| workspace_model_resolution | 2.778 | 2.681 | 4.492 | 0.0% |
| database_release | 1.886 | 0.860 | 8.673 | 0.0% |
| authorization_recheck | 0.901 | 0.773 | 1.307 | 0.0% |
| sparse_embedding | 0.442 | 0.410 | 0.597 | 0.0% |
| unattributed_runner | 0.415 | 0.403 | 0.510 | 0.0% |
| embedding_usage_record | 0.109 | 0.116 | 0.149 | 0.0% |
| candidate_decode | 0.043 | 0.034 | 0.066 | 0.0% |
| embedder_resolution | 0.010 | 0.011 | 0.016 | 0.0% |
| candidate_dedupe | 0.008 | 0.008 | 0.012 | 0.0% |
| reranker_resolution | 0.002 | 0.002 | 0.003 | 0.0% |
| embedding_cache_lookup | 0.001 | 0.001 | 0.002 | 0.0% |
| query_expansion | 0.000 | 0.001 | 0.001 | 0.0% |
| embedding_cache_store | 0.000 | 0.001 | 0.001 | 0.0% |
