# Post-MQR Delivery Master Plan

> **For the next Codex session:** The user explicitly prohibited Superpowers.
> Execute with ordinary repository tools in isolated worktrees. Bounded Luna
> reviewers may be used for independent, read-only audits, but the primary agent
> must reproduce every finding and run every required gate itself.

**Goal:** Land PR #11 safely, replace the ambiguous token meter with auditable
usage semantics, and evaluate CAG without mixing three independent risk domains
into one pull request.

**Architecture:** Treat this as three ordered projects. First repair and merge
the existing MQR PR without scope creep. Second introduce an append-only usage
ledger that explicitly separates provider-reported tokens, estimated processing
tokens, quota tokens, per-call units, and price completeness. Third perform a
security-gated CAG RFC and benchmark; implement CAG only if the provider and
corpus eligibility gates pass.

**Tech stack:** Python 3.12+, FastAPI, SQLAlchemy async, Alembic, PostgreSQL,
Redis, Qdrant, LiteLLM/OpenAI-compatible APIs, React/TypeScript, Vitest,
Playwright, Docker, GitHub Actions.

## Global constraints

- Never edit `/home/parshu/projects/ragz`; it is a dirty shared checkout owned
  by the user and other agents.
- Treat the existing PR #11 checkout
  `/home/parshu/projects/rag-comparison-sources/ragz-mqr-production-ready` as
  read-only; another session may still own it.
- Create the purpose-named remediation worktree
  `/home/parshu/projects/rag-comparison-sources/ragz-pr11-remediation` on a new
  local branch from the exact fork PR head. Push it only as a verified
  fast-forward to `origin/codex/mqr-production-ready`.
- Research/evidence checkout:
  `/home/parshu/projects/rag-comparison-sources/ragz-b91c898`.
- Never force-push, rewrite published commits, merge locally into shared main,
  or delete either worktree.
- Do not add token-accounting or CAG code to PR #11.
- Do not treat reviewer output as truth. Add a failing regression test or a
  deterministic reproducer before changing production behavior.
- Keep MQR and reranking disabled by default; only superadmins may mutate MQR.
- Preserve the Qdrant tenant/workspace/ACL/current-version filters and
  post-query security recheck on every retrieval path.
- Never print or persist raw keys from `/home/parshu/projects/ragz/.env`.
- Public evidence must not contain book text, user queries, generated
  alternatives, answers, prompts, authorization headers, or provider bodies.
- Use `DOCKER_HOST=unix:///var/run/docker.sock` for testcontainers.
- Record incomplete/blocked execution as a typed status; never invent zero
  metrics or claim a workflow passed when GitHub did not run it.
- Commit and push each independently reviewable task before moving to the next.

## Current state to verify before doing anything

