# Atomic Benchmark

Last updated: 2026-08-23

This is the canonical short-form record for the networking retrieval, atomic
latency, answer-model parity, AGNO boundary, and RAGFlow execution status. Raw
query/document text and credentials are not committed.

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

## Same-embedding retrieval result

| System | Recall@5 | MRR@5 | nDCG@5 | p50 | p95 |
|---|---:|---:|---:|---:|---:|
| AnythingLLM OpenAI + LanceDB | **0.7272** | 0.8611 | **0.7465** | **283.53 ms** | **400.28 ms** |
| RAGZ single | 0.6800 | **0.8778** | 0.7017 | 374.84 ms | 542.51 ms |
| RAGZ multi | 0.7244 | 0.8403 | 0.7295 | 525.47 ms | 633.10 ms |

AnythingLLM's Recall lead over RAGZ multi is only `0.0028` absolute. RAGZ
single leads MRR by `0.0167`. These small differences should not be described
as a universal product ranking from twelve answerable queries.

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

## RAGFlow attempt and cloud-provider status

### Self-hosted API-model path

RAGFlow v0.27.0 was configured conceptually for cloud/API models only:

- Embedding: `text-embedding-3-small`
- Generation/expansion: custom OpenAI-compatible `gpt-5.6-luna` through LiteLLM
- Local embedding/generation model: none

It remains resource-gated because the RAGFlow application/index stack—not the
models—requires at least 16 GB effective Docker/host memory. Current Docker
memory is 3,864,363,008 bytes; daemon disk and `vm.max_map_count` also remain
unverified in the Docker VM namespace. The stack was not started and no score
was emitted.

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

Therefore RAGFlow Cloud is `credential_gated`, not quality-failed and not zero.
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
- Complete HTML review:
  `docs/benchmarks/2026-08-22-complete-rag-review.html`
