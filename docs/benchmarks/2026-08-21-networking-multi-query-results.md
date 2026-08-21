# RAGZ Multi-Query Retrieval: Synthetic Fusion Pilot and Implementation Report

**Date:** 2026-08-21
**Feature branch:** `codex/multi-query-retrieval`
**Fork:** <https://github.com/Parswanadh/ragz/tree/codex/multi-query-retrieval>
**Base:** upstream `b23949853fa2c76584218d68ec619685525568ab`
**Scored feature commit:** `c020ef1826cd9d9aef9b5846fb5758ad2a583cd4`
**Benchmark status:** synthetic fusion pilot; live expansion/provider cell pending

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

On a 12-answerable-question, 3-off-corpus-probe networking pilot with 8,374 locally parsed chunks,
fixed alternatives improved every mean ranking metric at the cost of additional
retrieval latency. Recall@5 and nDCG@5 had positive paired bootstrap intervals in
both condition orders; MRR@5 remained uncertain. This is evidence about retrieval
fusion with independently fixed alternatives, not a completed live-LLM benchmark.
It supports keeping the feature optional and proceeding to a production-embedding,
live-expansion evaluation; it does not justify enabling it by default.

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
| `forouzan-2022` | 861 | 3,500 | 8.710 s |
| `kurose-2021` | 775 | 1,851 | 5.896 s |
| `tanenbaum-2021` | 946 | 3,023 | 8.458 s |
| **Total** | **2,582** | **8,374** | **23.063 s** |

The books were parsed locally with LiteParse. Committed artifacts contain only
independently authored questions, alternatives, SHA-256 hashes and PDF page
locators. No PDF or extracted textbook passage is committed or stored in result
artifacts.

The 12 questions cover bandwidth-delay product/window scaling, GBN versus SR,
distance-vector failure, BGP policy, hidden terminals, DNS resolution, CRC, packet
versus circuit switching, NDP versus ARP, TCP congestion control, HTTP multiplexing,
and NAT tradeoffs. Each book was annotated independently; low-confidence absent
support was excluded (for example, the Forouzan NAT pages are not qrels).

## Paired RAGZ synthetic fusion pilot

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
- Three post-publication off-corpus probes; retrieval metrics exclude those probes
- Explicit no-answer threshold `0.42` in maximum-dense-cosine score space

### Clean repeated result (`single-first`, 36 observations/condition)

| Metric | Single query | Multi-query | Absolute delta | Relative delta |
|---|---:|---:|---:|---:|
| Mean page Recall@5 | 0.1501 | 0.2165 | +0.0664 | +44.3% |
| Mean MRR@5 | 0.5833 | 0.6986 | +0.1153 | +19.8% |
| Mean nDCG@5 | 0.3313 | 0.4755 | +0.1442 | +43.5% |
| Retrieval p50 | 32.81 ms | 46.32 ms | +13.51 ms | +41.2% |
| Retrieval p95 | 50.16 ms | 57.33 ms | +7.17 ms | +14.3% |
| Retrieval p99 | 54.39 ms | 58.71 ms | +4.33 ms | +8.0% |
| Errors | 0 | 0 | 0 | — |

Query-level paired bootstrap (10,000 resamples, seed 42):

| Metric delta | Improved / regressed / tied queries | 95% bootstrap CI |
|---|---:|---:|
| Recall@5 | 9 / 1 / 2 | +0.0246 to +0.1046 |
| MRR@5 | 8 / 1 / 3 | -0.0208 to +0.2264 |
| nDCG@5 | 10 / 1 / 1 | +0.0619 to +0.2247 |

Recall and nDCG improvements are positive in this small pilot's bootstrap interval;
MRR remains uncertain. One query regressed, demonstrating why the toggle should
remain default-off.

### Reverse-order sensitivity run

The clean `multi-first` run, executed without a competing benchmark, reproduced
the quality direction: Recall@5 0.1526 → 0.2200, MRR@5 0.6250 → 0.6986, and
nDCG@5 0.3476 → 0.4814. Its paired Recall@5 CI was +0.0239 to +0.1077 and nDCG@5
CI was +0.0529 to +0.2140; MRR@5 again crossed zero (-0.0542 to +0.1722).

