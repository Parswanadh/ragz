# RAGZ networking retrieval summary

- Mode: `q1_rerank-off_cache-off`
- Queries: `24` × `2` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.451667`
- nDCG@5: `0.488982`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `773.155` / `825.037` / `850.222` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 697.458 | 747.895 | 796.635 | 96.2% |
| vector_search | 10.516 | 10.618 | 12.451 | 1.5% |
| no_answer_probe | 5.911 | 5.820 | 7.257 | 0.8% |
| authorization_prefilter | 3.064 | 2.961 | 5.242 | 0.4% |
| collection_ready | 2.452 | 2.420 | 3.262 | 0.3% |
| authorization_recheck | 1.673 | 1.034 | 5.644 | 0.2% |
| workspace_model_resolution | 1.486 | 1.505 | 2.077 | 0.2% |
| database_release | 1.276 | 1.062 | 1.555 | 0.2% |
| sparse_embedding | 0.453 | 0.449 | 0.632 | 0.1% |
| unattributed_runner | 0.267 | 0.255 | 0.354 | 0.0% |
| embedding_usage_record | 0.113 | 0.116 | 0.151 | 0.0% |
| candidate_decode | 0.034 | 0.026 | 0.062 | 0.0% |
| embedder_resolution | 0.009 | 0.009 | 0.013 | 0.0% |
| candidate_dedupe | 0.007 | 0.006 | 0.011 | 0.0% |
| embedding_cache_lookup | 0.001 | 0.001 | 0.001 | 0.0% |
| query_expansion | 0.000 | 0.001 | 0.001 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
