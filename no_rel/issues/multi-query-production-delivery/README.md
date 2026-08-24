# Multi-query retrieval delivery packet

Status: draft only; no issue or pull request has been submitted.

This folder is the handoff point for the production MQR proposal. It separates
the short public-facing drafts from the much larger research branch.

## Recommended sequence

1. Open the issue from `github-issue-body.md` and allow the maintainer to confirm
   the product/configuration direction.
2. Rebase or merge the production branch only if `upstream/main` has advanced.
3. Run `review-checklist.md` against that exact commit.
4. Open the PR from `pull-request-body.md`, linking the accepted issue.

An issue should come first here because this is not a small bug fix: it adds a
database-backed workspace capability, a superadmin-only policy decision,
provider calls, caches, production settings, and new latency/failure semantics.

## Branches and evidence

- Reviewable product branch: `codex/mqr-production-ready` at `649c3cc1`
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

The production branch intentionally excludes raw benchmark runs, private-corpus
adapters, generated reports, and competitor source trees.
