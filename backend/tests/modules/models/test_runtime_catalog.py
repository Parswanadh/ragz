from types import SimpleNamespace


def registry():
    return SimpleNamespace(
        LITELLM_CHAT_PROVIDERS=["openai", "new_provider", "openai", "chatgpt"],
        models_by_provider={
            "openai": ["gpt-test", "text-embedding-test"],
            "new_provider": ["new_provider/new-model"],
            "chatgpt": ["chatgpt/gpt-5.4"],
        },
        model_cost={
            "gpt-test": {
                "litellm_provider": "openai",
                "mode": "chat",
                "supports_reasoning": True,
                "supports_vision": False,
                "input_cost_per_token": 0.000002,
                "max_input_tokens": 128000,
            },
            "text-embedding-test": {
                "litellm_provider": "openai",
                "mode": "embedding",
                "output_vector_size": 1536,
            },
            "new_provider/new-model": {
                "litellm_provider": "new_provider",
                "mode": "chat",
                "supports_function_calling": True,
            },
            "chatgpt/gpt-5.4": {
                "litellm_provider": "chatgpt",
                "mode": "responses",
                "supports_reasoning": True,
            },
            "gpt-6-astra": {
                "litellm_provider": "openai",
                "mode": "responses",
                "input_cost_per_token": 0.00001,
            },
            "sample_spec": {"mode": "chat", "litellm_provider": "sample"},
        },
    )


def test_new_providers_appear_without_a_brand_table_entry():
    from ragz.modules.models.runtime_catalog import build_catalog

    result = build_catalog(registry(), version="test")
    providers = {p.id: p for p in result.providers}
    assert "new_provider" in providers
    assert providers["new_provider"].model_count == 1
    assert providers["new_provider"].needs_key is True
    assert providers["chatgpt"].auth_mode == "subscription"
    assert providers["chatgpt"].needs_key is False
    assert "sample" not in providers
    assert len([p for p in result.providers if p.id == "openai"]) == 1


def test_subscription_supplement_does_not_inherit_api_prices():
    from ragz.modules.models.runtime_catalog import build_catalog

    result = build_catalog(registry(), version="test")
    models = {m.id: m for m in result.models}
    model = models["chatgpt/gpt-6-astra"]
    assert model.mode == "responses"
    assert model.billing_mode == "subscription"
    assert model.input_cost_per_1m is None
    assert model.output_cost_per_1m is None
    assert model.supports_reasoning is True
    assert "ultra" in model.supported_reasoning_efforts
    assert models["gpt-6-astra"].input_cost_per_1m == 10.0


def test_native_subscription_metadata_wins_over_supplement():
    from ragz.modules.models.runtime_catalog import build_catalog

    source = registry()
    source.model_cost["chatgpt/gpt-6-astra"] = {
        "litellm_provider": "chatgpt",
        "mode": "responses",
        "max_input_tokens": 123456,
        "supports_vision": False,
    }
    result = build_catalog(source, version="test")
    model = next(m for m in result.models if m.id == "chatgpt/gpt-6-astra")
    assert model.max_input_tokens == 123456
    assert model.supports_vision is False


def test_embedding_models_survive_catalog_filtering_and_prices_are_nullable():
    from ragz.modules.models.runtime_catalog import build_catalog

    result = build_catalog(registry(), version="test")
    models = {m.id: m for m in result.models}
    assert models["text-embedding-test"].mode == "embedding"
    assert models["text-embedding-test"].dimension == 1536
    assert models["new_provider/new-model"].input_cost_per_1m is None
    assert models["new_provider/new-model"].supports_reasoning is None
    assert models["gpt-test"].input_cost_per_1m == 2.0
    assert "sample_spec" not in models


def test_canonical_names_preserve_native_routing_prefixes():
    from ragz.modules.models.runtime_catalog import build_catalog

    result = build_catalog(registry(), version="test")
    models = {m.id: m for m in result.models}
    assert models["new_provider/new-model"].name == "new_provider/new-model"
    assert models["gpt-test"].name == "gpt-test"


def test_pricing_groups_resolve_to_real_transport_providers():
    from ragz.modules.models.runtime_catalog import build_catalog

    source = registry()
    source.LITELLM_CHAT_PROVIDERS += ["vertex_ai", "fireworks_ai"]
    source.provider_list = source.LITELLM_CHAT_PROVIDERS
    source.models_by_provider["vertex_ai"] = ["vertex_ai/gemini-test"]
    source.model_cost.update(
        {
            "vertex_ai/gemini-test": {
                "litellm_provider": "vertex_ai-language-models",
                "mode": "chat",
                "supports_vision": True,
            },
            "gemini-embedding-test": {
                "litellm_provider": "vertex_ai-embedding-models",
                "mode": "embedding",
                "output_vector_size": 3072,
            },
            "fireworks_ai/WhereIsAI/test": {
                "litellm_provider": "fireworks_ai-embedding-models",
                "mode": "embedding",
                "output_vector_size": 1024,
            },
            "not-supported/test": {"litellm_provider": "not-supported", "mode": "embedding"},
        }
    )
    result = build_catalog(source, version="test")
    models = {m.id: m for m in result.models}
    assert models["vertex_ai/gemini-test"].supports_vision is True
    assert models["vertex_ai/gemini-embedding-test"].dimension == 3072
    assert models["fireworks_ai/WhereIsAI/test"].provider == "fireworks_ai"
    assert "not-supported/test" not in models
    assert all("-models/" not in name for name in models)


def test_explicit_native_reasoning_capabilities_beat_supplement():
    from ragz.modules.models.runtime_catalog import build_catalog

    source = registry()
    source.model_cost["chatgpt/gpt-6-astra"] = {
        "litellm_provider": "chatgpt",
        "mode": "responses",
        "supports_reasoning": True,
        "supports_ultra_reasoning_effort": False,
    }
    result = build_catalog(source, version="test")
    model = next(m for m in result.models if m.id == "chatgpt/gpt-6-astra")
    assert "ultra" not in model.supported_reasoning_efforts
