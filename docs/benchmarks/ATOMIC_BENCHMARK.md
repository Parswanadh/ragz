# Atomic Benchmark

Last updated: 2026-08-25

This is the canonical short-form record for the networking retrieval, atomic
latency, answer-model parity, AGNO boundary, and RAGFlow execution status. Raw
query/document text and credentials are not committed.

The expanded 70-query/ten-dimension campaign and the actual RAGFlow runtime
attempt are documented in
`docs/benchmarks/2026-08-23-professional-embedding-rag-triad-and-ragflow.md`.

## 2026-08-24 MQR/rerank/cache decision

The new large-books campaign evaluated all 12 unique ranking configurations
from query lanes `{1,3,5}` and rerank candidate pools `{off,10,20,50}`, plus
three cold/warm query-embedding cache pairs. It used three public PDFs (4,412
pages), 18,734 chunks, 24 queries (20 answerable/four off-corpus), OpenAI
`text-embedding-3-large` at 1,024 dimensions, Cohere `rerank-v4.0-fast`, Luna
answers and a separate GPT-5.4-mini judge.

- Recommended default: one query, reranker off.
- If reranking is explicitly enabled: retain `P=50` pending a larger repeated
  evaluation; reranking remains off by default.
- MQR remains superadmin-only and off by default; three lanes are safer than
  five when a workspace-specific evaluation justifies it.
- Retrieval Pareto set: Q1/no-rerank and Q1/P=50. No MQR condition survived.
- Q1/no-rerank Recall/MRR/nDCG: `0.6000 / 0.4767 / 0.5074` on exact-page qrels.
- Warm query-embedding cache mean: `19.00 / 42.80 / 54.78 ms` for Q1/Q3/Q5,
  versus cache-off `678.47 / 940.83 / 928.84 ms`.
- Low-reasoning Luna expansion mean/p95: `2,814.25 / 3,580.19 ms`, versus
  provider-default `6,635.31 / 21,559.85 ms`; all 24 expansions completed on
  the first attempt with zero fallback lanes.
- Complete RAG-Triad denominator: 288 unique zero-error query-condition rows,
  288 generation calls and 288 judge calls; answer+judge cost `$0.92281055`.
- Q1/no-rerank atomic retrieval mean: `839.50 ms`, of which dense embedding was
  `801.85 ms` (`95.5%`).
- Q1/P=50 Cohere provider mean: `710.70 ms`; benchmark quota wait is reported
  separately and is not mislabeled as model latency.

Complete interpretation, competitor boundaries and improvement order:
`docs/benchmarks/2026-08-24-ragz-mqr-rerank-cache-results.md`.

### Production-change confirmation

The post-implementation counterbalanced confirmation used one frozen index,
two warmups and five repetitions in both orders (960 scored rows, zero errors):

| Cell | Recall@5 | MRR@5 | nDCG@5 | Mean | p95 |
|---|---:|---:|---:|---:|---:|
| Q1 cache-off | 0.6000 | 0.4517 | 0.4890 | 728.49 ms | 913.52 ms |
| Q1 cache-warm | 0.6000 | 0.4517 | 0.4890 | **16.93 ms** | **19.68 ms** |
| Q3 cache-off | 0.6000 | 0.4475 | 0.4855 | 1,385.00 ms | 1,639.51 ms |
| Q3 cache-warm | 0.6000 | 0.4475 | 0.4855 | **33.76 ms** | **39.33 ms** |

Q3-minus-Q1 Recall was exactly zero across 200 answerable pairs; cache-off
latency added `656.50 ms` and warm latency added `16.83 ms`. Cache-on quality
matched cache-off exactly. A separate 24-query live expansion-cache pass had
warm p50/p95 `0.017/0.047 ms`, 24/24 exact matches and zero provider calls.
Detailed evidence:
`docs/benchmarks/2026-08-24-mqr-production-confirmation.md`.

### Large-books common-interval open-source result

The same large-books corpus, large/1,024 embedding alias and 20-page interval
qrels produced:

| System | Recall@5 | MRR@5 | nDCG@5 | p50 | p95 |
|---|---:|---:|---:|---:|---:|
| RAGZ Q1 cache-off | **0.8250** | **0.6583** | **0.7002** | 718.45 ms | 913.52 ms |
| RAGZ Q3 cache-off | 0.8000 | **0.6792** | **0.7096** | 1,440.66 ms | 1,639.51 ms |
| AnythingLLM | 0.8000 | 0.6517 | 0.6890 | **306.93 ms** | **354.01 ms** |

