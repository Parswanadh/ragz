# Open Manuals clean embedding pair analysis

Large 1024 minus small 1024; no-cache publication pair.

- Quality population: 60 answerable queries; abstention_correct uses all 70; citation_validity excludes answers with no citations; latency population: 70 queries.
- Triad/citation/retrieval quality metrics are answerable-only; abstention_correct and latency metrics use all 70 clean queries.
- Section-level qrels are unavailable; document/chunk hits are not promoted to section evidence.

## Actual provider cost

Large-minus-small premium: `0.02378513` USD (`10.28%`).

## Stage shares

| Condition | Stage | Mean ms | Share of total mean | N |
|---|---|---:|---:|---:|
| large | context_select_or_dense_retrieval | 403.5189 | 0.0772 | 70 |
| large | generation_provider | 3150.0074 | 0.6025 | 70 |
| large | generation_total | 3150.1929 | n/a | 70 |
| large | judge_provider | 1674.5926 | 0.3203 | 70 |
| large | judge_total | 1674.7919 | n/a | 70 |
| large | postprocess | 0.0432 | 0.0000 | 70 |
| small | context_select_or_dense_retrieval | 387.5327 | 0.0726 | 70 |
| small | generation_provider | 3280.6084 | 0.6150 | 70 |
| small | generation_total | 3280.7899 | n/a | 70 |
| small | judge_provider | 1666.0527 | 0.3123 | 70 |
| small | judge_total | 1666.2531 | n/a | 70 |
| small | postprocess | 0.0408 | 0.0000 | 70 |

## Paired quality and latency inference

| Metric | Population | N | Large-small mean delta | 95% bootstrap CI | W/T/L | Sign-flip p | Holm p |
|---|---|---:|---:|---|---:|---:|---:|
| judge.context_relevance | answerable_only | 60 | 0.014333 | [-0.00033, 0.04067] | 17/31/12 | 0.149099 | 1.000000 |
| judge.groundedness | answerable_only | 60 | 0.002500 | [-0.00133, 0.00667] | 21/24/15 | 0.266587 | 1.000000 |
| judge.answer_relevance | answerable_only | 60 | 0.025000 | [0.00000, 0.06267] | 14/37/9 | 0.100979 | 1.000000 |
| judge.correctness | answerable_only | 60 | 0.024000 | [0.00283, 0.05883] | 20/29/11 | 0.024350 | 0.438296 |
| judge.citation_entailment | answerable_only | 60 | 0.003167 | [-0.00083, 0.00783] | 17/31/12 | 0.193588 | 1.000000 |
| judge.citation_precision | answerable_only | 60 | -0.009167 | [-0.03433, 0.01367] | 18/27/15 | 0.496705 | 1.000000 |
| judge.citation_completeness | answerable_only | 60 | 0.014833 | [-0.01883, 0.05500] | 18/23/19 | 0.511405 | 1.000000 |
| metrics.abstention_correct | all_70_queries | 70 | 0.000000 | [-0.04286, 0.04286] | 1/68/1 | 1.000000 | 1.000000 |
| metrics.citation_document_coverage | answerable_only | 60 | 0.000000 | [-0.05000, 0.05000] | 1/58/1 | 1.000000 | 1.000000 |
| metrics.citation_evidence_coverage | answerable_only | 60 | 0.000000 | [-0.05000, 0.05000] | 1/58/1 | 1.000000 | 1.000000 |
| metrics.citation_validity | answerable_queries_with_citations_in_both_conditions | 59 | 0.000000 | [0.00000, 0.00000] | 0/59/0 | 1.000000 | 1.000000 |
| metrics.invalid_citation_rate | answerable_only | 60 | 0.000000 | [0.00000, 0.00000] | 0/60/0 | 1.000000 | 1.000000 |
| metrics.retrieval_required_document_coverage | answerable_only | 60 | 0.008333 | [0.00000, 0.02500] | 1/59/0 | 1.000000 | 1.000000 |
| metrics.valid_citation_count | answerable_only | 60 | -0.050000 | [-0.20000, 0.10000] | 7/42/11 | 0.666993 | 1.000000 |
| timings_ms.context_select_or_dense_retrieval | all_70_queries | 70 | 15.986130 | [-7.89572, 40.21822] | 30/0/40 | 0.205238 | 1.000000 |
| timings_ms.generation_provider | all_70_queries | 70 | -130.600974 | [-604.84397, 206.19517] | 33/0/37 | 0.724253 | 1.000000 |
| timings_ms.judge_provider | all_70_queries | 70 | 8.539960 | [-93.78844, 111.76328] | 35/0/35 | 0.870621 | 1.000000 |
| timings_ms.total_with_judge | all_70_queries | 70 | -106.043989 | [-593.95465, 244.40792] | 33/0/37 | 0.779912 | 1.000000 |
