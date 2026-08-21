# Networking Multi-Query Retrieval Benchmark

## Question

Does RAGZ query-time expansion improve page-level retrieval on a large technical
corpus enough to justify its latency and provider cost?

## Corpus

Three user-supplied, unencrypted networking textbooks are read from their local
paths. They total 2,582 PDF pages and approximately one million extractable words.
The repository and benchmark artifacts contain no textbook passages or extracted
text. They record only filename, SHA-256, size, page count, independently authored
questions, alternative queries, and page-level evidence locators.

## Paired RAGZ conditions

Both conditions reuse one index and hold constant PDF bytes, LiteParse version,
heading chunker, dense/sparse representations, Qdrant collection, ACL filter,
top-k, reranker setting, query order, hardware, and cache state.

- **Single:** `multi_query_enabled=false`; original query supplies one dense and
  one sparse lane.
- **Multi:** `multi_query_enabled=true`; the original plus two fixed, pre-recorded
  alternatives supply six lanes fused by Qdrant RRF.

Fixed alternatives make the retrieval comparison reproducible and isolate fusion
from model sampling. A separate native/live cell must measure LiteLLM expansion
latency, tokens, cost, failure rate, and alternative count before making production
latency claims.

## Gold labels

Questions cover terminology mismatch, comparisons, calculations, multi-evidence
concepts and off-corpus behavior. Each of the three books is annotated independently
with PDF page numbers. The held-out set should be adjudicated by a second
networking-literate reviewer. Query text must be independently phrased rather than
copied from the books.

## Metrics

- page-level Recall@5, MRR@5 and nDCG@5;
- evidence coverage and cross-book diversity;
- retrieval p50/p95/p99 and error rate;
- paired per-query metric/latency deltas with bootstrap confidence intervals;
- native expansion latency, input/output tokens, cost and fallback rate;
- indexing parse time, chunk count and total indexing time.

Recall/MRR/nDCG and their paired bootstrap deltas include only successful,
answerable queries. Unanswerable probes have no relevance labels and are evaluated
only through abstention precision/recall/F1; failed calls are excluded from both
quality and abstention denominators and reported separately as errors. Every run
must supply and record an explicit no-answer threshold in the maximum-dense-cosine
score space. Pilot threshold selection must be labeled as development-set
calibration rather than a production default.

## Open-source comparison policy

Use the same corpus and query order, but keep tracks separate:

- **Normalized:** common extracted chunks, models, top-k and fusion.
- **Native:** each product's documented parser/index/retrieval behavior.

AnythingLLM is feasible on this host and should be rerun in an isolated project.
RAGFlow, Onyx, FastGPT and Dify remain resource-gated on the current Docker memory
allocation; adapter-missing systems remain unmeasured. No gated system receives a
zero score. Framework feature-enabled results must state the exact flow/strategy
(for example R2R RAG-Fusion or Flowise Multi Query Retriever) and must not be
presented as that product's default behavior.

## Privacy and reproducibility

Run directories are immutable and refuse overwrite. Per-query artifacts contain
IDs, ranks, scores, page locators, timings, counts and typed errors only. They must
not contain queries, alternatives, document text, answers, provider response bodies,
keys, headers or tokens. Source hashes, code commit, dirty state, configuration and
tool versions are mandatory in the manifest.
