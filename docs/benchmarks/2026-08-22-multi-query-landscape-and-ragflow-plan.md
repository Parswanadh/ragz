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
- RAGFlow v0.27.0 was cloned and pinned locally, but its official Docker stack is
  resource-gated on this machine. It receives no quality score.

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
setting is not a substitute for the official 16 GB runtime floor. The live Docker
daemon exposes only `3864363008` memory bytes. Its disk and kernel-map values were
not independently verified inside the daemon/VM namespace, so the stack was not
started.

This already assumes API-only models. Since v0.22.0 RAGFlow ships only the slim
image and no longer bundles embedding models; v0.27.0 explicitly relies on external
LLM and embedding services. Switching between Elasticsearch and Infinity changes
the document engine but does not provide an officially supported profile that
removes the RAG index, metadata database, object store, cache, API, and workers
while preserving a native RAGFlow benchmark.

Evidence:

- `docs/benchmarks/artifacts/raw/2026-08-22/ragflow-networking-preflight-20260822-ec9c08d/`
- [RAGFlow v0.27.0 quick start](https://github.com/infiniflow/ragflow/blob/v0.27.0/docs/quickstart.mdx)

## Same-model contract for a compliant RAGFlow host

| Layer | Required value |
|---|---|
| Embedding provider | OpenAI through one shared, attested endpoint |
| Embedding model | `text-embedding-3-small` |
| Embedding dimension | 1,536 |
| Answer model | `gpt-5.6-luna` |
| Expansion model | `gpt-5.6-luna` |
| Reranker | Disabled for the parity baseline |
| Retrieval cutoff | Five unique 20-page evidence intervals |
| Native candidate depth | 50 before interval deduplication |
| Warmups / scored repetitions | 2 / 3 |

`text-embedding-3-small` exists in the pinned RAGFlow OpenAI catalog.
`gpt-5.6-luna` does not; it requires RAGFlow's custom OpenAI-compatible path
through the verified LiteLLM endpoint. That path has not been executed because
self-hosted RAGFlow is resource-gated and RAGFlow Cloud's custom-provider support
cannot be verified without an authenticated account. Credentials must remain in
environment/secret storage and must never enter manifests or command arguments.

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

## Blocked versus incomplete

RAGFlow is `resource_gated`, not failed quality and not zero. Completing the native
benchmark requires at least 16 GB effective Docker-daemon/host memory plus verified
50 GB daemon disk and daemon/VM `vm.max_map_count >= 262144`. The pinned 8.07 GB
per-container setting alone is insufficient evidence. A 24–32 GB host is preferable
for a side-by-side reproducible run.
