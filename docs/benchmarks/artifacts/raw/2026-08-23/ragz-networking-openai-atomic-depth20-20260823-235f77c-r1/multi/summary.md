# RAGZ networking retrieval summary

- Mode: `multi`
- Queries: `15` × `3` repetitions
- Recall@20: `0.484362`
- MRR@20: `0.777778`
- nDCG@20: `0.535188`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `502.894` / `521.998` / `529.561` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 418.278 | 451.089 | 464.240 | 88.4% |
| vector_search | 24.865 | 24.576 | 31.656 | 5.3% |
| no_answer_probe | 14.293 | 13.860 | 17.889 | 3.0% |
| authorization_prefilter | 4.648 | 4.663 | 6.189 | 1.0% |
| workspace_model_resolution | 3.446 | 3.498 | 4.228 | 0.7% |
| collection_ready | 3.247 | 3.175 | 4.099 | 0.7% |
| authorization_recheck | 1.507 | 1.536 | 1.822 | 0.3% |
| database_release | 1.345 | 1.303 | 2.010 | 0.3% |
| unattributed_runner | 0.480 | 0.511 | 0.617 | 0.1% |
| sparse_embedding | 0.464 | 0.485 | 0.569 | 0.1% |
| query_expansion | 0.158 | 0.178 | 0.196 | 0.0% |
| embedding_usage_record | 0.110 | 0.094 | 0.151 | 0.0% |
| candidate_decode | 0.079 | 0.087 | 0.106 | 0.0% |
| candidate_dedupe | 0.020 | 0.021 | 0.026 | 0.0% |
| embedder_resolution | 0.010 | 0.010 | 0.014 | 0.0% |
