# RAGZ vs AnythingLLM vs RAGFlow: foundational and code-level analysis

Status: measured comparison plus source audit. This document does not promote
the current runs into a universal product ranking.

## Pinned implementations

| System | Revision | Clean comparison checkout |
|---|---|---|
| RAGZ | `b91c898b5c3a1e8c49c2929ef6682f918e36ce26` | `/home/parshu/projects/rag-comparison-sources/ragz-b91c898` |
| AnythingLLM | `55b6ebcea132f0d7ac146da99a0cd0db507b9030` (`v1.16.0`) | `/home/parshu/projects/rag-comparison-sources/anything-llm-v1.16.0` |
| RAGFlow | `ec9c08d809f63ba2815090182fa225899d2437d5` (`v0.27.0`) | `/home/parshu/projects/rag-comparison-sources/ragflow-v0.27.0` |

The shared measured track uses Open Manuals v2: 22 documents, 70 queries, 60
answerable and 10 off-corpus. All three use OpenAI
`text-embedding-3-large` at 1,024 dimensions and top five. RAGZ and RAGFlow
also use `gpt-5.6-luna` for answers and a separate same-provider
`gpt-5.4-mini` judge. AnythingLLM's completed row is retrieval-only.

## Measured retrieval comparison

RAGZ document metrics below were recomputed from its r2 `retrieved_ids` and
the authoritative document qrels. RAGFlow metrics come from scored r3.
AnythingLLM reports three scored repetitions per query.

| Metric | RAGZ large/1,024 | AnythingLLM large/1,024 | RAGFlow large/1,024 |
|---|---:|---:|---:|
| Quality observations | 60 | 180 | 60 |
| Recall@5 | **1.0000** | **1.0000** | 0.9833 |
| MRR@5 | 0.9667 | **0.9833** | 0.9750 |
| nDCG@5 | 0.9754 | **0.9877** | 0.9772 |
| Required-document hit | **60/60** | **180/180** | 59/60 |
| Latency observations | 70 | 210 | 70 |
| Mean retrieval | 403.5 ms | **281.2 ms** | 467.2 ms |
| p50 | 409.6 ms | **250.8 ms** | 419.9 ms |
| p95 | **522.4 ms** | 536.7 ms | 593.8 ms |
| p99 | **663.4 ms** | 695.4 ms | 1,291.8 ms |
| Retrieval-threshold abstention F1 | not isolated | 0.0000 | 0.0000 |

Interpretation:

- AnythingLLM leads mean and median retrieval latency and has the best MRR and
  nDCG, but its quality advantage is only about 0.8--1.7 percentage points in
  a near-ceiling, single-relevant-document dataset.
- RAGZ has the best measured p95 and p99 in these runs despite a slower mean
  than AnythingLLM. It retrieved the required document for every answerable
  query, but ranked it first slightly less often.
- RAGFlow missed the required document for one query and has the widest tail.
  Its mean is 66.1% slower than AnythingLLM and 15.8% slower than RAGZ.
- The latency protocols are not identical: AnythingLLM has two warmups and
  three repetitions; RAGFlow's scored r3 followed three prior passes without
  a cache reset; RAGZ r2 is a clean no-cache provider run. Do not attach a
  significance claim to the cross-system latency differences yet.

## Answer and RAG-Triad comparison

| Metric | RAGZ large/1,024 | AnythingLLM | RAGFlow large/1,024 |
|---|---:|---:|---:|
| Answerable observations | 60 | not run | 60 |
| Context relevance | 0.9812 | — | **0.9870** |
| Groundedness | 0.9745 | — | **0.9815** |
| Answer relevance | 0.9898 | — | **0.9918** |
| Correctness | 0.9787 | — | **0.9877** |
| Citation validity | **1.0000** (N=59) | — | 0.9833 (N=60) |
| Answer abstention F1 | 0.9000 | — | **0.9474** |
| Mean retrieval+generation | 3,553.7 ms measured | — | 3,722.1 ms estimated/noncoincident |
| Mean with judge | **5,228.6 ms measured** | — | 5,376.0 ms estimated/noncoincident |