AnythingLLM indexes the intervals directly while RAGZ maps native chunks to
intervals after retrieval, so the evidence unit is common but chunking is not.
RAGFlow remains source-bound to Open Manuals and Onyx remains
eligible-protocol-gated; neither receives a fabricated common-corpus score.
Details: `docs/benchmarks/2026-08-25-normalized-four-system-followup.md`.

## Frozen published retrieval configuration

| Field | Value |
|---|---|
| Corpus | Three networking textbooks, 2,582 physical PDF pages |
| Evaluation unit | 131 unique 20-page intervals |
| Queries | 15 total: 12 answerable, 3 off-corpus |
| Scored repetitions | Three per query in each of two counterbalanced order runs |
| Embedding | OpenAI `text-embedding-3-small`, 1,536 dimensions |
| RAGZ single | One query; dense + BM25; Qdrant RRF |
| RAGZ multi | Original plus two fixed alternatives; six dense/sparse lanes; Qdrant RRF |
| Reranker | Disabled |
| Native candidate depth | RAGZ 20; AnythingLLM 50; both reduced to five unique intervals |
| Answer/expansion model | Not configured or invoked in the published retrieval rows |

The published AnythingLLM r6 runner used an unused `benchmark-unused` Ollama
placeholder, while the RAGZ multi row used fixed alternatives. Answer generation
was not involved in Recall/MRR/nDCG. `gpt-5.6-luna` is the target model for the
separate answer/live-expansion smokes and future generated-query/answer tracks.

## Same-embedding retrieval result (20-page interval qrels)

| System | Recall@5 | MRR@5 | nDCG@5 | p50 | p95 |
|---|---:|---:|---:|---:|---:|
| AnythingLLM OpenAI + LanceDB | **0.7272** | 0.8611 | **0.7465** | **283.53 ms** | **400.28 ms** |
| RAGZ single | 0.6800 | **0.8778** | 0.7017 | 374.84 ms | 542.51 ms |
| RAGZ multi | 0.7244 | 0.8403 | 0.7295 | 525.47 ms | 633.10 ms |

AnythingLLM's Recall lead over RAGZ multi is only `0.0028` absolute. RAGZ
single leads MRR by `0.0167`. These small differences should not be described
as a universal product ranking from twelve answerable queries.

These are 20-page-interval metrics, not exact physical-page metrics. The raw
exact-page small/1,536 parity run reports Recall@20 of `0.446140` (single) and
`0.484362` (multi). The interval Recall@5 values above (`0.6800` and
`0.7244`) must not be presented as interchangeable with those exact-page
values or as a regression between runs.

## Why AnythingLLM still leads some metrics

Using the same embedding model does not make the retrieval systems identical.
The model converts different text units into vectors and each product ranks
those vectors differently.

1. **Evaluation-unit alignment.** AnythingLLM indexed one document per 20-page
   interval—the same unit used for scoring. RAGZ indexed 8,374 fine-grained
   heading chunks and mapped retrieved pages into intervals after search. The
   metric therefore aligns more directly with AnythingLLM's adapter inputs.
2. **Chunk text differs.** AnythingLLM's collector/chunker embeds interval-level
   text; RAGZ embeds approximately 2,000-character heading-aware chunks with
   overlap. Identical embedding models do not produce comparable vectors from
   non-identical text.
3. **Ranking differs.** AnythingLLM uses LanceDB dense ranking. RAGZ fuses
   OpenAI dense results with FastEmbed BM25 using Qdrant RRF. Lexical candidates
   can improve some queries while displacing semantically strong candidates on
   others.
4. **Candidate pools differ.** AnythingLLM retrieves 50 native candidates and
   RAGZ 20 before keeping five unique intervals. Every scored observation fills
   five intervals, so this is not an empty-list artifact, but the deeper pool
   can still change *which* five intervals survive.
5. **Multi-query trades first-hit rank for coverage.** RAGZ multi nearly closes
   the Recall gap and improves nDCG versus RAGZ single, but additional candidates
   can move the first relevant interval downward, reducing MRR.
6. **The sample is small.** Only twelve answerable questions drive aggregate
   quality. The remaining gaps are compatible with query mix and system-level
   chunk/fusion effects; the current benchmark does not isolate one causal
   component.

The next causal experiment is to index the exact same 131 interval objects in
both systems, use the same candidate depth and dense-only ranking first, then
enable BM25/RRF and multi-query one factor at a time.

## Atomic RAGZ latency result

Two fresh OpenAI runs produced 90 successful observations per mode and zero
errors.

