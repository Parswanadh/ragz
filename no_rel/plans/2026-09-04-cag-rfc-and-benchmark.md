# Cache-Augmented Generation RFC and Benchmark Plan

> **Scope:** Determine whether CAG is safe, measurable, and useful for RAGZ,
> then implement only the variant that passes the gates below. Do not use
> Superpowers. Do not modify `/home/parshu/projects/ragz`. This work follows the
> usage-accounting foundation so cache/token/cost results are not misleading.

**Goal:** Add a provider-neutral, fail-closed cached-context capability for small
eligible corpora without weakening RAGZ tenant, ACL, version, citation,
abstention, or fallback guarantees.

## First clarify the term “CAG”

These mechanisms must remain separate in code, UI, metrics, and reports:

| Mechanism | What is reused | Still retrieves per query? | Valid name |
|---|---|---:|---|
| Query embedding/expansion cache | query-derived vectors/alternatives | Yes | retrieval cache |
| Provider prompt cache | repeated request prefix at an API provider | Maybe | API prompt caching |
| Local model KV cache | attention key/value tensors in one inference engine | Maybe | local prefix/KV caching |
| Retrieval-selected prompt prefix | the same fitted RAG sources | Yes | cached RAG prefix |
| Complete eligible knowledge snapshot | all allowed corpus content in context/KV | No on a hit | CAG |

The initial RFC benchmarks both true CAG and cached RAG prefixes. RAGZ must not
market the existing in-memory embedding/query-expansion caches as CAG. Because
the current deployment preference is cloud APIs rather than local models, API
prompt caching is the first candidate; local KV mode stays optional and cannot
be claimed without a measured local inference capability.

## Go/no-go gates

Production implementation is prohibited until all are true:

- [ ] The exact provider route and answer model demonstrate supported cache
      semantics through official documentation plus a synthetic capability probe.
- [ ] Cache telemetry is provider-reported or marked unknown; a latency change
      alone is not called a hit.
- [ ] The complete eligible snapshot fits its token budget while reserving space
      for policy, history, question, tool results, and output.
- [ ] The MVP operates on one ACL-homogeneous visibility cohort or a per-principal
      snapshot; no cross-principal restricted snapshot reuse.
- [ ] Every source is bound to document/version/security revision/currentness.
- [ ] ACL/group/version changes are fail-closed without depending on eventual
      cache eviction.
- [ ] Cached/uncached citation mappings and abstention behavior meet the hard
      correctness thresholds below.
- [ ] Warm latency or billable-input reduction is material enough to justify the
      extra invalidation and operations surface.

If a gate fails, ship the RFC and benchmark with a `NO_GO` result. Do not quietly
turn the experiment into a different feature.

## Branch and evidence setup

- [ ] Start only after the accounting work provides reliable provider/cache token
      detail or explicitly stack the prototype on that branch.
- [ ] Create `/home/parshu/projects/rag-comparison-sources/ragz-cag-evaluation`
      on branch `codex/cag-rfc-benchmark` from the exact selected base.
- [ ] Keep proprietary book PDFs and raw extracted text outside Git. Store only
      schemas, scripts, hashes, aggregate metrics, redacted examples, and
      environment manifests in version control.
- [ ] Record provider/model route, model identifier, context window, embedding
      model/dimensions for RAG baselines, parser, chunking, reranker, top-k,
      MQR count, prompt version, and commit SHA before every run.
- [ ] Never print API keys or provider request bodies. Use the existing secret
      injection path and redact request IDs if they encode account information.

## Task 1 — Produce an evidence-backed RFC before code

**Files:**

- Create: `docs/adr/<next>-cache-augmented-generation.md`
- Create: `no_rel/benchmarks/CAG_EXPERIMENT_PROTOCOL.md`
- Inspect:
  - `backend/src/ragz/modules/tenancy/context.py`
  - `backend/src/ragz/modules/documents/service.py`
  - `backend/src/ragz/modules/documents/models.py`
  - `backend/src/ragz/modules/retrieval/service.py`
  - `backend/src/ragz/modules/chat/prompting.py`
  - `backend/src/ragz/modules/chat/service.py`
  - `backend/src/ragz/modules/chat/llm.py`
  - `backend/src/ragz/modules/models/models.py`
  - `backend/src/ragz/modules/outbox/service.py`
  - `backend/src/ragz/worker/outbox.py`

**Research:**

- [ ] At execution time, read the current official provider/API documentation
      for prompt caching, minimum prefix size, expiry, supported request shape,
      usage fields, pricing, and streaming restrictions. Cite primary sources.
