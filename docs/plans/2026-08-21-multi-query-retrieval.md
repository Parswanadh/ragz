# Multi-Query Retrieval Implementation and Benchmark Plan

> **For agentic workers:** Execute this plan task-by-task on
> `codex/multi-query-retrieval`. Do not use Superpowers in this project session.
> Preserve the shared checkout and the existing `no_rel/benchmarks` campaign.

**Goal:** Add default-off, workspace-configurable multi-query retrieval to RAGZ,
verify it without weakening tenant/ACL guarantees, and measure single-query versus
multi-query quality, latency, and cost on three networking textbooks and feasible
open-source RAG comparators.

**Architecture:** When enabled, a designated utility model generates at most two
alternative searches in addition to the original query. RAGZ embeds all variants
in one dense batch, builds one sparse vector per variant, and sends every dense and
sparse lane through the same Qdrant tenant/ACL filter. Qdrant RRF fuses the lanes;
the existing reranker runs once against the original user query. Expansion is a
retrieval aid only and is never cited as evidence.

**Tech stack:** Python 3.12+, FastAPI, SQLAlchemy/Alembic, LiteLLM-compatible HTTP,
Qdrant Query API/RRF, React/TypeScript, Vitest, pytest/testcontainers, local
LiteParse, existing `no_rel/benchmarks` result contracts.

## Execution Status (2026-08-21)

- Implemented and pushed Tasks 1–5 plus the default-off UI/API toggle, retrieval
  fusion, accounting, transaction hardening, and tenant/workspace/group-ACL tests.
- Completed two clean synthetic fusion runs at
  `cfe7d1a105c153fd069af83a2091ba350d0c120f`, one per condition order, with 12
  page-labeled questions × 3 repetitions and zero retrieval errors.
- Corrected the page-level metric implementation after independent review: chunks
  from one PDF page now count once. The earlier `r2`–`r4` scores are superseded by
  `r5` and `r6`.
- Attempted AnythingLLM v1.16.0 native indexing; it is recorded as resource-gated
  after a server disconnect near the observed 2 GiB container limit. No score was
  assigned and the temporary extracted-text dataset was deleted.
- Preserved compact copyright-safe benchmark evidence under
  `docs/benchmarks/artifacts/`; raw local run files contain no query/book text.
- Pending before merge readiness: fresh full backend/frontend gates, rebase after
  upstream PRs #3/#8 and #6/#7, live-provider expansion/production embeddings,
  and any draft PR publication decision.

## Global Constraints

- Work only in `/tmp/ragz-multi-query-20260821` on
  `codex/multi-query-retrieval`; never reset, stash, or edit the shared checkout.
- Start from upstream `main` commit `b23949853fa2c76584218d68ec619685525568ab`.
- `multi_query_enabled` defaults to `false`; existing workspaces remain unchanged.
- Include the exact original query and generate at most two alternatives: three
  total retrieval queries.
- Use a designated, enabled chat utility model. Missing model, provider outage,
  malformed output, or zero valid alternatives must degrade to the original query.
- Never log query text, alternatives, document text, auth data, or provider secrets.
- Every dense and sparse prefetch must reuse `_tenant_filter`; no new Qdrant filter
  builder and no Python allow-filter are permitted.
- Use rank-based RRF for variant/dense/sparse fusion. Do not linearly combine raw
  dense, sparse, or cross-query scores.
- Rerank once, after fusion/deduplication, using the original user query.
- Without a reranker, no-answer uses the maximum top dense cosine across the
  original and valid alternative queries; generated text is never evidence.
- Record utility-model expansion tokens as `feature="query_expansion"` and dense
  embedding tokens once per retrieval call.
- Keep the direct search API, ordinary chat retrieval, and agent search tools on
  the same `retrieve()` path.
- Do not add a third-party query-expansion dependency.
- Do not copy or commit textbook content. Benchmark artifacts may contain hashes,
  IDs, page locators, metrics, and short independently written questions only.