| Metric | Single | Multi |
|---|---:|---:|
| Mean | 377.35 ms | 485.47 ms |
| p50 | 388.76 ms | 507.26 ms |
| p95 | 451.07 ms | 553.17 ms |
| Mean without dense-provider stage | 34.48 ms | 53.52 ms |

| Atomic stage | Single mean | Multi mean | Multi delta |
|---|---:|---:|---:|
| Dense OpenAI embedding | 342.87 ms | 431.95 ms | +89.08 ms |
| Qdrant fused search | 12.50 ms | 24.28 ms | +11.78 ms |
| No-answer dense probe | 7.31 ms | 14.03 ms | +6.73 ms |
| Authorization prefilter | 4.50 ms | 4.49 ms | −0.01 ms |
| Collection readiness | 3.25 ms | 3.20 ms | −0.05 ms |
| Workspace/model resolution | 2.52 ms | 3.39 ms | +0.88 ms |
| BM25 sparse embedding | 0.39 ms | 0.46 ms | +0.07 ms |

Dense embedding accounts for `90.9%` of single and `89.0%` of multi mean
latency. It explains `82.4%` of the `108.12 ms` multi-minus-single increase.

## Why the older report showed about 50 ms

The older track used deterministic hash embeddings and made no provider call:

| Historical hash track | Mean | p50 | p95 |
|---|---:|---:|---:|
| Single | 27.56 ms | 28.00 ms | 31.69 ms |
| Multi | 42.99 ms | 42.42 ms | 50.40 ms |

The new OpenAI residuals are in the same tens-of-milliseconds range but are
25.1%/24.5% above the historical means. They retain different vector width and
provider-backed index state, so they are not a controlled hash counterfactual.

## Direct OpenAI versus LiteLLM diagnostic

The source-bound diagnostic contains 40 scored request rows, two warmups per
condition, alternating forward/reverse order, HTTP 200 for every request, zero
errors, and 1,536-dimensional vectors.

| Path | Mean | p50 | p95 |
|---|---:|---:|---:|
| Direct OpenAI, one input | 408.00 ms | 379.16 ms | 579.21 ms |
| LiteLLM → OpenAI, one input | 350.86 ms | 344.62 ms | 416.18 ms |
| Direct OpenAI, three inputs | 462.29 ms | 460.80 ms | 486.49 ms |
| LiteLLM → OpenAI, three inputs | 373.04 ms | 429.99 ms | 496.59 ms |

The paths differed substantially, but these small unpaired samples do not prove
a fixed LiteLLM speedup or penalty. Both remain hundreds of milliseconds; the
OpenAI/provider-network stage is the dominant latency source.

## Expanded embedding and RAG-Triad result

A later run tested all ten valid OpenAI small/large dimension cells with 2,000
scored atomic embedding requests. It then ran 700 exploratory Open Manuals
query evaluations and an attested no-cache 70-query pair with Luna generation
and a separate GPT-5.4-mini judge.

- Large/1,024 versus small/1,024 retrieval mean: `403.5` versus `387.5 ms`.
- Required-document hit: `60/60` versus `59/60` (descriptive; 60 answerable
  queries).
- Answerable-query context relevance: `0.9812` versus `0.9668`.
- Answerable-query correctness: `0.9787` versus `0.9547`.
- Actual 70-query provider cost: `$0.25521` versus `$0.23143`.
- No paired delta among the tested judge metrics and latency stages survives
  Holm correction. Required-document hit and abstention F1 are descriptive in
  this short record; no Holm claim is attached to them. The judge-quality
  denominator is 60 answerable queries, abstention is evaluated over all 70
  queries, and citation validity is evaluated over 59 answerable queries with
  citations in both conditions.

The attested large/1,024 end-to-end mean is `5,228.6 ms`: retrieval is `7.7%`,
Luna generation `60.2%`, and automated judging `32.0%`. Judge time is not a
user-facing production layer.

The corresponding AnythingLLM large/1,024 row has 180 document-quality
observations (60 answerable queries × 3 repetitions) and 210 total latency
observations. These denominators are separate from RAGZ's 168 exact-page
quality observations per mode in the networking product run.

The production networking hybrid confirmation produces a different result.
Across 210 observations per mode, with 168 answerable quality observations per
mode (12 queries × 7 repetitions × 2 orderings), large/1,024 exact-page
Recall@5 is `0.2573` single and `0.2422` multi. The comparison with
small/1,536 is descriptive and uncontrolled because model, dimension,
repetition count, commit state, and metric granularity differ. It cannot
justify changing the default. The Open Manuals qrels are document-level;
networking qrels require an exact physical page. A same-commit, same-corpus
exact-page pair is required.

