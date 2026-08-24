# RAGZ MQR, rerank-pool, cache, atomic-latency and RAG-Triad benchmark

Date: 2026-08-24  
Status: completed, with fail-closed repair provenance  
Branch: `codex/multi-query-retrieval`

## Decision

Use **one query, no reranker** as the RAGZ default on the tested large-books
workload. Keep MQR behind the superadmin control and keep it off unless a
workspace-specific evaluation shows a gain. If reranking is explicitly enabled,
retain candidate pool **P=50** as the opt-in default for now; it was the only
reranked one-query configuration on the retrieval Pareto frontier, but it still
lost `0.05` absolute Recall@5 and added about `700.7 ms` mean Cohere provider
time.

Enable a versioned query-embedding cache after productionizing its invalidation,
replication and bounded-retention policy. Warm hits reduced mean retrieval from
`678.47` to `19.00 ms` for one query, from `940.83` to `42.80 ms` for three
queries, and from `928.84` to `54.78 ms` for five queries.

Pin Luna query expansion to `reasoning_effort=low`. This reduced the five-lane
expansion mean from `6,635.31` to `2,814.25 ms`, p95 from `21,559.85` to
`3,580.19 ms`, eliminated retries (`19/24` first-attempt success to `24/24`),
and eliminated four deterministic fallback lanes. Even after that improvement,
uncached live expansion is too slow for an unconditional synchronous path;
cache it and/or race it against the original-query retrieval under a deadline.

These are one-observation-per-query configuration results over 20 answerable
and four off-corpus queries. They select a conservative default; they are not a
statistical proof that MQR or reranking cannot help another corpus.

## Frozen protocol

| Field | Value |
|---|---|
| Corpus | `large-books-v1`: three public PDFs, 4,412 physical pages |
| Indexed chunks | 18,734 production LiteParse/heading chunks |
| Query denominator | 24: 20 answerable, four off-corpus |
| Retrieval qrels | Exact physical PDF page |
| Dense embedding | OpenAI `text-embedding-3-large`, 1,024 dimensions |
| Sparse/fusion | FastEmbed BM25 plus Qdrant RRF |
| Query lanes | Original only; original + two; original + four |
| Rerank pools | Off, 10, 20, 50; final `top_k=5` |
| Reranker | Cohere `rerank-v4.0-fast` through the provider API |
| Answer model | `gpt-5.6-luna`, Responses API, reasoning effort `low` |
| Judge | separate `gpt-5.4-mini`, reasoning effort `low` |
| Context | five retrieved chunks, bounded to 30,000 characters |
| LLM `top_p` | provider default; not sent and not varied |
| “P” in this report | pre-rerank candidate pool, not nucleus sampling |
| Public privacy | no question, alternative, context, answer, reference, credential or provider body |

The four alternative-query perspectives were:

1. exact entities, numbers, protocol names, negation, scope and constraints;
2. terminology, synonyms, acronyms and formal manual vocabulary;
3. mechanisms, prerequisites, cause/effect and implicit failure modes; and
4. evidence phrasing likely in definitions, headings, standards,
   configuration guides or troubleshooting material.

The original query always remained lane one. Four private alternatives were
generated once per source query and reused across MQR=3 and MQR=5 so the
retrieval comparison did not confound query-count with fresh LLM randomness.

## Retrieval and RAG-Triad results

`Retrieval p95` below removes only the benchmark's Cohere account-throttle wait.
It retains OpenAI query embedding, Cohere provider time, database/ACL work,
Qdrant RRF and all local processing.

