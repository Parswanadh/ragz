# PR #11 Review Remediation Plan

> **Scope:** Review, reproduce, and resolve the 15 Cubic candidates on
> `codex/mqr-production-ready`. Do not add usage-accounting or CAG work here.
> Do not use Superpowers. Do not modify `/home/parshu/projects/ragz`.

**Goal:** Turn PR #11 from a locally verified MQR implementation into a
maintainer-ready change whose reviewer findings, security properties, docs,
migrations, UI, and failure behavior are all backed by reproducible evidence.

**Starting point and target:**

- Existing dedicated checkout:
  `/home/parshu/projects/rag-comparison-sources/ragz-mqr-production-ready`
- Local and remote PR branch: `codex/mqr-production-ready`
- Expected head: `3fac9fb1`
- Base: `upstream/main` at `9d08839f6855967f3b141b731a269a54b76222fb`
- PR: <https://github.com/marketcalls/ragz/pull/11>
- Review source: successful Cubic check with 15 candidate findings

## Definition of done

- [ ] Every finding below is recorded as `confirmed_fixed`,
      `invalid_with_evidence`, or `documented_limitation`.
- [ ] Every `confirmed_fixed` item has a regression test or deterministic
      reproducer that fails at the starting head and passes after the fix.
- [ ] No fix weakens org/workspace/ACL/current-version isolation.
- [ ] Backend, frontend, generated-schema, migration, build, and browser gates
      pass from a clean working tree.
- [ ] The final branch is pushed without force and PR #11 describes all changes.
- [ ] Cubic is rerun on the final head; no unresolved P1/P2 remains.
- [ ] GitHub workflow state is reported accurately. `action_required` with zero
      jobs means “awaiting approval,” not “CI passed.”

## Candidate triage map

Priority is the reviewer’s candidate priority, not a confirmed severity. The
reproducer may downgrade or dismiss it with evidence.

| ID | Candidate priority | Claim | Routed task |
|---:|:---:|---|---:|
| 1 | P3 | Isolation test does not prove the expander ran | 2 |
| 2 | P1 | Invalid embedding/disabled workspace answer default | 4 |
| 3 | P2 | Client cancellation can lose completed paid usage | 8 |
| 4 | P2 | Alternative embedding failure aborts Q1 fallback | 6 |
| 5 | P2 | No-answer probe may retain a post-ACL-removed score | 6 |
| 6 | P2 | Playwright `isVisible()` setup race duplicates workspace | 9 |
| 7 | P3 | ADR incorrectly says all embeddings use one batch | 3 |
| 8 | P3 | ADR says cap three while code supports 1/3/5 total | 3 |
| 9 | P3 | MQR UI gate trusts claims instead of authoritative auth | 9 |
| 10 | P2 | Cache-owner cancellation can strand single-flight waiters | 5 |
| 11 | P2 | Cohere retry ignores HTTP-date `Retry-After` | 7 |
| 12 | P2 | Eval source assembly can roll back completed usage | 8 |
| 13 | P2 | Expansion provider receives an unnecessarily large query | 7 |
| 14 | P2 | Eval UI can retain an ineligible default model | 4 |
| 15 | P2 | Edited form relabels already submitted comparison results | 9 |

## Task 0 — Freeze provenance, prove checkout ownership, and create the ledger

**Files:**

- Create on the research branch, not the product branch:
  `no_rel/verification/pr11-cubic-dispositions-2026-09-04.md`

**Steps:**

- [ ] Before using the existing MQR checkout, verify its status and provenance:

  ```bash
  git status --short --branch
  git rev-parse HEAD
  git rev-parse upstream/main
  git rev-parse origin/codex/mqr-production-ready
  git log --oneline --decorate upstream/main..HEAD
  git diff --stat upstream/main...HEAD
  gh pr view 11 --json number,state,isDraft,baseRefName,headRefName,headRefOid,mergeable,mergeStateStatus,statusCheckRollup,reviews,url
  gh pr checks 11
  ```

- [ ] Require a clean tree and the expected head. If either differs, inspect the
      extra work and record the new provenance before continuing.
- [ ] Check live agents/processes and any session handoff for ownership of this
      checkout. The clean Git status alone does not prove it is unowned.
- [ ] If another session owns it or ownership is uncertain, stop and ask the
      user. Do not create another worktree: only CAG is authorized to do so.
- [ ] If it is clean and unowned, perform Phase 1 directly on the existing PR
      branch. Never reset or discard unrecognized changes.
- [ ] Create a 15-row disposition ledger with columns: ID, severity, claim,
      reproducer, result, code/test evidence, commit, residual risk.
