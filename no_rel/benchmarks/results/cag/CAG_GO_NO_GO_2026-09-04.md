# CAG Go/No-Go Record — 2026-09-04

**Branch:** `codex/cag-rfc-benchmark`
**Experimental base:** `3fac9fb1d02c9327f243418ebbb905466c8bcef5`
**Status:** Preliminary evidence and deterministic prototype; final private
benchmark not run

## Decision

| Mode | Current decision | Reason |
|---|---|---|
| `full_snapshot_cag`, combined three-book workspace | **NO_GO** | 1,577,342 raw source tokens exceed the 1,050,000-token model window before policy, markers, dynamic input, and output reserve; current RAGZ budget is 8,000 |
| `full_snapshot_cag`, small complete synthetic corpus | Pending, production **NO_GO** | Provider support passes; full security/citation/quality/performance gates and isolated pilot have not run |
| `cached_rag_prefix` | Pending; not CAG and production **NO_GO** | Exact route supports prefix caching, but representative quality/performance and fallback gates have not run |

The three-book failure is a corpus-fit gate. It cannot be repaired by selecting
top-k chunks and retaining the CAG name; that experiment is
`cached_rag_prefix`.

## Environment and capability evidence

- RAGZ base: open PR #11 head, so this branch is experimental.
- Route: `gpt-5.6-luna` → LiteLLM 1.96.2 → `openai/gpt-5.6-luna`.
- LiteLLM image:
  `sha256:154e23bb5f31b1f10e16392a8ef299bd2cde08de3a64a6849002cfcc25ce3c63`.
- Provider cache telemetry: confirmed for non-streaming and streaming calls with
  synthetic data. Cold calls reported writes and warm changed-question calls
  reported reads.
- Cache mechanism actually measured: OpenAI API prompt caching through the
  pinned LiteLLM Chat Completions route. No local KV engine, semantic answer
  cache, or full private-corpus CAG run was measured.
- Embedding for the final controlled protocol: OpenAI
  `text-embedding-3-large`, 1,024 dimensions. The live MQR test runtime uses
  local BGE-M3 and was not modified or treated as a scored cell.

## Corpus evidence

| Private ID | SHA-256 | Pages | Unique chunks | Raw-text tokens |
|---|---|---:|---:|---:|
| `book-01` | `fec3e7c7d583018633cbba69510cdb9bba01622f4eed6ef894f571b909c59f25` | 861 | 3,500 | 485,135 |
| `book-02` | `7599e188b2645104576b5502400565aff7892ef02abb866ed6899ef9b5865a9a` | 775 | 1,851 | 470,705 |
| `book-03` | `dca8648949db3f7f95f29917a32718d98a06888083c7f86712c9aa070cfebcb8` | 946 | 3,023 | 621,502 |

No PDF, filename/title, extracted text, private question, reference answer, or
provider request body is included.

## Gate status

| Gate | Status | Evidence or blocker |
|---|---|---|
| Exact provider route/docs | Passed | Official GPT-5.6 Luna docs plus synthetic route probe |
| Provider-reported telemetry | Passed | Sanitized probe records read/write/reasoning fields |
| Combined private snapshot fits | **Failed** | Raw source estimate already exceeds model window |
| Immutable key/eligibility prototype | Passed locally | Pure canonicalization, state binding, budget, visibility, and validation tests |
| Cross-org/workspace/principal deterministic isolation | Passed locally | Synthetic isolation tests |
| Live DB/Qdrant revocation races | Not run | Integration harness not yet implemented |
| Citation mapping/parity | Partial | Pure exact marker/version/page/chunk mapping passes; cached/uncached generation parity not run |
| Frozen 120-question set | Not frozen | Private fixture and qrels still required |
| Representative repeated benchmark | Not run | Correctness gates incomplete |
| AnythingLLM exact run | Not run | Adapter/configuration pending |
| RAGFlow exact run | `protocol_gated` | Exact three-book adapter absent |
| Onyx exact run | `protocol_gated` | Exact corpus/model evidence adapter absent |
| Backend lint/types/import boundaries | Passed | Ruff; mypy 162 source files; 17/17 import contracts |
| Backend unit/integration | Passed | 1,696 passed, 2 skipped |
| Backend tenant/ACL isolation | Passed | 123 passed |
| Migration head/chain | Passed | One Alembic head; 2 migration tests passed |
| Frontend lint/types/tests/build | Passed | 106 test files and 709 tests; production build passed |
| Bundle/browser compile | Passed | 171.7 kB / 200 kB gzip; two Playwright tests discovered |
| OpenAPI drift | Passed | Exported application schema matches committed client |
| Credential scan, CAG commit range | Passed | Gitleaks 8.30.1: three commits, no findings |
| Credential scan, complete history | **Failed (pre-existing)** | Three generic-api-key findings predate the CAG base; no unrelated remediation is authorized here |

## Runtime and GitHub state

The existing `ragz-mqr-local-test` API, worker, LiteLLM, Postgres, Redis,
Qdrant, and MinIO processes were not stopped, restarted, reconfigured, or
deployed from this branch. Synthetic provider probes consumed provider usage
and populated only ephemeral upstream prompt-cache state. No tenant content was
sent by those probes. No GitHub PR or issue was created, edited, commented on,
closed, labeled, submitted, or merged.

## Next gate

Add deterministic hybrid-routing and cancellation tests without wiring product
behavior, then run the repository correctness gates. Only after those pass may
the private question set be frozen and the controlled benchmark begin. Product
configuration/UI remains prohibited.
