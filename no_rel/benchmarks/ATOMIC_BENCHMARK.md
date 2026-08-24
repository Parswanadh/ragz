# Atomic benchmark navigation record

Last updated: 2026-08-25

The canonical, detailed record is
[`docs/benchmarks/ATOMIC_BENCHMARK.md`](../../docs/benchmarks/ATOMIC_BENCHMARK.md).
This copy exists under `no_rel` so later agents can find the result from the
repository's research/navigation area without duplicating the long report.

## Current decision

- Keep Q1/no-rerank as the default.
- Keep MQR superadmin-only and disabled by default.
- Use three lanes only after a workspace-specific evaluation; Q5 is not the
  default.
- Query-provider latency dominates cold retrieval. The bounded query-embedding
  cache is the highest-confidence latency improvement because it preserved exact
  quality while reducing Q1 mean/p95 from `728.49/913.52 ms` to
  `16.93/19.68 ms` in the post-change confirmation.
- Q3 did not improve Recall on the frozen exact-page corpus and added
  `656.50 ms` cold or `16.83 ms` warm versus Q1.
- Warm expansion-cache lookup was effectively local (`0.017/0.047 ms` p50/p95)
  and made zero provider calls on 24 repeated queries.

## Normalized open-source boundary

On common 20-page interval qrels with OpenAI large/1,024 embeddings, RAGZ Q1
scored Recall/MRR/nDCG `0.8250/0.6583/0.7002`, RAGZ Q3 scored
`0.8000/0.6792/0.7096`, and AnythingLLM scored
`0.8000/0.6517/0.6890`. AnythingLLM was faster because it indexed the scoring
intervals directly and used a different chunking/ranking path. RAGFlow and Onyx
remain protocol-gated for this exact corpus; they do not receive zero scores.

## Source documents

- `docs/benchmarks/2026-08-24-ragz-mqr-rerank-cache-results.md`
- `docs/benchmarks/2026-08-24-mqr-production-confirmation.md`
- `docs/benchmarks/2026-08-25-normalized-four-system-followup.md`
- `docs/benchmarks/artifacts/2026-08-24-mqr-production-confirmation.json`
- `docs/benchmarks/artifacts/2026-08-25-large-books-open-source-followup.json`