### Off-corpus abstention result

A development sweep tested maximum-dense-cosine thresholds 0.25, 0.35, 0.40,
0.42, and 0.50. Low thresholds missed all off-corpus probes; 0.50 caught them but
falsely abstained on most answerable queries. The selected 0.42 midpoint is not
held out or production calibrated. In the repeated single-first cell, single-query
precision/recall/F1 was 0.40/0.67/0.50; multi-query was 0.33/0.33/0.33. Multi-query
uses the best dense score across variants, so an alternative can make abstention
less likely. This baseline does not support a production no-answer threshold;
production embeddings need a larger held-out calibration set.

### Run artifacts

- Final clean single-first run:
  `no_rel/benchmarks/results/runs/ragz-networking-mq-synthetic-20260821-c020ef1-r12/`
- Final clean multi-first run:
  `no_rel/benchmarks/results/runs/ragz-networking-mq-synthetic-20260821-c020ef1-r13/`
- Threshold calibration runs: `r7` (`0.25`), `r8` (`0.35`), `r11` (`0.40`),
  `r10` (`0.42`), and `r9` (`0.50`) under the immutable
  `ragz-networking-mq-threshold-calibration-20260821-48ff9ec-*` prefix.
- Committed compact evidence, configurations, hashes, metrics and CIs:
  `docs/benchmarks/artifacts/2026-08-21-networking-multi-query-synthetic-pilot-v2.json`

Earlier `r2`–`r4` pilot values are superseded because their page-level nDCG
calculation counted duplicate chunks from the same PDF page. The corrected runner
deduplicates page evidence before Recall/MRR/nDCG and warms every query in each
condition. The `r5`/`r6` cells corrected that issue; `r12`/`r13` additionally
separate answerable retrieval metrics from unanswerable abstention metrics. Their
manifests record a clean Git tree and the exact scored commit.

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

Live status checked on 2026-08-21: upstream `main` remains
`b23949853fa2c76584218d68ec619685525568ab`; PRs #3–#8 are open and their current
GitHub checks are green. PRs #8 and #7 are stacked on #3 and #6 respectively. The
fork has no open PR, so this work remains a pushed feature branch rather than a
submitted change.

## Current issues not covered by those PRs

The sole open upstream GitHub issue is
[#9, LiteParse silently truncates documents over 1,000 pages](https://github.com/marketcalls/ragz/issues/9).
It includes public-corpus reproductions, resource measurements, acceptance criteria,
and a bounded page-range parsing proposal. It is not fixed on this branch.

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
- The question set is a 12-answerable-query plus 3-off-corpus-probe pilot with initial page annotations, not a public
  benchmark standard. A second human adjudicator and held-out queries are required.
- Approximate retrieval/ties produced small repetition-level variation.
- Page recall is strict: a relevant concept retrieved on an adjacent unlabeled page
  counts as a miss. Qrels need adjudication before release claims.
- The next campaign should run hosted/OpenAI or local bge-m3 embeddings, live utility
  expansion, optional Cohere rerank, larger held-out qrels, and paired answer/citation
  evaluation with settled provider cost.

## Independent final review

A read-only Sol re-review found no remaining Critical or Important branch-local
product or benchmark defect. It independently recomputed the `r12`/`r13` quality
means, abstention confusion matrices/F1, paired deltas, bootstrap intervals and
improved/regressed/tied counts; verified every committed raw-artifact, calibration
manifest and query-set hash; and found no prohibited query/text/auth fields in raw
per-query artifacts. The known upstream PR/migration integration conflict remains
an external merge blocker rather than a resolved branch claim.

## Verification snapshot

- Final full backend pytest after the harness correction: 1,708 passed, 14 skipped,
  0 failed
- Final benchmark-tooling focused suite: 13 passed
- Tenant/workspace/group-ACL focused suite: 3 passed
- Frontend Vitest: 698 passed, 0 failed
- Ruff: passed
- mypy: 158 source files passed
- import-linter: 2 contracts kept
- Frontend lint/typecheck/build: passed
- Alembic: one head (`6a8d2c4f1b90`)
- Docker Compose configuration and Git whitespace checks: passed