- Use unique immutable run directories. Never overwrite an existing benchmark run.
- Separate normalized and native comparator tracks; never present resource-gated or
  adapter-missing systems as measured.
- Rebase the feature branch after PRs #6/#7 and #3/#8 land, resolving retrieval
  metrics and tenancy-view conflicts before publication.

---

### Task 1: Record the retrieval decision and implement bounded query expansion

**Files:**
- Create: `docs/adr/ADR-0007-multi-query-retrieval.md`
- Create: `backend/src/ragz/modules/retrieval/query_expansion.py`
- Create: `backend/tests/modules/retrieval/test_query_expansion.py`

**Interfaces:**
- Produces `ExpandedQueries(queries, prompt_tokens, completion_tokens)`.
- Produces `QueryExpander.expand(query: str, *, model: str) -> ExpandedQueries`.
- Produces `build_query_expander(settings, transport=None) -> QueryExpander`.

- [ ] **Step 1: Write pure parsing and client tests**

  Cover exact JSON, fenced JSON, duplicate/case-equivalent alternatives, blank or
  overlong values, more than two alternatives, malformed output, prompt-injection
  text inside the query, LiteLLM usage fields, HTTP errors, and non-200 responses.
  Assert that the original query is always element zero and that output has at
  most three entries.

- [ ] **Step 2: Run the tests and confirm they fail**

  ```bash
  cd backend
  uv run pytest -q tests/modules/retrieval/test_query_expansion.py
  ```

  Expected: collection/import failure because `query_expansion.py` does not exist.

- [ ] **Step 3: Implement the expansion seam**

  Implement these exact shapes:

  ```python
  @dataclass(frozen=True, slots=True)
  class ExpandedQueries:
      queries: tuple[str, ...]
      prompt_tokens: int = 0
      completion_tokens: int = 0

  class QueryExpander(Protocol):
      async def expand(self, query: str, *, model: str) -> ExpandedQueries: ...
  ```

  The real client posts a non-streaming completion to LiteLLM with
  `temperature=0`, requests `{"queries": [string, string]}`, wraps the original
  query in a neutralized `<query>` data block, normalizes whitespace, de-duplicates
  with `casefold()`, enforces 2,000 characters, and returns original-only on
  syntactically valid JSON with no usable alternatives. Network/protocol failures
  raise `UpstreamError` for the retrieval caller to degrade explicitly.

- [ ] **Step 4: Write ADR-0007**

  Record: query-time expansion versus existing ingestion-time hypothetical
  questions; original-query inclusion; three-query cap; RRF; single rerank;
  graceful fallback; usage accounting; ACL inheritance; default-off rollout; and
  why generated alternatives are not citations.

- [ ] **Step 5: Run focused tests and quality checks**

  ```bash
  cd backend
  uv run pytest -q tests/modules/retrieval/test_query_expansion.py
  uv run ruff check src/ragz/modules/retrieval/query_expansion.py \
    tests/modules/retrieval/test_query_expansion.py
  uv run mypy src/ragz/modules/retrieval/query_expansion.py
  ```

- [ ] **Step 6: Commit the independently testable seam**

  ```bash
  git add -- docs/adr/ADR-0007-multi-query-retrieval.md \
    backend/src/ragz/modules/retrieval/query_expansion.py \
    backend/tests/modules/retrieval/test_query_expansion.py
  git commit -m "feat(retrieval): add bounded query expansion seam"
  ```

### Task 2: Add the default-off workspace setting

**Files:**
- Create: `backend/migrations/versions/6a8d2c4f1b90_workspace_multi_query.py`
- Modify: `backend/src/ragz/modules/tenancy/models.py`
- Modify: `backend/src/ragz/modules/tenancy/views.py`
- Modify: `backend/src/ragz/modules/tenancy/schemas.py`
- Modify: `backend/src/ragz/modules/tenancy/service.py`
- Modify: `backend/src/ragz/api/routes/workspaces.py`
- Modify: `backend/tests/api/test_workspace_settings.py`
- Create: `backend/tests/migrations/test_workspace_multi_query.py`