| Item | Expected state at handoff |
|---|---|
| PR base (`upstream/main`) | `9d08839f6855967f3b141b731a269a54b76222fb` |
| Fork `origin/main` | `b23949853fa2c76584218d68ec619685525568ab`; not the PR base |
| MQR branch | `codex/mqr-production-ready` at `3fac9fb1` |
| Research branch | `codex/multi-query-retrieval` at the latest pushed docs commit |
| Issue | [#10](https://github.com/marketcalls/ragz/issues/10), open |
| PR | [#11](https://github.com/marketcalls/ragz/pull/11), open and ready for review |
| PR diff | 14 commits, 47 files, zero commits behind main |
| Local full test | 1,762 passed, 14 skipped at `3fac9fb1` |
| Cubic | completed successfully as a check; 15 candidate findings posted |
| GitHub CI/audit | runs `33836126170` and `33836126191`: `action_required`, zero jobs, awaiting maintainer approval |
| Local test runtime | `ragz-mqr-local-test`, intentionally running on localhost |

If any SHA or PR base/head differs, stop and reconcile provenance before
editing. The PR base is `upstream/main`, not the fork's newer `origin/main`.
A changed upstream main requires a deliberate integration decision and all gates
must be rerun; do not rebase or rewrite a published branch without explicit user
approval.

## Required execution order

### Phase 1: Repair and finish PR #11

Execute
[`2026-09-04-pr11-review-remediation.md`](2026-09-04-pr11-review-remediation.md).

Exit criteria:

- Every Cubic finding has a disposition: `confirmed_fixed`,
  `invalid_with_evidence`, or `documented_limitation`.
- Confirmed findings have regression tests that fail on `3fac9fb1` and pass on
  the fix commit.
- Complete backend/frontend/build/migration/browser gates pass.
- GitHub workflows have either passed or are explicitly waiting for upstream
  maintainer approval with zero executed jobs.
- Cubic is re-triggered on the final head and no unresolved P1/P2 remains.
- PR #11 is merged by a maintainer, or the session ends with an exact external
  blocker and the branch safely pushed.

### Phase 2: Accurate usage accounting

Only after Phase 1 has no unresolved P1/P2, execute
[`2026-09-04-reliable-usage-accounting.md`](2026-09-04-reliable-usage-accounting.md).

Branching rule:

- If PR #11 is merged, fetch the new `upstream/main` and create
  `codex/accurate-usage-accounting` from it in a new isolated worktree.
- If PR #11 is still open, create the branch from
  `codex/mqr-production-ready`, clearly mark it stacked on #11, and do not open
  its PR until #11 merges. After #11 merges, transplant only the accounting
  commits onto updated main with a normal, reviewable operation.

Exit criteria:

- The chat header never labels corpus estimates as LLM tokens.
- Quota enforcement is backward compatible and reads explicit quota tokens.
- Provider, estimate, cache/reasoning, units, current corpus, and cost
  completeness are independently visible.
- Missing prices/usage are `unknown` or `partial`, never silently `$0`.
- Reindex does not increase the current-corpus gauge.
- Retry/replay semantics are idempotent where the same provider result is
  persisted twice, while genuinely repeated provider calls remain billable.
- Migration upgrade/downgrade and historical-data backfill are tested.

### Phase 3: CAG RFC and benchmark gate

Execute
[`2026-09-04-cag-rfc-and-benchmark.md`](2026-09-04-cag-rfc-and-benchmark.md).

Do not implement production CAG merely because the RFC is complete. Production
work begins only if all of these gates pass:

- The selected provider/model exposes usable and measurable cache semantics.
- The complete knowledge snapshot fits the configured token envelope with room
  for system prompt, history, question, and output.
- The initial MVP can be restricted to one ACL-homogeneous visibility cohort.
- Cache invalidation can bind document versions, security revisions, model,
  tokenizer, and prompt version atomically.
- Citation validity, abstention, latency, and cost meet the benchmark thresholds
  in the CAG plan.

## Evidence and commit protocol

For each phase:

1. Record branch, head SHA, upstream SHA, dirty status, environment, and exact
   commands before testing.
2. Preserve failing test output for confirmed defects without secrets or user
   content.
3. Make one commit per independently reviewable concern.
4. Push after every commit.
5. Run `git diff --check`, credential-pattern scanning, and generated-schema
   drift checks before reporting completion.
6. Record final results under `no_rel/verification/` on the research branch;
   keep benchmark raw data and competitor trees out of product PRs.

## Stop conditions

Stop and ask the user rather than guessing when:

- a fix would weaken tenant/ACL enforcement;
- a reviewer request requires an unrelated schema or product-policy change;
- upstream main advances with overlapping retrieval/accounting changes;
- workflow approval, maintainer action, or provider credentials are required;
- CAG requires sending a broader document visibility set than the caller may
  access;
- a destructive reset of the currently running local test runtime is required.

## Next-session kickoff prompt

Use this verbatim in the next session:

> Open and read
> `/home/parshu/projects/rag-comparison-sources/ragz-b91c898/no_rel/plans/2026-09-04-post-mqr-execution-master.md`
> and every subplan it routes to. Start with Phase 1 only. Do not use
> Superpowers, do not modify `/home/parshu/projects/ragz`, do not mix token
> accounting or CAG into PR #11, and do not accept Cubic findings without a
> failing test or deterministic reproducer. Treat the existing MQR checkout as
> read-only and create the purpose-named remediation worktree specified in the
> subplan. Commit and push reviewable fixes, rerun the specified gates, and leave
> the local `ragz-mqr-local-test` runtime running unless I explicitly ask you to
> stop it.
