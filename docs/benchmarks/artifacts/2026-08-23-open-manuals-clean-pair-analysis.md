# Open Manuals clean embedding pair analysis

Large 1024 minus small 1024; no-cache publication pair.

- Quality population: 60 answerable queries; abstention_correct uses all 70; latency population: 70 queries.
- Triad/citation/retrieval quality metrics are answerable-only; abstention_correct and latency metrics use all 70 clean queries.
- Section-level qrels are unavailable; document/chunk hits are not promoted to section evidence.

## Actual provider cost

Large-minus-small premium: `0.02245613` USD (`21.80%`).

## Stage shares

| Condition | Stage | Mean ms | Share of total mean | N |
|---|---|---:|---:|---:|
| large | context_select_or_dense_retrieval | 443.3524 | 0.0800 | 70 |
| large | generation_provider | 3257.6432 | 0.5876 | 70 |
| large | generation_total | 3257.8276 | n/a | 70 |
| large | judge_provider | 1842.4135 | 0.3323 | 70 |
| large | judge_total | 1842.6023 | n/a | 70 |
| large | postprocess | 0.0403 | 0.0000 | 70 |
| small | context_select_or_dense_retrieval | 445.8057 | 0.0798 | 70 |
| small | generation_provider | 3330.7416 | 0.5962 | 70 |
| small | generation_total | 3330.9242 | n/a | 70 |
| small | judge_provider | 1809.2151 | 0.3239 | 70 |
| small | judge_total | 1809.3928 | n/a | 70 |
| small | postprocess | 0.0352 | 0.0000 | 70 |

## Paired quality and latency inference

| Metric | Population | N | Large-small mean delta | 95% bootstrap CI | W/T/L | Sign-flip p | Holm p |
|---|---|---:|---:|---|---:|---:|---:|
| judge.context_relevance | answerable_only | 60 | 0.026333 | [-0.00067, 0.06650] | 14/30/16 | 0.192078 | 1.000000 |
| judge.groundedness | answerable_only | 60 | -0.002500 | [-0.01850, 0.00817] | 20/24/16 | 0.903601 | 1.000000 |
| judge.answer_relevance | answerable_only | 60 | 0.019000 | [0.00117, 0.05067] | 19/30/11 | 0.031960 | 0.575274 |
| judge.correctness | answerable_only | 60 | 0.023833 | [0.00200, 0.06033] | 17/30/13 | 0.047370 | 0.805282 |
| judge.citation_entailment | answerable_only | 60 | -0.004500 | [-0.02033, 0.00567] | 15/29/16 | 0.817042 | 1.000000 |
| judge.citation_precision | answerable_only | 60 | 0.002000 | [-0.02167, 0.02650] | 23/26/11 | 0.915021 | 1.000000 |
| judge.citation_completeness | answerable_only | 60 | 0.031333 | [0.00117, 0.07300] | 22/23/15 | 0.087829 | 1.000000 |
| metrics.abstention_correct | all_70_queries | 70 | 0.014286 | [0.00000, 0.04286] | 1/69/0 | 1.000000 | 1.000000 |
| metrics.citation_document_coverage | answerable_only | 60 | 0.016667 | [-0.03333, 0.08333] | 2/57/1 | 1.000000 | 1.000000 |
| metrics.citation_evidence_coverage | answerable_only | 60 | 0.016667 | [-0.03333, 0.08333] | 2/57/1 | 1.000000 | 1.000000 |
| metrics.citation_validity | answerable_only | 58 | 0.000000 | [0.00000, 0.00000] | 0/58/0 | 1.000000 | 1.000000 |
| metrics.invalid_citation_rate | answerable_only | 60 | 0.000000 | [0.00000, 0.00000] | 0/60/0 | 1.000000 | 1.000000 |
| metrics.retrieval_required_document_coverage | answerable_only | 60 | 0.008333 | [0.00000, 0.02500] | 1/59/0 | 1.000000 | 1.000000 |
| metrics.valid_citation_count | answerable_only | 60 | 0.000000 | [-0.18333, 0.16667] | 9/43/8 | 1.000000 | 1.000000 |
| timings_ms.context_select_or_dense_retrieval | all_70_queries | 70 | -2.453307 | [-25.17393, 23.15484] | 39/0/31 | 0.845362 | 1.000000 |
| timings_ms.generation_provider | all_70_queries | 70 | -73.098381 | [-301.39905, 143.15829] | 37/0/33 | 0.525115 | 1.000000 |
| timings_ms.judge_provider | all_70_queries | 70 | 33.198337 | [-222.02051, 269.09269] | 33/0/37 | 0.805062 | 1.000000 |
| timings_ms.total_with_judge | all_70_queries | 70 | -42.337043 | [-383.52329, 282.84908] | 37/0/33 | 0.808752 | 1.000000 |