| Configuration | Recall@5 | MRR@5 | nDCG@5 | Context relevance | Groundedness | Answer relevance | Correctness | Retrieval p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Q1, rerank off | **0.6000** | 0.4767 | **0.5074** | 0.8910 | **0.9755** | 0.8475 | 0.7880 | **1,188.25 ms** |
| Q1, P=10 | 0.4500 | 0.4000 | 0.4131 | 0.9195 | 0.9720 | **0.8560** | 0.7340 | 1,626.73 ms |
| Q1, P=20 | 0.5500 | 0.4600 | 0.4824 | **0.9605** | 0.8820 | 0.7995 | **0.8135** | 1,661.23 ms |
| Q1, P=50 | 0.5500 | **0.4917** | 0.5065 | 0.8835 | 0.9570 | 0.8110 | 0.7565 | 1,894.29 ms |
| Q3, rerank off | **0.6000** | 0.4642 | 0.4974 | 0.9175 | 0.9535 | 0.8030 | 0.7020 | 1,612.95 ms |
| Q3, P=10 | 0.5500 | 0.4600 | 0.4824 | 0.8960 | 0.8850 | 0.8400 | 0.7300 | 2,026.98 ms |
| Q3, P=20 | 0.5000 | 0.4500 | 0.4631 | 0.8770 | 0.9720 | 0.7725 | 0.7205 | 1,832.80 ms |
| Q3, P=50 | 0.5500 | **0.4917** | 0.5065 | 0.9065 | 0.9250 | 0.8540 | 0.8030 | 2,010.90 ms |
| Q5, rerank off | 0.5500 | 0.4517 | 0.4759 | 0.8105 | 0.9670 | 0.7630 | 0.7020 | 1,298.69 ms |
| Q5, P=10 | **0.6000** | 0.4700 | 0.5018 | 0.9220 | 0.9280 | 0.8190 | 0.7320 | 2,544.96 ms |
| Q5, P=20 | 0.5000 | 0.4500 | 0.4631 | 0.9070 | 0.9515 | 0.8120 | 0.7350 | 1,872.42 ms |
| Q5, P=50 | 0.5000 | 0.4750 | 0.4815 | 0.9510 | 0.9660 | 0.8210 | 0.7450 | 2,164.79 ms |

The Pareto calculation maximized Recall, MRR and nDCG while minimizing
throttle-adjusted retrieval p95. Only `q1_rerank-off_cache-off` and
`q1_rerank-50_cache-off` survived. Q1/no-rerank is the safer production
standard because it has higher recall, higher nDCG, better groundedness and
lower latency. Q1/P=50 remains a real tradeoff only for its `+0.015` MRR gain.

MQR=3 preserved Q1 recall without reranking but did not improve MRR, nDCG,
answer relevance or correctness. MQR=5/no-rerank reduced recall and every
reported answer-quality component except groundedness. Q5/P=10 recovered
recall to `0.60`, but Q1/no-rerank dominated it on MRR, nDCG and latency.

All 12 configurations had citation validity `1.0`. Citation-to-exact-qrel-page
precision/recall remained much lower (`0.44–0.56` / `0.45–0.55`), which is a
useful warning: a citation can be structurally valid and grounded in retrieved
text without pointing to the benchmark's exact reference page.

Answer abstention F1 ranged from `0.6154` to `0.7273`. Retrieval-level
`min_score=0` still cannot abstain; the answer model correctly abstained on all
four off-corpus questions but also abstained on some answerable questions.
Score-space-specific threshold calibration remains required.

## Query-embedding cache experiment

| Query lanes | Cache-off mean | Cold population mean | Warm-hit mean | Warm p95 | Mean saved | Speedup |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 678.47 ms | 723.10 ms | **19.00 ms** | 21.38 ms | 659.46 ms | **35.70×** |
| 3 | 940.83 ms | 932.89 ms | **42.80 ms** | 49.14 ms | 898.03 ms | **21.98×** |
| 5 | 928.84 ms | 1,052.51 ms | **54.78 ms** | 59.91 ms | 874.06 ms | **16.96×** |

The scored warm conditions recorded exactly 24/72/120 cache hits and zero
misses. The cache-off conditions recorded the inverse. A `-0.025` Q1 MRR delta
between independent off and warm passes is not evidence that caching changes
quality: the cached vector came from a different hosted-embedding call and
equal-score Qdrant RRF candidates were observed to change order/boundary slot.
Do not reuse answer/Triad output unless the exact context hash matches.

