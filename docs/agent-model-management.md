# Agent models and web search

Open `/agent/config` as a superadmin. The page mirrors the reference OpenAlgo
configuration order: registered Models, ChatGPT subscription, Providers, Web search.
`/admin/models` remains an alias; `/agent` and `/chat` open the same chat interface.
Model availability in chat remains limited to enabled registrations. Workspace
defaults, the utility model, and embedding-model configuration are preserved.

## Connect providers

- API providers: search the provider catalog, select a model and add its API key.
  Endpoint-specific providers also require a base URL. Keys are write-only and
  encrypted in Postgres; only fingerprints return to the browser.
- ChatGPT: select **Connect ChatGPT**, open the device-verification link and enter
  the displayed code. Then register a `chatgpt/` model and use **Test** to check
  account availability. No API key is required. The connection is installation-wide
  and managed only by superadmins. Cancellation/disconnection cannot be undone by
  an already-running login poll. Tokens never use LiteLLM's plaintext file cache.
- Embeddings: use the embedding tab and confirm the catalog-supplied dimension.
  Models without dimension metadata require a value. The dimension is immutable
  after registration; existing document collections are not changed.

ChatGPT uses native Responses streaming, including planner tool calls, with encrypted
credentials refreshed under a database lock. Subscription models are not registered
with the API-key gateway and are not assigned API per-token prices. Available names
include the reference's measured supplement (`gpt-5.5`, `gpt-5.6-sol`,
`gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-6-astra`); access depends on the signed-in
account. Explicit LiteLLM metadata takes precedence as upstream adds these models.
GitHub Copilot remains visible but disabled because its separate file-based OAuth
flow is not supported by Ragz's encrypted credential boundary.

In chat, the model button sits inside the message composer beside **+**, not in the
page header. It opens upward with reasoning effort first and a searchable model
submenu. **Default** uses the registered model's default. **Off** sends no reasoning
override; it does not disable mandatory model reasoning. Only supported effort
levels are offered, and selection is locked during an active send.

## Web search

Web provider settings and keys have one home in `/agent/config#web-search`.
General Settings links to this section instead of maintaining a second selector.

| Provider | Credential | Result |
| --- | --- | --- |
| DuckDuckGo | None | Search links, optionally enriched with guarded page content |
| Tavily | Separate Tavily API key | Search links |
| Perplexity | Separate Perplexity API key | Synthesized research with citations |

Perplexity uses the Agent API (`POST /v1/agent`), with a configurable research model
(default `openai/gpt-5.6-luna`). It is exposed as `web_research`, separately from
link-search `web_search`. Synthesized research is labeled as external, untrusted
evidence, not treated as verbatim primary-source text. Workspace enablement,
per-turn user consent, query redaction and shared daily/per-turn limits still apply.
Changing providers does not silently fall back to another paid service.

Provider **Test** buttons make real outbound requests when explicitly selected and
may incur usage. Automated tests substitute HTTP responses and isolated databases;
successful tests do not establish access for a real account.

## Catalog maintenance

The backend SDK and deployed gateway are pinned to LiteLLM **1.100.0**. Discovery
reads the installed package's provider/model dictionaries, not a generated frontend
list or the older database pricing cache. Unknown prices/capabilities remain unknown.
Pricing-group aliases are normalized to transport provider IDs; reporting keeps
compatibility with older bare model registrations.

To upgrade, update `backend/pyproject.toml`, regenerate `backend/uv.lock`, update the
verified version and immutable image digest in `deploy/compose.yaml`, then restart
the backend, gateway and workers. Reload catalog rebuilds the current process's
advisory view; it does not install a new library version. The library's network
pricing-map fetch is disabled for deterministic, offline-capable discovery.

The async AWS clients now use `aiobotocore` directly, retaining the same S3/SES
behavior: the older `aioboto3` wrapper pins boto3 versions incompatible with this
LiteLLM release. No database migration or credential copying is required.

Protocol references: [LiteLLM ChatGPT provider](https://docs.litellm.ai/docs/providers/chatgpt),
[OpenAI device authentication](https://learn.chatgpt.com/docs/auth),
[Perplexity Agent API compatibility](https://docs.perplexity.ai/docs/agent-api/openai-compatibility).