- [ ] Inspect LiteLLM’s exact pinned version and official documentation/source to
      determine which cache hints/usage details survive the gateway.
- [ ] Research current CAG implementations in open-source RAG systems using their
      repository code and official docs, not blog claims. For each, distinguish
      full-context CAG, provider prompt caching, semantic response caching, and
      retrieval caching.
- [ ] Write an evidence matrix with date, version/SHA, capability, configuration,
      invalidation behavior, security model, citation behavior, and source link.
- [ ] Any claim inferred from source code must be labeled as an inference.

**RFC decisions:**

- [ ] Define two separately named modes:
  - `full_snapshot_cag`: no vector retrieval after a valid complete-snapshot hit.
  - `cached_rag_prefix`: normal authorized retrieval, then cache/reuse the stable
    fitted source prefix.
- [ ] Set both modes default-off and superadmin-configurable if they ever reach
      product settings. Backend authorization remains decisive.
- [ ] Define provider-neutral interfaces, capability records, cache-key contents,
      invalidation, fallback, telemetry, rollout, and threat analysis.
- [ ] Record why full CAG is ineligible for large/mixed-ACL workspaces and why the
      fallback remains ordinary RAG/MQR.

**Acceptance:** The RFC makes a falsifiable choice and cannot confuse prompt
caching, local KV caching, semantic answer caching, and CAG.

**Commit:** `docs: define CAG security and benchmark gates`

## Task 2 — Specify immutable authorized snapshots

**Proposed module:**

- Create only in the prototype: `backend/src/ragz/modules/chat/cag.py`
- Tests: `backend/tests/modules/chat/test_cag.py`
- Isolation tests: `backend/tests/isolation/test_cag_isolation.py`

**Proposed types:**

```python
@dataclass(frozen=True)
class CagSource:
    document_id: UUID
    version: int
    page: int
    chunk_index: int
    section: str | None
    text: str
    marker: int
    acl_group_ids: tuple[UUID, ...] | None
    security_revision: int

@dataclass(frozen=True)
class CagSnapshot:
    snapshot_id: str
    mode: Literal["full_snapshot_cag", "cached_rag_prefix"]
    org_id: UUID
    workspace_id: UUID
    sources: tuple[CagSource, ...]
    rendered_prefix: str
    token_count: int
    authorization_fingerprint: str
    template_version: str
```

**Snapshot key:** SHA-256 over a canonical, length-delimited serialization of:

- org and workspace IDs;
- mode;
- ordered `(document_id, version, page, chunk_index, section, text_hash, marker)`;
- every document security revision, projection state, and current-version state;
- effective current group IDs plus ACL-bypass permissions;
- per-principal user ID for restricted snapshots;
- workspace prompt override hash;
- prompt/template/fitting-policy version;
- model ID, gateway route identity, tokenizer/version, context budget;
- CAG configuration version.

Never include raw source text, raw query, answer, or keys in cache keys/logs.

**Eligibility:**

- `full_snapshot_cag` includes every current/indexed/approved source visible to the
  caller. It is valid only if that complete authorized set fits and all sharing
  rules are safe.
- `cached_rag_prefix` forms its snapshot only after the existing retrieval,
  pinned/backfill merge, post-query ACL recheck, and `fit_sources`. It must not
  create a second retrieval/authorization path.
- Restricted snapshots are per-principal in v1. Cross-user reuse is allowed only
  when every source is unrestricted. Restricted ACL-cohort reuse is deferred.

**Steps:**

- [ ] Write pure snapshot/key/eligibility tests first with no provider or Docker.
- [ ] Test canonical ordering, Unicode, source mutation, prompt/model/config
      changes, membership changes, and digest collision resistance assumptions.
- [ ] Test that mixed org/workspace input is rejected rather than filtered.
- [ ] Test token-envelope reservation and deterministic “ineligible” reasons.

**Acceptance:** Equal authorized immutable input yields one key; every
security/content/model/prompt change yields a different key or an ineligible
result.

## Task 3 — Design invalidation as defense in depth

**Files:**

- Modify in prototype: document ACL/version/promotion paths
- Modify: `backend/src/ragz/modules/outbox/service.py`
- Modify: `backend/src/ragz/worker/outbox.py`
- Tests: existing outbox, ACL projection, version isolation, and new CAG tests

**Hard validation on every use:** Reject a snapshot if any source:

- has a changed `security_revision`;
- has `index_state != 'active'`;
- has `projected_security_revision != security_revision`;
- is deleted, non-current, unapproved where approval is required, or superseded;
- is no longer visible to the freshly built `TenantContext`;
- belongs to a different org/workspace.

Also reject when current group membership/permissions, workspace prompt,
template, model, route, tokenizer, fit policy, config version, or TTL differs.

**Steps:**

- [ ] Recompute the authorization fingerprint from fresh `TenantContext` on every
      request; current membership has no standalone revision counter.
- [ ] Publish `chat.cag.invalidate` transactionally with ACL, delete, version
      promotion, prompt, and relevant model/config changes.
- [ ] Treat the outbox event as an eviction optimization only. Correctness comes
      from hard key validation, so delayed/lost/duplicate handlers stay safe.
- [ ] Make handlers org/workspace/document scoped and idempotent.
- [ ] Test delayed event, duplicate event, worker outage, concurrent snapshot
      build during ACL update, membership revocation, v1→v2 promotion, and failed
      projection.

**Acceptance:** Every revocation/version race fails closed even when eviction
does not run.

## Task 4 — Add a provider-neutral cache capability seam

**Files:**

- Modify after accounting lands: `backend/src/ragz/modules/chat/llm.py`
- Modify: `backend/src/ragz/modules/models/models.py`
- Modify: `backend/src/ragz/modules/models/schemas.py`
- Modify: `backend/src/ragz/modules/models/service.py`
- Modify: `backend/src/ragz/modules/models/sync.py`
- Modify: `backend/src/ragz/api/routes/models.py`
- Modify: `backend/src/ragz/core/metrics.py`
- Tests: `backend/tests/modules/chat/test_llm.py`
- Tests: `backend/tests/modules/models/test_capabilities.py`

**Proposed protocol:**

```python
@dataclass(frozen=True)
class PromptCacheRequest:
    snapshot_id: str
    mode: Literal["auto", "disabled", "required"] = "auto"

@dataclass(frozen=True)
class CacheUsage:
    requested: bool
    outcome: Literal[
        "hit", "write", "miss", "unsupported", "unknown", "not_requested"
    ]
    read_tokens: int | None = None
    write_tokens: int | None = None
```

Extend stream/complete with an optional cache request and attach cache usage to
the accounting-aware `LLMUsage`. Default `None` preserves existing fakes.

**Measured model capability:** Store route/model-specific tri-state results:

```text
prompt_cache_api: unknown | supported | unsupported
local_prefix_kv: unknown | supported | unsupported
cache_control_adapter: identifier or null
minimum_prefix_tokens: integer or null
cache_usage_reported: boolean
probed_at, probe_version, error_code
```

**Steps:**

- [ ] Probe via the same LiteLLM route with a synthetic non-sensitive repeated
      prefix. Never send tenant content during capability detection.
- [ ] Do not infer support solely from provider kind, marketing name, latency, or
      model catalog metadata.
- [ ] Decorate provider payloads only through a small adapter selected by measured
      capability.
- [ ] On an explicit unsupported-cache response before any output, retry once
      without cache. Never retry after partial streamed output or ambiguous timeout.
- [ ] Unknown telemetry stays `unknown`; it is not a cache miss or hit.
- [ ] Bound metric labels to provider/route capability categories—no tenant IDs,
      snapshot IDs, document IDs, or queries.

**Acceptance:** Unsupported/unknown providers behave exactly like current
generation; cache hints cannot cause duplicate generation after partial output.

## Task 5 — Preserve prompting, citations, and fallback byte-for-byte

**Files:**

- Modify: `backend/src/ragz/modules/chat/prompting.py`
- Modify: `backend/src/ragz/modules/chat/service.py`
- Tests: `backend/tests/modules/chat/test_prompting.py`
- Tests: `backend/tests/api/test_chat_stream.py`
- Tests: `backend/tests/api/test_chat_backfill.py`
- Tests: citation and no-answer suites

**Design:** Current message ordering puts dynamic history before the source data,
which prevents a stable provider prefix. Add `build_cag_messages(...)` rather
than changing ordinary `build_messages(...)`:

1. stable system/policy content;
2. stable escaped source-data message;
3. dynamic summary/history;
4. current query and attachments.

The ordinary disabled/ineligible/fallback path must retain today’s message shape.

**Steps:**

- [ ] Produce identical ordered source markers for cached and uncached modes.
- [ ] Keep `_source_refs`, authorization checks, `parse_citation_markers`, and
      persisted citation document/version/page/chunk mapping authoritative.