**Interfaces:**
- Adds `Workspace.multi_query_enabled: bool` with server/Python default `false`.
- Adds the same field to `WorkspaceView`, `WorkspaceOut`, and `WorkspacePatch`.
- Treats the field as ranking-relevant so existing golden queries are re-evaluated.

- [ ] **Step 1: Add failing API and migration tests**

  Test an upgraded pre-feature workspace and a newly created workspace both return
  `false`; PATCH `{ "multi_query_enabled": true }` round-trips; explicit null is
  rejected; non-admin PATCH is denied; and the migration has the current single
  head `9cc2f9645fc0` as its parent.

- [ ] **Step 2: Run the tests and confirm field failures**

  ```bash
  cd backend
  uv run pytest -q tests/api/test_workspace_settings.py \
    tests/migrations/test_workspace_multi_query.py
  ```

- [ ] **Step 3: Add the migration and thread the setting**

  The migration adds:

  ```python
  sa.Column(
      "multi_query_enabled", sa.Boolean(),
      nullable=False, server_default=sa.false(),
  )
  ```

  Add `multi_query_enabled` to both route/service field allowlists and to
  `_RANKING_FIELDS`.

- [ ] **Step 4: Verify API, migration, and quality checks**

  ```bash
  cd backend
  uv run pytest -q tests/api/test_workspace_settings.py \
    tests/migrations/test_workspace_multi_query.py
  uv run alembic heads
  uv run ruff check src/ragz/modules/tenancy src/ragz/api/routes/workspaces.py \
    migrations/versions/6a8d2c4f1b90_workspace_multi_query.py
  uv run mypy src/ragz/modules/tenancy src/ragz/api/routes/workspaces.py
  ```

- [ ] **Step 5: Commit the settings contract**

  ```bash
  git add -- backend/migrations/versions/6a8d2c4f1b90_workspace_multi_query.py \
    backend/src/ragz/modules/tenancy/models.py \
    backend/src/ragz/modules/tenancy/views.py \
    backend/src/ragz/modules/tenancy/schemas.py \
    backend/src/ragz/modules/tenancy/service.py \
    backend/src/ragz/api/routes/workspaces.py \
    backend/tests/api/test_workspace_settings.py \
    backend/tests/migrations/test_workspace_multi_query.py
  git commit -m "feat(tenancy): add multi-query workspace toggle"
  ```

### Task 3: Fuse multi-query retrieval without weakening ACLs

**Files:**
- Modify: `backend/src/ragz/modules/retrieval/service.py`
- Modify: `backend/tests/modules/retrieval/test_retrieve.py`
- Modify: `backend/tests/modules/retrieval/test_retrieve_rerank.py`
- Create: `backend/tests/isolation/test_multi_query_isolation.py`

**Interfaces:**
- `retrieve()` remains source-compatible and accepts an optional keyword-only
  `query_expander: QueryExpander | None = None` test seam.
- When enabled, production resolves the designated utility model and constructs
  the real expander; tests inject a deterministic expander.

- [ ] **Step 1: Write failing retrieval tests**

  Prove: disabled means no expansion call; missing utility model means
  original-only; provider failure means original-only; enabled embeds exactly the
  returned three queries in one batch; Qdrant receives six filtered prefetches;
  duplicate chunks collapse; reranker is called once with the original query;
  expansion usage is staged once; max dense cosine drives no-answer without a
  reranker; and every variant remains tenant/workspace/ACL isolated.

- [ ] **Step 2: Run the focused tests and confirm failures**

  ```bash
  cd backend
  uv run pytest -q tests/modules/retrieval/test_retrieve.py \
    tests/modules/retrieval/test_retrieve_rerank.py \
    tests/isolation/test_multi_query_isolation.py
  ```

