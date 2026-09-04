# Final CAG Architecture and Security Review

**Reviewed SHA:** `ac4291e61e15d7f9bfcb7e9a13fbd28e5c04f10d`
**Reviewer class:** Independent `gpt-5.6-sol`, read-only
**Scope:** Experimental base through the RFC, prototype, harness, schemas, and
dated decision record

## Verdict

No critical finding was identified. The combined-three-book production
`NO_GO` is defensible because the complete source material cannot fit the
advertised model window and no production path is wired.

The review found that the pure prototype cannot itself prove that a caller
enumerated every authoritative visible source or supplied an accurate rendered
token count. That is a high-severity limitation for any future production use,
so the decision record now labels the prototype `Partial`; no product or pilot
claim relies on it.

## Findings and disposition

| Severity | Finding | Disposition |
|---|---|---|
| High | Snapshot builder/validator accept caller-supplied source sets and token counts, and dynamic history/query limits are not independently enforced | Not productionized; gate downgraded to `Partial`; required authoritative adapter recorded as future work |
| High | Aggregation did not enforce the frozen pair schedule and averaged independently by question | Fixed: schedule schema is mandatory, exact `(trial_id, pair_id, variant, question, repetition)` coverage is validated, deltas are computed per pair then clustered by question |
| Medium | Implicit provider cache telemetry was discarded when no explicit cache request existed | Fixed: explicit-request state and provider-observed cache outcome are separate; reported reads/writes are retained |
| Medium | TTL was identity metadata but not enforced | Fixed: immutable build/expiry timestamps and exact-boundary validation were added with deterministic tests |
| Medium | Workspace prompt hash and rendered policy are independent caller inputs | Not productionized; included in the `Partial` prototype limitation and future authoritative rendering requirement |
| Medium | Gated/failed statuses could carry numeric metrics and completed-observed aggregation was not status-filtered | Fixed: conditional schema rules prohibit gated/failed numeric metrics; completed-observed metrics filter to completed rows |
| Medium | Synthetic fixture missed same-name, lineage, and identical-text visibility traps; size tiers were descriptors only | Partially fixed: same-name workspaces, shared lineage, and restricted/unrestricted identical text are present; tier descriptors remain non-scored and no private/final run uses them |
| Low | Schemas missed several cache/provenance states and retrieval aggregation | Partially fixed: schedule schema, malformed/fallback cache states, question-ID/assessor provenance, and retrieval aggregation added; no schema is claimed final for a run that did not occur |

## Residual gates

- No authoritative DB/Qdrant adapter exists for complete snapshot enumeration.
- No full prompt-envelope measurement joins stable prefix with actual dynamic
  history, question, tools, attachments, and output reservation.
- No production invalidation/outbox, cache store, single-flight, or provider
  adapter is wired.
- No 120-question private set was frozen and no final quality benchmark ran,
  because the target corpus-fit gate had already failed.
- The complete repository history has three pre-existing generic-api-key scan
  findings; the CAG commit range is clean.

These residuals prohibit production CAG. They do not weaken the target
`NO_GO`; they reinforce it.
