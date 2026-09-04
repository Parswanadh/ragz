# CAG Experiment Protocol

**Protocol:** `ragz-cag-v1`
**Preregistered:** 2026-09-04, before the final question freeze or scored run
**Experimental base:** `3fac9fb1d02c9327f243418ebbb905466c8bcef5`
**Production status at registration:** `NO_GO`

## Purpose and naming contract

This protocol determines whether a small, fully authorized knowledge snapshot
can safely avoid query-time retrieval in RAGZ and whether provider KV reuse is
material. It evaluates two separate modes:

- `full_snapshot_cag`: every eligible source is in the stable prefix and no
  vector retrieval occurs after snapshot selection.
- `cached_rag_prefix`: ordinary authorized retrieval and fitting still occur;
  only the resulting prompt prefix is reused. This is not CAG.

Query-embedding cache, query-expansion cache, provider prompt cache, local KV
cache, semantic answer cache, and the two modes above use distinct variant IDs,
fields, and tables. A subset of a larger workspace is never relabeled
`full_snapshot_cag`.

## Preregistered hypotheses and decision rules

The primary comparison is each eligible warm mode against RAGZ single-query
RAG on identical question/repetition pairs.

An eligible mode may receive `LIMITED_PILOT` only if all hard security and
correctness gates pass and both conditions below hold:

1. Quality non-inferiority: the query-clustered paired-bootstrap 95% CI lower
   bound for the mode-minus-baseline difference is at least `-0.03` for
   groundedness, answer relevance, citation precision, and citation coverage,
   and at least `-0.05` for abstention F1. Exact persisted citation provenance
   validity remains 100 percent and has no margin.
2. Material benefit: either both warm p50 and warm p95 end-to-end latency are at
   least 20 percent lower, or known provider billable input cost per successful
   and assigned trial is at least 20 percent lower. Cache-savings claims require
   provider-reported hit/write fields.

`GO` additionally requires successful isolated rollout to a disposable
synthetic workspace and then a non-sensitive pilot with no increased fallback
or error rate. Product settings/UI are prohibited before a mode reaches at
least `LIMITED_PILOT`.

Any cross-org, cross-workspace, different-principal restricted reuse,
revoked/stale source, invalid persisted citation, duplicate generation,
private-data leak, unbounded cache, or stranded single-flight waiter is an
immediate production `NO_GO`, regardless of quality or latency.

## Fixed environment and controls

Record the following in every run manifest and refuse to combine rows whose
values differ:

| Field | Frozen value or rule |
|---|---|
| RAGZ source | Exact clean commit derived from the experimental base; record SHA and dirty flag |
| Answer model route | `gpt-5.6-luna` alias via the pinned LiteLLM route; record upstream model string |
| Answer model settings | Omit temperature; reasoning effort `none` for controlled quality unless a preregistered compatibility probe rejects it |
| Embedding | OpenAI `text-embedding-3-large`, 1,024 dimensions, exact measured width |
| Parser | `liteparse==2.12.0`; preserve page numbers |
| Chunking | RAGZ `heading`, target 2,000 characters, 15% overlap |
| Final retrieval depth | `top_k=5` for scored retrieval metrics |
| Reranker | Off; a reranker factorial is outside this experiment |
| MQR | Total queries 1, 3, or 5 as named by the variant |
| Prompt | Exact prompt/template hash in manifest; no prompt changes across scored variants except the preregistered stable-prefix ordering |
| History | Empty for primary single-turn quality; separate fixed multi-turn fixture only |
| Web/tools/attachments/generative UI | Off for primary comparison; otherwise mode is ineligible |
| Locale/time | Record host timezone, monotonic clock source, OS, CPU, RAM, and container/image identities |

The embedding choice is inherited from the prior controlled large/1,024
experiment. The currently running MQR test workspace uses local BGE-M3 and is
not a valid scored environment for this protocol. It must remain unchanged.

## Corpus

### Private target

