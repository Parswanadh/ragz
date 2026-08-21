# RAGZ Multi-Query Retrieval: Implementation, Branch, and Benchmark Report

**Date:** 2026-08-21  
**Feature branch:** `codex/multi-query-retrieval`  
**Fork:** <https://github.com/Parswanadh/ragz/tree/codex/multi-query-retrieval>  
**Base:** upstream `b23949853fa2c76584218d68ec619685525568ab`  
**Scored feature commit:** `e981c93150cec801d327b198a13f874dc3ecefe5`

## Executive result

Current upstream RAGZ has dense+sparse hybrid retrieval, Qdrant RRF, optional
reranking, ingestion-time hypothetical-question enrichment, heuristic escalation,
and an agent that may perform several sequential searches. It does **not** have a
dedicated query-time multi-query expansion, query rewrite, HyDE, or decomposition
abstraction.

This branch adds a default-off workspace toggle. When enabled, the designated
utility model produces at most two alternatives in addition to the exact original
query. Every dense and sparse lane inherits the same tenant/workspace/version/ACL
filter and Qdrant RRF fuses them. Reranking runs once against the original user
query. Missing utility configuration, malformed output, or provider failure
degrades to single-query retrieval.

On a 12-question page-labeled networking pilot with 8,374 locally parsed chunks,
fixed alternatives improved every mean ranking metric at the cost of additional
retrieval latency. The result supports keeping the feature optional and proceeding
to a larger production-embedding/live-expansion evaluation; it does not justify
enabling it by default yet.

## What changed

- ADR-0007 records query count, fusion, failure, security and cost semantics.
- `LiteLLMQueryExpander` uses a delimited data prompt, strict bounded parsing,
  sanitized errors, and usage metadata.
- `Workspace.multi_query_enabled` is default-off and Alembic-backfilled.
- Workspace API/read-only views and the generated frontend client expose the flag.
- The workspace settings dialog provides an on/off checkbox and explains the extra
  utility-model call and latency.
- `retrieve()` embeds all variants in one dense batch, generates sparse vectors per
  variant, constructs filtered dense+sparse prefetches, uses Qdrant RRF, deduplicates
  once, and preserves existing rerank/no-answer semantics.
- Query-expansion tokens use the existing usage ledger under
  `feature="query_expansion"`.
- New tests cover parsing, provider errors, default/round-trip authorization,
  migration backfill, six filtered lanes, usage, no-answer, one rerank call against
  the original query, and cross-tenant isolation.

## Corpus and gold labels

| Book ID | PDF pages | Parsed chunks | LiteParse time in clean repeated run |
|---|---:|---:|---:|
| `forouzan-2022` | 861 | 3,500 | 8.325 s |
| `kurose-2021` | 775 | 1,851 | 5.414 s |
| `tanenbaum-2021` | 946 | 3,023 | 9.351 s |
| **Total** | **2,582** | **8,374** | **23.089 s** |

The books were parsed locally with LiteParse. Committed artifacts contain only
independently authored questions, alternatives, SHA-256 hashes and PDF page
locators. No PDF or extracted textbook passage is committed or stored in result
artifacts.

The 12 questions cover bandwidth-delay product/window scaling, GBN versus SR,
distance-vector failure, BGP policy, hidden terminals, DNS resolution, CRC, packet
versus circuit switching, NDP versus ARP, TCP congestion control, HTTP multiplexing,
and NAT tradeoffs. Each book was annotated independently; low-confidence absent
support was excluded (for example, the Forouzan NAT pages are not qrels).

## Paired RAGZ benchmark

### Fixed configuration

- Local LiteParse, heading chunking
- Deterministic hash dense vectors, 1,024 dimensions
- FastEmbed BM25 sparse vectors
- Qdrant v1.18 RRF
- No reranker
- `top_k=5`
- Same index, workspace, filters, qrels and query order
- Two warmups and three repetitions
- Fixed two alternatives for reproducible retrieval/fusion comparison
- No hosted provider calls or cost in this scored cell

