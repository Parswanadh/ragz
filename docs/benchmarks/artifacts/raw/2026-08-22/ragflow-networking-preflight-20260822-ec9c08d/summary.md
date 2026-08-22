# RAGFlow v0.27.0 networking benchmark preflight

- Status: `resource_gated`
- Pinned commit: `ec9c08d809f63ba2815090182fa225899d2437d5`
- Docker CPU: `22`; required: `4`
- Host RAM: `16246616064` bytes
- Docker RAM: `3864363008` bytes
- Effective runtime RAM: `3864363008` bytes; official requirement: `16000000000` bytes
- Pinned Compose per-container MEM_LIMIT: `8073741824` bytes (configuration, not the official host/daemon RAM floor)
- Host free disk: `222503329792` bytes; Docker-daemon disk: `unverified`
- Host vm.max_map_count: `1048576`; Docker-daemon/VM value: `unverified`
- Intended embedding: `text-embedding-3-small` / `1536`d
- Intended generation model: `gpt-5.4-mini`
- Provider calls: `0`; quality score emitted: `false`

The full stack is not started when an official resource requirement fails. Unavailable is not scored as zero.

Official guidance: <https://github.com/infiniflow/ragflow/blob/v0.27.0/docs/quickstart.mdx>
