# Upstream branch and MQR audit

Date: 2026-09-04

## Decision

No branch in `marketcalls/ragz` contains multi-query retrieval, query expansion,
query variants, query rewriting, the `multi_query_enabled` workspace field, or
an MQR migration/UI control. No upstream pull request was open at the decision
boundary. The condition for submitting the verified MQR implementation was
therefore satisfied, and pull request
[#11](https://github.com/marketcalls/ragz/pull/11) was opened from
`Parswanadh:codex/mqr-production-ready` into `marketcalls:main`.

## Authoritative branches

`ahead/behind` is relative to upstream `main` at `9d08839f`. “MQR” was checked
with exact production symbols plus generic multi-query/query-expansion/rewrite
terms and the retrieval implementation shape.

| Branch | Head | Main-only / branch-only commits | MQR | Interpretation |
|---|---|---:|---|---|
| `main` | `9d08839f` | 0 / 0 | no | Authoritative target; single dense and single sparse query |
| `phase-2-api-orm` | `9eb16893` | 8 / 2 | no | Stacked API/service ORM cleanup, not on main |
| `phase-2-completion` | `e02bcd43` | 8 / 3 | no | Same cleanup plus stacked merge commit |
| `phase-3-bundle` | `8e35250d` | 11 / 0 | no | Stale ancestor; bundle work already merged to main |
| `phase-3-metrics` | `f2c89586` | 11 / 3 | no | Stacked OpenTelemetry work, not on main |
| `phase-3-streaming-uploads` | `7b2259d4` | 10 / 0 | no | Stale ancestor; streaming uploads already merged |
| `phase-3-tracing` | `c7896b26` | 11 / 2 | no | OpenTelemetry HTTP/Celery tracing only |
| `production-hardening` | `c9610324` | 13 / 0 | no | Stale ancestor; PR #2 content already merged |
| `spike/agno-vs-handrolled` | `52cd7ec3` | 399 / 1 | no | Old July architecture spike, not a product implementation |

All eight branches with the current retriever still contain the single-query
dense/sparse call shape. The older AGNO spike has neither the current retrieval
shape nor an MQR implementation.

## Fork branches

| Branch | Head | Main-only / branch-only commits | MQR | Use |
|---|---|---:|---|---|
| `Parswanadh:main` | `b2394985` | 12 / 0 | no | Stale fork main |
| `codex/mqr-production-ready` | `3fac9fb1` | 0 / 14 | yes | Focused 47-file PR source |
| `codex/multi-query-retrieval` | `b868b6cc` | 0 / 90 | yes | Research/evidence history; deliberately not PR source |

GitHub’s compare API reported the product branch as 14 commits ahead, zero
behind, 47 changed files, with merge base `9d08839f`.

## Fresh pre-PR verification

- Backend: `1762 passed, 14 skipped`; eight dependency deprecation warnings;
  `800.45 s`.
- Frontend: 106 files, `709 passed`.
- Ruff: passed.
- Strict mypy: no issues in 161 source files.
- ESLint and TypeScript: passed.
- Production build: passed.
- Initial download: `171.7 kB` gzip against the `200 kB` budget.
- Production Compose render: passed.
- Alembic: one head, `6a8d2c4f1b90`.
- Worktree: clean; product SHA matched the fork remote.

## PR state

- PR: [#11](https://github.com/marketcalls/ragz/pull/11)
- State: open, ready for review, not draft.
- Base/head: `marketcalls:main` ← `Parswanadh:codex/mqr-production-ready`.
- Head SHA: `3fac9fb1d02c9327f243418ebbb905466c8bcef5`.
- Linked issue: [#10](https://github.com/marketcalls/ragz/issues/10).
- CI and dependency-audit workflows: `action_required` with zero jobs; an
  upstream maintainer must approve workflows for the forked PR. This is an
  authorization gate, not a failing test result.
- Cubic reviewer: pending at the recording boundary.

The isolated worktree remains available for review feedback. No stale upstream
branch was merged into the focused PR, and the shared dirty checkout was not
modified.
