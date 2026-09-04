# Reliable Usage Accounting Plan

> **Scope:** Replace the misleading all-token sum with an auditable accounting
> model after PR #11 is review-ready. Do not use Superpowers. Do not modify
> `/home/parshu/projects/ragz`, reuse its secrets, or mix this work into PR #11.

**Goal:** Make RAGZ distinguish what the provider actually reported, what RAGZ
estimated locally, what counts against quota, what was a per-call unit, how much
corpus is currently indexed, and whether price data is complete.

**Observed defect:** The `1.7M tokens` chat header is dominated by an ingestion
estimate (`sum(len(chunk.text)) // 4`) recorded in the same legacy columns as
provider tokens. In the clean three-book run, the indexed-corpus estimate was
1,699,810 while all provider-reported work for the verified MQR chat was 10,126
tokens. The header is therefore a quota/processing counter, not an LLM billable
token meter. Missing catalog prices currently render as `$0`, which also confuses
“unknown” with “free.”

## Non-negotiable accounting invariants

1. Provider fields contain only values returned by that provider.
2. A missing provider usage block is unknown, never zero.
3. Cached-input and reasoning tokens are detail fields; never add them again if
   the provider’s input/output totals already include them.
4. Corpus and interrupted-stream estimates live only in estimate fields.
5. Per-call/search units never enter token totals.
6. `quota_tokens` is the sole quota-enforcement aggregate.
7. Idempotency identifies persistence of one provider response. A new provider
   HTTP attempt receives a new event ID even when it retries the same logical
   operation and may itself be billable.
8. Current indexed corpus is state, not cumulative usage. Reindexing may update
   its estimate but cannot increment the current-corpus gauge.
9. Unknown price is visibly unknown. A genuine configured price of zero is free.
10. The ledger remains append-only; repairs use explicit compensating records or
    a migration with recorded provenance, not silent mutation after launch.

## Branch and isolation setup

- [ ] Read the master plan and confirm Phase 1 has no unresolved P1/P2.
- [ ] Fetch both remotes without changing any existing checkout:

  ```bash
  git -C /home/parshu/projects/rag-comparison-sources/ragz-b91c898 fetch --all --prune
  ```

- [ ] If PR #11 is merged into `upstream/main`, create the meaningful worktree
      `/home/parshu/projects/rag-comparison-sources/ragz-accurate-usage` on a new
      `codex/accurate-usage-accounting` branch from that merge.
- [ ] If #11 is still open, branch from the exact PR head, mark the work stacked,
      and do not open its PR until #11 merges. Never rebase a published branch
      without explicit approval.
- [ ] Record base/head/remotes/dirty status under
      `no_rel/verification/usage-accounting-baseline-2026-09-04.md` on the
      research branch.

## Task 1 — Write the accounting ADR and truth table

**Files:**

- Create: `docs/adr/<next>-usage-ledger-semantics.md`
- Inspect: `backend/src/ragz/modules/quotas/models.py`
- Inspect: `backend/src/ragz/modules/quotas/service.py`
- Inspect: `backend/src/ragz/modules/quotas/reporting.py`
- Inspect: `backend/src/ragz/modules/quotas/costing.py`

**Steps:**

- [ ] Document these orthogonal dimensions for every event:
      provider usage, local estimate, quota debit, per-call unit, pricing status,
      feature/stage, model, tenant/workspace/user, and operation identity.
- [ ] Create a truth table for all current writers:

  | Writer | Feature/stage | Provider usage | Estimate | Units | Quota policy |
  |---|---|---|---|---|---|
  | final/planner/auditor/expander | LLM stage | provider input/output/details | only if usage absent | 0 | explicit |
  | hosted embedding | embedding | provider total if returned | corpus is separate | 0 | explicit |
  | TEI/hash embedding | embedding | known zero or no provider event | corpus is separate | 0 | explicit |
  | ingestion/chunking | ingestion | none | corpus/input/output estimate | 0 | preserve current debit initially |
  | rerank | rerank | provider details if supplied | none | search units | configured |
  | web search | web_search | none | none | calls | configured |