Three local networking books are private inputs. Public artifacts contain only:

| ID | SHA-256 | Pages | Current live unique chunks | Local raw-text token estimate |
|---|---|---:|---:|---:|
| `book-01` | `fec3e7c7d583018633cbba69510cdb9bba01622f4eed6ef894f571b909c59f25` | 861 | 3,500 | 485,135 |
| `book-02` | `7599e188b2645104576b5502400565aff7892ef02abb866ed6899ef9b5865a9a` | 775 | 1,851 | 470,705 |
| `book-03` | `dca8648949db3f7f95f29917a32718d98a06888083c7f86712c9aa070cfebcb8` | 946 | 3,023 | 621,502 |

The 1,577,342-token combined raw source estimate already exceeds the answer
model window. The combined `full_snapshot_cag` cell is therefore frozen as
`ineligible/context_budget` and receives no fabricated numeric metrics.
RAG/MQR and `cached_rag_prefix` retain the complete three-book corpus.

### Redistributable synthetic correctness corpus

Commit a small authored corpus containing no private material. It must include:

- two organizations and two same-named workspaces;
- unrestricted and restricted documents with identical text across tenants;
- two versions of one document with different page/chunk facts;
- one answerable fact, one cross-document synthesis, one bogus-marker trap, and
  one unanswerable question;
- Unicode and delimiter-like document text; and
- deterministic IDs, versions, security revisions, pages, chunks, and qrels.

Create complete synthetic-corpus tiers at approximately 512, 2k, 4k, and 8k
rendered tokens and 4, 8, 16, and 32 chunks. These are separate complete
corpora, not subsets mislabeled as complete snapshots.

## Frozen private question set

Before any final scored run, create at least 120 questions and seal the fixture
hash. The private fixture and reference answers remain outside Git. The public
manifest stores only schema version, counts, strata, salted question-ID hash,
fixture SHA-256, qrel SHA-256, freeze time, and assessor protocol.

| Stratum | Count |
|---|---:|
| Single-document fact/location | 25 |
| Multi-hop within one document | 20 |
| Cross-document synthesis/comparison | 20 |
| Terminology/paraphrase/ambiguous phrasing | 15 |
| Table/figure/page-sensitive | 15 |
| Answerable low lexical overlap | 15 |
| Unanswerable/adversarial | 10 |
| **Total** | **120** |

Each private row contains a stable opaque question ID, stratum, question,
answerability, acceptable atomic claims, relevant document/version/page/chunk
sets, acceptable alternative evidence, citation requirements, and reference
answer. Freeze ground truth before final runs. Assessors see randomized answers
without variant labels.

## Variants and feasibility states

| Variant ID | Retrieval | Cache state | Required disposition |
|---|---|---|---|
| `ragz_rag_q1` | RAGZ single | retrieval caches frozen off/on as named | Required |
| `ragz_mqr_q3` | RAGZ 3 total | same | Required |
| `ragz_mqr_q5` | RAGZ 5 total | same | Required |
| `ragz_cached_rag_prefix_cold` | Ordinary RAG then stable fitted prefix | cold/write | Required; not CAG |
| `ragz_cached_rag_prefix_warm` | Ordinary RAG then stable fitted prefix | provider hit | Required; not CAG |
| `ragz_full_snapshot_cag_cold` | None after valid complete snapshot | cold/write | Eligible corpus only |
| `ragz_full_snapshot_cag_warm` | None after valid complete snapshot | provider hit | Eligible corpus only |
| `ragz_hybrid_cag_rag` | CAG eligibility/validation, then ordinary RAG fallback | all typed states | Required |
| `anythingllm` | Native retrieval | native/provider cache state named | Required when exact adapter passes |
| `ragflow` | Native retrieval | no CAG claim | `protocol_gated` until exact private adapter passes |
| `onyx` | Native retrieval | provider prompt caching named separately | `resource_gated` or run only after adapter preflight |