- [ ] Copy only reviewer claims into the ledger. Do not present them as confirmed
      until the reproducer establishes the behavior.
- [ ] Record the Python, Node, Docker, PostgreSQL, Redis, Qdrant, and browser
      versions used for verification.

**Checkpoint:** Commit locally only after the first independently validated
group of dispositions; do not make an empty “review started” product commit.
Before each push, fetch the remote PR branch and require it to equal the last
observed SHA and be an ancestor of local `HEAD`.

## Task 1 — Establish the unchanged baseline

**Files inspected:**

- `backend/pyproject.toml`
- `frontend/package.json`
- `.github/workflows/`
- `docker-compose.yml` and any test compose files

**Steps:**

- [ ] Run the narrow existing MQR suites first:

  ```bash
  cd backend
  DOCKER_HOST=unix:///var/run/docker.sock uv run pytest -q \
    tests/modules/retrieval/test_query_expansion.py \
    tests/modules/retrieval/test_retrieve.py \
    tests/modules/retrieval/test_retrieve_rerank.py \
    tests/modules/evals/test_comparison.py \
    tests/api/test_evals_routes.py \
    tests/api/test_search_route.py \
    tests/isolation/test_multi_query_isolation.py
  cd ../frontend
  pnpm test -- \
    src/features/workspaces/workspace-settings-dialog.test.tsx \
    src/features/workspaces/evals-section.test.tsx
  ```

- [ ] Use the repository’s exact lint/typecheck commands discovered from
      `pyproject.toml` and `package.json`; record them in the ledger.
- [ ] Preserve the baseline output in the verification document. If baseline
      fails, separate pre-existing failure from regression before editing.

## Task 2 — Make isolation testing prove the expansion path ran (finding 1)

**Claim:** `backend/tests/isolation/test_multi_query_isolation.py` can pass even
when the query expander is never called.

**Files:**

- Modify: `backend/tests/isolation/test_multi_query_isolation.py`
- Inspect: `backend/src/ragz/modules/retrieval/service.py`

**Reproduction:**

- [ ] Temporarily replace the configured expander with a fake that records its
      input context and returns a unique alternative. Assert the call count,
      org/workspace identity, requested query count, and absence of foreign
      document content.
- [ ] Prove the old test still passes when the expansion call is disabled; save
      that output, then remove the temporary production sabotage.
- [ ] Add a positive assertion that fails if the expander is not invoked and a
      negative assertion that foreign-tenant points never appear in results.

**Acceptance:** The test independently proves both “MQR executed” and “MQR did
not cross the tenant/workspace/ACL boundary.”

## Task 3 — Align ADRs and executable behavior (findings 7–8)

**Claims:** The ADR says embeddings are a single batch although the code embeds
the original and alternatives separately; it also says a maximum of three
queries while the implementation supports 1, 3, and 5 total queries.

**Files:**

- Modify: the MQR ADR under `docs/adr/` identified with `rg -n "multi.query|batch|capped|three" docs`
- Verify: `backend/src/ragz/modules/retrieval/query_expansion.py`
- Verify: `backend/src/ragz/modules/retrieval/service.py`
- Verify: `frontend/src/features/workspaces/workspace-settings-dialog.tsx`

**Steps:**

- [ ] Confirm whether the two-stage embedding behavior is deliberate. Document
      the original query’s independent fallback role and the alternative batch.
- [ ] Define `query_count` unambiguously as total queries including the original.
- [ ] Document supported values `1`, `3`, and `5`, with `1` equivalent to the
      single-query retrieval path.
- [ ] Ensure config/schema comments and UI labels use the same terminology.
- [ ] Add a documentation contract test only if the repo already uses such tests;
      otherwise cite the exact code constants in the disposition ledger.

**Commit:** `docs: align MQR ADR with executable query semantics`

## Task 4 — Enforce valid workspace answer-model defaults (findings 2 and 14)

**Claims:** A workspace may reference an embedding/disabled model as its answer
model; the new chat-modality filtering can then break chat or the eval UI.

**Files:**

- Modify: `backend/src/ragz/modules/models/service.py`
- Modify if the invariant belongs there:
  `backend/src/ragz/modules/models/settings_service.py`
- Modify: model/workspace schemas and the relevant Alembic migration under
  `backend/alembic/versions/`
- Modify: `frontend/src/features/workspaces/evals-section.tsx`
- Tests: `backend/tests/modules/models/test_service.py`
- Tests: `backend/tests/modules/models/test_settings_service.py`
- Tests: workspace route tests under `backend/tests/api/`
- Tests: `frontend/src/features/workspaces/evals-section.test.tsx`