- [ ] State that the initial migration preserves historical quota totals exactly,
      including current hosted-embedding plus ingestion debits. Any later quota
      policy change needs a separate product decision and must not be smuggled
      into the meter fix.
- [ ] Define terminology used by API/UI: “quota used,” “provider-reported input,”
      “provider-reported output,” “estimated processing,” “currently indexed,”
      “service units,” and “cost completeness.”
- [ ] Explain that OpenAI-compatible providers may differ in which detail fields
      they return; the adapter must preserve unknowns.

**Acceptance:** A reviewer can classify every existing write without inspecting
implementation code, and no field is overloaded across categories.

**Commit:** `docs: define auditable usage-ledger semantics`

## Task 2 — Add a rolling-safe additive database migration

**Files:**

- Modify: `backend/src/ragz/modules/quotas/models.py`
- Modify: `backend/src/ragz/modules/documents/models.py`
- Create: one Alembic revision after current head `6a8d2c4f1b90`
- Modify: `backend/tests/test_migrations.py`

**UsageRecord fields:** Keep legacy `prompt_tokens`, `completion_tokens`, and
`units` during the compatibility period. Add:

```text
provider_prompt_tokens      BIGINT NULL
provider_completion_tokens  BIGINT NULL
provider_total_tokens       BIGINT NULL
provider_cached_tokens      BIGINT NULL
provider_reasoning_tokens   BIGINT NULL
provider_usage_known        BOOLEAN NOT NULL DEFAULT FALSE
estimated_prompt_tokens     BIGINT NULL
estimated_completion_tokens BIGINT NULL
estimated_corpus_tokens     BIGINT NULL
quota_tokens                BIGINT NULL during rollout
operation_id                UUID NULL during rollout
logical_operation_id        UUID NULL
provider_request_id         VARCHAR NULL
usage_origin                VARCHAR NOT NULL DEFAULT 'legacy'
unit_type                   VARCHAR NULL
```

Allowed `usage_origin` values should be enforced in code and, if consistent
with repository migration practice, by a DB check:

```text
provider_reported | provider_missing | local_estimate | configured_unit | mixed | legacy
```

`Document` additions:

```text
indexed_token_estimate       BIGINT NULL
token_estimator              VARCHAR NULL
token_estimator_version      VARCHAR NULL
```

**Migration sequence:**

- [ ] Add nullable/defaulted columns without rewriting writers first.
- [ ] Backfill `operation_id = id` for historical rows; this is deterministic and
      requires no PostgreSQL UUID extension.
- [ ] Backfill `quota_tokens = prompt_tokens + completion_tokens` for all legacy
      rows, preserving quota behavior exactly.
- [ ] For historical `feature='ingestion'`, copy the legacy total to
      `estimated_corpus_tokens` and mark `usage_origin='local_estimate'` only
      when the historical writer is unambiguous. Leave all other rows `legacy`;
      do not pretend estimates are provider truth.
- [ ] Do not backfill provider detail fields from ambiguous legacy data.
- [ ] Add a unique index on non-null `operation_id` after backfill.
- [ ] Keep new columns compatible with old application instances for one rollout.
      A later cleanup migration may set `operation_id` and `quota_tokens` non-null
      only after every writer is converted.
- [ ] Add nonnegative constraints for token/unit columns and document behavior for
      compensating entries if refunds are ever needed.
- [ ] Test upgrade from current main schema, backfill values, index uniqueness,
      downgrade, and re-upgrade on a disposable PostgreSQL database.

**Acceptance:** Historical quota totals are byte-for-byte equivalent before and
after migration; no old row is falsely marked provider-reported.

**Commit:** `feat: add explicit usage and corpus accounting fields`

