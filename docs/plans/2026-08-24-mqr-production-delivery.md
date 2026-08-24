# Multi-Query Retrieval Production Delivery Plan

**Goal:** Turn the measured MQR branch into production-ready, reviewable RAGZ
software; prove its authorization and latency behavior; complete normalized
competitor evidence where safely feasible; and prepare issue/PR material without
submitting either.

**Architecture:** Preserve one `retrieve()` security path and layer bounded,
fail-open performance helpers around it. Use process-local, explicitly
replica-local TTL caches with opaque SHA-256 keys; start original-query embedding
concurrently with cached/deadline-bounded expansion; make provider retry and
rate-wait evidence explicit; and stabilize equal-score ordering without removing
ACL filters or rechecks. Keep production defaults Q1/MQR-off/rerank-off, with P=50
when reranking is enabled.

**Tech stack:** Python 3.12+, FastAPI, SQLAlchemy async, Qdrant, httpx, Prometheus,
React/TypeScript, Vitest, Playwright, Docker, LiteLLM/OpenAI, Cohere.

## Global constraints

- Work only in `/home/parshu/projects/rag-comparison-sources/ragz-b91c898` on
  `codex/multi-query-retrieval`; do not edit the shared checkout.
- Do not use Superpowers or full-history subagents.
- `upstream/main` at `9d08839` is already an ancestor; never rebase merely for
  appearance.
- Do not open an issue or PR without a separate user instruction.
- Preserve MQR default off, reranking default off, and superadmin-only mutation.
- Preserve tenant/workspace/ACL/current-version filtering and post-query ACL
  recheck.
- Public artifacts must not contain queries, alternatives, context, answers,
  credentials, auth headers or provider bodies.
- Every live benchmark has a hard budget and zero-error denominator gate.
- Commit and push after every independently reviewable task.

---

### Task 1: Establish the integration and behavior baseline

**Files:**
- Create: `docs/verification/2026-08-24-mqr-production-baseline.md`

**Produces:** An attestation containing upstream merge base, ahead/behind count,
clean status, production defaults, authorization locations and exact verification
commands.

- [x] Record `git merge-base HEAD upstream/main` and
  `git rev-list --left-right --count upstream/main...HEAD`.
- [x] Record the defaults from `Workspace.rerank_enabled` and
  `Workspace.multi_query_enabled`.
- [x] Record the backend authorization in
  `modules/tenancy/service.py::update_workspace` and route defense in
  `api/routes/workspaces.py`.
- [x] Record frontend role gating and the admin/user-hidden tests.
- [x] Run the focused backend/frontend authorization tests and persist only
  command, exit code and counts.
- [x] Commit and push `docs: attest MQR production baseline`.

### Task 2: Production query-embedding cache

**Files:**
- Modify: `backend/src/ragz/core/config.py`
- Modify: `backend/src/ragz/modules/retrieval/embeddings.py`
- Modify: `backend/src/ragz/modules/retrieval/service.py`
- Modify: `backend/src/ragz/observability/metrics.py`
- Modify: `deploy/compose.yaml`
- Modify: `.env.example`
- Test: `backend/tests/modules/retrieval/test_query_embedding_cache.py`
- Test: `backend/tests/modules/retrieval/test_retrieve.py`

**Interfaces:**
- `InMemoryQueryEmbeddingCache(max_entries: int, ttl_seconds: float,
  clock: Callable[[], float] = monotonic)` remains the cache implementation.
- `get_query_embedding_cache(settings: Settings) -> QueryEmbeddingCache | None`
  returns one process-local cache or `None` when disabled.
- `retrieve(..., query_embedding_cache: QueryEmbeddingCache | None = None,
  query_embedding_cache_enabled_override: bool | None = None)` uses the supplied
  cache for tests/benchmarks, otherwise the configured singleton.
- Settings: `query_embedding_cache_enabled`,
  `query_embedding_cache_max_entries`, `query_embedding_cache_ttl_seconds`.

