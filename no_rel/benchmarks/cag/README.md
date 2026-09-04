# CAG Benchmark Harness

This directory contains only redistributable fixtures, strict schemas, and
sanitized evidence. Private PDFs, extracted book text, private questions,
reference answers, provider request bodies, credentials, and raw provider
responses must stay outside Git.

Current harness capabilities:

- deterministic randomized paired schedules from opaque question IDs;
- strict Draft 2020-12 validation for JSON and JSONL without echoing values;
- failure-inclusive aggregates and query-clustered paired-bootstrap 95% CIs;
- typed stage/security/result schemas; and
- a CC0 fictional correctness corpus.

System adapters and the frozen 120-question private run are not complete. The
provider capability probe is evidence that the exact route supports prompt
caching; it is not the final benchmark.

## Commands

Run from `backend/`.

```bash
uv run python scripts/bench_cag.py schedule \
  --questions /private/path/cag-question-manifest.json \
  --variants ragz_rag_q1,ragz_mqr_q3,ragz_mqr_q5,ragz_cached_rag_prefix_cold,ragz_cached_rag_prefix_warm,ragz_full_snapshot_cag_cold,ragz_full_snapshot_cag_warm,ragz_hybrid_cag_rag \
  --repetitions 3 \
  --seed 20260904 \
  --output /private/path/cag-schedule.json

uv run python scripts/bench_cag.py validate \
  --schema ../no_rel/benchmarks/cag/schemas/trial.schema.json \
  --input /private/path/cag-trials.jsonl

uv run python scripts/bench_cag.py aggregate \
  --trials /private/path/cag-trials.jsonl \
  --schedule /private/path/cag-schedule.json \
  --baseline-variant ragz_rag_q1 \
  --bootstrap-samples 10000 \
  --seed 20260904 \
  --output ../no_rel/benchmarks/results/cag/aggregate.json
```

Pure tests avoid the repository's unrelated integration autouse fixture:

```bash
uv run pytest --confcutdir=tests/modules/chat tests/modules/chat/test_cag.py -q
uv run pytest --confcutdir=tests/isolation tests/isolation/test_cag_isolation.py -q
uv run pytest --confcutdir=tests/benchmarks tests/benchmarks/test_bench_cag.py -q
```

The normal CI commands must still run before completion; `--confcutdir` is not a
replacement for repository integration/isolation gates.

## Privacy and provenance

- Public question-manifest rows may contain only `question_id` and `stratum`.
- Validation failures report schema paths and unexpected key names, never values.
- Trial rows contain scores, usage, timings, typed failure state, and opaque IDs,
  but no question/answer/source text.
- Every scored run must validate its clean commit, corpus/question hashes,
  provider capability probe, model route, embedding width, parser, chunking,
  retrieval configuration, prompt hash, and failure policy.
- A non-completed cell uses a typed status and reason. It never receives numeric
  zero metrics.

See [the protocol](../CAG_EXPERIMENT_PROTOCOL.md) and
[ADR-0008](../../../docs/adr/ADR-0008-cache-augmented-generation.md).