## Task 3 — Introduce typed usage events and idempotent persistence

**Files:**

- Modify: `backend/src/ragz/modules/quotas/service.py`
- Create if it improves module clarity:
  `backend/src/ragz/modules/quotas/events.py`
- Tests: `backend/tests/modules/quotas/test_service.py`

**Proposed interface:**

```python
@dataclass(frozen=True)
class ProviderTokenUsage:
    prompt: int | None
    completion: int | None
    total: int | None
    cached_prompt: int | None = None
    reasoning: int | None = None

@dataclass(frozen=True)
class UsageEstimate:
    prompt: int | None = None
    completion: int | None = None
    corpus: int | None = None
    estimator: str | None = None

@dataclass(frozen=True)
class UsageEvent:
    operation_id: UUID
    logical_operation_id: UUID
    org_id: UUID
    user_id: UUID
    workspace_id: UUID | None
    model_id: UUID | None
    feature: str
    stage: str
    provider: ProviderTokenUsage | None
    estimate: UsageEstimate | None
    quota_tokens: int
    units: int = 0
    unit_type: str | None = None
    provider_request_id: str | None = None
```

Exact naming may follow local conventions, but the semantics must not weaken.

**Steps:**

- [ ] Validate nonnegative values and internally consistent known/unknown state.
- [ ] Persist with PostgreSQL `INSERT ... ON CONFLICT (operation_id) DO NOTHING`
      and return `inserted: bool` so callers/tests can observe deduplication.
- [ ] Generate a new `operation_id` immediately before each provider attempt. A
      retry of the database write reuses it; a retry that calls the provider
      again gets a new ID. Share `logical_operation_id` across those attempts.
- [ ] For legacy callers without IDs, generate a unique non-idempotent event and
      write both legacy and new columns. Add a removal deadline in the ADR.
- [ ] Keep legacy `prompt_tokens`/`completion_tokens` populated as compatibility
      mirrors, but never use them for new quota/report calculations.
- [ ] Switch `_TOKENS`, `_sum_since`, `daily_usage`, `org_usage_summary`, and
      `platform_usage_by_org` to `quota_tokens` only after backfill exists.
- [ ] Invalidate the affected Redis user/org quota cache after a successful
      committed insert. A versioned cache namespace is preferred; TTL remains a
      fallback, not the primary freshness mechanism.
- [ ] Cover duplicate persistence, independent provider retries, rollback, staged
      writes, cache invalidation, unknown usage, known zero, estimates, and units.

**Acceptance:** One provider response cannot be recorded twice, two provider
attempts cannot collapse into one, and quota reads are fresh after a committed
write.

**Commit:** `feat: persist typed idempotent usage events`

## Task 4 — Parse provider usage without fabricating zeroes

**Files:**

- Modify: `backend/src/ragz/modules/chat/llm.py`
- Modify: embedding adapter(s) under `backend/src/ragz/modules/retrieval/`
- Modify: rerank adapter if it exposes token details
- Tests: `backend/tests/modules/chat/test_llm.py`
- Tests: `backend/tests/modules/retrieval/test_embeddings.py`
- Tests: `backend/tests/modules/retrieval/test_rerank.py`

**Steps:**

- [ ] Extend `LLMUsage` with nullable total, cached-input, reasoning-output,
      provider request ID, and a usage-known flag.
- [ ] Parse OpenAI-compatible common shapes, including nested input/output token
      details, through a small defensive helper used by stream and complete.
- [ ] Preserve absent, malformed, and explicit zero as three different cases.
- [ ] Treat cached/reasoning values as subsets/details unless provider semantics
      explicitly say otherwise; do not add them to total.
- [ ] Record a terminal streaming usage block when present. If a stream ends or
      disconnects before it, store a separately labeled local estimate only when
      RAGZ has enough information; otherwise record provider usage unknown.
