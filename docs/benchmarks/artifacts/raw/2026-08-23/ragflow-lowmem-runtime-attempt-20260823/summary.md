# RAGFlow v0.27.0 low-memory runtime attempt

- Status: `docker_desktop_content_store_gated`
- Intended document engine: `Infinity` with reduced temporary memory settings
- Intended models: API-hosted only; no TEI, DeepDoc, local embedding, or local generation service
- Docker memory: `3,864,363,008` bytes
- Image-acquisition attempts: `6`
- RAGFlow containers started: `0`
- Provider/model calls from RAGFlow: `0`
- Quality score emitted: `false`

The pinned RAGFlow application image was attempted from Docker Hub and the
official Huawei mirror. Docker Desktop/containerd repeatedly failed while
committing downloaded content layers, reporting a missing ingest data file.
Different layers failed across attempts, so the blocker is classified as a
Docker content-store failure, not RAGFlow model memory or application quality.

The Docker daemon was not restarted or repaired because it hosts unrelated
RAGZ and AGNO workloads. Host memory pressure improved during acquisition and
no stress-abort threshold fired. Dependency images for Infinity, MySQL, MinIO,
and Valkey were acquired, but no stack was started without the pinned RAGFlow
application image.

A separate native daemon was later discovered at
`unix:///var/run/docker.sock`. `skopeo` imported the pinned image there. The
native-daemon 3 GB project reached running state but was stopped by resource
thresholds; see `ragflow-native-daemon-lowmem-smoke-20260823-r5`.
