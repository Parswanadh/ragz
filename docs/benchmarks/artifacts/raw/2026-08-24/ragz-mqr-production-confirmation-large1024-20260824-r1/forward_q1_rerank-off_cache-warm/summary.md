# RAGZ networking retrieval summary

- Mode: `forward_q1_rerank-off_cache-warm`
- Queries: `24` × `5` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.451667`
- nDCG@5: `0.488982`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `16.568` / `20.427` / `21.875` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| vector_search | 11.087 | 10.857 | 13.099 | 65.6% |
| no_answer_probe | 7.247 | 7.075 | 8.554 | 42.9% |
| collection_ready | 2.018 | 1.910 | 2.717 | 11.9% |
| workspace_model_resolution | 1.158 | 1.038 | 1.727 | 6.9% |
| authorization_prefilter | 0.944 | 0.859 | 1.485 | 5.6% |
| authorization_recheck | 0.916 | 0.833 | 1.248 | 5.4% |
| sparse_embedding | 0.228 | 0.215 | 0.316 | 1.3% |
| database_release | 0.220 | 0.187 | 0.340 | 1.3% |
| candidate_decode | 0.042 | 0.035 | 0.063 | 0.2% |
| embedding_cache_lookup | 0.023 | 0.021 | 0.037 | 0.1% |
| dense_embedding | 0.009 | 0.008 | 0.015 | 0.1% |
| embedder_resolution | 0.008 | 0.007 | 0.012 | 0.0% |
| candidate_dedupe | 0.006 | 0.005 | 0.009 | 0.0% |
| embedding_usage_record | 0.000 | 0.000 | 0.001 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
| unattributed_runner | 0.000 | 0.000 | 0.000 | 0.0% |
