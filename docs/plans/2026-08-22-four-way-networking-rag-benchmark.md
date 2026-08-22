# Four-Way Networking RAG Benchmark Implementation Plan

> **For agentic workers:** Execute this plan with ordinary reviewed checkpoints.
> The operator explicitly disabled Superpowers for this session. Never edit the
> shared checkout or stop containers owned by another agent.

**Goal:** Produce an evidence-backed comparison of AnythingLLM native retrieval,
RAGZ single-query retrieval, RAGZ multi-query retrieval, and Onyx search on the
same three-book networking corpus and 15-query set.

**Architecture:** Use a common 20-PDF-page evidence unit for the primary retrieval
table. Recompute RAGZ results from the retained `r12`/`r13` page-level artifacts,
run AnythingLLM v1.16.0 over the same 131 temporary page segments, and record Onyx
v4.6.0 as resource-gated unless its official Standard minimum is available. Keep
native configuration and common-locator scoring separate in the report.

**Tech stack:** Python 3.13, pytest, Docker, AnythingLLM v1.16.0 with native MiniLM
and LanceDB, existing RAGZ/Qdrant artifacts, official Onyx v4.6.0 resource contract.

## Global Constraints

- Work only in `/tmp/ragz-multi-query-20260821` and unique `/tmp`/result paths.
- Never read or commit textbook text, provider keys, generated alternatives, or
  raw answers. Temporary extracted-text datasets remain under `/tmp`; Docker
  scratch storage must be a unique child of the explicitly allowed, untracked,
  Docker-shared `no_rel/benchmarks/work/` root and is deleted on exit.
- Use 15 total queries: 12 answerable and 3 off-corpus.
- Ranking metrics use successful answerable queries only; abstention uses all
  successful queries; failures are reported separately.
- Primary evidence unit is a unique `book_id-pages-START-END` 20-page interval.
- Deduplicate repeated chunks/pages that map to the same interval before top-k.
- Use `top_k=5`, two warmups per query, three scored repetitions, concurrency one.
- Do not call fixed RAGZ alternatives “live” or assign them provider cost.
- Do not substitute AnythingLLM results from another corpus.
- Do not substitute Onyx Lite: official documentation says it omits the
  vector/keyword index and background workers required for RAG.
- Onyx Standard requires at least 4 vCPU, 10 GB RAM and 32 GB disk; if Docker
  remains below 10 GB, emit no quality or latency score.
- Commit and push every independently reproducible code/report checkpoint.

---

### Task 1: Repair and verify the temporary common dataset

**Files:**
- Modify: `backend/scripts/build_networking_anythingllm_dataset.py`
- Modify: `backend/tests/scripts/test_networking_benchmark.py`

**Produces:** A temporary dataset with 131 twenty-page documents, 15 queries and
segment qrels, built only under `/tmp`.

- [ ] Add a regression test whose answerable query omits the `answerable` key and
  assert the adapter emits `answerable=true`.
- [ ] Change `row["answerable"]` to `row.get("answerable", True)`.
- [ ] Run:

  ```bash
  cd backend
  uv run pytest -q tests/scripts/test_networking_benchmark.py
  uv run ruff check scripts/build_networking_anythingllm_dataset.py \
    tests/scripts/test_networking_benchmark.py
  ```

- [ ] Commit and push `fix(bench): preserve default answerable query labels`.
- [ ] Build a fresh unique `/tmp/networking-four-way-<nonce>` dataset and verify:
  131 documents, 15 queries, 12 answerable, 3 unanswerable, and no output outside
  `/tmp`.

### Task 2: Add a bounded AnythingLLM networking runner

**Files:**
- Create: `backend/scripts/run_networking_anythingllm.py`
- Create: `backend/tests/scripts/test_networking_anythingllm.py`

**Consumes:** The Task 1 dataset.

**Produces:** Immutable privacy-safe `manifest.json`, `per_query.jsonl`,
`summary.json`, `summary.md`, and typed failure evidence.

- [ ] Test CLI validation, output refusal, exact metric denominators, unique
  interval deduplication, and batching of embedding-update requests.
- [ ] Pin image `mintplexlabs/anythingllm:1.16.0`, digest
  `sha256:68bcedecb720e3fadde986bcc4f3aad20059fa64805bc9b306a3023244947515`
  and release commit `55b6ebcea132f0d7ac146da99a0cd0db507b9030`.
- [ ] Use a fresh storage root, copy only the cached native model files, and never
  reuse the known partial networking index.
