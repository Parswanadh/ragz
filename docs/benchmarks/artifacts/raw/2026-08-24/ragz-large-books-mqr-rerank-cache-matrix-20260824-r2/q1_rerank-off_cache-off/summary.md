# RAGZ networking retrieval summary

- Mode: `q1_rerank-off_cache-off`
- Queries: `24` × `1` repetitions
- Recall@5: `0.600000`
- MRR@5: `0.461667`
- nDCG@5: `0.495232`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `720.146` / `826.965` / `831.927` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 647.638 | 693.298 | 798.286 | 95.5% |
| vector_search | 11.729 | 10.849 | 15.232 | 1.7% |
| no_answer_probe | 5.917 | 5.841 | 7.061 | 0.9% |
| unattributed_runner | 4.030 | 0.242 | 0.366 | 0.6% |
| authorization_prefilter | 2.655 | 2.488 | 4.228 | 0.4% |
| collection_ready | 2.587 | 1.944 | 3.566 | 0.4% |
| workspace_model_resolution | 1.510 | 1.359 | 2.049 | 0.2% |
| database_release | 0.930 | 0.790 | 1.530 | 0.1% |
| authorization_recheck | 0.879 | 0.828 | 1.290 | 0.1% |
| sparse_embedding | 0.438 | 0.454 | 0.595 | 0.1% |
| embedding_usage_record | 0.106 | 0.097 | 0.145 | 0.0% |
| candidate_decode | 0.031 | 0.028 | 0.045 | 0.0% |
| embedder_resolution | 0.009 | 0.008 | 0.012 | 0.0% |
| candidate_dedupe | 0.006 | 0.006 | 0.009 | 0.0% |
| embedding_cache_lookup | 0.001 | 0.001 | 0.001 | 0.0% |
| query_expansion | 0.000 | 0.000 | 0.001 | 0.0% |
| embedding_cache_store | 0.000 | 0.000 | 0.001 | 0.0% |