**Design decision:** A workspace answer-model reference must resolve to an
enabled chat-capable model. Enforce this on writes at the backend boundary. On
reads, tolerate historical invalid data by returning no usable default and let
the caller choose the first authorized enabled chat model; do not silently
rewrite rows during a GET.

**Steps:**

- [ ] Reproduce with a workspace whose default points to an enabled embedding
      model, then with a disabled chat model.
- [ ] Add backend validation tests for create/update/default-assignment paths.
- [ ] Search every mutation of the default model field and route all mutations
      through the same invariant.
- [ ] Decide whether historical invalid references need a data migration. If so,
      clear only demonstrably invalid defaults; do not guess a replacement model.
- [ ] In the eval UI, derive `effectiveModelId` only from the fetched enabled
      chat-model list. Fall back to its first eligible item or disable Run with a
      useful explanation.
- [ ] Cover “default missing,” “default disabled,” “default is embedding,” and
      “no eligible answer model” in backend and frontend tests.

**Acceptance:** Invalid assignments are rejected on write, existing bad rows do
not crash chat/evals, and tenant authorization still gates the model list.

**Commit:** `fix: enforce chat-capable workspace answer models`

## Task 5 — Make both in-memory single-flight caches cancellation-safe (finding 10)

**Claim:** If the cache owner is cancelled while acquiring or holding the store
lock, waiters can be left on an unresolved in-flight future.

**Files:**

- Modify: `backend/src/ragz/modules/retrieval/embeddings.py`
- Modify: `backend/src/ragz/modules/retrieval/query_expansion.py`
- Tests: `backend/tests/modules/retrieval/test_embeddings.py`
- Tests: `backend/tests/modules/retrieval/test_query_expansion.py`

**Required state machine:**

- One owner computes; waiters await one future.
- Owner success resolves the future and may populate the cache.
- Owner exception or cancellation resolves/removes the future for every waiter.
- Cancellation while waiting does not cancel the shared computation.
- No code awaits a provider call while holding the cache mutex.
- Expiry/eviction cannot delete a different generation’s in-flight entry.

**Steps:**

- [ ] Add deterministic asyncio tests with events/barriers for cancellation:
      before computation, during computation, while acquiring the final store
      lock, and one cancelled waiter among live waiters.
- [ ] Run those tests against `3fac9fb1` to confirm which scenarios fail.
- [ ] Implement a shared internal single-flight primitive only if doing so makes
      both caches simpler and preserves their distinct keys/metrics. Otherwise
      patch each with the same documented state machine.
- [ ] Ensure `BaseException`/`CancelledError` cleanup cannot be skipped and that
      futures do not emit “exception was never retrieved.”
- [ ] Add a bounded concurrency stress test with a timeout to prove no deadlock.

**Acceptance:** All callers finish or receive a typed exception within the test
timeout; cache metrics remain bounded and no in-flight entry is stranded.

**Commit:** `fix: make retrieval single-flight caches cancellation-safe`

## Task 6 — Preserve original-query degradation and post-ACL correctness (findings 4–5)

**Claims:** Alternative-query embedding failures may abort retrieval instead of
falling back to Q1; overlapping no-answer probes may score a document that was
removed by the post-query ACL revision recheck.

**Files:**

- Modify: `backend/src/ragz/modules/retrieval/service.py`
- Tests: `backend/tests/modules/retrieval/test_retrieve.py`
- Tests: `backend/tests/isolation/test_multi_query_isolation.py`
- Extend where appropriate:
  `backend/tests/isolation/test_acl_projection_outage.py`

**Steps:**

- [ ] Inject success for original embedding and failure for the alternative
      batch. Confirm whether the current code propagates or degrades.
- [ ] If confirmed, isolate failures by stage: retain original-query dense and
      sparse retrieval; emit a bounded `provider_failure`/degraded metric; do not
      manufacture alternative results.
- [ ] Test timeout, transport error, malformed dimension, and empty alternative
      vectors separately.
- [ ] Reproduce an ACL/security revision change after vector search but before
      result finalization while a no-answer probe overlaps.
- [ ] Ensure the no-answer decision is derived only from candidates remaining
      after the authoritative post-query security/current-version recheck.
- [ ] Prefer cancelling/restarting the probe with the filtered candidate set over
      carrying a score whose source was removed.
- [ ] Assert no removed document can influence result chunks, no-answer state,
      citations, logs, or observability labels.

**Acceptance:** MQR enhancement failure returns the single-query answer path;
authorization changes remain fail-closed even in overlapped work.

