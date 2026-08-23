# Professional embedding, RAG-Triad, and RAGFlow benchmark

Date: 2026-08-23

This report separates five experiments that answer different questions. It
does not merge them into a single product leaderboard.

1. A 2,000-observation OpenAI embedding endpoint matrix isolates model,
   dimension, batch size, and HTTP-client lifecycle latency.
2. A ten-cell, 700-query Open Manuals screen compares retrieval across every
   valid model/dimension cell. Its answer/judge cache and Luna self-judge make
   those answer totals exploratory only.
3. Two clean 70-query publication cells compare small and large embeddings at
   1,024 dimensions with no cache, GPT-5.6 Luna answers, and a separate
   GPT-5.4-mini judge.
4. AnythingLLM runs the selected large/1,024 cell through its native LanceDB
   retrieval path.
5. RAGFlow v0.27.0 is actually started under a 3 GB API-model-only budget and
   stopped by the resource guard before corpus benchmarking.

Raw document text, prompts, answers, provider bodies, and credentials are not
committed. The licensed/private working outputs remain outside the repository.

## Result in one sentence

`text-embedding-3-large` at 1,024 dimensions is the best measured
document-level quality/latency tradeoff, but it is **not** a safe universal
RAGZ default: the separate networking exact-page product track substantially
underperforms the existing small/1,536 baseline on Recall@5.

## Embedding matrix contract

OpenAI has no `text-embedding-3-medium` model. “Medium” below means a vector
width tier, not an invented model ID.

| Model | Tested dimensions |
|---|---|
| `text-embedding-3-small` | 1,024; 1,280; native 1,536 |
| `text-embedding-3-large` | 1,024; 1,280; 1,536; 1,792; 2,048; 2,096; native 3,072 |

Every cell uses a unique LiteLLM alias with provider-side dimensions fixed.
Ten live probes returned the exact requested width. Each real benchmark also
validates every returned vector before indexing or scoring.

## Atomic OpenAI embedding latency

The atomic run contains 2,000 scored requests and 160 excluded warmups:

- ten model/dimension cells;
- input counts 1, 3, 8, and 32;
- persistent and new-client conditions;
- 25 scored repetitions per condition;
- concurrency one and zero retries;
- zero errors, non-200 responses, width mismatches, or token mismatches;
- stage closure maximum absolute error `4.55e-13 ms`.

The following table uses the persistent-client condition. Single-input rows
represent normal single-query embedding; 32-input rows expose response-payload
and indexing-batch behavior.

| Cell | 1 input p50 / p95 | 32 inputs p50 / p95 |
|---|---:|---:|
| small / 1,024 | 313 / 403 ms | 846 / 901 ms |
| small / 1,280 | 314 / 412 ms | 819 / 973 ms |
| small / 1,536 | 298 / 433 ms | 848 / 1,049 ms |
| large / 1,024 | 302 / 455 ms | 722 / 908 ms |
| large / 1,280 | 345 / 471 ms | 873 / 1,146 ms |
| large / 1,536 | 348 / 443 ms | 1,011 / 1,158 ms |
| large / 1,792 | 297 / 394 ms | 867 / 1,083 ms |
| large / 2,048 | 283 / 388 ms | 955 / 1,140 ms |
| large / 2,096 | 342 / 391 ms | 1,000 / 1,185 ms |
| large / 3,072 | 351 / 452 ms | 1,148 / 1,674 ms |

Single-input latency is noisy and non-monotonic because provider/network time
dominates. The payload effect is much clearer at 32 inputs: large/3,072 is
about 70% slower at p50 than large/1,024. Across all conditions, HTTP wall time
accounts for more than 99% of measured embedding time; request construction,
JSON decoding, and width validation are collectively only a few milliseconds
even for the largest batches.

## Ten-cell Open Manuals screen

The licensed Open Manuals corpus has 22 Python/PostgreSQL documents and 70
queries: 60 answerable and ten off-corpus. All ten cells returned 70 unique
query IDs, five retrieved chunks per query, the requested width, and zero
errors.

This screen used a shared content-addressed answer/judge cache and Luna for
both answer and judge. Therefore:

- retrieval latency is fresh and comparable;
- cached total-answer latency and observed spend are not cross-cell metrics;
- its RAG-Triad values are explicitly self-evaluation, not independent proof;
- required-evidence hit is document-level, not exact-section evidence.

The corrected analyzer excludes answer totals and spend from its Pareto
frontier. The ten-cell result suggests large/1,024, large/2,096,
large/3,072, and small/1,024 as non-dominated retrieval/self-judge points.
No quality difference survives Holm correction. Larger dimensions from 2,048
through 3,072 have statistically supported retrieval-latency penalties versus
1,024 without a supported quality gain.

## Clean no-cache publication pair

Both cells below use:

- all 70 queries;
- no embedding, answer, or judge cache;
- `gpt-5.6-luna` answer generation;
- a separate `gpt-5.4-mini` judge;
- top five contexts from identical RAGZ page-block chunking;
- 211 successful provider calls per cell and zero failures.

| Metric | small / 1,024 | large / 1,024 | Large − small |
|---|---:|---:|---:|
| Required-document hit | 59 / 60 | 60 / 60 | +1 query |
| Context relevance (60 answerable) | 0.9618 | 0.9882 | +0.0263 |
| Groundedness (60 answerable) | 0.9842 | 0.9817 | −0.0025 |
| Answer relevance (60 answerable) | 0.9625 | 0.9815 | +0.0190 |
| Correctness (60 answerable) | 0.9552 | 0.9790 | +0.0238 |
| Abstention F1 | 0.8571 | 0.9000 | +0.0429 |
| Retrieval mean | 445.8 ms | 443.4 ms | −2.5 ms |
| Retrieval p95 | 545.9 ms | 607.2 ms | +61.3 ms |
| Full mean | 5,586.2 ms | 5,543.9 ms | −42.3 ms |
| Actual provider cost | $0.10299 | $0.12545 | +$0.02246 |

Paired 10,000-resample bootstrap and 100,000 sign-flip analysis finds no
Holm-significant quality or latency difference. Large’s answer-relevance and
correctness bootstrap intervals are above zero, but their Holm-adjusted
p-values are `0.5753` and `0.8053`.
The large-cell cost premium is 21.8%, almost entirely from document/query
embeddings.

The automated judge is a separate model but remains the same provider. Final
publication-quality answer claims still require blinded human calibration or
the locked atomic-claim dataset described below.

## End-to-end atomic attribution

For the clean large/1,024 cell:

| Layer | Mean | Share of full query time |
|---|---:|---:|
| Retrieval/context selection | 443.4 ms | 8.0% |
| Luna answer generation | 3,257.8 ms | 58.8% |
| GPT-5.4-mini judging | 1,842.6 ms | 33.2% |
| Post-processing | 0.04 ms | negligible |
| Total with judge | 5,543.9 ms | 100% |

The judge is benchmark-only overhead. For a user-facing answer, the comparable
path is retrieval plus generation, about 3.70 seconds mean before streaming
instrumentation. Retrieval-only tuning cannot remove the dominant generation
latency.

## RAGZ production hybrid confirmation

Two counterbalanced networking runs use the three textbooks, 8,374 production
heading chunks, large/1,024, fixed original-plus-two alternatives, five
warmups, and seven scored repetitions. Each run produces 105 observations per
mode with zero errors. Quality is identical across condition order.

Both manifests record `git_dirty: true` at base commit `e38b9f9` and bind the
same tracked-diff SHA-256. The final branch contains the relevant runner code,
but these are not presented as clean-commit artifacts.

Combined across both orderings:

| Metric | Single | Multi |
|---|---:|---:|
| Scored observations | 210 | 210 |
| Exact-page Recall@5 | 0.2573 | 0.2422 |
| MRR@5 | 0.8611 | 0.9167 |
| nDCG@5 | 0.5568 | 0.5612 |
| Mean latency | 368.6 ms | 451.0 ms |
| p50 latency | 380.7 ms | 481.9 ms |
| p95 latency | 461.6 ms | 532.8 ms |
| Dense embedding mean | 342.0 ms | 410.9 ms |
| Qdrant search mean | 8.8 ms | 15.0 ms |

Multi-query improves the first-hit rank and nDCG but slightly lowers exact-page
coverage. The paired Recall delta is `−0.0151`, with bootstrap 95% CI
`[-0.0680,+0.0417]`. This condition uses fixed alternatives, so its expansion
stage is local and near zero; live Luna expansion is a separate measured smoke.

Large/1,024 indexes faster/searches narrower vectors than small/1,536, but its
networking exact-page recall is materially worse than the earlier small/1,536
track. The two corpora score different granularities: Open Manuals recognizes
the correct document, while networking requires the correct physical page.
Large/1,024 is therefore a candidate for a document-level workspace, not a
global RAGZ default.

Indexing the three textbooks with large/1,024 spent:

- dense embedding: 249.3 seconds;
- PDF parsing: 17.7 seconds;
- Qdrant upsert: 7.7 seconds;
- sparse embedding: 1.5 seconds;
- chunk construction: 0.13 seconds.

## AnythingLLM native retrieval

AnythingLLM v1.16.0 successfully ran the selected large/1,024 alias on the
same 22-document, 70-query Open Manuals corpus:

| Metric | AnythingLLM |
|---|---:|
| Scored observations | 210 |
| Document Recall@5 | 1.0000 |
| MRR@5 | 0.9833 |
| nDCG@5 | 0.9877 |
| Retrieval p50 | 250.8 ms |
| Retrieval p95 | 536.7 ms |
| Indexing wall time | 38.8 s |
| Peak container memory | 396.6 MB |
| Errors / retries | 0 / 0 |