### Clean repeated result (`single-first`, 36 observations/condition)

| Metric | Single query | Multi-query | Absolute delta | Relative delta |
|---|---:|---:|---:|---:|
| Mean page Recall@5 | 0.1501 | 0.2069 | +0.0568 | +37.8% |
| Mean MRR@5 | 0.5926 | 0.6944 | +0.1019 | +17.2% |
| Mean nDCG@5 | 0.3678 | 0.5466 | +0.1788 | +48.6% |
| Retrieval p50 | 21.48 ms | 35.25 ms | +13.77 ms | +64.1% |
| Retrieval p95 | 24.45 ms | 38.86 ms | +14.41 ms | +58.9% |
| Errors | 0 | 0 | 0 | — |

Query-level paired bootstrap (10,000 resamples, seed 42):

| Metric delta | Improved / regressed / tied queries | 95% bootstrap CI |
|---|---:|---:|
| Recall@5 | 8 / 1 / 3 | +0.0149 to +0.0972 |
| MRR@5 | 8 / 1 / 3 | -0.0394 to +0.2222 |
| nDCG@5 | 10 / 1 / 1 | +0.0846 to +0.2873 |

Recall and nDCG improvements are positive in this small pilot's bootstrap interval;
MRR remains uncertain. One query regressed, demonstrating why the toggle should
remain default-off.

### Reverse-order sensitivity run

The `multi-first` run also improved mean recall, MRR and nDCG, but ran concurrently
with a CPU/memory-heavy AnythingLLM cold index, inflating tails. It is retained as
order-sensitivity evidence, not the headline latency result.

### Run artifacts

- Failed seed preflight:
  `no_rel/benchmarks/results/runs/ragz-networking-mq-paired-20260821-adb4bf2/`
- One-repetition pilot:
  `no_rel/benchmarks/results/runs/ragz-networking-mq-paired-20260821-adb4bf2-r2/`
- Reverse-order repeated run:
  `no_rel/benchmarks/results/runs/ragz-networking-mq-paired-20260821-e981c93-r3/`
- Clean repeated headline run:
  `no_rel/benchmarks/results/runs/ragz-networking-mq-paired-20260821-e981c93-r4/`

Privacy scans found no query, alternative, document text, API key or authorization
field in the successful raw run artifacts.

## Open-source comparator status

### AnythingLLM native attempt

The pinned AnythingLLM v1.16.0 native MiniLM/LanceDB adapter was run on 131
temporary twenty-page segments, with 12 original queries and 54 segment qrels.
The server disconnected during cold native indexing after memory reached an
observed `1.99 GiB / 2 GiB` limit. Because the container had already been removed
when logs were requested, OOM was not independently proven. The correct result is
**resource-gated failure**, not zero quality.

- Failure artifact:
  `no_rel/benchmarks/results/runs/anythingllm-v1.16.0-native-20260821T052120Z-dad9399e/`
- Quality score emitted: no
- Temporary 6.2 MB extracted-text adapter dataset: deleted
- Existing open-manuals AnythingLLM result remains valid for its original corpus;
  it is not substituted for this networking run.

### Capability context from official sources

| System | Verified query transformation capability | Fair comparison note |
|---|---|---|
| RAGFlow | Advanced/experimental multi-query and decomposition | Pin advanced path; not baseline API |
| Flowise | Multi Query Retriever, HyDE and sub-question components | Pin exact flow/version |
| R2R | `rag_fusion` and `hyde` search strategies | Feature-enabled track |
| Haystack | Experimental multi-query plus HyDE/decomposition recipes | Composed pipeline, not default |
| LlamaIndex | Query transforms, HyDE and sub-question engine | Opt-in configuration |
| LangChain | `MultiQueryRetriever` in `langchain-classic` | Pin package/prompt/version |
| Onyx | Agent Search decomposition and parallel investigation | Agent path, not basic search |
| Kotaemon | Full question-decomposition pipeline | Decomposition, not generic expansion |
| AnythingLLM | No first-class deterministic multi-query control verified | Agent behavior is not equivalent |
| Dify / MaxKB / Open WebUI | Custom workflow/agent composition possible | Do not claim native default support |
| LightRAG / GraphRAG | Graph-aware local/global/DRIFT expansion | Separate graph benchmark class |

