# RAGZ networking retrieval summary

- Mode: `q3_rerank-10_cache-off`
- Queries: `24` × `1` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.533333`
- nDCG@5: `0.550791`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `6655.842` / `20091.184` / `31871.729` ms
- Errors: `5`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| rerank | 6616.245 | 5587.849 | 18881.929 | 85.9% |
| dense_embedding | 1047.400 | 1027.203 | 1133.496 | 13.6% |
| vector_search | 21.978 | 21.257 | 25.117 | 0.3% |
| workspace_model_resolution | 3.886 | 3.793 | 5.956 | 0.1% |
| authorization_prefilter | 3.397 | 3.226 | 5.862 | 0.0% |
| collection_ready | 3.167 | 3.362 | 4.345 | 0.0% |
| authorization_recheck | 1.466 | 1.163 | 2.413 | 0.0% |
| database_release | 0.831 | 0.786 | 1.251 | 0.0% |
| sparse_embedding | 0.664 | 0.670 | 0.882 | 0.0% |
| unattributed_runner | 0.546 | 0.520 | 0.749 | 0.0% |
| query_expansion | 0.150 | 0.161 | 0.224 | 0.0% |
| embedding_usage_record | 0.101 | 0.092 | 0.131 | 0.0% |
| candidate_decode | 0.049 | 0.036 | 0.079 | 0.0% |
| embedder_resolution | 0.010 | 0.010 | 0.014 | 0.0% |
| candidate_dedupe | 0.010 | 0.009 | 0.014 | 0.0% |
| reranker_resolution | 0.002 | 0.002 | 0.003 | 0.0% |
| embedding_cache_lookup | 0.001 | 0.001 | 0.002 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