- [ ] **Step 3: Implement variant expansion and RRF lanes**

  Build prefetches in stable order:

  ```python
  prefetch = [
      lane
      for dense, sparse in zip(dense_vecs, sparse_vecs, strict=True)
      for lane in (
          models.Prefetch(query=dense, using="dense", filter=flt, limit=prefetch_limit),
          models.Prefetch(query=sparse, using="sparse", filter=flt, limit=prefetch_limit),
      )
  ]
  ```

  Keep the existing pre-query unprojected-document exclusion and post-query
  deny-only revision recheck unchanged. Use `models.Fusion.RRF`; do not expose
  generated variants in API output or citations.

- [ ] **Step 4: Implement no-answer and accounting semantics**

  Stage one `query_expansion` usage row when the utility call reports tokens.
  Stage one `embedding` usage row for the batch. If reranking is off or degraded,
  query top-one dense scores for every variant concurrently under `flt` and compare
  the maximum with `ws.min_score`. If reranking succeeds, retain its existing score
  and threshold semantics.

- [ ] **Step 5: Run retrieval, isolation, and quality checks**

  ```bash
  cd backend
  uv run pytest -q tests/modules/retrieval tests/isolation/test_multi_query_isolation.py
  uv run ruff check src/ragz/modules/retrieval tests/modules/retrieval \
    tests/isolation/test_multi_query_isolation.py
  uv run mypy src/ragz/modules/retrieval
  ```

- [ ] **Step 6: Commit retrieval behavior**

  ```bash
  git add -- backend/src/ragz/modules/retrieval/service.py \
    backend/tests/modules/retrieval/test_retrieve.py \
    backend/tests/modules/retrieval/test_retrieve_rerank.py \
    backend/tests/isolation/test_multi_query_isolation.py
  git commit -m "feat(retrieval): fuse workspace multi-query searches"
  ```

### Task 4: Expose the toggle in the workspace UI and generated API client

**Files:**
- Modify: `frontend/src/features/workspaces/workspace-settings-dialog.tsx`
- Modify: `frontend/src/features/workspaces/workspace-settings-dialog.test.tsx`
- Modify: `frontend/src/features/workspaces/queries.ts`
- Modify: `frontend/src/api/schema.d.ts`

**Interfaces:**
- Adds checkbox label `Expand each question into multiple searches`.
- PATCH sends only `multi_query_enabled` when that is the only edited field.

- [ ] **Step 1: Add failing UI/PATCH tests**

  Extend the `WorkspaceOut` fixture with `multi_query_enabled: false`, assert the
  checkbox state, click it, and assert an exact PATCH body of
  `{ multi_query_enabled: true }`. Assert untouched saves omit the field.

- [ ] **Step 2: Run the focused frontend test and confirm failure**

  ```bash
  cd frontend
  pnpm test -- workspace-settings-dialog.test.tsx
  ```

- [ ] **Step 3: Implement the checkbox and mutation type**

  Place it beside `Rerank with cross-encoder`, with copy explaining the extra
  utility-model call and retrieval latency. Preserve partial PATCH behavior.

- [ ] **Step 4: Regenerate OpenAPI types from the app object**

  ```bash
  cd backend
  uv run python scripts/export_openapi.py /tmp/ragz-multi-query-openapi.json
  cd ../frontend
  pnpm exec openapi-typescript /tmp/ragz-multi-query-openapi.json \
    -o src/api/schema.d.ts
  ```

- [ ] **Step 5: Verify frontend quality**

  ```bash
  cd frontend
  pnpm test -- workspace-settings-dialog.test.tsx
  pnpm lint
  pnpm typecheck
  ```

