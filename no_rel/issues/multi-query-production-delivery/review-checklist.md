# MQR production review checklist

Complete this file against the exact PR head. Do not copy results from a
different branch or a dirty checkout.

## Provenance

- [ ] PR head SHA recorded
- [ ] `git merge-base HEAD upstream/main` recorded
- [ ] `git status --short` is empty
- [ ] pushed remote SHA equals local SHA
- [ ] diff contains no benchmark raw data or competitor source trees

## Product and authorization

- [ ] migration upgrade/downgrade reviewed
- [ ] default is MQR off and rerank off
- [ ] superadmin UI control visible and persistent
- [ ] admin and user UI controls absent
- [ ] forged admin/user PATCH returns 403 and row remains unchanged
- [ ] Q1/Q3 comparison does not mutate workspace settings
- [ ] every query lane uses the same tenant/ACL/current-version filter
- [ ] post-query ACL recheck remains in place

## Latency and resilience

- [ ] query-embedding cache TTL, LRU, namespace and vector-width tests pass
- [ ] identical cold embedding/expansion calls coalesce and owner cancellation
      makes a waiter reclaim rather than fail the shared request
- [ ] expansion cache TTL, prompt/model/count namespace tests pass
- [ ] original embedding begins before expansion completes
- [ ] absolute deadline produces exact Q1 fallback and no leaked task
- [ ] Cohere retries only approved transient failures
- [ ] retry/backoff is bounded and 401 is not retried
- [ ] equal-score output is deterministic
- [ ] no-answer probes overlap fused search and are cancelled safely on errors
- [ ] incurred retrieval usage is visible from another transaction before
      backfill/source assembly and remains durable on LLM failure/disconnect

## Verification commands

```bash
cd backend
uv run ruff check .
uv run mypy src
DOCKER_HOST=unix:///var/run/docker.sock uv run pytest -q
uv run alembic heads

cd ../frontend
pnpm lint
pnpm typecheck
pnpm test -- --run
pnpm build
pnpm bundle-budget
pnpm exec playwright test e2e/mqr-settings.spec.ts
```

## Evidence hygiene

- [ ] every JSON/JSONL artifact parses
- [ ] every completed benchmark cell has a nonzero denominator and zero errors
- [ ] secrets/common credential formats are absent
- [ ] public artifacts contain no private book text, user query text, generated
      alternatives, prompts, answers, auth headers or provider bodies
- [ ] incomplete systems use an explicit non-numeric status such as
      `not_executed` or `eligible_not_executed`; protocol gating is stated as
      the reason, never encoded as a numeric zero
- [ ] no benchmark-owned containers remain running
