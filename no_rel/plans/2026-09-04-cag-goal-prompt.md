# CAG Execution Goal Prompt

Copy the block below into the goal field of the new session.

```text
Evaluate and, only if the evidence gates pass, implement Cache-Augmented
Generation for RAGZ using the plan at:

/home/parshu/projects/rag-comparison-sources/ragz-b91c898/no_rel/plans/2026-09-04-cag-rfc-and-benchmark.md

Read that file completely before taking action. This goal is CAG-only: do not
implement PR #11 reviewer fixes or the general usage-accounting project in this
session.

WORKTREE AND REPOSITORY RULES
- CAG is the only task authorized to create a new Git worktree.
- Create and use exactly this purpose-named worktree:
  /home/parshu/projects/rag-comparison-sources/ragz-cag-benchmark
- Use branch codex/cag-rfc-benchmark from the exact verified base. Prefer the MQR
  merge on upstream/main; if PR #11 is still open, use the exact PR head only as
  an experimental base and do not modify the PR branch.
- Do not edit /home/parshu/projects/ragz or either existing comparison checkout.
- Only the primary agent writes the CAG worktree. Preserve unknown changes.
- Commit and push each independently reviewable, sanitized artifact promptly.
  Never commit PDFs, extracted book text, raw private questions/answers, keys, or
  provider request bodies.
- Treat all GitHub PRs and issues as read-only. Do not create, edit, comment on,
  close, reopen, label, submit, or merge any PR or issue during this goal. Do not
  use gh, the web UI, or APIs to mutate them, even if all work passes.
- Leave ragz-mqr-local-test running unless I explicitly authorize stopping it.

AGENT AND CREDIT RULES
- Do not use Superpowers.
- The primary agent counts as one Sol. Never have more than two Sol agents active
  concurrently; therefore spawn at most one additional Sol, and reserve it for a
  bounded final architecture/security review.
- Use gpt-5.6-luna workers for high-volume research, documentation review,
  open-source repository analysis, benchmark-method research, and repetitive
  evidence extraction.
- Spawn all agents with fork_turns="none". Do not pass inherited conversation
  history. Give each worker a complete standalone prompt with exact paths, SHA or
  version, narrow questions, evidence requirements, and a read-only constraint.
- Do not let subagents spawn more agents. The primary agent owns scheduling.
- Luna findings are untrusted inputs: the primary must verify material claims
  against primary documentation or inspected source before using them.
- Do not run multiple heavy RAG systems concurrently. Inspect in parallel when
  cheap, but start and benchmark systems sequentially and stop a system if it
  materially stresses the host.

TECHNICAL OBJECTIVE
- Keep these concepts separate: existing query caches, API prompt caching, local
  KV caching, cached RAG prefixes, and true full-snapshot CAG.
- Research current provider and LiteLLM cache support using official docs and
  pinned source. Probe the exact route/model with synthetic non-sensitive data.
- Design immutable authorized snapshots bound to org, workspace, principal or
  safe visibility cohort, document IDs and versions, security revisions,
  projection/current state, prompt/template, model route, tokenizer, budget,
  and configuration version.
- Revalidate current authorization and source state on every use. Delayed cache
  invalidation must remain safe. Never reuse restricted snapshots across users
  in v1; cross-user reuse is allowed only for wholly unrestricted snapshots.
- Preserve ordinary RAG/MQR as fail-closed fallback. Cached and uncached paths
  must retain valid document/version/page/chunk citation mappings, abstention,
  quotas, audit, streaming, and ACL behavior.
- Do not call retrieval-selected prompt caching “CAG.” Benchmark it separately.

BENCHMARK OBJECTIVE
- Use the three local networking books privately, recording hashes and page
  counts but never publishing their text. Add a redistributable synthetic corpus
  for CI correctness.
- Freeze at least 120 stratified questions before the final run and compare RAGZ
  single-query, MQR-3, MQR-5, cached-RAG cold/warm, full-snapshot CAG cold/warm,
  hybrid fallback, AnythingLLM, RAGFlow, and Onyx when feasible.
- Keep the answer model, OpenAI embedding model/dimension, corpus, query set,
  parser assumptions, and retrieval settings controlled. Mark impossible or
  resource-gated cells explicitly; never invent zero metrics.
- Measure retrieval metrics, the RAG triad, citation precision/coverage and exact
  page/version validity, answer relevance, groundedness, abstention, failures,
  provider input/output/cached/reasoning tokens, known cost, and p50/p95/p99.
- Capture atomic latency for authorization, history, expansion, embeddings,
  vector search, fusion, ACL recheck, no-answer logic, rerank, cache lookup/build/
  validation, provider connection/TTFT/generation, citations, usage persistence,
  message persistence, SSE, and end-to-end.
- Use repeated randomized paired runs and bootstrap 95% confidence intervals.
  Keep failures in the denominator and label unknown provider usage or pricing.
- If the reliable application usage ledger is not yet merged, collect raw
  provider-returned usage in the benchmark harness. Never treat the current 1.7M
  meter as provider consumption.

DELIVERY AND STOP GATES
- First deliver an evidence-backed RFC and benchmark protocol. Then build the
  smallest deterministic prototype and security tests. Run the frozen benchmark
  only after correctness gates pass.
- A single cross-org, cross-workspace, stale-version, revoked-ACL, invalid-citation,
  duplicate-generation, or private-data leak is an immediate production NO_GO.
- Implement product configuration/UI only if the measured mode has no meaningful
  quality regression and improves warm p50/p95 latency or known billable input by
  at least 20%, with provider-confirmed cache telemetry where claimed.
- If provider support, corpus fit, security, citation, or performance gates fail,
  publish a clear NO_GO or LIMITED_PILOT result. Do not silently redefine CAG.
- Run repository CI, migration, OpenAPI, frontend, isolation, browser, credential,
  and Git cleanliness gates before claiming completion.
- Store sanitized RFC, protocol, raw-data schema, aggregate results, commands,
  SHAs, limitations, and the GO/LIMITED_PILOT/NO_GO decision under no_rel.
- End with exact branch/SHA, commits pushed, tests run, benchmark status, failed or
  blocked gates, and whether any runtime was changed.
```
