# RAGFlow v0.27.0 native-daemon 3 GB smoke

- Interpretation: `runtime_resource_limited`
- Runner status: `aborted_threshold`
- Docker endpoint: `unix:///var/run/docker.sock`
- Daemon memory: `16,246,616,064` bytes
- Project memory budget: `3,000,000,000` bytes
- Document engine: reduced-memory Infinity
- Services reaching running state: RAGFlow, Infinity, MySQL, MinIO, Redis
- Local model services: none
- Provider calls: `0`
- Corpus ingestion / quality score: not attempted / unavailable

The guard stopped the project at sample 3 because swap had grown by
`1,415,712,768` bytes and RAGFlow used `1,378,684,502 / 1,379,758,243`
bytes (`99.9%`) of its slice. Host available memory was still
`1,170,857,984` bytes and memory PSI was `4.2`. No container was OOM-killed
or restarted.

This proves the external-model-only stack can boot under the 3 GB project
limit, but it cannot be held in a stable benchmark posture on this already
swapped host. No retrieval or answer score is assigned.