The implemented cache is a bounded process-local benchmark seam. Production
needs a versioned key over model ID, provider model, dimension and normalized
query hash; bounded TTL/size; metrics; and either a shared cache or an explicit
per-replica hit-rate model. Raw queries must not be public cache keys.

## Query-expansion latency A/B

| Five-lane Luna expansion | Mean | p50 | p95 | p99 | First-attempt success | Fallback lanes | Completion tokens | Cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Provider-default reasoning | 6,635.31 ms | 3,482.78 ms | 21,559.85 ms | 23,743.28 ms | 19/24 | 4 | 5,300 | $0.00784 |
| Reasoning effort `low` | **2,814.25 ms** | **2,781.47 ms** | **3,580.19 ms** | **3,597.10 ms** | **24/24** | **0** | **4,002** | **$0.00628** |

Low reasoning cut mean latency `57.6%`, p95 `83.4%`, and completion tokens
`24.5%`. It is now pinned in RAGZ's Luna expansion payload. This A/B validates
latency/schema completion, not the retrieval quality of the newly generated
alternatives; the 12-condition quality matrix used the original frozen
alternative set.

Official OpenAI guidance says GPT-5.6 supports explicit reasoning effort and
recommends `low` for latency-sensitive workloads. RAG query rewriting and
extractive answering fit that shape. See
<https://developers.openai.com/api/docs/guides/latest-model>.

## Atomic latency

### Default Q1/no-rerank

| Stage | Mean | p50 | p95 | Mean share of retrieval |
|---|---:|---:|---:|---:|
| OpenAI dense embedding | 801.85 ms | 763.23 ms | 1,165.13 ms | 95.5% |
| Qdrant hybrid search/RRF | 10.31 ms | 9.90 ms | 12.47 ms | 1.2% |
| Dense no-answer probe | 5.97 ms | 5.53 ms | 7.13 ms | 0.7% |
| Sparse BM25 embedding | 4.69 ms mean* | 0.35 ms | 0.60 ms | 0.6% |
| ACL prefilter | 2.93 ms | 2.25 ms | 5.78 ms | 0.3% |
| Workspace/model resolution | 2.11 ms | 2.10 ms | 2.87 ms | 0.3% |
| Retrieval total | **839.50 ms** | **791.22 ms** | **1,188.25 ms** | 100% |

`*` One sparse outlier raises the mean; its median and p95 remain sub-millisecond.

Dense embedding is still the foundational bottleneck. Removing local ACL,
BM25 or Qdrant safety work would save little and weaken the product. The cache
result confirms that avoiding the hosted embedding call is the high-leverage
change.

### Q1/P=50 rerank

| Stage | Mean | p95 |
|---|---:|---:|
| OpenAI dense embedding | 799.30 ms | 817.21 ms |
| Cohere provider | 710.70 ms | 1,038.93 ms |
| Qdrant candidate search | 15.73 ms | 24.38 ms |
| Local rerank processing | near zero | near zero |
| Intrinsic retrieval (quota wait removed) | **1,539.09 ms** | **1,894.29 ms** |
| Benchmark account-throttle wait | 876.31 ms | 2,604.27 ms |
| Observed rate-gated retrieval | **2,415.40 ms** | **4,012.09 ms** |

The Cohere trial/account limit was empirically about 9–10 RPM. Static gates of
9 and even 8 RPM still produced isolated 429s; the final repair succeeded at 6
RPM. Production should honor `Retry-After`, use bounded jittered retry/circuit
logic, and expose queue wait separately from provider time. Do not describe
the roughly 2.4-second observed mean as pure model latency.

### Answer path

For Q1/no-rerank, mean Luna generation was `3,062.64 ms`, the separate judge
was `2,537.46 ms`, and retrieval+answer+judge was `6,439.78 ms`. The judge is
benchmark-only. User-facing retrieval+generation is about `3,902 ms` in this
run; answer streaming/TTFT, a context token budgeter and answer caching matter
more than micro-optimizing local retrieval code.

The complete 288-answer/288-judge pass used 551,995 Luna input tokens, 51,764
Luna output tokens, 591,895 judge input tokens and 68,083 judge output tokens.
Usage-derived answer+judge cost was `$0.92281055` against a `$5` hard cap.

