# Open Manuals embedding matrix analysis

Privacy-safe post-processing of ten completed 70-query cells.

- Section evidence: unavailable; document/chunk hit is not treated as section evidence.
- Cached and uncached totals are reported separately and never pooled for comparable latency.
- Observed provider spend is descriptive only and is not used to compare cells or rank the Pareto frontier.
- RAG Triad components are primary; the arithmetic composite is explicitly secondary.

## Cell summary

| Cell | Dimension | Triad context | Groundedness | Answer relevance | Fresh retrieval p95 (ms) | N | Observed cost (USD; descriptive) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `openai-text-embedding-3-large-d1024` | 1024 | 0.8677 | 0.9811 | 0.9874 | 541.5866 | 70 | 0.13570619 |
| `openai-text-embedding-3-large-d1280` | 1280 | 0.8630 | 0.9696 | 0.9840 | 571.3358 | 70 | 0.05328019 |
| `openai-text-embedding-3-large-d1536` | 1536 | 0.8651 | 0.9687 | 0.9836 | 647.4678 | 70 | 0.09408019 |
| `openai-text-embedding-3-large-d1792` | 1792 | 0.8664 | 0.9763 | 0.9853 | 611.2476 | 70 | 0.04483439 |
| `openai-text-embedding-3-large-d2048` | 2048 | 0.8720 | 0.9736 | 0.9854 | 789.9604 | 70 | 0.03529039 |
| `openai-text-embedding-3-large-d2096` | 2096 | 0.8711 | 0.9773 | 0.9847 | 694.6605 | 70 | 0.07024419 |
| `openai-text-embedding-3-large-d3072` | 3072 | 0.8691 | 0.9886 | 0.9851 | 767.8658 | 70 | 0.06231479 |
| `openai-text-embedding-3-small-d1024` | 1024 | 0.8403 | 0.9873 | 0.9656 | 488.9393 | 70 | 0.11709106 |
| `openai-text-embedding-3-small-d1280` | 1280 | 0.8387 | 0.9806 | 0.9680 | 578.5624 | 70 | 0.04268686 |
| `openai-text-embedding-3-small-d1536` | 1536 | 0.8409 | 0.9814 | 0.9704 | 593.9996 | 70 | 0.07953726 |

## Pareto frontier

The frontier maximizes the clearly labeled secondary self-judge Triad composite while minimizing fresh uncached retrieval p95. Provider spend and total answer latency are excluded because cache state is not cross-cell comparable.

| Cell | Secondary self-judge Triad composite | Fresh retrieval p95 (ms) | N |
|---|---:|---:|---:|
| `openai-text-embedding-3-large-d1024` | 0.9874 | 541.5866 | 70 |
| `openai-text-embedding-3-large-d2096` | 0.9881 | 694.6605 | 70 |
| `openai-text-embedding-3-large-d3072` | 0.9888 | 767.8658 | 70 |
| `openai-text-embedding-3-small-d1024` | 0.9703 | 488.9393 | 70 |

## Paired inference

Each non-baseline cell is paired query-by-query with `openai-text-embedding-3-small-d1024`; intervals are 10,000-resample query bootstraps, p-values are seeded sign-flip tests, and Holm correction spans all listed hypotheses. Because this matrix contains cache-contaminated cells, total/generation/judge latency hypotheses are excluded; uncached stage summaries are descriptive with their N.