- [ ] Never treat a cached prefix as the citation record.
- [ ] Confirm full-snapshot CAG has a defined abstention threshold and cannot cite
      outside the snapshot even if the model emits a bogus marker.
- [ ] If snapshot validation or provider capability fails, fall back to ordinary
      RAG/MQR before generation. Never combine a stale snapshot with fresh results.
- [ ] Preserve streaming stop, quota, audit, rich UI, web-search, attachments,
      and Gatekeeper semantics or explicitly mark a mode ineligible.

**Acceptance:** Deterministic fake-provider outputs produce identical valid
marker-to-source mappings in cached and uncached paths.

## Task 6 — Build a professional, controlled benchmark harness

**Files:**

- Create: `backend/scripts/bench_cag.py`
- Create: `no_rel/benchmarks/cag/README.md`
- Create: schemas under `no_rel/benchmarks/cag/schemas/`
- Store sanitized results under `no_rel/benchmarks/results/cag/`

**Corpus:** Use the three local networking books as a private corpus. Record file
hashes, page counts (861, 775, 946), parser/version, and total eligible token
estimate; never commit PDFs, raw chunks, raw prompts, or long excerpts. Add a
small redistributable synthetic corpus for CI correctness tests.

**Question set:** At least 120 private questions, stratified and frozen before
running systems:

- 25 single-document fact/location questions;
- 20 multi-hop within one document;
- 20 cross-document synthesis/comparison;
- 15 terminology/paraphrase/ambiguous phrasing;
- 15 table/figure/page-sensitive questions where parsers support them;
- 15 answerable but low lexical-overlap questions;
- 10 unanswerable/adversarial questions.

Use stable question IDs and private encrypted/local fixtures. Keep assessors blind
to variant. Freeze ground truth and relevance judgments before final runs.

**Controlled variants:**

1. RAGZ single-query retrieval.
2. RAGZ MQR total queries = 3.
3. RAGZ MQR total queries = 5.
4. RAGZ cached RAG prefix, cold and warm.
5. RAGZ full-snapshot CAG, cold and warm, only when eligible.
6. RAGZ hybrid CAG→ordinary RAG fallback.
7. AnythingLLM and RAGFlow using the same answer model, OpenAI embedding model,
   corpus, and query set where their configuration permits.
8. Onyx only when a completed run is feasible; otherwise emit
   `resource_gated` with reason—never zeroes.

Do not vary embedding model/dimension, reranking, top-k, prompt, and CAG in the
same comparison. Choose and freeze one retrieval configuration from the prior
embedding experiment. If a dimension factorial is still required, run it as a
separate experiment first and select the winner without using final test queries.

**Repeated trials:**

- [ ] Warm services and run at least 3 independent repetitions per query/variant;
      randomize variant order and record throttling/retries.
- [ ] Separate cold cache, first write, warm hit, expired, invalidated, and
      unsupported states.
- [ ] Benchmark snapshot sizes 4/8/16/32 chunks and approximately
      512/2k/4k/8k tokens, plus the full eligible corpus.
- [ ] Concurrency levels 1, 4, and 16 for latency/lock contention; quality runs
      remain controlled at low concurrency.

**Retrieval metrics:** Recall@5/@10, MRR@5/@10, nDCG@5/@10, hit rate, unique
relevant-document coverage. Full CAG reports these as not applicable, not zero.

**RAG triad and answer metrics:** context relevance, groundedness/faithfulness,
answer relevance, citation precision, citation recall/coverage, page/version
correctness, abstention precision/recall, exact/F1 where applicable, blinded
pairwise preference for synthesis.

**Atomic latency:** Record monotonic timings for request admission, auth/context,
history, expansion, each embedding batch, sparse embedding, each Qdrant search,
fusion, ACL recheck, no-answer probe, rerank, snapshot lookup/build/validation,
provider queue/connect/TTFT/generation, citation parsing, usage persistence,
message persistence, SSE serialization, end-to-end. Report p50/p95/p99 and sample
count; do not compare the earlier ~50 ms retrieval-only number to end-to-end
generation latency.

**Usage/cost:** Provider input/output/cached/reasoning tokens, local estimates,
quota debit, per-call units, price completeness, estimated cost only when known,
cache hit/write/miss/unsupported/unknown, and billed-input reduction.

**Statistics:** Publish means/medians and bootstrap 95% confidence intervals.
Use paired tests across identical questions and report effect sizes. Correct for
multiple comparisons or explicitly label exploratory results. Keep failures in
the denominator and publish typed failure/resource-gated counts.

