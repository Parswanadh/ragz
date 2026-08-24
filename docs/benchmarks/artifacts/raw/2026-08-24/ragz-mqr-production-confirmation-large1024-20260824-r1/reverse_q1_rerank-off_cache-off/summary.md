# RAGZ networking retrieval summary

- Mode: `reverse_q1_rerank-off_cache-off`
- Queries: `24` × `5` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.451667`
- nDCG@5: `0.488982`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `726.023` / `1252.639` / `1331.294` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 735.101 | 701.043 | 1231.257 | 96.9% |
| vector_search | 13.210 | 12.591 | 16.827 | 1.7% |
| no_answer_probe | 8.558 | 7.936 | 12.580 | 1.1% |
| authorization_prefilter | 3.130 | 2.730 | 6.167 | 0.4% |
| collection_ready | 2.181 | 2.058 | 3.108 | 0.3% |
| database_release | 1.407 | 1.313 | 1.772 | 0.2% |
| workspace_model_resolution | 1.313 | 1.179 | 2.089 | 0.2% |
| authorization_recheck | 1.075 | 1.057 | 1.510 | 0.1% |
| sparse_embedding | 0.438 | 0.409 | 0.699 | 0.1% |
| embedding_usage_record | 0.109 | 0.112 | 0.137 | 0.0% |
| candidate_decode | 0.048 | 0.045 | 0.066 | 0.0% |
| embedder_resolution | 0.008 | 0.007 | 0.013 | 0.0% |
| candidate_dedupe | 0.006 | 0.006 | 0.009 | 0.0% |
| embedding_cache_lookup | 0.001 | 0.001 | 0.001 | 0.0% |
| embedding_cache_store | 0.000 | 0.001 | 0.001 | 0.0% |
| unattributed_runner | 0.000 | 0.000 | 0.000 | 0.0% |
