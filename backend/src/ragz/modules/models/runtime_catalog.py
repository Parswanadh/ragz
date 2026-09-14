"""Advisory provider/model catalog from the installed LiteLLM registry.

No static frontend model list, pricing guesses, or get_model_info fallback.
Unknown providers survive package upgrades; local maps only supply display/setup hints.
ChatGPT's measured supplemental names mirror reference/openalgo until upstream lists them.
"""

from collections.abc import Mapping
from functools import lru_cache
from importlib.metadata import version
from typing import Any, Literal

from pydantic import BaseModel, Field

from ragz.modules.models.schemas import ProviderKind
from ragz.modules.models.sdk import load_sdk

CHAT_MODES = {"chat", "responses", "completion"}
_BRANDS = {
    "openai": "OpenAI",
    "chatgpt": "ChatGPT",
    "anthropic": "Anthropic",
    "gemini": "Google Gemini",
    "vertex_ai": "Google Vertex AI",
    "azure": "Azure OpenAI",
    "bedrock": "Amazon Bedrock",
    "ollama": "Ollama",
    "ollama_chat": "Ollama (chat)",
    "openrouter": "OpenRouter",
    "perplexity": "Perplexity",
    "groq": "Groq",
    "mistral": "Mistral AI",
    "deepseek": "DeepSeek",
    "xai": "xAI",
    "together_ai": "Together AI",
    "lm_studio": "LM Studio",
    "huggingface": "Hugging Face",
}
_SELF_HOSTED = {
    "custom",
    "custom_openai",
    "docker_model_runner",
    "hosted_vllm",
    "lemonade",
    "litellm_proxy",
    "llamafile",
    "lm_studio",
    "openai_like",
    "vllm",
}
_KEYLESS = _SELF_HOSTED | {
    "chatgpt",
    "ollama",
    "ollama_chat",
    "oobabooga",
    "petals",
    "triton",
    "bedrock",
    "sagemaker",
    "sagemaker_chat",
    "sagemaker_nova",
    "vertex_ai",
    "vertex_ai_beta",
}
_NEEDS_BASE = _SELF_HOSTED | {
    "azure",
    "azure_ai",
    "azure_text",
    "databricks",
    "ollama",
    "ollama_chat",
    "oobabooga",
    "triton",
    "watsonx",
    "watsonx_text",
}
_BASE_URLS = {
    "ollama": "http://localhost:11434",
    "ollama_chat": "http://localhost:11434",
    "lm_studio": "http://localhost:1234/v1",
}
_SUBSCRIPTION_MODELS = {
    "gpt-5.5": 1050000,
    "gpt-5.6-sol": 922000,
    "gpt-5.6-luna": 922000,
    "gpt-5.6-terra": 922000,
    "gpt-6-astra": 922000,
}


class CatalogProvider(BaseModel):
    id: str
    name: str
    icon: str
    model_count: int
    needs_key: bool
    needs_base_url: bool
    provider_kind: ProviderKind
    default_base_url: str | None
    auth_mode: Literal["api_key", "subscription", "none"]
    supported: bool = True
    configuration_note: str | None = None


class CatalogModel(BaseModel):
    id: str
    name: str
    provider: str
    mode: str | None
    display_name: str
    max_input_tokens: int | None
    max_output_tokens: int | None
    input_cost_per_1m: float | None
    output_cost_per_1m: float | None
    supports_reasoning: bool | None
    supports_vision: bool | None
    supports_function_calling: bool | None
    supported_reasoning_efforts: list[str] = Field(default_factory=list)
    registered: bool = False
    billing_mode: Literal["metered", "subscription"] = "metered"
    dimension: int | None = None


class RuntimeCatalog(BaseModel):
    available: bool = True
    litellm_version: str
    providers: list[CatalogProvider]
    models: list[CatalogModel]


class CatalogProvidersOut(BaseModel):
    available: bool
    litellm_version: str
    providers: list[CatalogProvider]


class CatalogModelsOut(BaseModel):
    available: bool
    litellm_version: str
    models: list[CatalogModel]