- [x] Add failing tests for TTL expiry, LRU eviction, model/dimension namespace
  misses, vector copying, malformed widths and concurrent correctness.
- [x] Run the cache tests and confirm they fail for missing TTL/config behavior.
- [x] Store `(expires_at, tuple[float, ...])`, remove expired entries under the
  lock, and keep raw text only long enough to hash the key.
- [x] Add the settings with safe bounds: entries `1..100000`, TTL `1..86400`.
- [x] Configure Compose default enabled with `10000` entries and `3600` seconds;
  leave unit tests explicitly disabled unless they inject a cache.
- [x] Add hit/miss/store/expired/evicted Prometheus counters with low-cardinality outcome
  labels only.
- [x] Wire the configured singleton into production retrieval while preserving
  benchmark cache-off overrides.
- [x] Run focused tests, Ruff and strict mypy.
- [x] Commit and push `perf: cache query embeddings with bounded TTL`.

### Task 3: Cached, deadline-bounded speculative MQR

**Files:**
- Modify: `backend/src/ragz/core/config.py`
- Modify: `backend/src/ragz/modules/retrieval/query_expansion.py`
- Modify: `backend/src/ragz/modules/retrieval/service.py`
- Test: `backend/tests/modules/retrieval/test_query_expansion.py`
- Test: `backend/tests/modules/retrieval/test_retrieve_multi_query.py`

**Interfaces:**
- `InMemoryQueryExpansionCache(max_entries, ttl_seconds, clock)` stores only
  `ExpandedQueries` under SHA-256 of prompt version, model, total lanes and query.
- `get_query_expander(settings, max_queries) -> QueryExpander` returns a shared
  cached expander.
- Settings: `multi_query_expansion_timeout_ms=3000`,
  `query_expansion_cache_max_entries=5000`,
  `query_expansion_cache_ttl_seconds=3600`.
- `retrieve()` starts expansion and original dense embedding together. It uses
  alternatives only when expansion finishes before the absolute deadline;
  otherwise it cancels/abandons expansion and returns the Q1 path.

- [x] Add failing cache tests for model/prompt/count isolation, TTL and no raw
  public keys.
- [x] Add failing service tests using events/fake clocks proving original
  embedding begins before expansion finishes.
- [x] Add timeout tests proving slow expansion produces exactly Q1, no leaked
  task, no expansion usage row and no delayed second provider call.
- [x] Add success tests proving timely expansion batches only the alternative
  embedding misses and preserves original-first order.
- [x] Implement the cache and shared expander resolver.
- [x] Refactor dense embedding into a private helper that can embed/cache the
  original lane before alternatives are resolved without duplicating usage.
- [x] Use an absolute monotonic deadline so embedding time consumes the expansion
  budget instead of granting another full timeout afterward.
- [x] Record critical-path `query_expansion`, cache outcome and timeout metrics without
  query/model-cardinality labels.
- [x] Run focused tests, Ruff and strict mypy.
- [x] Commit and push `perf: make multi-query expansion cached and deadline bounded`.

### Task 4: Cohere provider resilience and latency truthfulness

**Files:**
- Modify: `backend/src/ragz/core/config.py`
- Modify: `backend/src/ragz/modules/retrieval/rerank.py`
- Modify: `backend/src/ragz/modules/retrieval/service.py`
- Test: `backend/tests/modules/retrieval/test_rerank.py`
- Test: `backend/tests/modules/retrieval/test_retrieve_rerank.py`

**Interfaces:**
- `CohereReranker(..., max_retries: int, base_backoff_seconds: float,
  sleep: Callable[[float], Awaitable[None]] = asyncio.sleep)`.
- Retry only 408/425/429/500/502/503/504.
- Honor numeric `Retry-After`, bounded to 30 seconds; otherwise exponential
  backoff `base * 2**attempt`, bounded to 8 seconds.
- Expose request attempts and accumulated retry-wait milliseconds for metrics;
  never expose response bodies or credentials.

- [x] Add failing tests for 429→200, 503 exhaustion, no retry on 401, bounded
  `Retry-After`, malformed headers and billed units from the successful call.