- [ ] Ensure sanitized logs contain operation IDs and counts/status only—never
      prompts, keys, response bodies, or document text.

**Acceptance:** Recorded provider values equal deterministic fixture payloads;
missing data remains null/unknown and totals never double-count details.

**Commit:** `feat: preserve provider usage detail and unknown state`

## Task 5 — Convert every writer to one atomic event per paid operation

**Files:**

- Modify: `backend/src/ragz/modules/chat/service.py`
- Modify: `backend/src/ragz/modules/chat/audit.py`
- Modify: `backend/src/ragz/modules/documents/ingest.py`
- Modify: `backend/src/ragz/modules/retrieval/service.py`
- Modify: `backend/src/ragz/modules/evals/comparison.py`
- Modify: `backend/src/ragz/api/routes/search.py`
- Extend the corresponding backend tests listed below.

**Required conversion map:**

- [ ] Conversation-summary folds: local estimate, not provider-reported chat.
- [ ] Stopped/detached partial answers: provider values if terminal usage arrived;
      otherwise a clearly labeled partial estimate/unknown.
- [ ] Agent planning, Gatekeeper, final generation, validation, and query expansion:
      separate atomic provider events instead of merging several calls into one
      row. Share the turn’s logical operation ID.
- [ ] Web search and rerank: explicit units plus unit type; zero token fields.
- [ ] Query embeddings and ingestion embeddings: provider totals only if actually
      returned. An application cache hit creates no new provider event.
- [ ] Chunk corpus estimate: local estimate event only; assign the preserved quota
      debit explicitly.
- [ ] Enrichment source/summary estimate: local estimate fields only.
- [ ] Eval comparison: one logical comparison ID, one atomic provider event per
      variant/call; persist returned usage before fallible source enrichment.
- [ ] Direct-search staged events: commit durably at the endpoint boundary with
      deterministic operation IDs.

**Cancellation/transaction requirements:**

- [ ] Once a provider returns usage, persist it before yielding a cancellable
      externally visible frame or beginning unrelated fallible work.
- [ ] Shield only the bounded ledger persistence, not the entire request.
- [ ] Preserve assistant-message plus citation atomicity; accounting durability
      must not commit a half-written chat message.
- [ ] Add cancellation barriers/tests after each paid stage and assert exactly
      one event for every completed provider response.

**Acceptance:** A trace of one MQR chat can be reconciled stage-by-stage with the
provider fixtures and contains no aggregated row that hides which call spent it.

**Commits:** Split into reviewable commits, for example:

- `refactor: meter chat and eval provider calls atomically`
- `refactor: separate retrieval and ingestion accounting`

## Task 6 — Store current indexed-corpus state separately

**Files:**

- Modify: `backend/src/ragz/modules/documents/ingest.py`
- Modify: document deletion/version-promotion flows under
  `backend/src/ragz/modules/documents/`
- Add service query under `backend/src/ragz/modules/documents/service.py` or a
  usage-owned read model that respects module boundaries
- Tests: `backend/tests/modules/documents/test_ingest.py`
- Tests: document reindex/reembed/version/deletion tests

**Steps:**

- [ ] At successful indexing, set `Document.indexed_token_estimate` from the
      exact chunks stored for that version and record estimator name/version.
- [ ] Reindex/reembed sets the same current value; it never adds to a gauge.
- [ ] Failed/deleting/non-current documents are excluded from current-corpus
      totals. Version promotion atomically changes which row contributes.
- [ ] Provide an org/user/workspace-authorized aggregate for currently indexed
      corpus. Do not derive it from cumulative `usage_records`.
- [ ] Test upload, retry, reindex, reembed, new version promotion, failed version,
      and deletion. The three-book corpus must remain one corpus after reindex.

**Acceptance:** Current-corpus display is stable across reprocessing and tracks
the current authorized indexed set.

**Commit:** `feat: track current indexed corpus estimates`