| Cell | Metric | N | Mean delta | 95% CI | W/T/L | Sign-flip p | Holm p |
|---|---|---:|---:|---|---:|---:|---:|
| `openai-text-embedding-3-large-d1024` | context_relevance | 60 | 0.024666666666666667 | [0.0032, 0.0577] | 17/36/7 | 0.021398 | 0.577742 |
| `openai-text-embedding-3-large-d1024` | groundedness | 60 | 0.0010000000000000009 | [-0.0042, 0.0060] | 11/42/7 | 0.751125 | 1.000000 |
| `openai-text-embedding-3-large-d1024` | answer_relevance | 60 | 0.025666666666666667 | [0.0025, 0.0575] | 8/50/2 | 0.076592 | 1.000000 |
| `openai-text-embedding-3-large-d1024` | context_select_or_dense_retrieval | 70 | 6.5883085714285725 | [-26.4357, 40.0489] | 33/0/37 | 0.710129 | 1.000000 |
| `openai-text-embedding-3-large-d1280` | context_relevance | 60 | 0.019000000000000003 | [-0.0037, 0.0523] | 17/33/10 | 0.197180 | 1.000000 |
| `openai-text-embedding-3-large-d1280` | groundedness | 60 | -0.0003333333333333318 | [-0.0073, 0.0057] | 11/43/6 | 0.968403 | 1.000000 |
| `openai-text-embedding-3-large-d1280` | answer_relevance | 60 | 0.021833333333333333 | [0.0017, 0.0517] | 6/49/5 | 0.120988 | 1.000000 |
| `openai-text-embedding-3-large-d1280` | context_select_or_dense_retrieval | 70 | 31.117520000000006 | [-0.2981, 59.5120] | 24/0/46 | 0.049795 | 1.000000 |
| `openai-text-embedding-3-large-d1536` | context_relevance | 60 | 0.024333333333333335 | [0.0018, 0.0570] | 19/33/8 | 0.055994 | 1.000000 |
| `openai-text-embedding-3-large-d1536` | groundedness | 60 | 0.0011666666666666676 | [-0.0037, 0.0060] | 10/43/7 | 0.686231 | 1.000000 |
| `openai-text-embedding-3-large-d1536` | answer_relevance | 60 | 0.021 | [0.0007, 0.0517] | 6/49/5 | 0.116888 | 1.000000 |
| `openai-text-embedding-3-large-d1536` | context_select_or_dense_retrieval | 70 | 53.93219714285715 | [20.7429, 87.8252] | 16/0/54 | 0.002100 | 0.067193 |
| `openai-text-embedding-3-large-d1792` | context_relevance | 60 | 0.02616666666666667 | [0.0010, 0.0622] | 18/33/9 | 0.069793 | 1.000000 |
| `openai-text-embedding-3-large-d1792` | groundedness | 60 | -0.0024999999999999983 | [-0.0108, 0.0048] | 10/43/7 | 0.591241 | 1.000000 |
| `openai-text-embedding-3-large-d1792` | answer_relevance | 60 | 0.023 | [0.0010, 0.0547] | 6/49/5 | 0.118888 | 1.000000 |
| `openai-text-embedding-3-large-d1792` | context_select_or_dense_retrieval | 70 | 46.96537000000001 | [18.3500, 72.6492] | 20/0/50 | 0.000700 | 0.023098 |
| `openai-text-embedding-3-large-d2048` | context_relevance | 60 | 0.02866666666666667 | [0.0038, 0.0648] | 19/33/8 | 0.020298 | 0.568343 |
| `openai-text-embedding-3-large-d2048` | groundedness | 60 | 0.0006666666666666673 | [-0.0065, 0.0065] | 12/41/7 | 0.892111 | 1.000000 |
| `openai-text-embedding-3-large-d2048` | answer_relevance | 60 | 0.023666666666666666 | [0.0020, 0.0555] | 6/50/4 | 0.114189 | 1.000000 |
| `openai-text-embedding-3-large-d2048` | context_select_or_dense_retrieval | 70 | 124.60153571428572 | [89.0959, 160.4379] | 7/0/63 | 0.000100 | 0.003600 |
| `openai-text-embedding-3-large-d2096` | context_relevance | 60 | 0.029166666666666667 | [0.0065, 0.0637] | 19/35/6 | 0.003000 | 0.092991 |
| `openai-text-embedding-3-large-d2096` | groundedness | 60 | 0.0013333333333333346 | [-0.0050, 0.0070] | 14/40/6 | 0.703130 | 1.000000 |
| `openai-text-embedding-3-large-d2096` | answer_relevance | 60 | 0.02266666666666667 | [0.0023, 0.0538] | 8/49/3 | 0.074293 | 1.000000 |
| `openai-text-embedding-3-large-d2096` | context_select_or_dense_retrieval | 70 | 114.91400142857144 | [80.7783, 147.8649] | 9/0/61 | 0.000100 | 0.003600 |
| `openai-text-embedding-3-large-d3072` | context_relevance | 60 | 0.029333333333333336 | [0.0048, 0.0652] | 21/31/8 | 0.014099 | 0.408859 |
| `openai-text-embedding-3-large-d3072` | groundedness | 60 | 0.001833333333333335 | [-0.0035, 0.0070] | 14/39/7 | 0.511149 | 1.000000 |
| `openai-text-embedding-3-large-d3072` | answer_relevance | 60 | 0.024333333333333332 | [0.0020, 0.0563] | 7/48/5 | 0.100090 | 1.000000 |
| `openai-text-embedding-3-large-d3072` | context_select_or_dense_retrieval | 70 | 208.54405428571428 | [175.5373, 237.7965] | 2/0/68 | 0.000100 | 0.003600 |
| `openai-text-embedding-3-small-d1280` | context_relevance | 60 | 0.0006666666666666677 | [-0.0068, 0.0070] | 9/44/7 | 0.870213 | 1.000000 |
| `openai-text-embedding-3-small-d1280` | groundedness | 60 | 0.0016666666666666663 | [-0.0005, 0.0043] | 7/50/3 | 0.276572 | 1.000000 |
| `openai-text-embedding-3-small-d1280` | answer_relevance | 60 | 0.002833333333333333 | [-0.0017, 0.0102] | 2/56/2 | 0.745325 | 1.000000 |
| `openai-text-embedding-3-small-d1280` | context_select_or_dense_retrieval | 70 | 18.755845714285716 | [-16.7504, 52.9209] | 32/0/38 | 0.309069 | 1.000000 |
| `openai-text-embedding-3-small-d1536` | context_relevance | 60 | 0.0003333333333333353 | [-0.0088, 0.0100] | 10/40/10 | 0.948205 | 1.000000 |
| `openai-text-embedding-3-small-d1536` | groundedness | 60 | 0.001833333333333333 | [-0.0012, 0.0050] | 9/47/4 | 0.314069 | 1.000000 |
| `openai-text-embedding-3-small-d1536` | answer_relevance | 60 | 0.005 | [-0.0007, 0.0137] | 5/51/4 | 0.355864 | 1.000000 |
| `openai-text-embedding-3-small-d1536` | context_select_or_dense_retrieval | 70 | 49.86989428571429 | [14.7906, 85.7803] | 18/0/52 | 0.005199 | 0.155984 |
