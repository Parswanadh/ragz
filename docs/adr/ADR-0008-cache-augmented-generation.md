# ADR-0008: Benchmark-Gated Cache-Augmented Generation

**Status:** Experimental; production `NO_GO` for the three-book target corpus
**Date:** 2026-09-04
**Base:** `3fac9fb1d02c9327f243418ebbb905466c8bcef5` (open PR #11 head; experimental)

## Context

Cache-Augmented Generation (CAG) has a narrow meaning in this decision. The
original CAG method preloads the complete knowledge collection, preserves its
model KV state, and answers later questions without query-time retrieval
([Chan et al., 2025](https://doi.org/10.1145/3701716.3715490)). It is intended
for limited, manageable knowledge bases. A cache that merely avoids recomputing
a query embedding, expansion, retrieved answer, or retrieval-selected prefix is
not CAG.

RAGZ is multi-tenant and version-aware. Its current retrieval path constructs
the one Qdrant tenant/ACL/current-version filter, excludes unprojected security
revisions before search, and performs a deny-only post-query recheck
([retrieval/service.py](../../backend/src/ragz/modules/retrieval/service.py)).
Citation persistence resolves each source through the current document access
gate and stores document, version, page, and chunk identity independently of the
prompt ([chat/service.py](../../backend/src/ragz/modules/chat/service.py)). Any
CAG experiment must preserve those guarantees without trusting provider cache
expiry or eviction.

This branch is intentionally based on the exact head of still-open PR #11. It
does not modify that PR branch and cannot be treated as production-ready base
provenance until the base is merged and rebased deliberately.

## Terms that must remain distinct

| Name | Reused object | Per-query retrieval? | RAGZ classification |
|---|---|---:|---|
| Retrieval cache | Query embeddings or query expansions | Yes | Existing optimization; not CAG |
| Semantic response cache | A prior answer selected by similarity | Maybe | Out of scope and unsafe by default |
| API prompt caching | Provider KV work for an identical prompt prefix | Maybe | A provider mechanism, not inherently CAG |
| Local prefix/KV caching | KV tensors retained by a local inference engine | Maybe | Optional future mechanism; not measured here |
| `cached_rag_prefix` | Stable prompt prefix containing retrieval-selected sources | Yes | Benchmark mode; explicitly not CAG |
| `full_snapshot_cag` | Every source in one complete authorized snapshot | No after a valid snapshot selection | CAG |

API prompt caching can implement the KV-reuse part of `full_snapshot_cag` only
when the stable prefix contains the complete eligible knowledge snapshot and the
application does no vector retrieval for that request. The same provider feature
over top-k retrieved chunks is `cached_rag_prefix`, not CAG.

## Evidence as of 2026-09-04

### Exact provider route

The inspected local route is:

```text
RAGZ alias gpt-5.6-luna
  -> LiteLLM 1.96.2, image sha256:154e23bb5f31b1f10e16392a8ef299bd2cde08de3a64a6849002cfcc25ce3c63
  -> openai/gpt-5.6-luna
```

OpenAI documents a 1,050,000-token context window, 128,000 maximum output,
Chat Completions streaming, $0.20/M uncached input, $0.02/M cached input, and
$1.20/M output for GPT-5.6 Luna. Cache writes cost 1.25 times ordinary input
([model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna)).

For GPT-5.6 and later, the official prompt-cache contract says:

- the minimum visible cacheable prefix is 1,024 tokens;
- implicit and explicit breakpoints are supported;
- explicit mode uses `prompt_cache_options` plus a nested
  `prompt_cache_breakpoint`;
- the only documented/default TTL is `30m` after the most recent write or reuse;
- `prompt_cache_key` influences routing but neither pins a machine nor
  guarantees a hit;
- caches are not shared across OpenAI organizations or regional processing
  boundaries; and
- provider usage reports `cached_tokens`, `cache_write_tokens`, and reasoning
  token detail.

Source: [OpenAI prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching).

LiteLLM's current documentation describes OpenAI prompt caching and normalized
`prompt_tokens_details.cached_tokens`
([LiteLLM prompt caching](https://docs.litellm.ai/docs/completion/prompt_caching)).
The pinned 1.96.2 installed source statically lists `prompt_cache_key` and the
older `prompt_cache_retention` for OpenAI Chat, and preserves nested usage
details. It does not name `prompt_cache_options` or
`prompt_cache_breakpoint`. That source-level gap is a version-specific warning,
not proof of failure: the exact live proxy's permissive request path was probed
and the upstream provider behavior below proves those newer fields survived
this route. Future image changes require a fresh probe; catalog/provider type
alone is not capability evidence.

### Sanitized capability probe

Only synthetic repeated text was sent. Keys, request bodies, outputs, request
IDs, and tenant data were not retained. The complete sanitized record is
[provider-capability-probe-2026-09-04.json](../../no_rel/benchmarks/cag/evidence/provider-capability-probe-2026-09-04.json).

| Probe | Prompt tokens | Cached | Cache write | Latency |
|---|---:|---:|---:|---:|
| Implicit cold | 7,158 | 0 | 7,155 | 2,433 ms |
| Implicit exact repeat | 7,158 | 7,155 | 0 | 1,262 ms |
| Implicit, changed question | 7,158 | 7,144 | 11 | 1,329 ms |
| Explicit mode, no breakpoint | 6,736 | 0 | 0 | 1,378 ms |
| Explicit marked prefix, cold | 6,736 | 0 | 6,724 | 1,108 ms |
| Explicit marked prefix, changed question | 6,736 | 6,724 | 0 | 909 ms |
| Streaming explicit cold | 5,895 | 0 | 5,884 | TTFB 1,670 ms |
| Streaming explicit warm, changed question | 5,896 | 5,884 | 0 | TTFB 930 ms |

This is a capability probe, not a representative latency benchmark. It proves
supported semantics and telemetry on the exact route. It does not prove a
20-percent product benefit, quality parity, cache isolation inside RAGZ, or
correctness under revocation.

### Target corpus fit

The three private networking books are represented only by hashes and aggregate
facts. No title, PDF, extracted text, prompt, or answer is committed.

| Private ID | SHA-256 | PDF pages | Unique chunks | Raw text tokens |
|---|---|---:|---:|---:|
| `book-01` | `fec3e7c7d583018633cbba69510cdb9bba01622f4eed6ef894f571b909c59f25` | 861 | 3,500 | 485,135 |
| `book-02` | `7599e188b2645104576b5502400565aff7892ef02abb866ed6899ef9b5865a9a` | 775 | 1,851 | 470,705 |
| `book-03` | `dca8648949db3f7f95f29917a32718d98a06888083c7f86712c9aa070cfebcb8` | 946 | 3,023 | 621,502 |
| **Total** | — | **2,582** | **8,374** | **1,577,342** |

Token counts use `tiktoken==0.13.0` with `cl100k_base` over unique current
chunk text. They are an estimator rather than provider token telemetry. Raw
source text alone is about 50 percent larger than Luna's advertised context
window and excludes prompt policy, data markers, history, the question, and
output reserve. RAGZ's current application context budget is 8,000 tokens.
The complete three-book workspace is therefore deterministically ineligible for
`full_snapshot_cag` under both the application budget and the provider window.

An independent no-overlap check streamed Poppler `pdftotext==24.02.0` output
directly into local token counters without persisting text. It measured
1,472,177 `cl100k_base` tokens and 1,465,157 `o200k_base` tokens. Even the lower
count exceeds the advertised window by 415,157 tokens before any required
prompt or output reserve, so chunk overlap is not the cause of the `NO_GO`.

### Open-source comparison

Inspection found no general full-snapshot CAG mode in the pinned comparison
systems:

| System | Pinned source | Relevant behavior | Not found |
|---|---|---|---|
| AnythingLLM 1.16.0 | [`55b6ebc`](https://github.com/Mintplex-Labs/anything-llm/tree/55b6ebcea132f0d7ac146da99a0cd0db507b9030) | Opt-in Anthropic prompt caching; document-vector reuse | Full-snapshot CAG, semantic answer cache |
| RAGFlow 0.27.0 | [`ec9c08d`](https://github.com/infiniflow/ragflow/tree/ec9c08d809f63ba2815090182fa225899d2437d5) | Ordinary retrieval and provider usage fields | Full-snapshot CAG or a RAGFlow prompt-cache layer |
| Onyx 4.6.0 | [`b4553eb`](https://github.com/onyx-dot-app/onyx/tree/b4553eb55ceb2c6a561c57892a528c65bd8626b1) | Provider prompt-cache adapters and tenant-scoped query-embedding cache | Full-snapshot CAG, semantic answer cache |

These are code-inspection inferences, not vendor claims. Prompt-cache metadata
or a cache table alone was not treated as evidence of CAG.

## Decision

1. Keep all CAG behavior absent and default-off in production. Do not add model,
   workspace, API, migration, or UI configuration from this evidence alone.
2. Build a deterministic, provider-independent prototype for immutable snapshot
   identity, eligibility, and fail-closed validation. It may be imported by a
   benchmark harness, but it is not wired into `stream_reply`.
3. Benchmark `full_snapshot_cag` only on corpora that are complete and eligible.
   The combined three-book cell must be emitted as `ineligible` with the measured
   token reason, never as zero and never as a subset silently relabeled CAG.
4. Benchmark `cached_rag_prefix` separately after the existing retrieval,
   pinned/backfill merge, authorization recheck, and source fitting. It may not
   create a second retrieval or ACL path.
5. Ordinary RAG/MQR remains the fail-closed fallback. A cache miss, unsupported
   provider, stale snapshot, validation error, or ineligible request must fall
   back before generation. A stale prefix is never combined with fresh results.
6. The production decision remains `NO_GO` until every hard security and
   citation gate passes and the preregistered quality/performance thresholds in
   the benchmark protocol are met. The target three-book workspace has already
   failed the complete-snapshot fit gate, so it cannot become a production CAG
   pilot regardless of later latency results.

This is falsifiable: an eligible small-corpus mode advances only if provider
telemetry, exact snapshot validation, citation parity, quality non-inferiority,
and at least one material performance/cost threshold all pass. Otherwise its
decision stays `NO_GO` or, only for a narrowly bounded non-sensitive cohort,
`LIMITED_PILOT`.

## Authorized snapshot design

### Immutable values

The prototype owns frozen `CagSource`, `SnapshotPolicy`, `CagSnapshot`, and
`ValidationState` values. A source binds:

- org and workspace;
- document ID, content hash, version, current/approval/status state;
- page, chunk index, section, source marker, and source-text hash;
- exact source text for rendering, but never in a key or log;
- ACL group IDs, security revision, projected security revision, and index
  state.

The snapshot also binds mode; visibility scope; restricted principal ID when
required; effective groups and ACL-bypass posture; workspace prompt hash;
template and fitting-policy versions; model, gateway route, tokenizer and
version; input/output/history/tool reserve; context budget; configuration
version; TTL; and ordered sources.

### Canonical identity

`snapshot_id` is SHA-256 over a versioned, typed, length-delimited UTF-8
serialization. Collections are sorted before serialization; sources use the
canonical `(document_id, version, page, chunk_index, marker)` order. Strings are
encoded exactly, including Unicode, and each field carries its type and byte
length. Raw source text is represented only by SHA-256 in the identity. This
avoids delimiter ambiguity and prevents document text, questions, answers, or
credentials from entering cache keys or labels.

Restricted snapshots are always per-principal in v1. Cross-user reuse is
permitted only when every source is unrestricted; even then, every request must
freshly prove workspace membership and `chat.generate`. A shared unrestricted
key includes org/workspace and all state/config bindings but omits user-specific
groups so equivalent workspace members can reuse it safely.

### Eligibility

`full_snapshot_cag` is eligible only when all of the following are true:

- the snapshot includes every current, indexed, active, properly projected
  source visible to the freshly authorized caller;
- all rows belong to exactly one org and workspace;
- restricted content is bound to the current principal;
- the fully rendered stable prefix meets the provider minimum and fits after
  policy, history, query/tool/attachment, and output reservations;
- parser/page metadata, tokenizer identity, route, and model are known;
- the request uses no web results, chat attachments, image content, agent tool
  results, or other dynamic source class not captured in the snapshot; and
- the mode has a defined abstention policy and authoritative source map.

An empty complete workspace is ineligible. A source subset selected to fit is
not full-snapshot CAG. Large or mixed-ACL workspaces are expected to be
ineligible frequently; ordinary RAG/MQR is the intended behavior for them.

`cached_rag_prefix` receives its sources only from the existing fitted RAG path.
It is eligible only after that path's post-query ACL recheck and retains every
ordinary source/citation object.

## Validation and invalidation

Every use rebuilds `TenantContext` and compares a fresh authoritative manifest,
not only the cached sources. This detects both revoked/changed sources and newly
visible current sources that would make a supposedly complete snapshot
incomplete. Reject when any of these differs:

- principal membership, groups, relevant permissions, or ACL-bypass posture;
- document set, ID, content hash, version, `is_current`, approval requirement,
  status, deletion state, or projection state;
- `security_revision` or `projected_security_revision`;
- prompt, template, fit policy, model, route, tokenizer, budgets, config, or TTL.

Outbox event `chat.cag.invalidate` may later evict org/workspace/document-scoped
local entries, but it is defense in depth only. Delayed, lost, duplicated, or
out-of-order eviction cannot authorize a snapshot. Handlers must be idempotent.
Membership has no revision counter today, so a fresh context and authorization
fingerprint are mandatory on every use.

Concurrent construction uses a manifest-before/render/manifest-after protocol.
If the two manifests differ, construction is discarded. A single-flight owner
may share work only for the same full key; waiters must be released on success,
failure, or owner cancellation.

## Provider seam and telemetry

The production seam, if a later decision permits it, uses:

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

`LLMUsage` must preserve provider input, output, cached, cache-write, and
reasoning tokens without estimating unknown fields. A provider-reported
positive read is `hit`; a positive write is `write`; absent fields are
`unknown`, not a miss. Model capability is route/model/version/probe-specific
and tri-state. Metrics use bounded provider/route capability labels only.

On an explicit cache-parameter rejection before any output, a future production
adapter may retry once without cache. It must never retry after a streamed
delta, ambiguous timeout, disconnect, or other state in which generation may
already have occurred. Current RAGZ exceptions do not carry enough typed state
to implement that safely, so the prototype does not wire this retry.

## Prompt, citations, abstention, and fallback

Ordinary `build_messages` remains byte-for-byte unchanged. A future
`build_cag_messages` would order:

1. stable system/policy content;
2. one stable, escaped source-data message and explicit breakpoint;
3. dynamic summary/history; and
4. current question and supported attachments.

Markers and persisted `SourceRef`/`Citation` objects remain authoritative. The
provider cache never becomes a citation record. Emitted markers outside the
snapshot map are discarded exactly as ordinary out-of-range markers are.

Full-snapshot CAG cannot use retrieval score for pre-generation no-answer. Its
experimental prompt therefore requires an explicit insufficient-evidence
outcome with no citations; answerable/unanswerable quality and selective risk
are hard benchmark gates. Until those gates pass, ordinary RAG's existing
score-based abstention remains the production behavior.

## Threat analysis

| Threat | Required control | Hard failure |
|---|---|---|
| Cross-org/workspace key collision | Typed key includes both IDs; mixed input rejected | Any exposure => `NO_GO` |
| Restricted prefix reused by another user | Per-principal v1 key and fresh context | Any reuse => `NO_GO` |
| ACL/group revocation races provider cache | Fresh manifest/fingerprint before every call; validate twice on build | Any stale source => `NO_GO` |
| Version promotion/deletion/projection outage | Bind current/version/projection state; fail closed | Any stale source => `NO_GO` |
| Prefix injection | Reuse existing escaped `<data>` rendering and fixed policy | Escaped-boundary regression => `NO_GO` |
| Forged citation marker | Persist only markers in authoritative source map | Invalid persisted reference => `NO_GO` |
| Cache telemetry inferred from latency | Provider usage only; otherwise `unknown` | False hit claim => `NO_GO` |
| Duplicate generation on retry | Retry only typed pre-output rejection, once | Any post-output retry => `NO_GO` |
| Content in keys/logs/metrics | Hash raw text; bounded labels; content/credential scan | Any leak => `NO_GO` |
| Memory/cardinality exhaustion | Bounded TTL/entries/bytes and cancellation-safe single-flight | Unbounded growth/stranded waiter => `NO_GO` |

## Consequences

- The exact provider route is capable of measured prefix caching, including
  streaming telemetry.
- The target three-book corpus is not a full-snapshot CAG candidate. This is a
  useful negative result, not a reason to rename retrieval-selected caching.
- Small complete corpora can be evaluated safely through a pure prototype and
  synthetic fixtures before any product surface exists.
- API prompt caching still transmits the prefix on every request and depends on
  provider routing/retention. It does not create a local durable snapshot store.
- The present application usage ledger drops cache and reasoning details, so
  the benchmark harness must capture raw provider-returned usage until the
  broader accounting foundation lands. The current 1.7M meter is not provider
  consumption evidence.
- No migration, API, UI, runtime, or GitHub state is changed by this decision.
