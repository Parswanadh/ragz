# RAGZ networking retrieval summary

- Mode: `multi`
- Queries: `15` × `7` repetitions
- Recall@5: `0.242248`
- MRR@5: `0.916667`
- nDCG@5: `0.561232`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `507.479` / `536.827` / `546.374` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 438.783 | 468.490 | 493.102 | 91.6% |
| vector_search | 15.202 | 14.730 | 18.226 | 3.2% |
| no_answer_probe | 11.447 | 10.741 | 17.626 | 2.4% |
| authorization_prefilter | 4.026 | 3.932 | 5.406 | 0.8% |
| workspace_model_resolution | 3.199 | 3.177 | 3.951 | 0.7% |
| collection_ready | 2.867 | 2.900 | 3.591 | 0.6% |
| authorization_recheck | 1.403 | 1.457 | 1.738 | 0.3% |
| database_release | 1.194 | 1.167 | 1.472 | 0.2% |
| sparse_embedding | 0.426 | 0.419 | 0.563 | 0.1% |
| unattributed_runner | 0.363 | 0.368 | 0.500 | 0.1% |
| query_expansion | 0.142 | 0.158 | 0.181 | 0.0% |
| embedding_usage_record | 0.106 | 0.120 | 0.137 | 0.0% |
| candidate_decode | 0.034 | 0.039 | 0.043 | 0.0% |
| embedder_resolution | 0.010 | 0.010 | 0.015 | 0.0% |
| candidate_dedupe | 0.007 | 0.008 | 0.009 | 0.0% |
