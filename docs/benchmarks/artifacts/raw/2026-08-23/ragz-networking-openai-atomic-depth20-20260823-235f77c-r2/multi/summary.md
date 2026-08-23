# RAGZ networking retrieval summary

- Mode: `multi`
- Queries: `15` × `3` repetitions
- Recall@20: `0.484362`
- MRR@20: `0.777778`
- nDCG@20: `0.535188`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `528.749` / `562.640` / `575.403` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 445.617 | 475.320 | 508.998 | 89.5% |
| vector_search | 23.697 | 23.531 | 27.286 | 4.8% |
| no_answer_probe | 13.775 | 13.548 | 17.473 | 2.8% |
| authorization_prefilter | 4.331 | 4.360 | 5.364 | 0.9% |
| workspace_model_resolution | 3.342 | 3.293 | 4.275 | 0.7% |
| collection_ready | 3.151 | 3.156 | 4.135 | 0.6% |
| authorization_recheck | 1.485 | 1.528 | 1.806 | 0.3% |
| database_release | 1.331 | 1.312 | 1.547 | 0.3% |
| sparse_embedding | 0.452 | 0.493 | 0.561 | 0.1% |
| unattributed_runner | 0.445 | 0.429 | 0.616 | 0.1% |
| query_expansion | 0.160 | 0.179 | 0.217 | 0.0% |
| embedding_usage_record | 0.101 | 0.088 | 0.142 | 0.0% |
| candidate_decode | 0.077 | 0.086 | 0.101 | 0.0% |
| candidate_dedupe | 0.018 | 0.021 | 0.027 | 0.0% |
| embedder_resolution | 0.011 | 0.011 | 0.016 | 0.0% |