Allowed cell status values are `completed`, `failed`, `ineligible`,
`unsupported`, `credential_gated`, `protocol_gated`, and `resource_gated`.
Only `completed` cells have numeric metrics. All other states require a typed
reason and evidence; they never receive zeros.

AnythingLLM 1.16.0, RAGFlow 0.27.0, and Onyx 4.6.0 must use the same answer
model, OpenAI embedding model/dimension, corpus, question set, and final evidence
depth where their configuration permits. Native parser/chunker/ranker
differences remain explicit limitations. Heavy stacks run sequentially with a
resource preflight and are stopped after their own run; the existing MQR runtime
is never stopped by this protocol.

## Trial schedule

1. Run deterministic unit/isolation correctness first.
2. Run provider capability probes with synthetic data only.
3. Index the isolated controlled corpus once per system/configuration; attest
   vector/chunk/document/page counts before scoring.
4. Run unscored warmups.
5. For quality, run at least three independent repetitions for every
   question/variant at concurrency 1.
6. Randomize variant order inside each question/repetition block with a seed
   derived from protocol version and frozen fixture hash. Preserve pair IDs.
7. Run separate latency/lock-contention tracks at concurrency 1, 4, and 16.
8. Label cold, first write, warm hit, expired, invalidated, unsupported,
   malformed-telemetry, and fallback states separately.

Provider retries and throttling are recorded as trial fields. A retry does not
replace or erase the assigned trial. Failures remain in reliability, accuracy,
and abstention denominators. Conditional quality among completed calls may be
reported only alongside the all-assigned primary result.

## Metrics

### Retrieval

For RAG variants, compute at 5 and 10 where available:

- Recall: relevant evidence retrieved divided by judged relevant evidence;
- reciprocal rank of the first relevant result, zero on no hit;
- nDCG with frozen graded relevance;
- any-hit rate; and
- unique relevant-document coverage.

For `full_snapshot_cag`, retrieval metrics are `not_applicable`, not zero.

### Answer, grounding, citations, and abstention

Score separately and macro-average by question:

- context relevance, groundedness/faithfulness, and answer relevance using a
  frozen judge rubric and judge model/version;
- citation precision (supported emitted citation links / emitted links);
- citation coverage (citation-required supported claims with a valid citation /
  all citation-required claims);
- exact document/version/page/chunk resolution and support;
- exact match/F1 where appropriate;
- answerable and unanswerable abstention precision, recall, F1, coverage, and
  selective risk; and
- blinded pairwise preference for synthesis.