Heavy native products remain resource-gated on this host: RAGFlow and Onyx need a
larger dedicated benchmark machine; Dify and FastGPT need more Docker headroom.
No unexecuted system receives a numeric score.

## Open branches and integration order

| PR | Scope | Multi-query interaction |
|---|---|---|
| #3 | Agent-loop connection release/import boundaries | May conflict in chat/tenancy context |
| #8 | Stacked on #3; API/service ORM cleanup | Likely tenancy view/settings conflict |
| #4 | Frontend route code splitting | Independent; fixes current bundle warning |
| #5 | Streaming upload ingress | Independent of retrieval |
| #6 | Prometheus and retrieval-stage metrics | Direct conflict in `retrieval/service.py` |
| #7 | Stacked on #6; HTTP tracing | Merge after #6 |

Recommended upstream order is #3 → #8 and #6 → #7; #4/#5 are independent. This
feature branch must be rebased after #6/#7 and #3/#8 land so expansion/vector/fusion
latency remains instrumented and tenancy boundaries stay enforceable.

## Current issues not covered by those PRs

1. TXT/Markdown still route into unsupported LiteParse when explicitly selected.
2. ACL managers can restrict a document away from themselves and lose the ability
   to repair its ACL without a bypass/group change.
3. Production `/readyz` still checks only PostgreSQL.
4. Redis persistence and residual non-outbox task/counter recovery are undefined.
5. Superadmin reranker health always probes local TEI even when Cohere is active.
6. Uploaded HTML/SVG active-content preview remains security-sensitive and should
   be disclosed privately; the repository has no security policy/private reporting.
7. Nightly red-team CI requests generic Python 3.12, resolves to 3.12.3, and fails
   before tests because the project requires >=3.12.4.

Already covered: ACL projection split-brain, upload/delete commit-to-enqueue loss,
and ambient Redis/Celery/KEK test leakage were fixed in merged PR #2.

## Missing product features after open PRs

- Explicit query decomposition/sub-question execution
- Conversational document-query rewriting
- Query-time HyDE
- Tenant/security-revision-aware retrieval caching
- Feedback-driven retrieval/rerank adaptation
- Explicit multilingual retrieval policy and evaluation
- Graph RAG/entity traversal
- Visual/multimodal embeddings and retrieval
- External source connectors with incremental sync and ACL projection
- End-to-end streaming parse/chunk/embed (PR #5 streams only upload ingress)
- Worker metrics/health, alerting/SLOs and HTTP→outbox→Celery trace propagation

## Limits and next evidence required

- The scored expansion variants are fixed, not live model generations. This isolates
  fusion quality but excludes native expansion latency, tokens, cost and variance.
- Hash dense embeddings are a deterministic benchmark baseline, not the production
  bge-m3/OpenAI configuration.
- The question set is a 12-query pilot with initial page annotations, not a public
  benchmark standard. A second human adjudicator and held-out queries are required.
- Approximate retrieval/ties produced small repetition-level variation.
- Page recall is strict: a relevant concept retrieved on an adjacent unlabeled page
  counts as a miss. Qrels need adjudication before release claims.
- The next campaign should run hosted/OpenAI or local bge-m3 embeddings, live utility
  expansion, optional Cohere rerank, larger held-out qrels, and paired answer/citation
  evaluation with settled provider cost.

## Verification snapshot

- Relevant backend baseline: 49 passed
- Multi-query/query-expansion/retrieval/settings/isolation suite: 110 passed
- Workspace API + migration: 28 passed
- Benchmark tooling: 9 passed
- Frontend: 698 passed
- Ruff: passed
- mypy: 158 source files passed
- import-linter: 2 contracts kept
- Frontend lint/typecheck/build: passed
- Full backend pytest: 1,694 passed, 14 skipped, 0 failed