## Open-source comparison boundaries

No score is invented for an unexecuted system, and metrics from different
corpora/evidence units are not placed in one winner column.

### Same large-books corpus

| System | Embedding | Page metric | Document retrieval | Retrieval latency | Status/boundary |
|---|---|---|---|---|---|
| RAGZ Q1/no-rerank | OpenAI large/1,024 | Recall/MRR/nDCG `0.6000/0.4767/0.5074` | Recall/MRR `1.0/1.0` | screen p50/p95 `720.15/826.97 ms` | Production path, exact-page capable |
| AnythingLLM v1.16.0 | OpenAI small/default width | unavailable | Recall/MRR `1.0/1.0` | p50/p95 `336.86/410.99 ms` | Same corpus, different embedding; native chat OOM, completed answer track external |
| Onyx v4.6.0 Standard | not run | unavailable | unavailable | unavailable | Native daemon now passes official CPU/RAM/disk preflight; stack not executed |
| RAGFlow v0.27.0 | not run on this corpus | unavailable | unavailable | unavailable | Existing completed result uses Open Manuals, not large-books |

The current native Docker daemon exposes 22 CPUs, 16,246,620,160 bytes RAM and
183,061,700,608 bytes free disk, so Onyx is now `eligible_not_executed`, not
resource-gated. Starting and scoring it is a separate high-resource campaign;
the previous 3.6-GiB Docker Desktop gate must not be reused as its current
status.

### Same large/1,024 embedding on Open Manuals

The prior 22-document/70-query track remains the best direct three-system
retrieval comparison:

| Metric | RAGZ | AnythingLLM | RAGFlow |
|---|---:|---:|---:|
| Recall@5 | **1.0000** | **1.0000** | 0.9833 |
| MRR@5 | 0.9667 | **0.9833** | 0.9750 |
| nDCG@5 | 0.9754 | **0.9877** | 0.9772 |
| Mean retrieval | 403.5 ms | **281.2 ms** | 467.2 ms |
| p50 | 409.6 ms | **250.8 ms** | 419.9 ms |
| p95 | **522.4 ms** | 536.7 ms | 593.8 ms |

RAGFlow's same-model Open Manuals RAG-Triad was context relevance `0.9870`,
groundedness `0.9815`, answer relevance `0.9918` and abstention F1 `0.9474`.
Those values cannot be ranked against the present large-books result because
the corpus, query denominator, chunking, retrieval protocol and reasoning
settings differ.

## Why AnythingLLM leads some same-model metrics

The model is only the text-to-vector function; identical models do not make
retrieval systems identical.

1. AnythingLLM's hot LanceDB baseline is one query embedding plus one
   in-process dense cosine search. RAGZ also computes BM25, applies
   tenant/workspace/current-version/ACL filters, crosses a Qdrant boundary,
   performs RRF, rechecks authorization and runs a separate no-answer probe.
2. Chunk boundaries and text differ. AnythingLLM's indexed units align more
   directly with some benchmark evidence units; RAGZ uses finer heading-aware
   chunks and maps them back to pages/documents after search.
3. Candidate depth and ranking differ. Dense cosine, hybrid RRF and optional
   cross-encoder reranking can return different top five items from the same
   embedding model.
4. MQR trades coverage against first-hit rank. Extra lanes add candidates but
   can displace the first relevant result, lowering MRR even when recall is
   unchanged.
5. AnythingLLM's speed advantage does not include RAGZ's policy enforcement or
   page-attributable evidence. Conversely, those features do not excuse RAGZ's
   avoidable duplicate provider waits.

## Confirmed benchmark/harness findings

The campaign found and patched several real defects rather than averaging over
them:

1. A matrix with five query failures was incorrectly marked `completed`; the
   runner now fails the campaign when any condition has an error.
2. Cohere usage units were cumulative across conditions; summaries now report
   condition-local deltas.
3. A networking-specific helper mislabeled `large-books-v1`; dataset identity
   is now an explicit runner argument. The original r2 manifest remains intact
   and a signed post-run correction records the error.
