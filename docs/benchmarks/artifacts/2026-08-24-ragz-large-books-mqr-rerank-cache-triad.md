# RAGZ large-books MQR/rerank/cache/RAG-Triad analysis

| Condition | Recall@5 | MRR@5 | nDCG@5 | Context rel. | Grounded | Answer rel. | Retrieval p95* |
|---|---:|---:|---:|---:|---:|---:|---:|
| q1_rerank-off_cache-off | 0.6000 | 0.4767 | 0.5074 | 0.8910 | 0.9755 | 0.8475 | 1188.25 ms |
| q1_rerank-10_cache-off | 0.4500 | 0.4000 | 0.4131 | 0.9195 | 0.9720 | 0.8560 | 1626.73 ms |
| q1_rerank-20_cache-off | 0.5500 | 0.4600 | 0.4824 | 0.9605 | 0.8820 | 0.7995 | 1661.23 ms |
| q1_rerank-50_cache-off | 0.5500 | 0.4917 | 0.5065 | 0.8835 | 0.9570 | 0.8110 | 1894.29 ms |
| q3_rerank-off_cache-off | 0.6000 | 0.4642 | 0.4974 | 0.9175 | 0.9535 | 0.8030 | 1612.95 ms |
| q3_rerank-10_cache-off | 0.5500 | 0.4600 | 0.4824 | 0.8960 | 0.8850 | 0.8400 | 2026.98 ms |
| q3_rerank-20_cache-off | 0.5000 | 0.4500 | 0.4631 | 0.8770 | 0.9720 | 0.7725 | 1832.80 ms |
| q3_rerank-50_cache-off | 0.5500 | 0.4917 | 0.5065 | 0.9065 | 0.9250 | 0.8540 | 2010.90 ms |
| q5_rerank-off_cache-off | 0.5500 | 0.4517 | 0.4759 | 0.8105 | 0.9670 | 0.7630 | 1298.69 ms |
| q5_rerank-10_cache-off | 0.6000 | 0.4700 | 0.5018 | 0.9220 | 0.9280 | 0.8190 | 2544.96 ms |
| q5_rerank-20_cache-off | 0.5000 | 0.4500 | 0.4631 | 0.9070 | 0.9515 | 0.8120 | 1872.42 ms |
| q5_rerank-50_cache-off | 0.5000 | 0.4750 | 0.4815 | 0.9510 | 0.9660 | 0.8210 | 2164.79 ms |

\* Retrieval p95 excludes only the benchmark account-rate wait; it retains OpenAI embedding, Cohere provider, Qdrant, database and local work.

Pareto conditions: `q1_rerank-off_cache-off`, `q1_rerank-50_cache-off`

## Query embedding cache

| Query lanes | Cache off mean | Cold population mean | Warm-hit mean | Speedup |
|---:|---:|---:|---:|---:|
| 1 | 678.47 ms | 723.10 ms | 19.00 ms | 35.70x |
| 3 | 940.83 ms | 932.89 ms | 42.80 ms | 21.98x |
| 5 | 928.84 ms | 1052.51 ms | 54.78 ms | 16.96x |
