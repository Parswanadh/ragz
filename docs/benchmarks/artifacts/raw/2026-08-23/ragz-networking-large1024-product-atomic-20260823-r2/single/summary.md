# RAGZ networking retrieval summary

- Mode: `single`
- Queries: `15` × `7` repetitions
- Recall@5: `0.257317`
- MRR@5: `0.861111`
- nDCG@5: `0.556765`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `337.616` / `467.475` / `717.035` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 325.374 | 311.339 | 433.596 | 92.5% |
| vector_search | 8.750 | 7.972 | 13.892 | 2.5% |
| no_answer_probe | 5.630 | 5.607 | 6.909 | 1.6% |
| authorization_prefilter | 3.968 | 4.011 | 5.172 | 1.1% |
| collection_ready | 2.707 | 2.743 | 3.339 | 0.8% |
| workspace_model_resolution | 2.142 | 2.169 | 2.688 | 0.6% |
| database_release | 1.259 | 1.267 | 1.506 | 0.4% |
| authorization_recheck | 1.210 | 1.209 | 1.591 | 0.3% |
| sparse_embedding | 0.329 | 0.301 | 0.481 | 0.1% |
| unattributed_runner | 0.228 | 0.227 | 0.298 | 0.1% |
| embedding_usage_record | 0.090 | 0.080 | 0.133 | 0.0% |
| candidate_decode | 0.030 | 0.035 | 0.040 | 0.0% |
| embedder_resolution | 0.010 | 0.009 | 0.014 | 0.0% |
| candidate_dedupe | 0.007 | 0.007 | 0.009 | 0.0% |
| query_expansion | 0.000 | 0.000 | 0.001 | 0.0% |