RAGFlow has the larger automated-judge means, but the differences are small,
the judge is a separate model on the same provider rather than an independent
human evaluator, and the RAGFlow total is an arithmetic composition of
noncoincident retrieval and QA passes. AnythingLLM cannot be ranked for answer
quality because no answer/Triad calls were made.

RAGZ's usage-derived `$0.25521224` includes embedding, answer, and judge calls.
RAGFlow's `$0.28185800` covers answer and judge only; ingestion and query
embedding cost is unavailable. AnythingLLM's retrieval row has no comparable
answer/judge cost. The totals are therefore not a fair cost ranking.

## Why each system dominates where it does

### AnythingLLM: shortest hot retrieval path

The default LanceDB path performs one query embedding and one in-process cosine
search. `performSimilaritySearch()` calls `embedTextInput()` and then the
non-reranked `similarityResponse()`; LanceDB opens the table, runs
`vectorSearch(...).distanceType("cosine").limit(topN)`, applies the threshold,
and returns sources. See:

- `server/utils/vectorDbProviders/lance/index.js:176-215`
- `server/utils/vectorDbProviders/lance/index.js:410-459`

This path has no sparse embedding, RRF fusion, external vector-database hop,
tenant ACL projection/recheck, or extra no-answer probe. That economy explains
its mean/p50 advantage. Optional native reranking expands to 10--50 candidates
and is explicitly documented as expensive (`index.js:92-160`), but it was not
part of this baseline. The tradeoff is less retrieval-stage observability and
no calibrated abstention in the measured row.

### RAGZ: provider-bound latency plus production safety and hybrid work

RAGZ's production path resolves workspace/model configuration, releases the DB
transaction, optionally expands the query, embeds dense and BM25 sparse forms,
applies tenant/ACL/current-version filters, sends dense+sparse lanes to Qdrant
RRF, rechecks authorization, deduplicates, optionally reranks, and performs an
extra dense probe for the no-answer threshold. See
`backend/src/ragz/modules/retrieval/service.py:485-764`.

That work buys multi-tenant security, hybrid recall, current-version semantics,
optional reranking, and the admin-only multi-query switch. It also creates more
hops than AnythingLLM. In the networking product trace, however, almost all
time is not local safety logic: the hosted dense embedding dominates.

### RAGFlow: flexible search pipeline and the heaviest runtime

RAGFlow's public endpoint validates dataset ownership and embedding
compatibility, resolves model configuration, optionally expands keywords,
calls `Dealer.retrieval`, prunes deleted-document chunks, applies backend
fusion/reranking rules, thresholds, stable sorting, child/KG enhancement, and
response field mapping. See:

- `api/apps/restful_apis/chunk_api.py:329-455`
- `rag/nlp/search.py:562-710`

Even at the measured `vector_similarity_weight=1`, no keyword expansion and no
external reranker, `Dealer.search()` constructs dense search plus a near-dense
weighted fusion (`0.001,1`) for Infinity and crosses API, worker and Infinity
process boundaries (`rag/nlp/search.py:134-219`). This helps explain why it is
slower and has a wider tail than in-process LanceDB. Its 512-token newline-aware
native chunks produced 415 chunks versus RAGZ's 467 approximately
2,000-character/15%-overlap chunks. The coarser index may have helped its
answer context while still missing one document-level query.

The RAGFlow run also exposed an Infinity first-table race during concurrent
initial ingestion. Sequential recovery completed 22/22 documents, but the
user-approved 5 GB-plus-swap smoke reached 98.27% of the RAGFlow slice and is
not sustained-stability evidence.

## Atomic latency analysis

### Hosted embedding boundary

The 2,000-request OpenAI embedding matrix is the foundational result shared by
all three systems. For persistent `text-embedding-3-large`/1,024:

| Batch | Total mean | Total p50 | Total p95 | HTTP/provider mean | Local build+decode+validate | Provider share |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 328.705 ms | 302.148 ms | 455.229 ms | 328.283 ms | 0.422 ms | 99.87% |
| 32 | 724.466 ms | 722.157 ms | 908.186 ms | 717.085 ms | 7.382 ms | 98.98% |

Changing local JSON handling cannot materially fix the observed retrieval
latency. Provider/network placement, connection reuse, batching, and avoiding
duplicate query embeddings are the high-leverage controls.

