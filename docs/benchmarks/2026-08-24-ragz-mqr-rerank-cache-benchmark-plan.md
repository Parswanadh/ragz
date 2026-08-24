# RAGZ MQR, rerank and embedding-cache benchmark plan

**Execution status (2026-08-24): completed with documented deviations.** The
executed corpus was `large-books-v1` (three public PDFs, 4,412 pages, 24
queries/20 answerable/four off-corpus), not the 22-document Open Manuals corpus
named in Tasks 4–7 below. The retrieval screen used one scored observation per
query because Cohere's account limit was empirically 9–10 RPM; the independent
restored-state Triad pass supplied a second fresh retrieval observation for all
12 ranking configurations. The first screen had one incomplete cell and was
preserved as invalid; the final provenance-checked resume artifact has 288/288
zero-error query-condition cells. No frequentist significance claim is made.
Results: `docs/benchmarks/2026-08-24-ragz-mqr-rerank-cache-results.md`.

**Goal:** Measure RAGZ with one, three and five total query lanes; rerank
candidate pools `P={10,20,50}`; and query-embedding cache off/cold/warm, with
atomic latency, retrieval quality, abstention, RAG-Triad, cost and resource
evidence comparable to AnythingLLM, RAGFlow and the resource-gated Onyx row.

**Architecture:** Extend retrieval through benchmark-only override seams while
keeping production defaults unchanged. Generate at most four alternatives once
per source query with Luna, reuse that private expansion set for both MQR=3 and
MQR=5, and run a staged retrieval screen before spending answer/judge budget.
Cache state changes latency/cost only; RAG-Triad is reused only after exact
ranking/context hashes prove cache-on and cache-off outputs identical.

**Execution:** Inline root-agent execution only. No full-history subagents.

## Global constraints

- Work only on branch `codex/multi-query-retrieval` in the clean comparison
  checkout.
- OpenAI embedding: `text-embedding-3-large`, 1,024 dimensions, fixed attested
  LiteLLM alias and proxy fingerprint.
- Answer/expansion model: `gpt-5.6-luna`; omit unsupported temperature.
- Judge: separate same-provider `gpt-5.4-mini`.
- Rerank provider: Cohere cloud `rerank-v4.0-fast`; no local model.
- Final retrieval output: top five; candidate-pool `P` is varied before
  reranking. “Top-p” in this plan means this pool, not LLM nucleus sampling.
- LLM `top_p` stays at provider default `1.0` and is not a reranker control.
- Public artifacts contain no questions, alternatives, source text, answers,
  credentials or provider response bodies.
- Every completed condition requires exact denominators and zero unclassified
  errors. Partial conditions receive no quality aggregate.
- Provider budget hard cap: `$10`; preflight estimates and call ceilings are
  persisted before live execution.

## Frozen condition matrix

Retrieval screen conditions (`3 query counts × 5 retrieval/cache modes = 15`):

| Query lanes | Rerank pool | Cache condition |
|---:|---:|---|
| 1, 3, 5 | off | off |
| 1, 3, 5 | off | warm hit |
| 1, 3, 5 | 10 | off |
| 1, 3, 5 | 20 | off |
| 1, 3, 5 | 50 | off |

Cold-cache latency is the first miss used to populate each warm condition and
is reported separately rather than treated as another ranking condition.

RAG-Triad ranking conditions (`3 × 4 = 12`): query lanes 1/3/5 crossed with
rerank off/P10/P20/P50. Cache variants share a Triad result only when retrieved
IDs, ordering, scores and context hashes match exactly.

## Query-expansion perspectives

The original user query is always lane 1 and is never rewritten away.

- Lane 2: exact entities, numbers, protocol names and constraints, expressed
  as a self-contained retrieval query.
- Lane 3: terminology expansion—synonyms, acronyms, formal/manual vocabulary—
  without adding facts.
- Lane 4: mechanism and relationship view—components, cause/effect,
  prerequisites and failure modes that are already implicit in the question.
- Lane 5: evidence/source view—phrasing likely to occur in definitions,
  headings, configuration guides, standards or troubleshooting documentation.

The prompt treats the `<query>` block as untrusted data, forbids answering,
requires one strict JSON object, preserves negation and scope, and rejects
duplicates or strings over 2,000 characters.

## Task 1: Configurable expansion contract

**Files:**

- Modify `backend/src/ragz/modules/retrieval/query_expansion.py`
- Modify `backend/src/ragz/modules/retrieval/service.py`
- Modify/add focused tests under `backend/tests/retrieval/`

**Produces:** `QueryExpander.expand(query, model, total_queries)` supporting
only total counts `1`, `3`, `5`; dynamic strict prompt; exact original-first,
deduplicated bounded result.

Verification:

- Prompt-injection strings stay data.
- MQR=3 returns original plus at most two alternatives.
- MQR=5 returns original plus at most four alternatives.
- Malformed/short results degrade to the original without fabricated lanes.
- Luna payload omits temperature and uses provider-default `top_p`.

## Task 2: Rerank pool benchmark seam

**Files:**

- Modify `backend/src/ragz/modules/retrieval/service.py`
- Add focused retrieval tests

**Produces:** validated benchmark override `rerank_candidate_pool_override` in
`{10,20,50}`. Production remains at the current pool of 50 until evidence
selects another standard. Final `top_k=5` is unchanged.

Verification:

