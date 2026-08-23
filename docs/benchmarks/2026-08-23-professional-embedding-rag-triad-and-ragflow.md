# Professional embedding, RAG-Triad, and RAGFlow benchmark

Date: 2026-08-23

This report separates five experiments that answer different questions. It
does not merge them into a single product leaderboard.

1. A 2,000-observation OpenAI embedding endpoint matrix isolates model,
   dimension, batch size, and HTTP-client lifecycle latency.
2. A ten-cell, 700-query Open Manuals screen compares retrieval across every
   valid model/dimension cell. Its answer/judge cache and Luna self-judge make
   those answer totals exploratory only.
3. Two attested 70-query no-cache publication cells compare small and large
   embeddings at 1,024 dimensions with GPT-5.6 Luna answers and a separate
   GPT-5.4-mini judge.
4. AnythingLLM runs the selected large/1,024 cell through its native LanceDB
   retrieval path.
5. RAGFlow v0.27.0 is actually benchmarked with API-hosted models on the
   native Docker daemon. Its scored retrieval and a private RAG-Triad pass are
   complete; resource samples remain smoke-only and do not establish sustained
   stability.

Raw document text, prompts, answers, provider bodies, and credentials are not
committed. The licensed/private working outputs remain outside the repository.

## Result in one sentence

`text-embedding-3-large` at 1,024 dimensions is a provisional document-level
quality/latency candidate, but it is **not** a safe universal RAGZ default. The
separate networking comparison against small/1,536 is descriptive only: it
changes model, vector width, repetition count, commit state, and metric
granularity, so it cannot establish a default or a regression. A same-commit,
same-corpus, exact-page pair is required before changing the default.

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
The tested retrieval/self-judge quality differences do not survive Holm
correction. Larger dimensions from 2,048 through 3,072 have statistically
supported retrieval-latency penalties versus 1,024 without a supported,
multiplicity-adjusted quality gain.

## Attested no-cache publication pair

Both cells below use:

- all 70 queries;
- no embedding, answer, or judge cache;
- `gpt-5.6-luna` answer generation;
- a separate `gpt-5.4-mini` judge;
- top five contexts from identical RAGZ page-block chunking;
- 211 successful provider calls per cell and zero failures.

| Metric | small / 1,024 | large / 1,024 | Large − small |
|---|---:|---:|---:|
| Required-document hit (descriptive; 60 answerable queries) | 59 / 60 | 60 / 60 | +1 query |
| Context relevance (60 answerable) | 0.9668 | 0.9812 | +0.0143 |
| Groundedness (60 answerable) | 0.9720 | 0.9745 | +0.0025 |
| Answer relevance (60 answerable) | 0.9648 | 0.9898 | +0.0250 |
| Correctness (60 answerable) | 0.9547 | 0.9787 | +0.0240 |
| Abstention F1 (descriptive; 70 total queries) | 0.9091 | 0.9000 | −0.0091 |
| Retrieval mean | 387.5 ms | 403.5 ms | +16.0 ms |
| Retrieval p95 | 482.2 ms | 522.4 ms | +40.1 ms |
| Full mean | 5,334.7 ms | 5,228.6 ms | −106.0 ms |
| Actual provider cost | $0.23143 | $0.25521 | +$0.02379 |

Paired 10,000-resample bootstrap and 100,000 sign-flip analysis finds no
Holm-significant difference among the tested judge metrics and latency stages.
The largest raw judge signal is correctness, `+0.0240` with raw sign-flip
`p=0.02435`, but its Holm-adjusted `p=0.43830` is not significant. Required-
document hit and abstention F1 are descriptive endpoint summaries; no Holm
claim is attached to them. Citation validity is `1.0000` in both cells over
the 59 answerable queries that supplied citations in both conditions.
The large-cell provider-cost premium is `$0.02379` (`10.28%`), mostly from
large-model document/query embeddings.

The r2 pair is attested for explicit no-cache operation: 211 provider calls
per cell, zero errors, zero cache hits, and the same proxy fingerprint
`e5a2913bf2fe061ba9811d8c102b740230c33ee549cc34e507aa03639200eb31`. Both
manifests bind commit `5b9241dc7d8a05520b05953dd2a018f49d22830f` with
`git_dirty=true`, dataset hash
`a7e6f35fda062cf04ab1435ffac269486f3920a6abe520f0a384673f64e9d335`, matrix
hash `136f049e5dc8f15281b8e2076ff35581c5513e13ac6217c70ac09cbf045f142e`,
wrapper hash `6ec46a2e4d0b969e8772d838fdfb87cca0ea269b43f6498b92131e949d014946`,
and upstream-runner hash
`e71a735a4ab1130edab0e7caa7e851fc9b828f5975beadbf4764dd1973da9fdd`.
This binds the primary runner files, dataset, queries, matrix, and proxy, but
does not fully reconstruct imports from the dirty, partly untracked benchmark-
lab tree. Treat it as source-bound dirty-base evidence, not a fully
reproducible clean-commit release gate.

