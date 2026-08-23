# Multi-query retrieval landscape and RAGFlow benchmark status

Date: 2026-08-22

## Executive result

- RAGZ now has default-off, workspace-scoped multi-query retrieval using the
  original question plus at most two generated alternatives and Qdrant RRF.
- Only a superadmin sees the control in the settings UI or can change the persisted
  value through the API/service. Workspace readers can still observe the boolean in
  `WorkspaceOut`, and ordinary members receive the configured retrieval behavior.
- With `text-embedding-3-small` at 1,536 dimensions on both products, RAGZ multi
  reached Recall@5 `0.7244`, versus AnythingLLM `0.7272`. RAGZ single led MRR@5
  at `0.8778`, versus AnythingLLM `0.8611`.
- Those are 20-page-interval qrels. The raw exact-page small/1,536 parity run
  reports Recall@20 `0.446140` (single) and `0.484362` (multi); the measures
  are not interchangeable or evidence of a regression.
- The attested Open Manuals r2 pair uses no cache, `text-embedding-3-small` or
  `text-embedding-3-large` at 1,024 dimensions, `gpt-5.6-luna` generation, and
  a separate `gpt-5.4-mini` judge. Over 60 answerable and 10 off-corpus
  queries, large/small correctness is `0.9787/0.9547`, retrieval mean is
  `403.5/387.5 ms`, and provider cost is `$0.25521/$0.23143` (large premium
  `10.28%`). The paired quality and latency tests have no Holm-significant
  difference; citation validity is measured over 59 queries with citations in
  both conditions. Both manifests share proxy fingerprint
  `e5a2913bf2fe061ba9811d8c102b740230c33ee549cc34e507aa03639200eb31` and
  record commit `5b9241dc7d8a05520b05953dd2a018f49d22830f` with dirty working
  tree plus primary file hashes. Imported siblings in the partly untracked
  benchmark-lab tree are not exhaustively hashed, so this is source-bound
  dirty-base evidence rather than a fully reproducible clean-commit gate.
- RAGFlow v0.27.0 was cloned and pinned locally, then run API-only on the native
  daemon. Its scored r3 retrieval reached Recall@5 `0.983333`, MRR@5
  `0.975000`, and nDCG@5 `0.977182` over 60 answerable queries; a separate
  sanitized triad pass measured context relevance `0.9870`, groundedness
  `0.9815`, answer relevance `0.991833`, and answer-abstention F1 `0.947368`.
  These are manually guarded quality observations, not a sustained-stability
  claim.

## What current systems mean by “multi-query”

These features should not be collapsed into one benchmark row. Parallel semantic
rewrites, keyword expansion, query decomposition, HyDE, graph search, and repeated
agent tool calls have different model-call budgets and fusion behavior.

| System | Current behavior | Default / control | Classification |
|---|---|---|---|
| RAGZ | Original plus up to two utility-model alternatives; dense and BM25 lanes fused with RRF | Default off; persisted toggle is superadmin-only | Runtime semantic multi-query |
| RAGFlow v0.27.0 | Public retrieval accepts one question. Auto-question/auto-keyword enrich chunks during indexing. Native advanced/agentic modules generate multiple queries and recursive searches, but are not a stable ordinary retrieval API toggle | No first-class public runtime toggle verified | Single-query public API plus native advanced/agentic multi-query |
| LangChain | `MultiQueryRetriever` generates three alternatives and unions unique documents | Optional component; original excluded by default | Runtime semantic multi-query |
| LlamaIndex | `QueryFusionRetriever` defaults to original plus three generated queries and supports simple, RRF, relative-score, and distance fusion | Optional; `num_queries=4` | Runtime query fusion |
| Haystack | `QueryExpander` defaults to four generated alternatives plus the original; multi-query retrievers execute supplied lists | Optional stable components | Runtime semantic multi-query |
| Open WebUI | Retrieval-query generation asks for one to three queries, with single-query fallback | Enabled by default; admin task configuration | Runtime semantic multi-query |
| Onyx | Generates a semantic rephrase plus up to three keyword queries and uses weighted RRF in internal search | Native agent/tool path; no ordinary end-user toggle | Agentic multi-query search |
| AnythingLLM | Documented standard RAG embeds the question once; an agent may call RAG Search repeatedly | No first-class deterministic multi-query control verified | Single-query default; optional agent repetition |
| Dify | “Multiple retrieval” fans the same query across multiple datasets | Workflow setting | Multi-dataset, not multi-query |
| Microsoft GraphRAG | DRIFT generates iterative follow-up questions and local-search branches | Agentic depth/follow-up controls | Iterative graph query expansion |
| LightRAG | Extracts high/low-level keywords and combines local/global/vector branches | Retrieval-mode control | Multi-branch hybrid, not conventional multi-query |