4. “Rerank latency” included benchmark account throttling; confirmation now
   splits quota wait, Cohere provider and local work without double counting.
5. Qdrant RRF ties can reorder or change the equal-score boundary candidate
   after snapshot restoration. The runner records exact, tie-equivalent,
   boundary-tie, drift and repaired states, and never reuses answer/Triad output
   across a changed context hash.
6. Default-medium reasoning exhausted 1,000- and 3,000-token strict JSON budgets
   on a table query. Low reasoning completed the same query and bounded output.
7. The Triad runner now supports provenance-checked resume: the final r7 reused
   only 287 zero-error rows from r6 and reran the one failed cell. The final
   grid has 288 unique zero-error cells and 576 uniquely sequenced provider
   calls.

## Improvement order

1. **Ship the query-embedding cache carefully.** It has the largest measured
   retrieval payoff. Add TTL/size bounds, model/dimension/prompt-version
   namespaces, distributed invalidation or explicit replica-local semantics,
   hit/miss telemetry and privacy-safe hashed keys.
2. **Keep MQR off by default.** If enabled, use three total lanes before five,
   cache expansions and run the original query immediately in parallel. Fuse
   alternatives only if they arrive before a strict deadline.
3. **Keep reranking off by default; P=50 when explicitly enabled.** Route it
   only for uncertain/ambiguous queries and calibrate its score-space threshold
   separately. Add provider-aware retry/backoff and a concurrency limiter.
4. **Make RRF ties deterministic.** Apply a stable secondary key after score
   ordering so equal-score candidates do not produce context drift.
5. **Reuse an application-scoped LiteLLM HTTP client.** The current embedder
   constructs a client per call. Validate connection reuse with a same-order
   probe.
6. **Run the no-answer dense probe concurrently with fused Qdrant search.** It
   costs roughly 6–17 ms and depends on the same already-computed vectors.
7. **Cache unchanged document embeddings and batch incrementally.** Dense
   embedding remains the dominant ingestion and retrieval layer.
8. **Budget answer context and stream immediately.** Generation dominates the
   user-facing answer path; record TTFT and tokens/second, not only completion.
9. **Expand evaluation before changing defaults.** Add at least 100 answerable
   and 30 adversarial off-corpus questions, repeated counterbalanced runs,
   bootstrap paired deltas, Holm correction, concurrency/load tests and human
   review of a blinded answer sample.

Do not remove ACL rechecks or hybrid retrieval merely to chase AnythingLLM's
shorter path. They are not the dominant cost and enforce RAGZ's product
contract.

## Evidence

- Machine analysis:
  `docs/benchmarks/artifacts/2026-08-24-ragz-large-books-mqr-rerank-cache-triad.json`
- Short generated table:
  `docs/benchmarks/artifacts/2026-08-24-ragz-large-books-mqr-rerank-cache-triad.md`
- Complete zero-error Triad run:
  `docs/benchmarks/artifacts/raw/2026-08-24/ragz-large-books-mqr-rerank-triad-20260824-r7/`
- Retrieval/cache screen and validation:
  `docs/benchmarks/artifacts/raw/2026-08-24/ragz-large-books-mqr-rerank-cache-matrix-20260824-r2/`
- Original and low-reasoning expansion evidence:
  `docs/benchmarks/artifacts/raw/2026-08-24/ragz-mqr-five-perspective-expansions-20260824-r6/`
  and `...expansions-low-20260824-r8/`
- Onyx native-daemon preflight:
  `docs/benchmarks/artifacts/raw/2026-08-24/onyx-native-daemon-preflight-20260824/`
- Foundational three-system code analysis:
  `docs/benchmarks/2026-08-23-three-system-foundational-and-code-analysis.md`

Qdrant guidance used for the causal design:

- <https://qdrant.tech/documentation/concepts/hybrid-queries/>
- <https://qdrant.tech/documentation/guides/optimize/>
- <https://qdrant.tech/documentation/concepts/indexing/#tenant-index>