## Task 7 — Make costs honest and auditable

**Files:**

- Modify: `backend/src/ragz/modules/quotas/costing.py`
- Modify: `backend/src/ragz/modules/quotas/reporting.py`
- Modify: report schemas/routes under `backend/src/ragz/api/routes/reports.py`
- Tests: `backend/tests/modules/quotas/test_reporting.py`
- Tests: report route/export tests

**Decision for this PR:** Keep price lookup out of hot usage writes. Reporting
calculates an estimate from the current catalog/config and returns its as-of time
and completeness. A later dedicated ledger-pricing migration may snapshot price
at event time if immutable historical billing is required.

**Steps:**

- [ ] Replace scalar-only cost math with `{amount: Decimal | None, status,
      priced_units, unpriced_units, as_of}`.
- [ ] Distinguish `known`, `partial`, `unknown`, and `not_applicable`.
- [ ] Preserve a true zero price as `known` and `$0.00`.
- [ ] For old clients, keep additive compatibility fields as needed, but new UI
      must not render a numeric zero when `cost_known=false`.
- [ ] Append new CSV columns after the existing header:
      `provider_prompt_tokens,provider_completion_tokens,provider_total_tokens,
      estimated_tokens,quota_tokens,per_call_units,cost_status,cost_as_of`.
      Do not reorder the original five during the compatibility window.
- [ ] Add fixtures for catalog miss (gpt-5.6-luna), known paid, known free,
      mixed priced/unpriced groups, per-call configured/unconfigured, and legacy.

**Acceptance:** Missing gpt-5.6-luna pricing displays “unknown,” not `$0/free`,
and partial rollups disclose their unpriced share.

**Commit:** `fix: distinguish unknown and free usage costs`

## Task 8 — Publish additive APIs and regenerate the client

**Files:**

- Modify: `backend/src/ragz/modules/quotas/schemas.py`
- Modify: `backend/src/ragz/api/routes/usage.py`
- Modify: report route schemas
- Modify: `backend/tests/api/test_usage_endpoints.py`
- Modify: report endpoint tests
- Regenerate: `frontend/src/api/schema.d.ts`
- Modify aliases: `frontend/src/api/types.ts`

**Proposed `/usage/me` response:** Retain legacy fields and add structured data:

```json
{
  "used_tokens": 1710000,
  "allocated_tokens": null,
  "quota": {"used_tokens": 1710000, "allocated_tokens": null},
  "provider": {
    "prompt_tokens": 8678,
    "completion_tokens": 1448,
    "total_tokens": 10126,
    "cached_prompt_tokens": null,
    "reasoning_tokens": null,
    "completeness": "partial"
  },
  "estimates": {
    "processing_tokens": 1699810,
    "current_indexed_tokens": 1699810,
    "estimator": "chars_div_4:v1"
  },
  "units": [{"type": "web_search", "count": 0}],
  "cost": {"usd": null, "status": "unknown", "as_of": "..."},
  "resets_at": "...",
  "warning": false
}
```

Numbers above illustrate shape only; tests must use fixture values.

**Steps:**

- [ ] Decide whether the current-corpus total is user-owned, workspace-visible,
      or org-scoped and enforce that policy server-side. Never accept an
      unvalidated workspace ID from the UI.
- [ ] Add equivalent dimensions to daily/admin/report APIs without breaking
      existing consumers.
- [ ] Make completeness explicit for rollups containing legacy or unknown events.
- [ ] Regenerate TypeScript from OpenAPI; never hand-edit generated definitions.
- [ ] Add route authorization/isolation tests for every scope.

**Acceptance:** Old clients keep working, new clients can display every category
without recomputing accounting semantics in JavaScript.

**Commit:** `feat: expose separated usage dimensions`

## Task 9 — Replace misleading UI language

**Files:**