- [ ] **Step 6: Commit the UI/API contract**

  ```bash
  git add -- frontend/src/features/workspaces/workspace-settings-dialog.tsx \
    frontend/src/features/workspaces/workspace-settings-dialog.test.tsx \
    frontend/src/features/workspaces/queries.ts frontend/src/api/schema.d.ts
  git commit -m "feat(web): add multi-query retrieval toggle"
  ```

### Task 5: Add reproducible networking-corpus benchmark tooling

**Files:**
- Create: `backend/scripts/build_networking_benchmark.py`
- Create: `backend/scripts/run_multi_query_benchmark.py`
- Create: `backend/tests/scripts/test_networking_benchmark.py`
- Create: `docs/benchmarks/networking-multi-query-methodology.md`

**Interfaces:**
- Builder accepts three repeated `--pdf PATH` arguments and writes metadata,
  hashes, independently authored queries, and page/chunk qrels without copying
  textbook text.
- Runner requires `--multi-query on|off`, `--output NEW_DIRECTORY`, fixed top-k,
  parser, embedding model, reranker policy, query order, and seed.
- Runner refuses an existing output directory and emits `manifest.json`,
  `per_query.jsonl`, `summary.json`, and `summary.md` compatible with the existing
  benchmark result policy.

- [ ] **Step 1: Write failing artifact-contract tests**

  Test PDF hashing/page metadata, copyright-safe output, duplicate output refusal,
  paired query ordering, Recall/MRR/nDCG calculations, timing summaries, provider
  usage fields, and multi-query expansion count/error reporting.

- [ ] **Step 2: Run tests and confirm failures**

  ```bash
  cd backend
  uv run pytest -q tests/scripts/test_networking_benchmark.py
  ```

- [ ] **Step 3: Implement builder and runner**

  Use the RAGZ local parser/ingestion/retrieval seams rather than a separate toy
  index. Disable OCR unless page extraction proves necessary. Do not read `.env`;
  require explicit process environment supplied by the operator. Record every
  model/provider/config choice and all source hashes.

- [ ] **Step 4: Document the paired methodology**

  Define query classes: direct terminology, paraphrase, comparison, calculation,
  multi-evidence, cross-book synthesis, and off-corpus abstention. Require page or
  chapter qrels, two independent annotations for the held-out set, paired bootstrap
  intervals, and separate retrieval/answer/cost/latency reporting.

- [ ] **Step 5: Verify tooling and commit**

  ```bash
  cd backend
  uv run pytest -q tests/scripts/test_networking_benchmark.py
  uv run ruff check scripts/build_networking_benchmark.py \
    scripts/run_multi_query_benchmark.py tests/scripts/test_networking_benchmark.py
  uv run mypy scripts/build_networking_benchmark.py scripts/run_multi_query_benchmark.py
  git add -- scripts/build_networking_benchmark.py scripts/run_multi_query_benchmark.py \
    tests/scripts/test_networking_benchmark.py \
    ../docs/benchmarks/networking-multi-query-methodology.md
  git commit -m "bench: add multi-query networking evaluation harness"
  ```

### Task 6: Execute single-query, multi-query, and feasible comparator runs

**External source files (read-only):**
- `/home/parshu/Desktop/DCN/BOOKS/1_Behrouz A. Forouzan - Data Communications and Networking with TCP_IP Protocol Suite-McGraw-Hill (2022).pdf`
- `/home/parshu/Desktop/DCN/BOOKS/2_James W. Kurose, Keith W. Ross - Computer Networking_ A Top-Down Approach-Pearson (2021).pdf`
- `/home/parshu/Desktop/DCN/BOOKS/3_Andrew S. Tanenbaum, Nick Feamster, David J. Wetherall - Computer Networks-Pearson (2021).pdf`

**Unique external outputs:**
- `no_rel/benchmarks/results/runs/ragz-networking-single-<timestamp>-<sha>/`
- `no_rel/benchmarks/results/runs/ragz-networking-multi-<timestamp>-<sha>/`
- `no_rel/benchmarks/results/runs/anythingllm-networking-native-<timestamp>-<sha>/`
- `no_rel/benchmarks/results/MULTI_QUERY_NETWORKING_COMPARISON_2026-08-21.md`