- [x] Implement one reusable `httpx.AsyncClient` per reranker instance and the
  bounded retry loop.
- [x] Preserve graceful fusion fallback in production and strict failure in
  benchmark mode.
- [x] Split provider/retry-wait/local latency metrics without double counting.
- [x] Run focused tests, Ruff and strict mypy.
- [x] Commit and push `fix: retry transient Cohere rerank failures safely`.

### Task 5: Deterministic tie ordering and concurrent no-answer probe

**Files:**
- Modify: `backend/src/ragz/modules/retrieval/service.py`
- Test: `backend/tests/modules/retrieval/test_retrieve.py`
- Test: `backend/tests/modules/retrieval/test_retrieve_rerank.py`

**Interfaces:**
- `_stable_chunk_order(chunks)` sorts by descending score, then document UUID,
  page, chunk index and version.
- Reranker ties use the same stable secondary key.
- Dense no-answer probes start concurrently with fused Qdrant search after dense
  vectors and the authorization filter exist; their results are consumed only
  on the non-rerank path.

- [x] Add failing tests that reverse equal-score Qdrant inputs and require
  byte-identical output IDs/order.
- [x] Add failing reranker-tie tests.
- [x] Add scheduling tests proving fused search and probes overlap while every
  query retains the same tenant filter.
- [x] Implement stable ordering before HQ dedupe and after rerank scoring.
- [x] Start probe tasks with structured cancellation; cancel them on empty or
  reranked paths and await cancellation to avoid task leaks.
- [x] Prove ACL prefilter/recheck and no-answer semantics are unchanged.
- [x] Run focused tests, Ruff and strict mypy.
- [x] Commit and push `perf: stabilize retrieval ties and overlap no-answer probe`.

### Task 6: Superadmin product-path verification

**Files:**
- Modify if required: `frontend/src/features/workspaces/workspace-settings-dialog.tsx`
- Modify if required: `frontend/src/features/workspaces/workspace-settings-dialog.test.tsx`
- Modify if required: `backend/tests/api/test_workspaces.py`
- Create: `docs/verification/2026-08-24-mqr-superadmin-product-smoke.md`

**Produces:** Evidence that only superadmins see and mutate MQR, admins/users
cannot forge the PATCH, defaults remain off, and a real enabled workspace returns
`query_count=3` while disabled returns one.

- [x] Run existing component tests for visible/hidden/PATCH behavior.
- [x] Add API tests for superadmin success plus admin/user 403 and unchanged row.
- [x] Add an integration retrieval test for enabled/disabled query counts.
- [x] Run a local browser smoke with a superadmin and retain the admin/user
  negative proof at API/component boundaries; capture only route, role, control
  visibility, response status and setting value.
- [x] Regenerate OpenAPI/TypeScript schema only if the contract changed.
- [x] Commit and push `test: prove superadmin-only MQR product controls`.

### Task 7: Post-change RAGZ confirmation

**Files:**
- Create: `docs/benchmarks/2026-08-24-mqr-production-confirmation.md`
- Create: `docs/benchmarks/artifacts/2026-08-24-mqr-production-confirmation.json`
- Add benchmark scripts/tests only when an existing runner cannot express the
  condition without changing production code.

**Produces:** Q1/Q3 cache cold/warm, expansion cache cold/warm/timeout, Cohere
retry, tie determinism and concurrent-probe measurements on the current commit.

- [x] Freeze code, dataset, provider alias, proxy fingerprint and budget hashes.
- [x] Run two warmups plus five repetitions in forward/reverse order for Q1 and
  Q3/no-rerank.
- [x] Run a 24-query cold/warm expansion A/B using low reasoning.
- [x] Run deterministic tie replay through five repetitions in both condition
  orders on one frozen Qdrant index.
- [x] Run Cohere 429 fault injection locally and one guarded cloud smoke.
- [x] Reject any completed aggregate with errors or missing cells.
- [x] Compare quality against the published Q1 standard; cache/deadline changes
  must not reduce exact-page metrics.
