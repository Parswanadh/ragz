# RAGZ networking retrieval summary

- Mode: `multi`
- Queries: `15` × `7` repetitions
- Recall@5: `0.242248`
- MRR@5: `0.916667`
- nDCG@5: `0.561232`
- Abstention precision/recall/F1: `not measured` / `0.000` / `not measured`
- p50/p95/p99: `399.420` / `517.152` / `576.968` ms
- Errors: `0`

## Atomic retrieval latency

| Stage | Mean ms | p50 ms | p95 ms | Mean share |
|---|---:|---:|---:|---:|
| dense_embedding | 383.052 | 356.631 | 476.863 | 90.6% |
| vector_search | 14.775 | 14.582 | 17.837 | 3.5% |
| no_answer_probe | 11.296 | 11.023 | 16.086 | 2.7% |
| authorization_prefilter | 4.218 | 4.184 | 5.797 | 1.0% |
| workspace_model_resolution | 3.117 | 3.087 | 3.930 | 0.7% |
| collection_ready | 2.743 | 2.730 | 3.491 | 0.6% |
| authorization_recheck | 1.349 | 1.325 | 1.758 | 0.3% |
| database_release | 1.211 | 1.206 | 1.468 | 0.3% |
| sparse_embedding | 0.458 | 0.467 | 0.628 | 0.1% |
| unattributed_runner | 0.360 | 0.387 | 0.486 | 0.1% |
| query_expansion | 0.138 | 0.120 | 0.188 | 0.0% |
| embedding_usage_record | 0.101 | 0.085 | 0.139 | 0.0% |
| candidate_decode | 0.034 | 0.028 | 0.049 | 0.0% |
| embedder_resolution | 0.010 | 0.010 | 0.015 | 0.0% |
| candidate_dedupe | 0.007 | 0.008 | 0.010 | 0.0% |