- Dense and sparse prefetch limits equal the selected candidate pool.
- Reranker receives exactly P unique candidates when available.
- No-rerank behavior and security filters are byte-for-byte unchanged.

## Task 3: Query-embedding cache seam

**Files:**

- Modify `backend/src/ragz/modules/retrieval/embeddings.py`
- Modify `backend/src/ragz/modules/retrieval/service.py`
- Add focused cache tests

**Produces:** benchmarkable cache interface keyed by model ID, provider model,
dimension and normalized-query SHA-256. It reports hit/miss counts and preserves
provider usage for misses. No raw query is stored in public evidence.

Verification:

- First request is a cold miss; repeated request is a warm hit.
- Model/dimension/prompt-version changes miss.
- Batch order and vector width remain exact.
- Concurrent identical misses coalesce or remain correct without usage races.
- Cache-off and cache-on rankings match exactly.

## Task 4: Production-path Open Manuals matrix runner

**Files:**

- Create `backend/scripts/run_open_manuals_ragz_matrix.py`
- Create `backend/tests/scripts/test_open_manuals_ragz_matrix.py`

**Produces:** private expansion/context evidence and public per-condition
records with query ID, condition ID, repetition, ranked IDs/scores, cache
counters, stage timings, usage and typed error only.

The runner seeds the 22-document corpus through RAGZ's real chunk/upsert path,
verifies 1,024-wide Qdrant vectors, freezes 70 ordered queries, generates four
private alternatives once, then executes:

- screening: one warmup plus two repetitions for all 15 conditions;
- confirmation: two warmups plus five repetitions for the baseline, MQR=3,
  MQR=5 and Pareto rerank finalists;
- both forward and reverse condition order with a fixed Latin-square schedule.

Required atomic stages include expansion, embedding cache lookup, dense
embedding, sparse embedding, ACL prefilter/recheck, Qdrant search/RRF,
candidate decode/dedupe, rerank and no-answer probe, with wall-clock closure.

## Task 5: Retrieval/cost/statistical analyzer

**Files:**

- Create `backend/scripts/analyze_open_manuals_ragz_matrix.py`
- Create `backend/tests/scripts/test_analyze_open_manuals_ragz_matrix.py`

**Produces:** validated JSON and Markdown containing:

- document Recall@5, MRR@5, nDCG@5 and required-document hit;
- abstention confusion/precision/recall/F1;
- mean, p50, p95, p99 and bootstrap CI per atomic stage;
- cache cold/warm hit latency and blended latency at 0/10/25/50% hit rates;
- expansion/embedding/rerank usage-derived cost;
- paired deltas, sign-flip tests and Holm correction;
- Pareto frontier over Recall, nDCG, p95 and cost.

The analyzer rejects duplicate/missing query×repetition cells, mismatched
corpus/model/proxy/code hashes, ranking drift between cache variants, or any
completed condition with errors.

## Task 6: RAG-Triad finalists and anchors

**Files:**

- Create `backend/scripts/run_ragz_matrix_triad.py`
- Create `backend/tests/scripts/test_ragz_matrix_triad.py`

**Produces:** answerable-only context relevance, groundedness, answer relevance,
correctness and citation metrics; all-query answer-abstention metrics; separate
retrieval/generation/judge clocks; endpoint-specific cost.

Triad runs for all 12 unique ranking conditions. Cache variants reuse a result
only after hash equality. Same prompts, Luna model, GPT-5.4-mini judge, token
limits and no-cache answer policy apply to every condition.

## Task 7: Competitor comparison

**Files:**

- Create `docs/benchmarks/2026-08-24-ragz-matrix-vs-open-source.md`
- Create machine-readable comparison JSON under `docs/benchmarks/artifacts/`

AnythingLLM and RAGFlow retain their source-bound large/1,024 results. They are
not rerun merely to fill RAGZ matrix columns. Onyx remains
`resource_gated/not_executed` unless its pinned API-only stack passes the same
resource and 70-query denominator gates; no synthetic score is allowed.

The comparison must distinguish different repetitions, chunking and cache
states and may identify winners only inside a comparable metric row.

## Task 8: Final verification and checkpoint

- Run focused tests, Ruff and strict mypy for every modified/new file.
- Run the complete backend suite.
- Parse every JSON/JSONL artifact; verify hashes and privacy patterns.
- Confirm all benchmark containers are stopped and temporary credentials are
  removed.
- Commit and push the branch; do not open a PR without a separate request.

## Qdrant-specific experiment notes

Current Qdrant guidance supports RRF as the baseline when dense cosine and BM25
scores are incomparable, recommends tuning RRF rank sensitivity/weights only
from measured distributions, and warns against arbitrary linear fusion. Search
diagnosis should check warm-vs-cold behavior, payload/vector return cost,
filter indexes and optimizer state before changing HNSW.

RAGZ already indexes tenant/workspace/document/ACL/current-version payload
fields. Add a separate Qdrant diagnostic row for `is_tenant=true` on the primary
tenant field and for optimizer/indexed-only state, but do not mix it into the
MQR/rerank causal matrix. Qdrant is currently only 2--3% of retrieval latency.

Canonical guidance:

- https://qdrant.tech/documentation/concepts/hybrid-queries/
- https://qdrant.tech/documentation/guides/optimize/
- https://qdrant.tech/documentation/concepts/indexing/#tenant-index