## Primary-source evidence

- RAGFlow normal chat/retrieval path and query handling:
  [dialog service](https://github.com/infiniflow/ragflow/blob/v0.27.0/api/db/services/dialog_service.py),
  [HTTP API](https://github.com/infiniflow/ragflow/blob/v0.27.0/docs/references/http_api_reference.md),
  [auto-question/auto-keyword](https://github.com/infiniflow/ragflow/blob/v0.27.0/docs/guides/dataset/advanced/autokeyword_autoquestion.mdx),
  [tree-structured multi-query decomposition](https://github.com/infiniflow/ragflow/blob/v0.27.0/rag/advanced_rag/tree_structured_query_decomposition_retrieval.py),
  and [agentic RAG](https://github.com/infiniflow/ragflow/blob/v0.27.0/rag/advanced_rag/agentic_rag.py).
- LangChain:
  [`MultiQueryRetriever`](https://github.com/langchain-ai/langchain/blob/master/libs/langchain/langchain_classic/retrievers/multi_query.py).
- LlamaIndex:
  [`QueryFusionRetriever`](https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/retrievers/fusion_retriever.py).
- Haystack:
  [QueryExpander](https://docs.haystack.deepset.ai/docs/queryexpander),
  [multi-query text retriever](https://github.com/deepset-ai/haystack/blob/main/haystack/components/retrievers/multi_query_text_retriever.py),
  and [multi-query embedding retriever](https://github.com/deepset-ai/haystack/blob/main/haystack/components/retrievers/multi_query_embedding_retriever.py).
- Open WebUI:
  [query-generation defaults](https://github.com/open-webui/open-webui/blob/main/backend/open_webui/config.py)
  and [retrieval middleware](https://github.com/open-webui/open-webui/blob/main/backend/open_webui/utils/middleware.py).
- Onyx:
  [internal search tool](https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/tools/tool_implementations/search/search_tool.py)
  and [query expansion](https://github.com/onyx-dot-app/onyx/blob/main/backend/onyx/secondary_llm_flows/query_expansion.py).
- AnythingLLM:
  [standard RAG](https://docs.anythingllm.com/chatting-with-documents/rag-in-anythingllm)
  and [RAG Search agent skill](https://docs.anythingllm.com/agent/usage/rag-search).
- Dify:
  [dataset retrieval implementation](https://github.com/langgenius/dify/blob/main/api/core/rag/retrieval/dataset_retrieval.py).
- Microsoft GraphRAG:
  [query overview](https://microsoft.github.io/graphrag/query/overview/)
  and [DRIFT search](https://microsoft.github.io/graphrag/query/drift_search/).
- LightRAG:
  [official repository and retrieval modes](https://github.com/HKUDS/LightRAG).

## RAGFlow clone and resource evidence

The dedicated local checkout is:

```text
../ragflow-v0.27.0
```

It is clean and detached at the official release tag:

```text
version: v0.27.0
commit: ec9c08d809f63ba2815090182fa225899d2437d5
```

Official RAGFlow requirements are at least four x86 cores, 16 GB effective host/
Docker-daemon RAM, 50 GB disk, and `vm.max_map_count >= 262144`. The pinned
Compose configuration sets a per-container `MEM_LIMIT=8073741824` bytes; that
setting is not a substitute for the official 16 GB runtime floor. The Docker
Desktop endpoint exposes only `3864363008` memory bytes. Its disk and kernel-map
values were not independently verified inside the daemon/VM namespace. A later
explicitly selected native endpoint (`unix:///var/run/docker.sock`) measured
`16246616064` daemon bytes and hosted the scored run. These are two endpoint
observations, not time-varying measurements of one daemon. Every result manifest
retains the endpoint string and daemon fingerprint so rows cannot be merged
accidentally.

Endpoint ledger:

| Endpoint label | Docker endpoint | Daemon memory | Interpretation |
|---|---|---:|---|
| Docker Desktop | current Docker Desktop context (endpoint not explicitly pinned in the preflight artifact) | `3864363008` bytes (3.86 GB) | not used for scored run |
| Native daemon | `unix:///var/run/docker.sock` | `16246616064` bytes (16.25 GB) | scored API-only endpoint; disk and `vm.max_map_count` remain host caveats |

The native project used RAGFlow, reduced-memory Infinity, MySQL, MinIO, and
Redis, with no TEI, DeepDoc, local embedding, local generation, or reranking
service. The r6 resource artifact is a three-minute smoke only. During the
quality run, an initial concurrent 22-document ingestion exposed an Infinity
first-table race; 17 tasks were cancelled, the app was restarted once, and the
unfinished tasks were indexed sequentially. Final preflight reached 22/22 DONE,
415 chunks, and zero document failure messages. The scored project was stopped
project-scoped after measurement with no containers left running. This supports
the recorded quality result but does not establish sustained stability.

The user-approved 5 GB-plus-swap smoke used a `5,000,000,000`-byte aggregate
budget. RAGFlow peaked at `2,260,226,539 / 2,299,954,987` bytes (`98.27%`),
maximum swap growth was `4,917,555,200` bytes, minimum host `MemAvailable` was
`824,561,664` bytes, and maximum memory PSI avg10 was `7.79`; the sampled smoke
recorded zero OOM kills and zero restarts. These samples cover only the
three-minute smoke, not the full manually guarded quality run.

The scored r3 retrieval pass used 22 documents and 415 chunks, 70 queries
(60 answerable and 10 off-corpus), and zero errors. Recall@5 was `0.983333`
(59/60), MRR@5 `0.975000`, and nDCG@5 `0.977182`, with mean/p50/p95/p99
retrieval latency `467.227/419.919/593.821/1,291.788 ms`. Its zero-threshold
retrieval abstention F1 was `0`. The separate sanitized triad pass used the
same 60-answerable/10-off-corpus denominator: context relevance `0.9870`,
groundedness `0.9815`, answer relevance `0.991833`, citation validity
`0.983333` (N=60), and answer-abstention TP=9, FP=0, FN=1, TN=60,
F1=`0.947368`. Generation mean was `3,254.878 ms`; judge mean was
`1,653.819 ms`. Arithmetic estimates for retrieval+generation and
retrieval+generation+judge were `3,722.106 ms` and `5,375.967 ms`, not
measured wall times. QA cost was `$0.281858` for answer plus judge only;
embedding ingestion/query cost was unavailable and excluded.

The run used `text-embedding-3-large` at 1,024 dimensions, `gpt-5.6-luna`
generation, and `gpt-5.4-mini` judging through proxy fingerprint
`e5a2913bf2fe061ba9811d8c102b740230c33ee549cc34e507aa03639200eb31`. It is
bound to RAGFlow v0.27.0 commit `ec9c08d809f63ba2815090182fa225899d2437d5`
and image digest
`sha256:e9fe71c5ff14762eeb8e251b3b8ed37c02a99ae2bad3d7b11467260ced79578b`.
The earlier r1/r2 artifacts are warmup-only invalid provenance; r3 had two
public warmups plus one private capture pass, with no cache reset.

The low-memory runner performs an explicit `docker compose --project-name … ps
--all -q` project-collision guard before writing its generated override or
starting services. Project reuse is always refused; the runner never stops a
project that already had containers before this run.

This already assumes API-only models. Since v0.22.0 RAGFlow ships only the slim
image and no longer bundles embedding models; v0.27.0 explicitly relies on external
LLM and embedding services. Switching between Elasticsearch and Infinity changes
the document engine but does not provide an officially supported profile that
removes the RAG index, metadata database, object store, cache, API, and workers
while preserving a native RAGFlow benchmark.

Evidence:

- `docs/benchmarks/artifacts/raw/2026-08-22/ragflow-networking-preflight-20260822-ec9c08d/`
- `docs/benchmarks/artifacts/raw/2026-08-23/ragflow-native-daemon-swap-smoke-20260823-r6/`
- `docs/benchmarks/artifacts/raw/2026-08-23/ragflow-open-manuals-large1024-retrieval-20260823-r3/`
- `docs/benchmarks/artifacts/raw/2026-08-23/ragflow-open-manuals-large1024-triad-20260823-r1/`
- `docs/benchmarks/artifacts/raw/2026-08-23/open-manuals-publication-large-1024-nocache-gpt54judge-20260823-r2/`
- `docs/benchmarks/artifacts/raw/2026-08-23/open-manuals-publication-small-1024-nocache-gpt54judge-20260823-r2/`
- `docs/benchmarks/artifacts/2026-08-23-open-manuals-clean-pair-analysis-r2.md`
- [RAGFlow v0.27.0 quick start](https://github.com/infiniflow/ragflow/blob/v0.27.0/docs/quickstart.mdx)

## Same-model contract for a compliant RAGFlow host

This is the future networking/20-page-interval parity contract, not the
completed large/1,024 Open Manuals row above. The completed row uses
document-level Open Manuals qrels and RAGFlow's native top-five chunk response.

| Layer | Required value |
|---|---|
| Embedding provider | OpenAI through one shared, attested endpoint |
| Embedding model | `text-embedding-3-large` |
| Embedding dimension | 1,024 |
| Answer model | `gpt-5.6-luna` |
| Expansion model | `gpt-5.6-luna` |
| Reranker | Disabled for the parity baseline |
| Retrieval cutoff | Five unique 20-page evidence intervals |
| Native candidate depth | 50 before interval deduplication |
| Warmups / scored repetitions | 2 / 3 |

`text-embedding-3-large` at 1,024 dimensions was bound through the shared
OpenAI-compatible proxy and its observed Infinity vector width was 1,024.
`gpt-5.6-luna` does not; it requires RAGFlow's custom OpenAI-compatible path
through the verified LiteLLM endpoint, which was executed for the scored run.
Credentials remain in environment/secret storage and never enter manifests or
command arguments.

## Required RAGFlow rows on a compliant host

1. `ragflow_native_single`: one public retrieval call per question.
2. `ragflow_native_advanced_agentic`: pin and execute RAGFlow's advanced/agentic
   multi-query implementation separately from the stable public API path.
3. `ragflow_normalized_fixed_three_query`: original plus the exact two fixed RAGZ
   alternatives, adapter-side RRF. This isolates retrieval/index differences.
4. `ragflow_generated_three_query`: original plus two alternatives generated by
   the same `gpt-5.6-luna` prompt used by RAGZ, adapter-side RRF.
5. RAGZ single and RAGZ multi using the already validated OpenAI embedding track.

RAGFlow’s auto-question enrichment must be a separate indexing-time row. It must
not be described as runtime multi-query retrieval.

Before changing the RAGZ embedding default, regenerate a controlled exact-page
pair for small/1,536 and large/1,024 on the same commit, corpus, candidate
depth, repetitions, and qrels. The existing large/1,024 versus historical
small/1,536 networking comparison is descriptive only and cannot support a
default decision.

## Blocked versus incomplete

RAGFlow's native API-only benchmark is complete for the 70-query Open Manuals
retrieval/triad observation, but the run is manually guarded and its resource
sampling is smoke-only. A clean-ingest repeat on a higher-memory host remains
preferable before making a sustained-operability or production-performance
claim. RAGFlow Cloud itself remains credential-gated because no cloud API key
was available.