- [x] Commit and push `bench: confirm production MQR latency controls`.

### Task 8: Normalized open-source comparison

**Files:**
- Create: `docs/benchmarks/2026-08-24-normalized-four-system-followup.md`
- Create: `docs/benchmarks/artifacts/2026-08-24-normalized-four-system-followup.json`
- Store raw runs under `docs/benchmarks/artifacts/raw/2026-08-24/`.

**Produces:** Same large-books corpus, large/1,024 embedding, top five, query
order, answer model/reasoning, judge, context budget and cache regime for every
system that exposes a valid path.

- [x] AnythingLLM: rebuild the large-books index with large/1,024 and run 24
  retrieval rows; do not invent physical-page metrics if metadata is absent.
- [x] RAGFlow: retain its completed API-only cloud-model Open Manuals run and
  mark large-books `protocol_gated/not_executed` because the automated adapter
  requires a pre-seeded exact 22-document corpus; do not perform an unaudited
  manual database setup.
- [x] Onyx: retain the eligible native-daemon preflight and mark large-books
  `eligible_protocol_gated/not_executed` because no frozen hosted-model/evidence
  adapter exists; do not spend the 10-GB envelope without a scoreable protocol.
- [x] Record `not_executed`, `credential_gated` or `resource_stopped` rather than
  zero for any incomplete system.
- [x] Compare only common metrics/evidence units and label native adapter paths.
- [x] Commit and push `bench: add normalized four-system follow-up`.

### Task 9: Issue and PR package, without submission

**Files:**
- Create: `no_rel/issues/multi-query-production-delivery/github-issue-body.md`
- Create: `no_rel/issues/multi-query-production-delivery/pull-request-body.md`
- Create: `no_rel/issues/multi-query-production-delivery/review-checklist.md`
- Create: `no_rel/issues/multi-query-production-delivery/README.md`
- Create: `no_rel/benchmarks/ATOMIC_BENCHMARK.md`
- Update: `docs/benchmarks/ATOMIC_BENCHMARK.md`
- Update: `no_rel/verification/AGENT_TOKEN_USAGE_POLICY.md` only if execution
  reveals a new quota failure mode.

- [x] Draft a respectful issue with problem, measured evidence, scope,
  acceptance criteria, security/privacy notes and reproducible commands.
- [x] Draft a PR summary separating product behavior, performance, tests,
  migrations/configuration and benchmark-only files.
- [x] Include rollback: disable cache/MQR/rerank independently through config or
  workspace settings.
- [x] Include every known limitation and explicitly state no universal ranking.
- [x] Run link, JSON/JSONL, credential-pattern and public-text privacy checks.
- [ ] Commit and push `docs: prepare MQR issue and PR package`.

### Task 10: Final verification and cleanup

- [ ] Run Ruff over the backend.
- [ ] Run strict mypy over `src` and every changed script.
- [ ] Run the complete backend suite against native Docker.
- [ ] Run frontend lint, typecheck, unit tests and production build/bundle gate.
- [ ] Run targeted Playwright browser smoke.
- [ ] Parse every new JSON/JSONL artifact and verify unique denominators/hashes.
- [ ] Verify no credentials/private text and no benchmark-owned containers.
- [ ] Move private temporary state to trash after public hashes are durable.
- [ ] Verify branch equals its pushed remote and remains based on upstream main.
- [ ] Do not open the issue or PR; report exact commit, tests and remaining
  external gates.

## Self-review

- Spec coverage: integration, cache, speculative/cached expansion, Cohere
  resilience, deterministic ordering, no-answer overlap, superadmin controls,
  RAGZ confirmation, four-system normalization, issue/PR drafts and cleanup all
  have explicit tasks.
- No placeholders: every conditional has a fail-closed status and exact output
  location; “modify if required” is restricted to already-implemented UI code
  whose audit may prove no change is necessary.
- Type consistency: cache, expander, reranker and retrieval signatures are named
  once and reused by later tasks.
- Execution mode: inline in this session; Superpowers are explicitly prohibited
  by the user.