The automated judge is a separate model but remains the same provider. Final
publication-quality answer claims still require blinded human calibration or
the locked atomic-claim dataset described below.

## End-to-end atomic attribution

For the attested large/1,024 cell:

| Layer | Mean | Share of full query time |
|---|---:|---:|
| Retrieval/context selection | 403.5 ms | 7.7% |
| Luna answer generation | 3,150.0 ms | 60.2% |
| GPT-5.4-mini judging | 1,674.6 ms | 32.0% |
| Post-processing | 0.04 ms | negligible |
| Total with judge | 5,228.6 ms | 100% |

The judge is benchmark-only overhead. For a user-facing answer, the comparable
path is retrieval plus generation, about 3.55 seconds mean before streaming
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
| Scored observations (latency) | 210 | 210 |
| Quality observations (exact-page qrels) | 168 | 168 |
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

Large/1,024 indexes faster/searches narrower vectors than small/1,536 in this
track, but that cross-track comparison is uncontrolled: it changes the model,
dimension, repetition count, commit state, and quality unit. The two reported
networking baselines must also be kept separate. The older parity table reports
20-page-interval Recall@5 of `0.6800` (single) and `0.7244` (multi), whereas the
raw exact-physical-page small/1,536 run reports Recall@20 of `0.446140`
(single) and `0.484362` (multi). They are not interchangeable measures or a
like-for-like regression. Open Manuals recognizes the correct document, while
this networking row requires the correct physical page. Large/1,024 is
therefore only a document-level candidate until a same-commit, same-corpus
small/1,536-versus-large/1,024 exact-page pair is regenerated.

The networking product quality denominator is 168 answerable observations per
mode (12 answerable queries × 7 scored repetitions × 2 orderings), within 210
total latency observations per mode. The 168-observation quality denominator
must not be conflated with the 90-observation historical small/1,536 latency
track.

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
| Scored observations (latency) | 210 |
| Quality observations (document qrels) | 180 |
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
calibration and must not be inferred from this parity row. Its document-level
quality denominator is 180 observations (60 answerable queries × 3 scored
repetitions); latency uses all 210 observations. This is retrieval only;
AnythingLLM answer/RAG-Triad scores were not fabricated.

## RAGFlow API-only scored result

RAGFlow v0.27.0 was run on the native daemon at
`unix:///var/run/docker.sock`, with no local model services. The pinned
RAGFlow image is `sha256:e9fe71c5ff14762eeb8e251b3b8ed37c02a99ae2bad3d7b11467260ced79578b`
from commit `ec9c08d809f63ba2815090182fa225899d2437d5`. The embedding contract
was OpenAI `text-embedding-3-large` at 1,024 dimensions through alias
`ragz-openai-text-embedding-3-large-d1024`, with proxy fingerprint
`e5a2913bf2fe061ba9811d8c102b740230c33ee549cc34e507aa03639200eb31`. The
answer model was `gpt-5.6-luna`; the separate same-provider judge was
`gpt-5.4-mini`.

The corpus contained 22 documents and 415 final chunks. The public scored
retrieval pass covered 70 queries (60 answerable, 10 off-corpus), with zero
errors. It returned Recall@5 `0.983333` (59/60), MRR@5 `0.975000`, and nDCG@5
`0.977182`, all over the 60 answerable queries. Retrieval latency was
`467.227 ms` mean, `419.919 ms` p50, `593.821 ms` p95, and `1,291.788 ms`
p99. The threshold policy's abstention F1 was `0` because its threshold was
zero; this is not a calibrated abstention result.

The separate sanitized RAG-Triad pass used the same 70-query denominator:
context relevance `0.9870`, groundedness `0.9815`, and answer relevance
`0.991833`, each over 60 answerable queries. Citation validity was `0.983333`
(N=60). Answer abstention was TP=9, FP=0, FN=1, TN=60, F1=`0.947368`.
Generation latency was `3,254.878 ms` mean and judge latency was `1,653.819
ms` mean. Arithmetic composition gives estimated retrieval+generation
`3,722.106 ms` and retrieval+generation+judge `5,375.967 ms`; these are not
measured wall times. QA cost was `$0.281858` for answer generation plus judge
only; embedding ingestion/query provider cost is unavailable and excluded.