**Commit:** `fix: preserve secure single-query fallback in retrieval`

## Task 7 — Bound expansion input and parse Retry-After correctly (findings 11, 13)

**Claims:** Expansion can send the full 32k query to the utility model; Cohere
retry logic ignores the valid HTTP-date form of `Retry-After`.

**Files:**

- Modify: `backend/src/ragz/modules/retrieval/query_expansion.py`
- Modify: `backend/src/ragz/modules/retrieval/rerank.py`
- Modify if configurable: `backend/src/ragz/core/config.py`
- Tests: `backend/tests/modules/retrieval/test_query_expansion.py`
- Tests: `backend/tests/modules/retrieval/test_rerank.py`
- Tests: `backend/tests/core/test_config.py`

**Steps:**

- [ ] Keep the original query intact for retrieval and audit semantics, but
      construct a separately bounded expansion-model input.
- [ ] Set the bound in model tokens if a reliable tokenizer is available;
      otherwise use a documented conservative character cap. Never split a
      Unicode code point, and record only lengths/hashes in logs.
- [ ] Test boundary-1, boundary, boundary+1, whitespace-only, and multi-byte text.
- [ ] Parse `Retry-After` as either delta-seconds or RFC-compliant HTTP-date.
- [ ] Use an injected/frozen clock; clamp negative dates to zero and cap waits at
      the configured retry ceiling. Invalid values use bounded backoff.
- [ ] Do not perform real sleeps in tests.

**Acceptance:** Provider request size is bounded without truncating the actual
retrieval query; both Retry-After forms produce deterministic bounded delays.

**Commit:** `fix: bound expansion input and honor HTTP-date retries`

## Task 8 — Make provider-usage persistence cancellation-safe (findings 3, 12)

**Claims:** A client disconnect after paid web search/intermediate agent work can
roll back usage; eval comparison can perform source enrichment before committing
provider usage and lose it on a later failure.

**Files:**

- Modify: `backend/src/ragz/modules/chat/service.py`
- Modify: `backend/src/ragz/modules/evals/comparison.py`
- Possibly modify the usage helper only to provide a narrow durability API:
  `backend/src/ragz/modules/quotas/service.py`
- Tests: `backend/tests/api/test_chat_stream.py`
- Tests: `backend/tests/modules/evals/test_comparison.py`
- Tests: `backend/tests/api/test_evals_routes.py`

**Transaction rule:** Once a provider call has returned billable usage, persist
that usage before yielding an externally cancellable stream frame or beginning
unrelated source-enrichment work. Do not commit partial chat messages or break
the existing atomic assistant-message/citation write.

**Steps:**

- [ ] Build deterministic provider fakes and cancellation barriers around web
      search, agent planning, generation completion, stream yield, source lookup,
      and final persistence.
- [ ] Verify exactly which completed provider calls lose rows at the starting
      head. A call that never returned usage must remain unknown, not fabricated.
- [ ] Introduce an explicit operation identifier/idempotent persistence seam if
      needed so retrying the same completed provider response cannot double-write.
- [ ] Shield only the minimal usage commit from caller cancellation; bound it with
      the normal DB timeout and propagate failures to telemetry.
- [ ] Persist comparison-generation usage before `_sources()` or equivalent
      post-provider enrichment.
- [ ] Assert a genuinely repeated provider request creates a new billable row;
      idempotency is per returned operation, not per identical prompt.

**Acceptance:** Completed, reported provider work survives downstream errors and
disconnects exactly once; message/citation transaction guarantees are unchanged.

**Commit:** `fix: durably persist completed provider usage`

## Task 9 — Use authoritative authorization and snapshot eval inputs (findings 6, 9, 15)

**Claims:** Workspace MQR controls use unverified JWT claims while evals use the
authoritative authorization endpoint; Playwright visibility checks race; result
labels change when the editable question/model changes after submission.

**Files:**

- Modify: `frontend/src/features/workspaces/workspace-settings-dialog.tsx`
- Modify: `frontend/src/features/workspaces/evals-section.tsx`
- Modify: relevant component tests
- Modify: `frontend/e2e/mqr-settings.spec.ts`

**Steps:**

- [ ] Replace role gating for the MQR mutation control with the authoritative
      `useAuthorization()` result. While authorization is pending or failed, keep
      the control hidden/disabled fail-closed.
- [ ] Confirm the backend route remains the final superadmin-only enforcement;
      frontend gating is only user experience.
- [ ] Store a submitted comparison snapshot containing trimmed question, selected
      model ID/name, query-count configuration, request ID, and start time. Render
      completed/error results from that snapshot, not live form state.
