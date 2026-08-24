# RAGZ networking retrieval summary

- Mode: `q3_rerank-off_cache-warm`
- Queries: `24` × `1` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.464167`
- nDCG@5: `0.497423`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `43.053` / `49.136` / `49.950` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| vector_search | 22.631 | 22.697 | 25.996 | 52.9% |
| no_answer_probe | 11.793 | 11.512 | 14.875 | 27.6% |
| collection_ready | 2.480 | 2.462 | 3.564 | 5.8% |
| workspace_model_resolution | 2.255 | 1.982 | 3.118 | 5.3% |
| authorization_prefilter | 1.360 | 1.474 | 1.767 | 3.2% |
| authorization_recheck | 1.030 | 0.982 | 1.367 | 2.4% |
| sparse_embedding | 0.450 | 0.478 | 0.566 | 1.1% |
| unattributed_runner | 0.317 | 0.309 | 0.453 | 0.7% |
| database_release | 0.268 | 0.205 | 0.427 | 0.6% |
| query_expansion | 0.129 | 0.104 | 0.184 | 0.3% |
| candidate_decode | 0.033 | 0.026 | 0.047 | 0.1% |
| embedding_cache_lookup | 0.025 | 0.020 | 0.040 | 0.1% |
| dense_embedding | 0.014 | 0.012 | 0.020 | 0.0% |
| embedder_resolution | 0.009 | 0.008 | 0.013 | 0.0% |
| candidate_dedupe | 0.007 | 0.006 | 0.011 | 0.0% |
| embedding_usage_record | 0.000 | 0.000 | 0.001 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