The r2 pair is attested for no-cache operation, but both manifests record
commit `5b9241dc7d8a05520b05953dd2a018f49d22830f` with `git_dirty=true`. Its
dataset, matrix, wrapper, upstream-runner, and shared proxy hashes are recorded
in the paired analysis. Imported siblings in the dirty, partly untracked
benchmark-lab tree are not exhaustively hashed, so treat it as source-bound
dirty-base evidence, not a fully reproducible clean-commit default-selection
gate.

## `gpt-5.6-luna` answer-model parity

- The supplied OpenAI account returned HTTP 200 for model
  `gpt-5.6-luna`.
- The model was registered as `openai/gpt-5.6-luna` in the shared LiteLLM
  gateway.
- RAGZ's `LiteLLMStreamer.complete()` returned `OK`, with 10 prompt and 4
  completion tokens.
- RAGZ's live `LiteLLMQueryExpander` omitted the unsupported temperature field
  and returned three effective queries, with 127 prompt and 50 completion
  tokens; generated alternative text was not persisted.
- AnythingLLM v1.16.0's native `/api/v1/workspace/{slug}/chat`, with workspace
  `openAiTemp` explicitly set to `1`, returned HTTP 200, `OK`, model
  `gpt-5.6-luna`, provider `LiteLLM`, and 84 total tokens.
- The model rejects `temperature: 0`. RAGZ omits the field and uses the provider
  default (`1`); AnythingLLM must explicitly pin its workspace to `1` unless a
  future model contract supports another shared value.
- Retrieval-only manifests must continue to say answer generation was not
  executed; answer-quality results require a reference-answer/atomic-claim
  rubric that the current networking query set does not yet contain.

## AGNO boundary

AGNO does not participate in these RAGZ measurements. `rag_agno` is a separate
application with separate PostgreSQL, Qdrant, model configuration, corpus and
benchmark runner. Its architecture already records authorization, query
embedding, Qdrant, text hydration, reranking and final-authorization timings,
but no AGNO score is included until a clean same-corpus/same-model/same-prompt
run is frozen.

## RAGFlow API-only result and cloud-provider status

### Self-hosted API-model path

RAGFlow v0.27.0 was executed with cloud/API models only:

- Embedding: `text-embedding-3-large`, 1,024 dimensions, alias
  `ragz-openai-text-embedding-3-large-d1024`
- Generation: custom OpenAI-compatible `gpt-5.6-luna`
- Judge: separate `gpt-5.4-mini`
- Local embedding/generation model: none

Two different Docker endpoints were found. Docker Desktop exposes
`3,864,363,008` bytes. A separate native daemon at
`unix:///var/run/docker.sock` exposes `16,246,616,064` bytes and received the
pinned image through `skopeo` after Docker Desktop hit content-store commit
errors.

The native daemon ran an isolated RAGFlow/Infinity/MySQL/MinIO/Redis project
with no local model service. The scored r3 retrieval pass covered 70 queries
(60 answerable, 10 off-corpus), 22 documents and 415 chunks, with zero errors:
Recall@5 `0.983333` (59/60), MRR@5 `0.975000`, nDCG@5 `0.977182`; latency mean /
p50 / p95 / p99 was `467.227 / 419.919 / 593.821 / 1,291.788 ms`. The
retrieval-threshold abstention F1 was `0` at threshold zero and is not a
calibrated abstention result.

The separate triad pass scored context relevance `0.9870`, groundedness
`0.9815`, answer relevance `0.991833`, and citation validity `0.983333` (all
N=60 answerable). Answer abstention was TP=9, FP=0, FN=1, TN=60,
F1=`0.947368`. Mean generation and judge stages were `3,254.878 ms` and
`1,653.819 ms`; estimated arithmetic retrieval+generation was `3,722.106 ms`
and with judge `5,375.967 ms`, neither measured wall time. QA cost was
`$0.281858` for answer plus judge only; embedding ingestion/query cost was
unavailable and excluded.

This was a manually guarded quality run, not a sustained-stability test. A
22-document concurrent ingestion exposed an Infinity first-table race; 17
tasks were cancelled, the app was intentionally restarted once, and the
unfinished documents were indexed sequentially. Final preflight was 22/22
DONE with zero document failures. The r6 resource artifact is only a
three-minute smoke. The r3 run's runtime-stop, dataset-vector, and
measurement-protocol attestations bind the RAGFlow commit/image, embedding
width, proxy fingerprint, vector count, recovery sequence, and project-scoped
stop (zero containers left running). r1/r2 are warmup-only invalid provenance;
r3 had two public warmups plus one private capture pass, with no cache reset.

