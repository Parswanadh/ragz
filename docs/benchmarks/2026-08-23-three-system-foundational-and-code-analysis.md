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