- [ ] Start the container with `2 CPU / 2 GiB`, telemetry disabled, native
  `Xenova/all-MiniLM-L6-v2`, LanceDB and no generation provider.
- [ ] Upload all 131 raw-text segments, then call `update-embeddings` in bounded
  batches of four locations instead of one 131-location request.
- [ ] Warm every query twice, run every query three times, and record typed errors,
  retrieval latency and container memory samples without query/document text.
- [ ] On disconnect/OOM, preserve a failure artifact and emit no score.
- [ ] Run focused tests, Ruff and mypy; commit and push
  `bench: add bounded AnythingLLM networking runner`.

### Task 3: Normalize RAGZ evidence to the same intervals

**Files:**
- Create: `backend/scripts/compare_networking_rag_systems.py`
- Create: `backend/tests/scripts/test_compare_networking_rag_systems.py`

**Consumes:** Committed RAGZ `r12`/`r13` raw artifacts, Task 1 qrels, and the Task
2 AnythingLLM result/failure.

**Produces:** One machine-readable comparison and one Markdown report.

- [ ] Convert every RAGZ `book_id:page` hit into the same 20-page segment ID used
  by Task 1 and deduplicate before truncating to five intervals.
- [ ] Pool `r12` and `r13` by query and condition while retaining condition-order
  metadata. Average per query before computing the 12-query macro means.
- [ ] Compute Recall@5, MRR@5 and nDCG@5 over answerable queries; compute
  abstention precision/recall/F1 over all 15; exclude errors from denominators.
- [ ] Report p50/p95 over successful observations. Label p99 descriptive because
  fewer than 100 observations exist per AnythingLLM condition.
- [ ] Include native configuration fields and never imply common embedding models.
- [ ] Add paired query-level bootstrap intervals for RAGZ multi-minus-single.

### Task 4: Refresh the Onyx Standard resource gate

**Files:**
- Create: `backend/scripts/run_networking_onyx_preflight.py`
- Create: `backend/tests/scripts/test_networking_onyx_preflight.py`

**Produces:** An Onyx row with either executable status or a typed resource gate.

- [ ] Pin Onyx v4.6.0 and commit
  `b4553eb55ceb2c6a561c57892a528c65bd8626b1`.
- [ ] Read Docker CPU/memory without starting Onyx.
- [ ] Compare against the official Standard floor: 4 CPU, 10 GB RAM, 32 GB disk.
- [ ] Record official source URL, measured deficit, zero provider calls and
  `quality_score_emitted=false` when gated.
- [ ] State that Onyx Lite is excluded because it has no vector/keyword index or
  background indexing workers.
- [ ] Do not start Onyx unless all minimums pass and the operator confirms no
  contention with other agents.

### Task 5: Execute, preserve and review the comparison

**Files:**
- Create: `docs/benchmarks/2026-08-22-four-way-networking-rag-comparison.md`
- Create: `docs/benchmarks/artifacts/2026-08-22-four-way-networking-rag.json`
- Add privacy-safe raw AnythingLLM/Onyx artifacts under
  `docs/benchmarks/artifacts/raw/2026-08-22/`.

- [ ] Stop only comparison-lab processes owned by this branch if memory is needed;
  never stop shared Docker services or another agent’s containers.
- [ ] Execute AnythingLLM sequentially. Preserve exact command, image digest,
  resource samples, index wall time and errors.
- [ ] Execute the Onyx preflight. A resource-gated row is the final measured result
  on this host, not a failed task and not a numeric zero.
- [ ] Generate tables for eligibility/configuration, common interval retrieval,
  native configuration, abstention and resources.
- [ ] State that answer-quality comparison is unavailable because the current
  query set has page qrels but no reference-answer/atomic-claim rubric.
- [ ] Privacy-scan artifacts for keys, authorization headers, queries, alternatives
  and textbook content before committing.
- [ ] Run all new tests, full Ruff/mypy/import boundaries, and `git diff --check`.
- [ ] Obtain independent read-only review; fix all Critical/Important findings.
- [ ] Commit and push the final report/artifacts. Do not create a PR.

## Self-Review

- Spec coverage: all requested rows are represented; executable rows receive
  numeric metrics and Onyx receives a measured eligibility result.
- Fairness: common interval and native-configuration tracks are separate.
- Denominators: answerable quality, all-query abstention and error counts are
  explicitly distinct.
- Resource safety: no shared container is stopped and Onyx cannot start below its
  official floor.
- Copyright/privacy: extracted text remains temporary and only hashes, IDs,
  locators, metrics and typed failures can be committed.
- No placeholders or invented scores are permitted.