### RAGZ production retrieval stages

The counterbalanced networking trace has 210 observations per mode and exact
stage closure.

| Stage | Single mean/share | Fixed-three-query mean/share |
|---|---:|---:|
| Dense embedding | 341.952 ms / 92.76% | 410.918 ms / 91.10% |
| Qdrant search/RRF | 8.757 ms / 2.38% | 14.988 ms / 3.32% |
| No-answer probe | 5.619 ms / 1.52% | 11.371 ms / 2.52% |
| ACL prefilter + recheck | 5.344 ms / 1.45% | 5.498 ms / 1.22% |
| Sparse embedding | 0.353 ms / 0.10% | 0.442 ms / 0.10% |
| Total | 368.636 ms | 451.039 ms |

Multi-query adds `82.403 ms`; dense embedding accounts for `68.966 ms`
(83.7%) of that increase, vector search for `6.231 ms` (7.6%), and the extra
no-answer probes for `5.752 ms` (7.0%). The trace used fixed alternatives, so
its `0.140 ms` expansion stage does not measure live Luna generation.

Indexing shows the same bottleneck: dense embedding is 90.24% of mean index
time, parsing 6.40%, Qdrant upsert 2.77%, sparse embedding 0.54%, and chunking
0.05%.

### Answer pipeline

| Layer | RAGZ mean/share | RAGFlow mean/share |
|---|---:|---:|
| Retrieval | 403.519 ms / 7.72% | 467.227 ms / 8.69% |
| Luna generation | 3,150.007 ms / 60.25% | 3,254.878 ms / 60.55% |
| GPT-5.4-mini judge | 1,674.593 ms / 32.03% | 1,653.819 ms / 30.76% |
| Total with judge | 5,228.618 ms measured | 5,375.967 ms estimated/noncoincident |

Generation dominates user-facing latency in both systems. The judge is
benchmark-only overhead. Retrieval optimization alone cannot reduce the
roughly 3.6--3.7 second retrieval-plus-answer path below one second.

AnythingLLM currently exposes only end-to-end retrieval timing in this
campaign. Its source has no benchmark spans around query embedding, table open,
Lance search, result materialization, filtering and source curation. Any claim
that a particular AnythingLLM substage dominates would be inference, not a
measurement.

## How to make RAGZ materially faster and better

The order matters. Optimizing a 0.35 ms sparse encoder while ignoring a 342 ms
hosted embedding call cannot move the user experience.

### P0: remove or hide hosted-model waits

| Change | Measured basis | Expected effect | Main risk / required guard |
|---|---|---|---|
| Versioned query-embedding cache | Dense embedding is 341.95 ms / 92.76% of single retrieval | Repeated-query hits can remove most of ~342 ms | Key by model, dimension and normalized-query hash; bound TTL/size; never persist raw query text |
| Versioned answer cache | Generation is ~3.15 s / 60.25% of measured end-to-end | Repeated approved answers can save seconds | Key by org, workspace, ACL/security projection, document-index generation, model and prompt version; fail closed on any mismatch |
| Context/token budgeter | Generation dominates and five chunks are always available | Fewer input tokens should reduce generation latency and cost | Keep required evidence; quality/citation floors must gate rollout |
| Speculative multi-query | Current code waits for Luna expansion before original retrieval | Start original embedding/search immediately; late-fuse alternatives within a deadline | Generated alternatives must not delay or replace a good single result |
| Cache query expansion | Same normalized query/model/prompt produces reusable alternatives | Removes the live Luna expansion wait on repeats | Version prompt/model; hash-only key; bounded TTL; original query always retained |

The multi-query controller should have a strict latency budget. A practical
flow is:

1. Start original-query dense/sparse retrieval immediately.
2. Start Luna expansion concurrently.
3. If alternatives arrive before the frozen budget, batch-embed them and fuse.
4. Otherwise return the single-query result and optionally record a late result
   for offline analysis; never hold the user request indefinitely.

This preserves the measured single-query floor while allowing multi-query to
help ambiguous queries. The current fixed-three-query result improves MRR by
`+0.0556` and nDCG by `+0.0045`, but lowers Recall by `-0.0151`; it does not
justify enabling expansion for every query.

