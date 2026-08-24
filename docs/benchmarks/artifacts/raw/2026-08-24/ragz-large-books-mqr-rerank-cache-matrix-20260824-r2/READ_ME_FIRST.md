# Effective run status: invalid as a complete matrix

`manifest.json` is retained byte-for-byte as the runner emitted it so the
downstream provenance hashes remain verifiable. Its historical top-level
`"status": "completed"` is not the effective validation result: condition
`q3_rerank-10_cache-off` contains five errors and only 15 answerable quality
observations.

Consumers must read `post_run_validation.json`, whose effective status is
`invalid_as_complete_matrix` and whose `quality_aggregate_eligible` value is
`false`. The derived aggregate also records
`screen_status: invalid_as_complete_matrix`. Only the 14 individually complete
screening conditions may be interpreted, and this run must never be presented
as a complete 15-cell matrix.