- Modify: `frontend/src/features/chat/usage-meter.tsx`
- Modify: `frontend/src/features/usage/usage-page.tsx`
- Modify: `frontend/src/features/reports/reports-page.tsx`
- Modify: `frontend/src/features/admin/dashboard/dashboard-page.tsx`
- Modify: `frontend/src/features/admin/quotas/org-quota-dialog.tsx`
- Modify all corresponding tests.

**UI contract:**

- Header compact meter: `Quota 1.7M` or `10.1K provider tokens`; never bare
  `1.7M tokens` when it includes estimates. A tooltip/popover shows the split.
- Personal usage: separate cards for quota debit, provider-reported input/output,
  estimated processing, currently indexed corpus, and service units.
- Reports: category-aware columns and badges for estimated/partial/unknown.
- Cost: `Unknown price` or `Partial estimate`, never `$0.00` unless known free.
- Cached and reasoning tokens appear as included details, not additional totals.

**Steps:**

- [ ] Implement loading, unavailable, legacy-only, partial, unknown, and known-zero
      states accessibly.
- [ ] Explain estimator limitations in plain language.
- [ ] Keep quota warnings based solely on quota usage/allocated quota.
- [ ] Add component tests for the clean three-book shape: large corpus estimate,
      small provider usage, and unknown model price.
- [ ] Verify responsive layout and keyboard/screen-reader labels.

**Acceptance:** A user cannot reasonably mistake indexed text estimates for LLM
provider consumption or unknown price for free service.

**Commit:** `fix: label quota provider and corpus usage accurately`

## Task 10 — Verification, benchmark, and rollout

**Backend gates:**

```bash
cd backend
DOCKER_HOST=unix:///var/run/docker.sock uv run ruff check src tests
DOCKER_HOST=unix:///var/run/docker.sock uv run mypy src
DOCKER_HOST=unix:///var/run/docker.sock uv run lint-imports
DOCKER_HOST=unix:///var/run/docker.sock uv run pytest tests -q
```

**Frontend gates:**

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm bundle-budget
```

**Additional verification:**

- [ ] Migration upgrade/backfill/downgrade/re-upgrade from a current-main dump
      containing representative legacy rows.
- [ ] Generated OpenAPI client produces no drift after regeneration.
- [ ] Concurrency test: duplicate DB persistence of one provider response.
- [ ] Cancellation test after every completed provider stage.
- [ ] Quota freshness test immediately after a committed event.
- [ ] Isolation tests across user/org/workspace/report scopes.
- [ ] Reindex/reembed/version/delete current-corpus state tests.
- [ ] Compare one deterministic MQR chat’s fixture-provider usage to ledger sums
      exactly, field by field.
- [ ] Measure usage-recording overhead at p50/p95/p99 for single insert and an MQR
      turn under concurrent load. Record DB commit time separately. Target no more
      than 5 ms p95 added in the ordinary staged path and no extra provider calls;
      if the environment cannot meet that target, report evidence and redesign.
- [ ] Credential scan and `git diff --check`.

**Rollout order:**

1. Deploy additive migration.
2. Deploy dual-writing backend and additive APIs.
3. Verify old/new aggregate parity for quota in shadow logs/metrics.
4. Deploy new UI.
5. Switch reads to explicit fields.
6. Observe one full quota period before removing compatibility fields.

**Rollback:** Old columns and response fields remain populated. Rolling back the
application leaves additive columns unused. Do not downgrade the migration while
new binaries may still write new-only semantics.

## Required verification artifact

Create `no_rel/verification/reliable-usage-accounting-<date>.md` on the research
branch with:

- branch/base/head and migration revision;
- before/after truth table for every writer;
- exact test commands and summaries;
- legacy/new quota parity results;
- three-book provider/corpus split using redacted identifiers only;
- cost completeness cases;
- latency overhead distribution;
- known limitations and rollout status.

Commit and push every independently reviewable change. Do not open or merge the
PR without explicit user authorization.
