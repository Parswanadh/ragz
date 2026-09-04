# Multi-query retrieval delivery packet

Status: upstream issue
[`#10`](https://github.com/marketcalls/ragz/issues/10) and ready-for-review pull
request [`#11`](https://github.com/marketcalls/ragz/pull/11) are open. The PR was
submitted on 2026-09-04 after every upstream branch was confirmed MQR-free and
the complete verification suite passed again.

This folder is the handoff point for the production MQR proposal. It separates
the short public-facing drafts from the much larger research branch.

## Recommended sequence

1. Issue #10 is open from `github-issue-body.md`; allow the maintainer to confirm
   the product/configuration direction.
2. PR #11 targets the unchanged `upstream/main` from the production branch.
3. The review checklist was rerun against exact head `3fac9fb1`.
4. An upstream maintainer must approve the forked CI/dependency-audit workflows;
   then address CI or review feedback without deleting the worktree.

An issue should come first here because this is not a small bug fix: it adds a
database-backed workspace capability, a superadmin-only policy decision,
provider calls, caches, production settings, and new latency/failure semantics.

## Branches and evidence

- Reviewable product branch: `codex/mqr-production-ready` at `3fac9fb1`
- Research/evidence branch: `codex/multi-query-retrieval` at `294a8846`
- Upstream base used for assembly: `9d08839`
- Canonical implementation plan:
  `docs/plans/2026-08-24-mqr-production-delivery.md`
- Canonical atomic benchmark: `docs/benchmarks/ATOMIC_BENCHMARK.md`
- Post-change confirmation:
  `docs/benchmarks/2026-08-24-mqr-production-confirmation.md`
- Normalized comparator follow-up:
  `docs/benchmarks/2026-08-25-normalized-four-system-followup.md`
- Browser/API authorization attestation:
  `docs/verification/2026-08-24-mqr-superadmin-product-smoke.md`

The final independent review also closed cold-cache stampedes, owner-cancellation
fan-out, pre-deadline cancellation, retrieval-usage rollback windows, invalid
embedding-model selection, and permission-mismatched Evals hooks. See the PR
draft and final verification record for the exact regression coverage.

The production branch intentionally excludes raw benchmark runs, private-corpus
adapters, generated reports, and competitor source trees.