- [ ] **Step 1: Record corpus identity and build qrels**

  Record SHA-256, page counts (861, 775, 946), extraction/parser versions, actual
  chunk count, and no copied book passages. Independently annotate support pages
  for a development set and a held-out set.

- [ ] **Step 2: Run paired RAGZ conditions**

  Use identical PDF bytes, parser, chunks, hosted embedding model, reranker setting,
  top-k, utility model, query order, and warm/cold policy. Change only
  `multi_query_enabled`. Record expansion queries only as hashes/counts, never text.

- [ ] **Step 3: Run feasible open-source comparators sequentially**

  Reuse the existing pinned AnythingLLM adapter in a new isolated project/volume.
  Run other systems only when their official resource floor fits the host and a
  stable adapter exists. Mark RAGFlow, Dify, FastGPT, Onyx, and adapter-missing
  systems as resource/adapter gated rather than assigning zero scores.

- [ ] **Step 4: Produce the comparison report**

  Report paired deltas and confidence intervals for Recall/MRR/nDCG@k, evidence
  coverage, abstention, redundancy/diversity, retrieval p50/p95/p99, expansion
  latency/tokens/cost, total latency/cost, indexing time, and error rate. Keep
  normalized and native tracks separate.

- [ ] **Step 5: Commit only copyright-safe summarized results**

  Copy the result summary—not PDFs, extracted text, provider output, secrets, or
  raw questions if held out—into:

  ```text
  docs/benchmarks/2026-08-21-networking-multi-query-results.md
  ```

  Then commit:

  ```bash
  git add -- docs/benchmarks/2026-08-21-networking-multi-query-results.md
  git commit -m "bench: compare single and multi-query retrieval"
  ```

### Task 7: Full verification, upstream integration, and publication readiness

**Files:** all feature/benchmark files above.

- [ ] **Step 1: Run complete backend gates**

  ```bash
  cd backend
  uv run ruff check
  uv run mypy
  uv run lint-imports
  uv run pytest -q
  uv run alembic heads
  ```

- [ ] **Step 2: Run complete frontend gates**

  ```bash
  cd frontend
  pnpm lint
  pnpm typecheck
  pnpm test
  pnpm build
  ```

- [ ] **Step 3: Verify deployment/API contracts**

  ```bash
  docker compose -f deploy/compose.yaml config --quiet
  git diff --check
  git status --short
  ```

- [ ] **Step 4: Rebase on the newest upstream main after overlapping PRs land**

  Fetch only inside the isolated worktree, rebase `codex/multi-query-retrieval`,
  resolve #6/#7 retrieval metrics and #3/#8 tenancy-view conflicts, rerun every
  gate, and preserve the milestone commits.

- [ ] **Step 5: Push to a fork and prepare a draft PR**

  Create or reuse `Parswanadh/ragz`, push only
  `codex/multi-query-retrieval`, and open a draft PR describing architecture,
  migration, security invariants, tests, benchmark evidence, costs, limitations,
  and open-PR dependency order. Do not mark ready for review until all gates pass.

## Plan Self-Review

- Spec coverage: repository/branch analysis, missing-feature analysis, explicit
  multi-query on/off toggle, local parsing of all three books, paired benchmark,
  feasible open-source comparison, history, tests, and merge path are covered.
- Placeholder scan: the plan contains no deferred implementation markers.
- Type consistency: `ExpandedQueries`, `QueryExpander`, `multi_query_enabled`, and
  `query_expander` names are consistent across tasks.
- Security: all variants inherit `_tenant_filter`; generated queries never become
  evidence; failure degrades to the original query.
- Benchmark validity: only the toggle changes in the paired RAGZ condition;
  normalized/native tracks remain separate; gated systems are not scored.