### P1: shorten the retrieval critical path

| Change | Current cost | Target |
|---|---:|---:|
| Launch dense no-answer probe concurrently with the fused Qdrant request | 5.62 ms single / 11.37 ms multi after fusion | Hide most of the probe behind vector search |
| Cache successful collection schema readiness by `(collection, dimension)` | 2.76--2.80 ms/request | Pay once per process/model generation |
| Consolidate workspace/model/ACL reads without weakening the post-query recheck | ~7--10 ms combined DB/security stages | Save round trips while retaining fail-closed enforcement |
| Reuse one application-scoped LiteLLM HTTP client | Client currently constructed in every `embed_with_usage()` call | Reduce connection/object churn; validate with a controlled same-order probe |

The no-answer probe can run beside the RRF request because both depend only on
the already-computed dense vectors and authorization filter. Its result is
needed only at the final decision. This changes scheduling, not threshold
semantics.

Do not remove the post-query ACL recheck for speed. It closes a real
read-then-query race, costs only about 1.2--1.4 ms, and is not the bottleneck.

### P1: make indexing incremental and provider-efficient

Dense embedding is 90.24% of index time. The current batch size of 32 is
correct: the atomic matrix shows a large/1,024 batch of 32 completes in
724.5 ms total, versus 328.7 ms for one input. Improvements should therefore
focus on avoiding calls rather than shrinking Python chunking code.

- Cache document embeddings by `(model, dimension, canonical-text SHA-256)`.
- Reuse unchanged chunk vectors across document versions and duplicate uploads.
- Persist an index manifest mapping source hash to chunk hash and vector ID.
- Re-embed only changed chunks; delete superseded vectors transactionally.
- Adapt batch concurrency to provider rate-limit headers while keeping batch
  width at the measured efficient point.
- Keep Qdrant upserts batched; they are only 2.77% of current indexing time.

### P1: improve quality without applying expensive features globally

- Enable multi-query only for ambiguous, multi-hop or demonstrated low-recall
  query classes. Exact/simple questions should stay single-query.
- Invoke a reranker only inside an uncertainty band, for example when top
  candidates are close or the dense/no-answer confidence is marginal.
- Use hybrid lane weights or RRF parameters selected on the development split,
  then freeze them before the locked run.
- Add parent/section-aware context assembly so repeated chunks from one document
  do not crowd out other required evidence.
- Calibrate abstention separately for dense cosine, RRF and reranker score
  spaces. One numeric threshold is not portable across them.
- Route low-risk document-level workspaces to small/1,024 only after a frozen
  quality gate. On Open Manuals it saves about 16 ms retrieval mean and lowers
  cost, but the current differences are not statistically decisive and do not
  cover exact-page networking quality.

### P2: improve perceived answer latency

Generation, not retrieval, dominates the full answer path. Add and optimize:

- provider time-to-first-token, first-byte and tokens/second spans;
- immediate SSE flush once the first provider token arrives;
- prompt-prefix caching where supported;
- smaller evidence payloads selected by the context budgeter;
- concise answer/output-token defaults with user-overridable depth;
- optional answer generation started from high-confidence early retrieval only
  when later retrieval cannot invalidate the cited evidence.

The benchmark judge is not on the production path and must never be included
in user-facing latency SLOs.

### Optimization acceptance gates

Every optimization must run against the same commit/corpus/query order and
publish both cold and warm results.

| Gate | Required outcome |
|---|---|
| Security | All tenant/ACL/current-version and race-closure tests pass; no permissive fallback |
| Reliability | Exact denominator, zero unclassified errors, no OOM/restart |
| Retrieval quality | No Recall@5 regression larger than 0.02; MRR/nDCG reported with paired CI |
| Answer quality | No material groundedness/citation regression; human-calibrated sample included |
| Single-query latency | Improve p50 and p95 against 380.7/461.6 ms networking baselines |
| Multi-query latency | Live expansion has a frozen deadline; p95 cannot exceed the agreed SLO |
| End-to-end latency | Report TTFT separately; reduce retrieval+generation, not benchmark-judge time |
| Cost | Usage-derived embedding/generation cost cannot increase without a predeclared quality gain |