The quality run required recovery: an initial concurrent 22-document ingest
hit an Infinity first-table race, 17 tasks were cancelled, the RAGFlow app was
restarted once, and those tasks were indexed sequentially. Final preflight was
22/22 documents DONE, 415 chunks, and zero document failure messages. The r6
resource artifact is a three-minute smoke only; it is not a full-run resource
profile or sustained-stability claim. The scored project was stopped
project-scoped after measurement, with no containers left running. Earlier r1
and r2 retrieval outputs are warmup-only invalid provenance; the scored r3
pass records two public warmups plus the private context-capture pass (three
prior passes total, no cache reset).

The user-approved 5 GB-plus-swap smoke recorded a `5,000,000,000`-byte
aggregate container budget. RAGFlow peaked at `2,260,226,539 / 2,299,954,987`
bytes (`98.27%`) of its slice; maximum swap growth was `4,917,555,200` bytes,
minimum host `MemAvailable` was `824,561,664` bytes, and maximum memory PSI
avg10 was `7.79`. The sampled smoke recorded zero OOM kills and zero restarts.
These figures cover only the three-minute smoke, not the later manually
guarded ingestion and quality interval.

The r3 folder's `runtime-stop-attestation.json`,
`dataset-vector-attestation.json`, and `measurement-protocol-attestation.json`
are the authoritative runtime, vector-width, and pass-sequence bindings. The
r6 `manifest.json` and `samples.jsonl` are authoritative only for the earlier
three-minute smoke resource sample.

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

1. Keep small/1,536 as the production default until a same-commit,
   same-corpus exact-page pair (small/1,536 versus large/1,024), with
   independently adjudicated qrels and regenerated provenance/cost
   attestation, clears a quality floor.
2. Offer large/1,024 only as a provisional opt-in candidate for
   document-level/manual corpora; it is not a global product ranking.
3. Do not make a model or dimension change a global default from the current
   cross-track evidence. The measured latency penalties above 1,024 are useful
   screening evidence, while quality gains remain exploratory and
   multiplicity-limited.
4. Optimize generation before micro-optimizing Qdrant: it is approximately 60%
   of clean end-to-end time, versus 8% for retrieval.
5. Treat RAGFlow's API-only r3/triad result as a completed, manually guarded
   retrieval/quality observation, not as evidence of sustained low-memory
   operability. A higher-memory, clean-ingest repeat is required before a
   production stability conclusion.

## Evidence map

- Atomic endpoint matrix:
  `docs/benchmarks/artifacts/raw/2026-08-23/openai-embedding-atomic-matrix-20260823-r1/`
- Width/proxy attestation:
  `docs/benchmarks/artifacts/raw/2026-08-23/openai-embedding-matrix-preflight-20260823-r3/`
- Corrected ten-cell exploratory analysis:
  `docs/benchmarks/artifacts/2026-08-23-open-manuals-embedding-matrix-analysis-r3.md`
- Attested no-cache large/1,024 cell:
  `docs/benchmarks/artifacts/raw/2026-08-23/open-manuals-publication-large-1024-nocache-gpt54judge-20260823-r2/`
- Attested no-cache small/1,024 cell:
  `docs/benchmarks/artifacts/raw/2026-08-23/open-manuals-publication-small-1024-nocache-gpt54judge-20260823-r2/`
- Clean-pair paired analysis:
  `docs/benchmarks/artifacts/2026-08-23-open-manuals-clean-pair-analysis-r2.md`
- AnythingLLM successful run:
  `docs/benchmarks/artifacts/raw/2026-08-23/anythingllm-open-manuals-large-1024-20260823-r2/`
- RAGZ product runs:
  `docs/benchmarks/artifacts/raw/2026-08-23/ragz-networking-large1024-product-atomic-20260823-r1/`
  and `...-r2/`
- RAGZ product combined analysis:
  `docs/benchmarks/artifacts/2026-08-23-ragz-large1024-product-analysis.md`
- RAGFlow scored retrieval:
  `docs/benchmarks/artifacts/raw/2026-08-23/ragflow-open-manuals-large1024-retrieval-20260823-r3/`
- RAGFlow private sanitized RAG-Triad:
  `docs/benchmarks/artifacts/raw/2026-08-23/ragflow-open-manuals-large1024-triad-20260823-r1/`
- RAGFlow resource smoke and runtime attestations:
  `docs/benchmarks/artifacts/raw/2026-08-23/ragflow-native-daemon-swap-smoke-20260823-r6/`
  and the `runtime-stop-attestation.json`, `dataset-vector-attestation.json`,
  and `measurement-protocol-attestation.json` files in the scored r3 folder
- Dataset contract:
  `docs/benchmarks/networking-pdfs-v2-dataset.md`