def _integer(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _price(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return round(value * 1_000_000, 6)


def _boolean(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def reasoning_efforts(name: str, entry: Mapping[str, Any]) -> list[str]:
    if entry.get("supports_reasoning") is not True:
        return []
    # "off" means do not send an effort override, not disable mandatory reasoning.
    efforts = ["off", "low", "medium", "high"]
    bare = name.removeprefix("chatgpt/")
    for effort in ("xhigh", "max", "ultra"):
        supported = entry.get(f"supports_{effort}_reasoning_effort") is True
        if (
            name.startswith("chatgpt/")
            and bare in _SUBSCRIPTION_MODELS
            and f"supports_{effort}_reasoning_effort" not in entry
        ):
            ceiling = "xhigh" if bare == "gpt-5.5" else "max" if bare == "gpt-5.6-luna" else "ultra"
            supported = ("xhigh", "max", "ultra").index(effort) <= ("xhigh", "max", "ultra").index(
                ceiling
            )
        if supported:
            efforts.append(effort)
    return efforts


def _canonical(name: str, provider: str) -> str:
    # Ragz's openai/ollama and compatible kinds add their own transport prefix.
    if provider in {"openai", "ollama"} | _SELF_HOSTED:
        return name.removeprefix(f"{provider}/")
    return name if name.startswith(f"{provider}/") else f"{provider}/{name}"


def _pricing_provider(provider: str) -> str:
    if provider == "bedrock_converse":
        return "bedrock"
    for native in ("vertex_ai", "fireworks_ai"):
        if provider.startswith(f"{native}-"):
            return native
    return provider


def canonical_catalog_name(name: str, provider: str) -> str:
    """Provider-aware cache alias; shared with cost reporting of registered models."""
    return _canonical(name, _pricing_provider(provider))


def build_catalog(source: Any, *, version: str) -> RuntimeCatalog:
    """Pure builder so incomplete/future LiteLLM registries can be regression-tested."""
    costs = {
        k: dict(v)
        for k, v in source.model_cost.items()
        if k != "sample_spec" and isinstance(v, Mapping)
    }
    providers: set[str] = {p for p in source.LITELLM_CHAT_PROVIDERS if isinstance(p, str)}
    providers.add("chatgpt")
    transport_providers = set(getattr(source, "provider_list", providers)) | providers

    def owner(provider: str) -> str:
        provider = _pricing_provider(provider)
        if provider in transport_providers:
            return provider
        # LiteLLM uses pricing groups such as vertex_ai-language-models;
        # those are not valid transport prefixes.
        return next(
            (
                p
                for p in sorted(transport_providers, key=len, reverse=True)
                if provider.startswith(f"{p}-")
            ),
            provider,
        )

    names: dict[tuple[str, str], dict[str, Any]] = {}
    for listed_provider, listed in source.models_by_provider.items():
        provider = owner(listed_provider)
        for name in listed:
            if not isinstance(name, str) or name == "sample_spec":
                continue
            candidates = (f"{provider}/{name}", name, name.removeprefix(f"{provider}/"))
            # Never borrow a different provider's prices for a shared bare model name.
            entry = next(
                (
                    costs[k]
                    for k in candidates
                    if k in costs and owner(str(costs[k].get("litellm_provider", ""))) == provider
                ),
                {},
            )
            names[provider, _canonical(name, provider)] = entry
    for name, entry in costs.items():
        raw_provider = entry.get("litellm_provider")
        if not isinstance(raw_provider, str) or not raw_provider:
            continue
        provider = owner(raw_provider)
        if provider not in transport_providers:
            continue
        # Embedding-only providers are useful in Ragz even when not chat providers.
        if provider not in providers and entry.get("mode") != "embedding":
            continue
        providers.add(provider)
        names[provider, _canonical(name, provider)] = entry
    for bare, context in _SUBSCRIPTION_MODELS.items():
        key = ("chatgpt", f"chatgpt/{bare}")
        if not names.get(key):
            names[key] = {
                "mode": "responses",
                "max_input_tokens": context,
                "max_output_tokens": 128000,
                "supports_reasoning": True,
                "supports_vision": True,
                "supports_function_calling": True,
            }
    models: list[CatalogModel] = []
    for (provider, name), entry in names.items():
        if provider not in providers:
            continue
        subscription = provider == "chatgpt"
        mode = entry.get("mode")
        if mode is not None and mode not in CHAT_MODES | {"embedding"}:
            continue
        # Capability-only fallback for native ChatGPT entries with incomplete metadata.
        # Explicit native values win; API prices are never used for subscription billing.
        if subscription:
            sibling = costs.get(name.removeprefix("chatgpt/"), {})
            entry = {**{k: v for k, v in sibling.items() if k.startswith("supports_")}, **entry}
        models.append(
            CatalogModel(
                id=name,
                name=name,
                provider=provider,
                mode=mode,
                display_name=name.removeprefix(f"{provider}/"),
                max_input_tokens=_integer(entry.get("max_input_tokens", entry.get("max_tokens"))),
                max_output_tokens=_integer(entry.get("max_output_tokens")),
                input_cost_per_1m=None
                if subscription
                else _price(entry.get("input_cost_per_token")),
                output_cost_per_1m=None
                if subscription
                else _price(entry.get("output_cost_per_token")),
                supports_reasoning=_boolean(entry.get("supports_reasoning")),
                supports_vision=_boolean(entry.get("supports_vision")),
                supports_function_calling=_boolean(entry.get("supports_function_calling")),
                supported_reasoning_efforts=reasoning_efforts(name, entry),
                billing_mode="subscription" if subscription else "metered",
                dimension=_integer(entry.get("output_vector_size")),
            )
        )
    provider_rows = []
    for provider in sorted(providers, key=lambda p: (_BRANDS.get(p) or p).casefold()):
        kind: ProviderKind = "litellm"
        if provider == "openai":
            kind = "openai"
        elif provider == "ollama":
            kind = "ollama"
        elif provider in _SELF_HOSTED:
            kind = "openai_compatible"
        provider_rows.append(
            CatalogProvider(
                id=provider,
                name=_BRANDS.get(provider, provider),
                icon="openai" if provider == "chatgpt" else provider,
                model_count=sum(m.provider == provider and m.mode != "embedding" for m in models),
                needs_key=provider not in _KEYLESS,
                needs_base_url=provider in _NEEDS_BASE,
                provider_kind=kind,
                default_base_url=_BASE_URLS.get(provider),
                auth_mode="subscription"
                if provider == "chatgpt"
                else ("none" if provider in _KEYLESS else "api_key"),
                supported=provider != "github_copilot",
                configuration_note=(
                    "GitHub Copilot requires its own OAuth connection, which Ragz does not support."
                    if provider == "github_copilot"
                    else None
                ),
            )
        )
    return RuntimeCatalog(litellm_version=version, providers=provider_rows, models=models)


@lru_cache(maxsize=1)
def get_runtime_catalog() -> RuntimeCatalog:
    return build_catalog(load_sdk(), version=version("litellm"))


def find_catalog_model(name: str) -> CatalogModel | None:
    for model in get_runtime_catalog().models:
        if model.id == name or model.id == name.removeprefix("openai/"):
            return model
    return None
