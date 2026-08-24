# Add bounded, superadmin-controlled multi-query retrieval

Closes: `#<accepted-issue-number>`

## What this changes

- Adds a migrated `multi_query_enabled` workspace setting, defaulting to off.
- Enforces superadmin-only mutation in the service and route policy; the UI
  control is hidden from admins and users.
- Adds single-versus-multi answer comparison without mutating the workspace.
- Expands into bounded query perspectives and fuses all dense/sparse lanes in
  one filtered Qdrant RRF request.
- Starts the original embedding speculatively while expansion is in flight and
  falls back to Q1 on a bounded deadline or provider failure.
- Adds bounded process-local TTL/LRU caches for query embeddings and expansions.
- Adds bounded transient Cohere retries, deterministic tie ordering and an
  overlapping no-answer probe.
- Adds low-cardinality cache, expansion and rerank-stage metrics.
- Adds component, API, retrieval, isolation and Playwright coverage.

## Security properties preserved

Every lane uses the same org/workspace/ACL/current-version Qdrant filter and the
existing fail-closed security-projection exclusion. The post-query ACL recheck
is unchanged. Server-side authorization rejects non-superadmin mutations, so UI
hiding is not the security boundary. No query text, generated alternatives,
credentials, authorization headers or provider response bodies are emitted in
the new metrics or public evidence.

## Configuration and rollback

Production Compose enables the two bounded caches and uses a 3,000 ms expansion
deadline; application/unit-test defaults remain conservative. MQR and reranking
remain off per workspace.

Operators can independently roll back behavior by:

1. disabling `multi_query_enabled` on the workspace;
2. disabling the query-expansion cache;
3. disabling the query-embedding cache; or
4. leaving `rerank_enabled` off.

The additive database column can remain in place during rollback.

## Measured result

On the frozen three-book exact-page benchmark, Q3 did not improve Recall over
Q1. The feature therefore remains opt-in. Warm query-embedding caching reduced
Q1 mean/p95 retrieval from `728.49/913.52 ms` to `16.93/19.68 ms`, with exactly
matching Recall/MRR/nDCG. Warm query-expansion cache lookup had p50/p95
`0.017/0.047 ms` and made zero provider calls across 24 repeats.

The normalized 20-page-interval follow-up reported RAGZ Q1 Recall/MRR/nDCG
`0.8250/0.6583/0.7002`, RAGZ Q3 `0.8000/0.6792/0.7096`, and AnythingLLM
`0.8000/0.6517/0.6890`. AnythingLLM remained faster because it indexed the
scoring intervals directly and used a different chunking/ranking pipeline.
RAGFlow and Onyx were protocol-gated for this exact corpus and were not assigned
fabricated zero scores. These results are not a universal product ranking.

## Verification

- Focused backend MQR/cache/retry/isolation tests: `102 passed`
- Frontend unit/component suite: `701 passed`
- Ruff: passed
- Strict mypy (`src`, 161 files): passed
- ESLint and TypeScript: passed
- Production frontend build: passed
- Initial bundle: `171.5 kB` gzip against a `200 kB` budget
- Production Compose render: passed
- Alembic: one head (`6a8d2c4f1b90`)
- Full backend and final Playwright checks: fill from `review-checklist.md` at
  the exact commit immediately before opening the PR

## Review guide

Suggested order:

1. migration, workspace schema and authorization policy;
2. query expansion parser/cache and query embedding cache;
3. retrieval orchestration, filter reuse and failure fallbacks;
4. Cohere retry behavior and metrics;
5. frontend role gating and comparison screen; and
6. tests and production configuration.

## Known limitations

- Caches are per process, so replicas do not share warm state.
- MQR quality is corpus-dependent and did not beat Q1 Recall on the frozen
  exact-page corpus.
- Expansion adds a provider call on a cold key and can increase cost/latency.
- The 3,000 ms deadline is a guardrail, not a guarantee on total retrieval time.
- Cohere retries can extend rerank latency within the configured bounds.
- Exact large-books scores for RAGFlow and Onyx require frozen native adapters;
  they are not claimed by this PR.
