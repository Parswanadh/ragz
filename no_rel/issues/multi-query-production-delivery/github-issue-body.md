# Proposal: bounded, superadmin-controlled multi-query retrieval

## Summary

Would you be open to adding multi-query retrieval as an opt-in workspace
capability controlled only by a superadmin?

The proposed path keeps the current single-query hybrid retriever as the
default. When enabled, a designated utility model generates bounded query
perspectives, all dense and sparse lanes use the same tenant/ACL/current-version
filter, and Qdrant performs one RRF fusion. Provider failure or deadline expiry
falls back to the original query.

## Why this is worth considering

Multi-query can improve coverage for vocabulary mismatch, but the measured
benefit is workload-dependent and its provider latency is material. On the
frozen three-book exact-page set, Q3 did not improve Recall over Q1, so this
proposal deliberately does **not** change the default.

The post-change confirmation covered 960 zero-error retrieval observations,
including 800 answerable quality observations:

| Mode | Recall@5 | MRR@5 | nDCG@5 | Mean | p95 |
|---|---:|---:|---:|---:|---:|
| Q1, cache off | 0.6000 | 0.4517 | 0.4890 | 728.49 ms | 913.52 ms |
| Q1, cache warm | 0.6000 | 0.4517 | 0.4890 | 16.93 ms | 19.68 ms |
| Q3, cache off | 0.6000 | 0.4475 | 0.4855 | 1,385.00 ms | 1,639.51 ms |
| Q3, cache warm | 0.6000 | 0.4475 | 0.4855 | 33.76 ms | 39.33 ms |

Q3 minus Q1 Recall was exactly zero on 200 paired answerable observations. A
separate 24-query expansion-cache check returned 24/24 exact query sets and made
zero warm provider calls. These numbers support an opt-in evaluation feature,
not a claim that MQR is universally better.

## Proposed behavior

- Add `multi_query_enabled`, default `false`, to workspace settings.
- Permit only a superadmin to mutate it; ordinary admins and users receive 403
  even if they forge the PATCH request.
- Support one, three, or five total query lanes in internal comparison/eval
  paths; the workspace product toggle uses the bounded production setting.
- Run the original dense embedding concurrently with query expansion.
- Impose an absolute expansion deadline, then use the exact Q1 path on timeout.
- Cache query embeddings and expansions in bounded, process-local TTL/LRU
  caches using opaque SHA-256 namespaced keys; coalesce identical cold keys so
  concurrent requests do not duplicate provider calls.
- Retry only transient Cohere statuses/transport failures with bounded backoff;
  never retry authentication failures.
- Preserve the same tenant, workspace, ACL, security-projection and
  current-version filter on every lane, followed by the existing ACL recheck.
- Make equal-score fusion and rerank output deterministic.
- Persist incurred retrieval-provider usage before downstream source assembly
  or answer generation can fail/cancel.
- Preserve independent off switches for MQR, reranking and both caches.

## Acceptance criteria

- [ ] MQR and reranking remain off by default.
- [ ] Only superadmins see the UI control and only superadmins can change it.
- [ ] Admin/user forged mutations fail closed and do not change the row.
- [ ] Missing utility model, malformed output, provider failure and deadline
      expiry all return the original-query retrieval path.
- [ ] Every generated lane receives the identical authorization filter.
- [ ] Expansion count, cache, retry and stage metrics use bounded labels and do
      not contain query text, generated alternatives, credentials or bodies.
- [ ] Caches are bounded, expiring, copy-safe and namespaced by effective model,
      dimension/prompt version and lane count as applicable.
- [ ] Cancelling the request that owns a cold single-flight key does not cancel
      unrelated waiters; one waiter reclaims the key.
- [ ] A migration, configuration examples and production defaults are included.
- [ ] Backend, frontend, browser authorization and production-build gates pass.
- [ ] Benchmark claims state corpus, qrels unit, denominator, cache state and
      provider path; incomplete competitors are marked not executed, not zero.

## Operational and privacy notes

The caches are replica-local accelerators, not durable shared truth. A restart
or another replica can miss without changing correctness. Cache keys and public
metrics contain no raw user query. Query expansion remains a provider call when
there is no warm entry, so operators should review provider data policy and cost
before enabling the workspace feature.

Rollback does not require a schema rollback: disable the workspace toggle,
disable either cache through configuration, and leave reranking off.

## Reproduction

```bash
cd backend
DOCKER_HOST=unix:///var/run/docker.sock uv run pytest -q \
  tests/core/test_config.py \
  tests/modules/retrieval/test_embeddings.py \
  tests/modules/retrieval/test_query_expansion.py \
  tests/modules/retrieval/test_rerank.py \
  tests/modules/retrieval/test_retrieve.py \
  tests/modules/retrieval/test_retrieve_rerank.py \
  tests/isolation/test_multi_query_isolation.py

cd ../frontend
pnpm test -- --run
```
