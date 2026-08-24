# RAGZ production MQR/cache confirmation

| Cell | Recall@5 | MRR@5 | nDCG@5 | Mean ms | p50 ms | p95 ms | Stable groups |
|---|---:|---:|---:|---:|---:|---:|---:|
| Q1 cache-off | 0.6000 | 0.4517 | 0.4890 | 728.49 | 718.45 | 913.52 | 33/48 |
| Q1 cache-warm | 0.6000 | 0.4517 | 0.4890 | 16.93 | 16.68 | 19.68 | 33/48 |
| Q3 cache-off | 0.6000 | 0.4475 | 0.4855 | 1385.00 | 1440.66 | 1639.51 | 48/48 |
| Q3 cache-warm | 0.6000 | 0.4475 | 0.4855 | 33.76 | 33.16 | 39.33 | 48/48 |

Vector search and the dense no-answer probe overlap; request elapsed time is authoritative and the parallel group's critical duration is their maximum, not sum.