Its zero-threshold abstention F1 is zero because every off-corpus query returns
at least one candidate. Abstention requires a held-out threshold/classifier
calibration and must not be inferred from this parity row. This is retrieval
only; AnythingLLM answer/RAG-Triad scores were not fabricated.

## RAGFlow 3 GB runtime result

RAGFlow was not rejected solely from its published 16 GB recommendation. It
was actually attempted with API-hosted models only.

Two Docker endpoints exist on this host:

- Docker Desktop: 3.86 GB, where native image pulls repeatedly hit a
  containerd content-store commit failure.
- Native daemon at `unix:///var/run/docker.sock`: 16.25 GB daemon capacity,
  used for the controlled 3 GB Compose project after `skopeo` imported the
  pinned image.

The isolated project contained RAGFlow, reduced-memory Infinity, MySQL, MinIO,
and Redis. It started no TEI, DeepDoc, local embedding, local generation, or
reranking service. Every service had a hard limit, restart policy `no`, unique
loopback ports, and a project-scoped stop guard.

The final run reached all five running containers, then stopped after about 15
seconds when:

- RAGFlow reached 1,378.7 / 1,379.8 MB (`99.9%` of its slice);
- swap grew by 1,415.7 MB;
- host available memory fell to 1,170.9 MB;
- memory PSI reached 4.2;
- no container was OOM-killed or restarted.

The project was stopped before provider configuration, ingestion, or quality
scoring. Status is `runtime_resource_limited`, not zero quality. Raising the
budget or repairing/reallocating the host requires a separate operator
decision; this run does not justify a RAGFlow score.

## Professional networking dataset contract

`networking-pdfs-v2` defines 360 locked and 60 development questions with:

- 240/120 answerable/negative locked balance;
- difficulty, query-type, source-scope, and per-book coverage targets;
- out-of-scope, insufficient-evidence, false-premise, and ambiguity strata;
- exact physical-page graded qrels;
- atomic claims and claim-to-evidence links;
- concept-cluster leakage checks;
- two human reviewers plus third-person adjudication before locking.

The builder deliberately emits only metadata-based `draft_unverified` work
items. It cannot call a generated set “gold” without the human review gate.
This is why the current measured quality campaign uses the existing 70-query
licensed set rather than pretending 420 machine-written questions are a
professional benchmark.

## Decision

1. Keep small/1,536 as the production default until an exact-page,
   independently adjudicated large/1,024 product evaluation clears a quality
   floor.
2. Offer large/1,024 as an opt-in candidate for document-level/manual corpora;
   it gives the best measured document-quality/latency tradeoff.
3. Do not increase dimensions above 1,024 by default. The measured latency
   penalties are clear; quality gains are small and not multiplicity-robust.
4. Optimize generation before micro-optimizing Qdrant: it is approximately 59%
   of clean end-to-end time, versus 8% for retrieval.
5. Keep RAGFlow unavailable on the 3 GB project budget and preserve its stopped
   project/artifacts for a future higher-memory run.

## Evidence map

- Atomic endpoint matrix:
  `docs/benchmarks/artifacts/raw/2026-08-23/openai-embedding-atomic-matrix-20260823-r1/`
- Width/proxy attestation:
  `docs/benchmarks/artifacts/raw/2026-08-23/openai-embedding-matrix-preflight-20260823-r2/`
- Corrected ten-cell exploratory analysis:
  `docs/benchmarks/artifacts/2026-08-23-open-manuals-embedding-matrix-analysis-r3.md`
- Clean large/1,024 and small/1,024 cells:
  `docs/benchmarks/artifacts/raw/2026-08-23/open-manuals-publication-*-1024-nocache-gpt54judge-20260823-r1/`
- Clean-pair paired analysis:
  `docs/benchmarks/artifacts/2026-08-23-open-manuals-clean-pair-analysis.md`
- AnythingLLM successful run:
  `docs/benchmarks/artifacts/raw/2026-08-23/anythingllm-open-manuals-large-1024-20260823-r2/`
- RAGZ product runs:
  `docs/benchmarks/artifacts/raw/2026-08-23/ragz-networking-large1024-product-atomic-20260823-r1/`
  and `...-r2/`
- RAGZ product combined analysis:
  `docs/benchmarks/artifacts/2026-08-23-ragz-large1024-product-analysis.md`
- RAGFlow attempts:
  `docs/benchmarks/artifacts/raw/2026-08-23/ragflow-native-daemon-lowmem-smoke-20260823-r2/`
  through `...-r5/`
- Dataset contract:
  `docs/benchmarks/networking-pdfs-v2-dataset.md`