Calibrate judge prompts on a held-out set and report human/judge agreement.
Primary methodology references are
[RAGAS](https://aclanthology.org/2024.eacl-demo.16/),
[ALCE](https://aclanthology.org/2023.emnlp-main.398/), and
[selective question answering](https://aclanthology.org/2020.acl-main.503/).

### Atomic latency

Use a monotonic clock. Record milliseconds and status for:

- admission and quota;
- authorization/context;
- history/summary;
- query expansion;
- each dense/sparse embedding batch;
- each vector search and no-answer probe;
- fusion/dedupe;
- ACL recheck;
- rerank local/provider/retry wait;
- snapshot manifest, lookup, build, validation, single-flight wait, and
  invalidation;
- provider queue/connect, first byte, first non-empty token (TTFT), generation,
  and complete stream;
- citation parse/validation;
- usage and message persistence;
- SSE serialization; and
- request end-to-end.

Report N, mean, p50, p95, and p99 from raw assigned trial rows. Do not compare
the earlier retrieval-only latency with generation end-to-end latency.

### Usage and cost

Capture the raw provider-returned fields in the harness:

- input/prompt tokens;
- output/completion tokens;
- cached/read tokens;
- cache-write/creation tokens;
- reasoning tokens;
- cache outcome `hit|write|miss|unsupported|unknown|not_requested`;
- local token estimate and tokenizer identity;
- application quota debit separately;
- price source/date and completeness; and
- known cost.

For GPT-5.6 Luna at the registered price, cost is computed from provider fields
using $0.20/M ordinary input, $0.02/M cached input, $0.25/M cache-write input,
and $1.20/M output. Unknown fields or pricing make cost `null` with a reason.
The current application meter is never substituted for provider usage.

## Raw-data contract

The versioned JSON Schemas under `no_rel/benchmarks/cag/schemas/` will define:

- `manifest.schema.json`: source/config/image/SHA, corpus/question hashes,
  provider capability and price provenance;
- `trial.schema.json`: one assigned query × repetition × variant observation;
- `stage.schema.json`: monotonic atomic timings attached by trial ID;
- `security-gate.schema.json`: scenario, expected/actual decision and leak flag;
  and
- `aggregate.schema.json`: estimates, CIs, denominators, failures, and decision.

No schema permits raw PDF text, raw private questions/answers, provider request
bodies, keys, or unredacted account/request identifiers. Public examples use the
synthetic corpus only. Logs and metric labels exclude tenant, snapshot,
document, and query identifiers.

## Statistical analysis

- The query is the resampling cluster; repetitions for the same query remain
  together.
- For every paired comparison, resample query IDs with replacement 10,000
  times using a committed seed, recompute the paired delta, and publish the
  percentile 95% CI. Publish medians/quantiles and effect sizes even when a
  p-value is not used.
- Predeclare one primary quality family and one primary performance family.
  Apply Holm correction to secondary simultaneous comparisons and publish raw
  and adjusted values.
- Report stratum estimates and denominators without presenting underpowered
  subgroup differences as definitive.
- Keep timeouts, malformed output, refusals, provider errors, disconnects, and
  invalid citations in assigned denominators with typed failure counts.

References: [Dror et al., 2018](https://aclanthology.org/P18-1128/),
[Koehn, 2004](https://aclanthology.org/W04-3250/), and
[Holm, 1979](https://doi.org/10.1007/978-1-4419-9863-7_1214).

## Correctness and security matrix

The deterministic suite must cover:

- same-user repeat;
- different-user unrestricted repeat;
- different-user restricted repeat (must not reuse);
- cross-org/workspace identical text;
- mixed unrestricted/restricted documents;
- ACL update during build and generation;
- group membership revocation;
- v1→v2 promotion, rejected version, deletion, and projection outage;
- prompt/model/tokenizer/route/config/TTL changes;
- expiry, delayed/duplicate invalidation, and worker outage;
- provider supported/rejected/malformed/missing usage;
- partial streaming failure and disconnect; and
- concurrent identical requests and owner cancellation.

Pass requires zero exposure/staleness, 100-percent valid persisted provenance,
identical deterministic cached/uncached source maps, no retry after output, at
most one uncached retry after an explicit typed pre-output rejection, no private
data in public artifacts, and bounded cancellation-safe cache behavior.

## Execution stop gates

- Do not run the frozen private benchmark until repository unit, isolation, and
  deterministic CAG security tests pass.
- Stop a mode immediately on a hard security/citation failure and mark
  production `NO_GO`; retain sanitized failure evidence.
- Stop before a heavy competitor when its exact adapter, corpus attestation, or
  resource envelope is missing. Emit a typed gated cell.
- Do not implement product configuration/UI without a measured
  `GO`/`LIMITED_PILOT` decision.
- Do not mutate any GitHub PR or issue.

## Required deliverables

Publish sanitized RFC, protocol, schemas, commands, environment/SHAs,
aggregate results, limitations, and a dated per-mode
`GO|LIMITED_PILOT|NO_GO` decision under `no_rel/benchmarks/results/cag/`.
Before completion run current repository backend, frontend, migration, OpenAPI,
browser-list, isolation, credential/content, `git diff --check`, and remote-SHA
verification gates. The final handoff records branch/SHA, pushed commits,
benchmark status, every failed/gated cell, and whether any runtime changed.