## Task 7 — Enforce hard security and correctness tests

**Required scenarios:**

- [ ] Same-user repeat.
- [ ] Different-user unrestricted repeat.
- [ ] Different-user restricted repeat (must not reuse v1 snapshot).
- [ ] Cross-org and cross-workspace identical text.
- [ ] Mixed unrestricted/restricted documents.
- [ ] ACL update during snapshot creation and generation.
- [ ] Group membership revocation.
- [ ] Document v1→v2 promotion, rejected version, deletion, projection outage.
- [ ] Prompt/model/tokenizer/route change.
- [ ] Expiry, duplicate invalidation, worker outage.
- [ ] Cache provider support/rejection/malformed/missing usage.
- [ ] Partial streaming failure and client disconnect.
- [ ] Concurrent identical requests and owner cancellation.

**Hard pass thresholds:**

- Zero cross-org/workspace/revoked source exposure.
- Zero stale source after security/version/membership changes.
- 100% valid persisted citation version/page/chunk references.
- Cached and uncached deterministic fixtures have identical source mappings.
- No retry after partial output; at most one uncached retry after explicit
  pre-output unsupported-cache rejection.
- No raw tenant text/query/key in cache keys, logs, metrics, or public artifacts.
- Bounded memory/cardinality and no stranded single-flight waiter.

Any failure is a production `NO_GO`, regardless of latency gains.

## Task 8 — Make the go/no-go decision

Create `no_rel/benchmarks/results/cag/CAG_GO_NO_GO_<date>.md` with:

- environment/SHAs/configuration and data exclusions;
- provider capability evidence;
- eligibility rate by workspace/corpus size;
- quality, citation, abstention, latency, token, and known-cost tables;
- confidence intervals and failure counts;
- security gate results;
- comparison limitations and parser/indexing differences;
- explicit `GO`, `LIMITED_PILOT`, or `NO_GO` for each mode.

Suggested performance gate for an eligible mode:

- no statistically meaningful regression in groundedness, answer relevance,
  citation precision/coverage, or abstention;
- warm p50 and p95 improve by at least 20% **or** known billable input cost falls
  by at least 20%;
- cache-hit observability is provider-confirmed for claims about token savings;
- cold-path p95 stays within the existing SLO and fallback error rate does not
  increase materially.

Thresholds must be frozen before final benchmark runs. If the pilot misses them,
document why and stop.

## Task 9 — Conditional production implementation

Perform this task only for a mode whose decision is `GO` or `LIMITED_PILOT`.

- [ ] Add default-off global/workspace configuration with backend superadmin-only
      mutation and audit event. Do not rely on a frontend-only gate.
- [ ] Add capability/eligibility read-only status for authorized users.
- [ ] Add bounded TTL/size, single-flight cancellation safety, sanitized metrics,
      outbox eviction, and ordinary-RAG fallback.
- [ ] Do not expose raw cached content or snapshot identifiers in public APIs.
- [ ] Add frontend toggle/status only after backend tests pass; explain eligible,
      warming, hit, fallback, unsupported, and invalidated states accurately.
- [ ] Add migration, OpenAPI regeneration, component, Playwright, isolation,
      cancellation, full backend/frontend, and rollback tests.
- [ ] Roll out to one disposable/synthetic workspace, then one non-sensitive pilot,
      before broader enablement.

Suggested commits:

- `feat: add provider-neutral cache capability probes`
- `feat: build fail-closed authorized CAG snapshots`
- `feat: add measured CAG execution and fallback`
- `feat: expose superadmin CAG controls and telemetry`

Do not put experimental competitor repositories, generated benchmark outputs with
private content, or raw provider traces in the product PR.

## Final verification and handoff

- [ ] Run the exact backend/frontend/migration/schema/browser gates from the
      current CI workflow.
- [ ] Run the CAG security matrix with deterministic fakes and an isolated DB,
      Redis, and Qdrant.
- [ ] Run the frozen private benchmark only after correctness gates pass.
- [ ] `git diff --check`; credential/content scan; verify remote SHA after push.
- [ ] Keep the user’s existing `ragz-mqr-local-test` runtime unchanged unless
      explicitly authorized to deploy the pilot there.
- [ ] Do not open or merge a CAG PR without explicit user authorization.

The handoff must state which mode was evaluated, which cache mechanism was
actually measured, whether provider telemetry confirmed hits, every failed gate,
and the exact branch/SHA containing the evidence.
