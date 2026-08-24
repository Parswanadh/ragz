# MQR production baseline attestation

Date: 2026-08-24

## Repository integration

- Branch: `codex/multi-query-retrieval`
- Upstream: `https://github.com/marketcalls/ragz.git`
- `upstream/main`: `9d08839f6855967f3b141b731a269a54b76222fb`
- Merge base: `9d08839f6855967f3b141b731a269a54b76222fb`
- Ahead/behind (`upstream/main...HEAD` at plan freeze): `0 / 71`
- Interpretation: current upstream main is already an ancestor. No rebase or
  merge is required before the production tasks begin.

## Defaults and authorization

- `Workspace.rerank_enabled` defaults to `False`.
- `Workspace.multi_query_enabled` defaults to `False`.
- The backend route rejects any non-superadmin PATCH containing
  `multi_query_enabled` before sibling settings can mutate.
- `tenancy.service.update_retrieval_settings` repeats the same check for direct
  service/worker callers.
- The workspace settings dialog renders the MQR toggle only when the decoded
  role is `superadmin` and omits the field from non-superadmin PATCH bodies.
- Existing API coverage includes superadmin round-trip, null rejection,
  admin/user forged PATCH rejection and mixed-PATCH atomicity.

## Fresh verification

Backend command:

```text
DOCKER_HOST=unix:///var/run/docker.sock uv run pytest -q \
  tests/api/test_workspace_settings.py \
  tests/modules/tenancy/test_service.py \
  tests/modules/retrieval/test_query_expansion.py \
  tests/modules/retrieval/test_retrieve.py \
  tests/isolation/test_multi_query_isolation.py
```

Result: `93 passed`, zero failures, seven dependency/deprecation warnings.

Frontend command:

```text
pnpm test -- workspace-settings-dialog.test.tsx
```

Vitest currently treats the trailing filename as an argument rather than a
filter and ran the complete suite. Result: `106` files and `701` tests passed,
zero failures. Existing React `act(...)` and undefined-query-data warnings are
non-fatal baseline warnings and must not be silently presented as new MQR
regressions.

## Current behavior gaps

- Query embedding cache exists only as an explicitly injected benchmark seam;
  production callers do not use it.
- Expansion is low-reasoning but still synchronous and uncached.
- Cohere has no transient retry/`Retry-After` handling.
- Equal-score RRF and reranker results do not have a deterministic secondary
  order.
- The no-answer dense probe starts only after fused vector search.

These gaps map directly to Tasks 2–5 in
`docs/plans/2026-08-24-mqr-production-delivery.md`.