The user-approved 5 GB-plus-swap smoke used a `5,000,000,000`-byte aggregate
budget. RAGFlow peaked at `2,260,226,539 / 2,299,954,987` bytes (`98.27%`),
swap growth peaked at `4,917,555,200` bytes, minimum host `MemAvailable` was
`824,561,664` bytes, and maximum memory PSI avg10 was `7.79`; sampled OOMs and
restarts were both zero. These are smoke-only resource measurements.

### Official RAGFlow Cloud

- `https://cloud.ragflow.io/` returned HTTP 200.
- `/api/v1/datasets` returned HTTP 401 without authentication.
- No `RAGFLOW_CLOUD_API_KEY` is available locally.
- Public Cloud material does not establish that custom OpenAI-compatible
  `gpt-5.6-luna` can be selected for exact model parity.
- Official Helm/configuration supports external MySQL, Redis, MinIO and
  S3/OSS/Azure Blob/GCS-style storage, but no credentials for those managed
  services were supplied and RAGFlow's own application/workers are still
  required.

Therefore RAGFlow Cloud remains `credential_gated`, not quality-failed and not
zero. The completed score above is the native API-only run, not RAGFlow Cloud.
An authenticated API-enabled account is required before dataset creation,
model-selection verification, ingestion or retrieval benchmarking. No account
or paid plan was created.

## Evidence

- Detailed latency report:
  `docs/benchmarks/2026-08-23-ragz-atomic-latency-analysis.md`
- Machine-readable aggregate:
  `docs/benchmarks/artifacts/2026-08-23-ragz-atomic-latency.json`
- Atomic raw runs and endpoint probe:
  `docs/benchmarks/artifacts/raw/2026-08-23/`
- `gpt-5.6-luna` product-adapter smoke:
  `docs/benchmarks/artifacts/raw/2026-08-23/gpt-5.6-luna-answer-parity-smoke.json`
- Same-embedding quality report:
  `docs/benchmarks/2026-08-22-openai-embedding-parity-comparison.md`
- RAGFlow self-hosted/cloud-model preflight:
  `docs/benchmarks/artifacts/raw/2026-08-23/ragflow-cloud-model-preflight-20260823-ec9c08d-gpt56/`
- RAGFlow Cloud API preflight:
  `docs/benchmarks/artifacts/raw/2026-08-23/ragflow-cloud-api-preflight-20260823/`
- RAGFlow scored retrieval and attestations:
  `docs/benchmarks/artifacts/raw/2026-08-23/ragflow-open-manuals-large1024-retrieval-20260823-r3/`
- RAGFlow sanitized RAG-Triad:
  `docs/benchmarks/artifacts/raw/2026-08-23/ragflow-open-manuals-large1024-triad-20260823-r1/`
- RAGFlow resource smoke:
  `docs/benchmarks/artifacts/raw/2026-08-23/ragflow-native-daemon-swap-smoke-20260823-r6/`
- Complete HTML review:
  `docs/benchmarks/2026-08-22-complete-rag-review.html`
- Professional embedding/RAG-Triad/RAGFlow report:
  `docs/benchmarks/2026-08-23-professional-embedding-rag-triad-and-ragflow.md`
- Three-system source, dominance, atomic-latency and foundational analysis:
  `docs/benchmarks/2026-08-23-three-system-foundational-and-code-analysis.md`
- Atomic ten-cell endpoint matrix:
  `docs/benchmarks/artifacts/raw/2026-08-23/openai-embedding-atomic-matrix-20260823-r1/`
- Clean no-cache publication cells:
  `docs/benchmarks/artifacts/raw/2026-08-23/open-manuals-publication-large-1024-nocache-gpt54judge-20260823-r2/`
  and
  `docs/benchmarks/artifacts/raw/2026-08-23/open-manuals-publication-small-1024-nocache-gpt54judge-20260823-r2/`
- Clean-pair statistics:
  `docs/benchmarks/artifacts/2026-08-23-open-manuals-clean-pair-analysis-r2.md`
- RAGZ large/1,024 product confirmations:
  `docs/benchmarks/artifacts/raw/2026-08-23/ragz-networking-large1024-product-atomic-20260823-r1/`
  and `...-r2/`
- Combined large/1,024 product analysis:
  `docs/benchmarks/artifacts/2026-08-23-ragz-large1024-product-analysis.md`
