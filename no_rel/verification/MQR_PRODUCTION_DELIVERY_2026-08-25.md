# MQR production delivery verification

Date: 2026-08-25

## Outcome

The requested multi-query retrieval work is implemented, benchmarked,
independently reviewed, assembled into a clean production branch, fully tested,
and pushed to the fork. Under a subsequent explicit user instruction, upstream
issue [#10](https://github.com/marketcalls/ragz/issues/10) was submitted and
verified on 2026-08-26. After an all-branch MQR audit and a fresh complete test
run, ready-for-review PR [#11](https://github.com/marketcalls/ragz/pull/11) was
submitted on 2026-09-04 from the focused production branch.

- Product branch: `codex/mqr-production-ready`
- Verified product commit: `3fac9fb1d02c9327f243418ebbb905466c8bcef5`
- Research/evidence branch: `codex/multi-query-retrieval`
- Upstream base/current `main`: `9d08839f6855967f3b141b731a269a54b76222fb`
- Product branch ahead/behind upstream: `14 / 0`
- Local product SHA equals fork remote SHA.
- Both isolated worktrees were clean at the verification boundary.

## Delivered behavior

- Additive workspace migration; MQR remains off by default.
- Server-enforced superadmin-only MQR mutation and role-hidden UI control.
- Single-versus-multi answer comparison without mutating workspace state.
- Q1/Q3/Q5 internal evaluation controls and bounded perspective prompt.
- Identical tenant/workspace/ACL/security-projection/current-version filters on
  every lane, followed by the existing authorization recheck.
- Speculative original embedding with an absolute expansion deadline and exact
  Q1 fallback.
- Bounded replica-local TTL/LRU embedding and expansion caches with opaque keys.
- Exact-key single-flight coalescing; a waiter reclaims the key if the owner is
  cancelled instead of inheriting cancellation.
- Bounded transient Cohere retries, deterministic ties, and concurrent
  no-answer probes.
- Retrieval-provider usage is committed before downstream hydration/source
  assembly, client-visible frames, and answer-provider calls.
- Completion/eval model resolution rejects embedding-only IDs.
- Evals UI maps `evals.read/manage/run`, `documents.list`, and `models.read`
  independently and does not issue known-forbidden dependent requests.

## Independent review findings closed

Three bounded Luna reviewers performed read-only audits. Every confirmed issue
was reproduced before patching and regression-tested afterward.

| Finding | Resolution |
|---|---|
| Q1 count override constructed an unsupported expander | Q1 now bypasses expansion entirely |
| Expansion deadline waited for original embedding first | timeout task starts at expansion launch and cancels on the absolute deadline |
| Identical cold keys duplicated provider calls | per-key single-flight coalescing in both caches |
| Cancelling the single-flight owner cancelled waiters | internal retry signal lets one waiter reclaim the key |
| Retrieval usage could roll back on LLM/downstream failure or disconnect | durable commit immediately after retrieval/agent work and before outbound frames/providers |
| Embedding model ID accepted by comparison/completion resolution | enabled-model resolver now requires `modality=chat` |
| Evals tab/controls did not match `evals.*` capabilities | independent read/manage/run control gating |
| Evals capabilities triggered unrelated document/model 403s | dependent hooks additionally require `documents.list`/`models.read` |

The final retrieval/concurrency reviewer and authorization/UI reviewer reported
no remaining confirmed P1/P2 or permission-hook mismatch in their assigned
scope.

## Exact verification results

| Gate | Result |
|---|---|
| Backend full suite on native Docker | `1762 passed, 14 skipped`, 8 dependency deprecation warnings, 697.64 s |
| Focused MQR/cache/retry/chat/eval/isolation suite | `153 passed` before the final regression additions; all later targeted regressions also passed |
| Ruff | passed |
| Strict mypy | no issues in 161 source files |
| Frontend Vitest | 106 files, `709 passed` |
| ESLint | passed |
| TypeScript | passed |
| Production build | passed |
| Initial bundle budget | 171.7 kB gzip / 200 kB; 28.3 kB headroom |
| Alembic | one head, `6a8d2c4f1b90` |
| Production Compose render | passed with explicit dummy required secrets |
| Fresh isolated Playwright product smoke | `1 passed` in 3.9 s |
| Benchmark analyzer test | `2 passed` |
| Research artifact parsing | 226 JSON and 129 JSONL files parsed |
| Credential/private-text pattern scan | no match in the changed public evidence |

The browser smoke used a fresh migrated database, bootstrap superadmin,
deterministic hash embedder, lexical reranker, real login, real workspace create,
real PATCH, dialog reopen, and persisted-state check. It made no hosted-provider
call. Its dedicated Compose project, volumes, ports, temporary KEK, and test
output were removed afterward.

The initial focused test invocation used this shell's nonexistent default Docker
socket and failed only in fixture setup. It was discarded and rerun against
`unix:///var/run/docker.sock`; it is not counted as a product result.

## Benchmark decision

The frozen post-change confirmation has 960 zero-error retrieval observations,
including 800 answerable quality observations.

| Cell | Recall@5 | MRR@5 | nDCG@5 | Mean | p95 |
|---|---:|---:|---:|---:|---:|
| Q1 cache off | 0.6000 | 0.4517 | 0.4890 | 728.49 ms | 913.52 ms |
| Q1 cache warm | 0.6000 | 0.4517 | 0.4890 | 16.93 ms | 19.68 ms |
| Q3 cache off | 0.6000 | 0.4475 | 0.4855 | 1,385.00 ms | 1,639.51 ms |
| Q3 cache warm | 0.6000 | 0.4475 | 0.4855 | 33.76 ms | 39.33 ms |

Q3 did not improve Recall on this exact-page corpus, so Q1/no-rerank remains the
recommended default and MQR remains opt-in. The audit patches affect concurrent
coalescing, deadlines, usage durability, model validation, and UI authorization;
they do not change serial vectors, fusion inputs, qrels, or ranking, so the
frozen quality comparison remains applicable.

On the normalized 20-page interval comparison, RAGZ Q1 scored
`0.8250/0.6583/0.7002`, RAGZ Q3 `0.8000/0.6792/0.7096`, and AnythingLLM
`0.8000/0.6517/0.6890` for Recall/MRR/nDCG. AnythingLLM completed 120
retrieval/latency observations, including 100 answerable quality observations.
RAGFlow remains source-bound to a different corpus, and Onyx is canonically
`eligible_not_executed`; neither receives a fabricated score.

The historical 15-cell screening manifest that says `completed` remains
byte-for-byte immutable for provenance. Its adjacent `READ_ME_FIRST.md` and
`post_run_validation.json` establish the effective status
`invalid_as_complete_matrix`; only 14 complete cells are eligible.

## Repository and external state

- Upstream has no open pull requests.
- Existing issue #9, “LiteParse silently truncates documents over 1,000 pages,”
  remains open.
- MQR proposal issue #10 and implementation PR #11 are open. Forked-PR workflow
  execution awaits upstream maintainer approval; local tests are green.
- No RAGZ benchmark/smoke/Testcontainers workloads or test ports remain.
- Other pre-existing AGNO containers were observed but never modified.

## Recommended next action

Open the drafted issue first because this feature changes schema, authorization,
provider/cost behavior, caches, and failure semantics. After maintainer agreement,
run the review checklist once more against the then-current upstream head and
open the production PR. Do not merge the research/evidence branch as the product
PR.