### Recommended implementation order

1. Add TTFT/token and missing cache-hit telemetry.
2. Implement document-vector reuse and query-embedding cache with versioned,
   privacy-safe keys.
3. Parallelize the no-answer probe and cache collection readiness.
4. Implement speculative, deadline-bound multi-query with expansion caching.
5. Add context budgeting and prompt-prefix caching.
6. Add uncertainty-gated reranking and query-class-gated multi-query.
7. Re-run the normalized and native foundational tracks before changing any
   production default.

## Foundational benchmark audit

| Requirement | Current status |
|---|---|
| Pinned source/image/model/dimension/corpus | Strong |
| Exact 70-query denominator and zero-error gating | Strong |
| Document Recall/MRR/nDCG and off-corpus behavior | Strong |
| Same answer/judge model | RAGZ/RAGFlow only |
| Identical chunking and candidate semantics | Missing; native-product track differs |
| Identical warmups/repetitions/cache state | Missing |
| Per-stage retrieval spans for all systems | RAGZ only |
| Full-run CPU/RAM/swap/disk telemetry | Missing; RAGFlow has smoke-only sampling |
| End-to-end provider cost | RAGZ only |
| Paired three-system significance tests | Missing |
| Blinded human judge calibration | Missing |
| Locked 420-query exact-claim networking set | Contract exists; not executed |

The current campaign is strong evidence about these exact configurations, but
it is not yet a defensible universal leaderboard.

## Strong next benchmark protocol

1. Run two tracks:
   - **Native product:** each system's production chunker/index/retriever.
   - **Normalized retrieval:** identical prebuilt chunks, OpenAI
     large/1,024 embeddings, candidate depth 50, top five, no reranker.
2. Use both Open Manuals and the locked networking set. Do not call the 420
   networking questions gold until two reviewers plus adjudication finish.
3. Separate cold-index, cold-query and warm-query results. Use two warmups and
   at least ten scored repetitions per query, Latin-square system order, with
   cache state recorded rather than inferred.
4. Require a common atomic schema:
   `request_parse`, `query_expand`, `query_embed`, `lexical_embed`,
   `vector_search`, `fusion`, `rerank`, `filter/dedupe`, `serialize`,
   `generation`, `judge`, plus wall-clock closure.
5. Add spans at these exact source seams:
   - AnythingLLM: `embedTextInput`, `openTable`, `vectorSearch/toArray`,
     threshold/filter, `curateSources`.
   - RAGFlow: `get_vector`, datastore search, deleted-chunk prune, fusion or
     reranker, threshold/sort/page assembly, response mapping.
   - RAGZ: retain the existing stage timings.
6. Calibrate abstention thresholds only on the development split; freeze them
   before the locked run. Report precision/recall/F1 and coverage-risk curves.
7. Report document, exact-section/page, and atomic-claim metrics separately.
   Add citation entailment/completeness and blinded human calibration.
8. Capture CPU, RSS, swap, disk, index time, provider tokens and usage-derived
   cost over the entire run. Abort on incomplete denominators, OOM/restart,
   provenance mismatch or any unclassified provider error.
9. Use paired bootstrap intervals and paired permutation/sign-flip tests by
   query; apply Holm correction across the frozen metric family.

Only after this protocol should small differences such as MRR `0.9833` versus
`0.9750` drive a product-default decision.

## Evidence

- `docs/benchmarks/artifacts/2026-08-23-open-manuals-clean-pair-analysis-r2.json`
- `docs/benchmarks/artifacts/2026-08-23-ragz-large1024-product-analysis.json`
- `docs/benchmarks/artifacts/raw/2026-08-23/anythingllm-open-manuals-large-1024-20260823-r2/`
- `docs/benchmarks/artifacts/raw/2026-08-23/ragflow-open-manuals-large1024-retrieval-20260823-r3/`
- `docs/benchmarks/artifacts/raw/2026-08-23/ragflow-open-manuals-large1024-triad-20260823-r1/`
- `docs/benchmarks/artifacts/raw/2026-08-23/openai-embedding-atomic-matrix-20260823-r1/`