- [ ] Decide whether editing the form while a run is pending is allowed. If yes,
      it prepares the next run only; it must not relabel the in-flight result.
- [ ] Replace immediate `isVisible()` branching in Playwright with a deterministic
      locator wait/API-seeded fixture. Create a workspace only after the list has
      reached a known loaded state and prove reruns do not duplicate it.
- [ ] Add component tests for forged/stale `superadmin` claims with authoritative
      denial, pending authorization, mid-run edits, and consecutive runs.

**Acceptance:** Only authoritative superadmin authorization reveals the toggle;
browser setup is idempotent; comparison results describe the request actually run.

**Commit:** `fix: harden MQR authorization and eval state`

## Task 10 — Reconcile dispositions and update PR documentation

**Files:**

- Modify: PR #11 body through `gh pr edit`
- Modify on research branch:
  `no_rel/verification/pr11-cubic-dispositions-2026-09-04.md`

**Steps:**

- [ ] For every candidate, attach the reproducer result and final status.
- [ ] For invalid findings, explain the exact guard/invariant and cite the test;
      do not change code merely to appease a false positive.
- [ ] For limitations, state why it is out of scope, its impact, and a follow-up
      issue only if independently actionable.
- [ ] Update the PR body with behavior, permissions, migration notes, fallback
      semantics, test matrix, benchmark limitations, and reviewer dispositions.
- [ ] Never paste secrets, book text, raw questions, provider payloads, or answers.

## Task 11 — Full local verification

Run commands from the existing MQR checkout. These mirror the required CI jobs:

```bash
git diff --check upstream/main...HEAD
cd backend
DOCKER_HOST=unix:///var/run/docker.sock uv run ruff check src tests
DOCKER_HOST=unix:///var/run/docker.sock uv run mypy src
DOCKER_HOST=unix:///var/run/docker.sock uv run lint-imports
DOCKER_HOST=unix:///var/run/docker.sock uv run pytest tests --ignore=tests/isolation --ignore=tests/redteam -q
DOCKER_HOST=unix:///var/run/docker.sock uv run pytest tests/isolation -q
DOCKER_HOST=unix:///var/run/docker.sock uv run pytest tests/test_migrations.py -q
cd ../frontend
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm bundle-budget
pnpm exec playwright test --list
```

- [ ] Run Alembic upgrade from the current main schema to head, downgrade one
      revision, and upgrade again using a disposable test database.
- [ ] Generate OpenAPI/schema output exactly like CI and require no drift:

  ```bash
  cd backend
  uv run python scripts/export_openapi.py /tmp/ragz-openapi.json
  cd ../frontend
  pnpm exec openapi-typescript /tmp/ragz-openapi.json -o /tmp/ragz-schema.d.ts
  diff -u src/api/schema.d.ts /tmp/ragz-schema.d.ts
  ```

- [ ] Treat `playwright test --list` as compile/discovery only. Run the MQR
      Playwright spec and authorization/chat comparison smoke with `E2E=1` in an
      isolated stack, not against the user’s live local stack.
- [ ] Run the repository’s module-boundary/architecture contracts.
- [ ] Run a credential scan over `upstream/main...HEAD` for common key prefixes and
      private-key headers. Review matches manually; do not print secret values.
- [ ] Inspect `git status --short`, test summaries, and process exit codes.

## Task 12 — Push, rerun review, and hand off

**Steps:**

- [ ] Push after every reviewable commit only if the remote PR tip has not moved
      and the update is a fast-forward:

  ```bash
  git fetch origin codex/mqr-production-ready
  git merge-base --is-ancestor origin/codex/mqr-production-ready HEAD
  git push origin codex/mqr-production-ready
  ```

- [ ] Verify local and remote head equality.
- [ ] Re-trigger Cubic on the final head and wait for its completed result.
- [ ] Re-run or request approval for GitHub workflows. If they remain
      `action_required` with zero jobs, report that exact external gate.
- [ ] Do not merge PR #11 without the user/maintainer’s explicit instruction.
- [ ] Leave `ragz-mqr-local-test` running. If code changed materially, explain
      that the live stack is still on the earlier image until the user authorizes
      a rebuild.

## Final handoff format

Report:

1. Final branch and SHA.
2. Disposition counts and a one-line result for each of the 15 findings.
3. Commits pushed and PR URL.
4. Exact local gate results.
5. Cubic and GitHub Actions status, distinguishing executed from unexecuted jobs.
6. Any residual limitation or maintainer-only action.
7. Whether the local test runtime was changed (expected: no).
