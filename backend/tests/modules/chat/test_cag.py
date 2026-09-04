from dataclasses import replace
from uuid import UUID

import pytest

from ragz.modules.chat.cag import (
    CagSource,
    PromptCacheRequest,
    SnapshotContext,
    SnapshotPolicy,
    build_cag_messages,
    build_snapshot,
    cache_usage_from_provider,
    may_retry_without_cache,
    resolve_snapshot_citations,
    validate_snapshot,
)

ORG_ID = UUID("10000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-4000-8000-000000000001")
USER_ID = UUID("30000000-0000-4000-8000-000000000001")
GROUP_ID = UUID("50000000-0000-4000-8000-000000000001")


def _source(document: int, *, page: int, text: str) -> CagSource:
    return CagSource(
        org_id=ORG_ID,
        workspace_id=WORKSPACE_ID,
        document_id=UUID(f"40000000-0000-4000-8000-{document:012d}"),
        content_hash=f"content-{document}",
        version=1,
        page=page,
        chunk_index=0,
        filename=f"source-{document}.md",
        section=None,
        text=text,
        marker=99,
        acl_group_ids=None,
        security_revision=3,
        projected_security_revision=3,
        index_state="active",
        status="indexed",
        is_current=True,
        approved=False,
    )


def _context() -> SnapshotContext:
    return SnapshotContext(
        org_id=ORG_ID,
        workspace_id=WORKSPACE_ID,
        principal_id=USER_ID,
        group_ids=frozenset(),
        acl_bypass=False,
        permissions=frozenset({"chat.generate"}),
        workspace_ids=frozenset({WORKSPACE_ID}),
    )


def _policy() -> SnapshotPolicy:
    return SnapshotPolicy(
        template_version="cag-prompt-v1",
        fit_policy_version="complete-v1",
        model_id="gpt-5.6-luna",
        route_id="litellm/openai/gpt-5.6-luna",
        tokenizer_id="cl100k_base",
        tokenizer_version="0.13.0",
        context_budget=8_000,
        history_reserve_tokens=500,
        question_reserve_tokens=500,
        tool_reserve_tokens=0,
        output_reserve_tokens=1_000,
        minimum_cacheable_prefix_tokens=1_024,
        configuration_version="cag-v1",
        ttl_seconds=1_800,
    )


def test_equivalent_authorized_inputs_produce_one_canonical_snapshot_key() -> None:
    first_source = _source(1, page=2, text="alpha")
    second_source = _source(2, page=1, text="beta")

    forward = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(first_source, second_source),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )
    reverse = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(second_source, first_source),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert forward.eligible is True
    assert forward.snapshot is not None
    assert reverse.snapshot is not None
    assert forward.snapshot.snapshot_id == reverse.snapshot.snapshot_id
    assert [source.marker for source in forward.snapshot.sources] == [1, 2]


def test_cached_rag_prefix_preserves_authoritative_fitted_source_order() -> None:
    first_source = _source(1, page=2, text="alpha")
    second_source = _source(2, page=1, text="beta")

    decision = build_snapshot(
        mode="cached_rag_prefix",
        context=_context(),
        sources=(second_source, first_source),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert decision.snapshot is not None
    assert [source.document_id for source in decision.snapshot.sources] == [
        second_source.document_id,
        first_source.document_id,
    ]
    assert [source.marker for source in decision.snapshot.sources] == [1, 2]


def test_cag_messages_put_stable_sources_before_dynamic_history_and_question() -> None:
    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(_source(1, page=7, text="stable evidence"),),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )
    assert decision.snapshot is not None

    messages = build_cag_messages(
        decision.snapshot,
        history=(("user", "older question"), ("assistant", "older answer")),
        user_query="current question",
        summary="earlier summary",
    )

    assert messages[0] == {"role": "system", "content": "stable policy"}
    assert messages[1]["role"] == "system"
    assert "<data id=\"1\"" in str(messages[1]["content"])
    assert messages[2] == {
        "role": "system",
        "content": "[Earlier conversation summary]\nearlier summary",
    }
    assert messages[-1] == {"role": "user", "content": "current question"}


def test_snapshot_citations_keep_exact_version_page_chunk_and_drop_bogus_markers() -> None:
    source = replace(
        _source(1, page=7, text="stable evidence"),
        version=2,
        chunk_index=4,
    )
    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(source,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )
    assert decision.snapshot is not None

    citations = resolve_snapshot_citations(
        decision.snapshot,
        "Supported claim [1]. Forged marker [99]. Duplicate [1].",
    )

    assert [(c.marker, c.document_id, c.version, c.page, c.chunk_index) for c in citations] == [
        (1, source.document_id, 2, 7, 4)
    ]


@pytest.mark.parametrize(
    ("usage", "capability", "expected_outcome", "expected_read", "expected_write"),
    [
        (
            {"prompt_tokens_details": {"cached_tokens": 1900, "cache_write_tokens": 0}},
            "supported",
            "hit",
            1900,
            0,
        ),
        (
            {"prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 1900}},
            "supported",
            "write",
            0,
            1900,
        ),
        (
            {"prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0}},
            "supported",
            "miss",
            0,
            0,
        ),
        ({"prompt_tokens": 2000}, "supported", "unknown", None, None),
        (None, "unknown", "unknown", None, None),
        (None, "unsupported", "unsupported", None, None),
    ],
)
def test_provider_cache_usage_never_infers_a_hit_from_latency(
    usage: dict[str, object] | None,
    capability: str,
    expected_outcome: str,
    expected_read: int | None,
    expected_write: int | None,
) -> None:
    cache_usage = cache_usage_from_provider(
        usage,
        request=PromptCacheRequest(snapshot_id="a" * 64),
        capability=capability,
    )

    assert cache_usage.outcome == expected_outcome
    assert cache_usage.read_tokens == expected_read
    assert cache_usage.write_tokens == expected_write


@pytest.mark.parametrize(
    ("explicit_unsupported", "output_started", "ambiguous", "retry_count", "expected"),
    [
        (True, False, False, 0, True),
        (True, True, False, 0, False),
        (True, False, True, 0, False),
        (True, False, False, 1, False),
        (False, False, False, 0, False),
    ],
)
def test_cache_fallback_never_retries_after_output_or_ambiguous_failure(
    explicit_unsupported: bool,
    output_started: bool,
    ambiguous: bool,
    retry_count: int,
    expected: bool,
) -> None:
    assert may_retry_without_cache(
        explicit_unsupported=explicit_unsupported,
        output_started=output_started,
        ambiguous_failure=ambiguous,
        retry_count=retry_count,
    ) is expected


def test_mixed_org_or_workspace_sources_are_rejected_instead_of_filtered() -> None:
    source = _source(1, page=1, text="alpha")
    foreign_org = replace(
        _source(2, page=1, text="beta"),
        org_id=UUID("10000000-0000-4000-8000-000000000099"),
    )

    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(source, foreign_org),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert decision.eligible is False
    assert decision.reason == "mixed_org_or_workspace"
    assert decision.snapshot is None


def test_snapshot_that_does_not_fit_reserved_context_is_ineligible() -> None:
    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(_source(1, page=1, text="alpha"),),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=6_001,
    )

    assert decision.eligible is False
    assert decision.reason == "context_budget_exceeded"
    assert decision.snapshot is None


def test_snapshot_below_provider_cache_minimum_is_ineligible() -> None:
    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(_source(1, page=1, text="alpha"),),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=1_023,
    )

    assert decision.eligible is False
    assert decision.reason == "below_minimum_cacheable_prefix"
    assert decision.snapshot is None


def test_duplicate_source_identity_is_rejected_instead_of_silently_deduplicated() -> None:
    source = _source(1, page=1, text="alpha")
    duplicate = replace(source, text="conflicting duplicate")

    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(source, duplicate),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert decision.eligible is False
    assert decision.reason == "duplicate_source"
    assert decision.snapshot is None


def test_unprojected_security_revision_fails_closed() -> None:
    stale = replace(
        _source(1, page=1, text="alpha"),
        security_revision=4,
        projected_security_revision=3,
        index_state="pending",
    )

    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(stale,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert decision.eligible is False
    assert decision.reason == "security_projection_stale"
    assert decision.snapshot is None


def test_restricted_source_not_visible_to_current_principal_is_rejected() -> None:
    restricted = replace(
        _source(1, page=1, text="restricted"),
        acl_group_ids=(GROUP_ID,),
    )

    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(restricted,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert decision.eligible is False
    assert decision.reason == "source_not_visible"
    assert decision.snapshot is None


def test_empty_restricted_acl_is_invalid_not_unrestricted() -> None:
    invalid_acl = replace(
        _source(1, page=1, text="restricted"),
        acl_group_ids=(),
    )

    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(invalid_acl,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert decision.eligible is False
    assert decision.reason == "invalid_empty_acl"
    assert decision.snapshot is None


def test_restricted_snapshot_is_scoped_to_one_principal_in_v1() -> None:
    restricted = replace(
        _source(1, page=1, text="restricted"),
        acl_group_ids=(GROUP_ID,),
    )
    first_context = replace(_context(), group_ids=frozenset({GROUP_ID}))
    second_context = replace(
        first_context,
        principal_id=UUID("30000000-0000-4000-8000-000000000002"),
    )

    first = build_snapshot(
        mode="full_snapshot_cag",
        context=first_context,
        sources=(restricted,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )
    second = build_snapshot(
        mode="full_snapshot_cag",
        context=second_context,
        sources=(restricted,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert first.snapshot is not None
    assert second.snapshot is not None
    assert first.snapshot.visibility_scope == "principal"
    assert first.snapshot.snapshot_id != second.snapshot.snapshot_id


def test_restricted_snapshot_rotates_when_effective_membership_changes() -> None:
    other_group = UUID("50000000-0000-4000-8000-000000000002")
    restricted = replace(
        _source(1, page=1, text="restricted"),
        acl_group_ids=(GROUP_ID,),
    )
    first_context = replace(_context(), group_ids=frozenset({GROUP_ID}))
    changed_context = replace(
        first_context,
        group_ids=frozenset({GROUP_ID, other_group}),
    )

    first = build_snapshot(
        mode="full_snapshot_cag",
        context=first_context,
        sources=(restricted,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )
    changed = build_snapshot(
        mode="full_snapshot_cag",
        context=changed_context,
        sources=(restricted,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert first.snapshot is not None
    assert changed.snapshot is not None
    assert first.snapshot.snapshot_id != changed.snapshot.snapshot_id


def test_restricted_snapshot_requires_concrete_principal_even_with_acl_bypass() -> None:
    restricted = replace(
        _source(1, page=1, text="restricted"),
        acl_group_ids=(GROUP_ID,),
    )

    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=replace(_context(), principal_id=None, acl_bypass=True),
        sources=(restricted,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert decision.eligible is False
    assert decision.reason == "principal_required_for_restricted_snapshot"
    assert decision.snapshot is None


def test_wholly_unrestricted_snapshot_can_be_shared_by_authorized_users() -> None:
    source = _source(1, page=1, text="public to workspace members")
    second_context = replace(
        _context(),
        principal_id=UUID("30000000-0000-4000-8000-000000000002"),
        group_ids=frozenset({GROUP_ID}),
    )

    first = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(source,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )
    second = build_snapshot(
        mode="full_snapshot_cag",
        context=second_context,
        sources=(source,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert first.snapshot is not None
    assert second.snapshot is not None
    assert first.snapshot.visibility_scope == "unrestricted"
    assert first.snapshot.snapshot_id == second.snapshot.snapshot_id


def test_principal_without_generation_permission_is_ineligible() -> None:
    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=replace(_context(), permissions=frozenset()),
        sources=(_source(1, page=1, text="alpha"),),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert decision.eligible is False
    assert decision.reason == "generation_not_authorized"
    assert decision.snapshot is None


def test_principal_without_current_workspace_membership_is_ineligible() -> None:
    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=replace(_context(), workspace_ids=frozenset()),
        sources=(_source(1, page=1, text="alpha"),),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert decision.eligible is False
    assert decision.reason == "workspace_not_authorized"
    assert decision.snapshot is None


def test_empty_complete_snapshot_is_ineligible() -> None:
    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert decision.eligible is False
    assert decision.reason == "empty_snapshot"
    assert decision.snapshot is None


def test_deleting_document_is_not_snapshot_eligible() -> None:
    deleting = replace(_source(1, page=1, text="alpha"), status="deleting")

    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(deleting,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert decision.eligible is False
    assert decision.reason == "source_not_indexed"
    assert decision.snapshot is None


def test_superseded_document_version_is_not_snapshot_eligible() -> None:
    superseded = replace(_source(1, page=1, text="alpha"), is_current=False)

    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(superseded,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert decision.eligible is False
    assert decision.reason == "source_not_current"
    assert decision.snapshot is None


def test_unapproved_source_is_rejected_when_policy_requires_approval() -> None:
    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(_source(1, page=1, text="alpha"),),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=replace(_policy(), require_approved=True),
        rendered_prefix_token_count=2_000,
    )

    assert decision.eligible is False
    assert decision.reason == "source_not_approved"
    assert decision.snapshot is None


@pytest.mark.parametrize(
    "change",
    [
        "source_text",
        "content_hash",
        "security_revision",
        "stable_policy",
        "workspace_prompt",
        "model",
        "route",
        "tokenizer",
        "budget",
        "configuration",
    ],
)
def test_every_bound_content_prompt_model_or_config_change_rotates_key(change: str) -> None:
    source = _source(1, page=1, text="caf\u00e9")
    context = _context()
    policy = _policy()
    stable_policy = "stable policy"
    workspace_prompt = "workspace prompt"
    changed_source = source

    if change == "source_text":
        changed_source = replace(source, text="cafe\u0301")
    elif change == "content_hash":
        changed_source = replace(source, content_hash="content-changed")
    elif change == "security_revision":
        changed_source = replace(
            source,
            security_revision=4,
            projected_security_revision=4,
        )
    elif change == "stable_policy":
        stable_policy = "stable policy v2"
    elif change == "workspace_prompt":
        workspace_prompt = "workspace prompt v2"
    elif change == "model":
        policy = replace(policy, model_id="gpt-5.6-terra")
    elif change == "route":
        policy = replace(policy, route_id="other/openai/gpt-5.6-luna")
    elif change == "tokenizer":
        policy = replace(policy, tokenizer_version="0.14.0")
    elif change == "budget":
        policy = replace(policy, context_budget=9_000)
    elif change == "configuration":
        policy = replace(policy, configuration_version="cag-v2")

    original = build_snapshot(
        mode="full_snapshot_cag",
        context=context,
        sources=(source,),
        stable_policy_prefix="stable policy",
        workspace_prompt="workspace prompt",
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )
    changed = build_snapshot(
        mode="full_snapshot_cag",
        context=context,
        sources=(changed_source,),
        stable_policy_prefix=stable_policy,
        workspace_prompt=workspace_prompt,
        policy=policy,
        rendered_prefix_token_count=2_000,
    )

    assert original.snapshot is not None
    assert changed.snapshot is not None
    assert original.snapshot.snapshot_id != changed.snapshot.snapshot_id


def test_length_delimited_identity_distinguishes_ambiguous_string_boundaries() -> None:
    first_source = replace(
        _source(1, page=1, text="same"),
        filename="ab",
        section="c",
    )
    second_source = replace(
        first_source,
        filename="a",
        section="bc",
    )

    first = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(first_source,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )
    second = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(second_source,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert first.snapshot is not None
    assert second.snapshot is not None
    assert first.snapshot.snapshot_id != second.snapshot.snapshot_id


def test_membership_revocation_invalidates_restricted_snapshot_on_use() -> None:
    restricted = replace(
        _source(1, page=1, text="restricted"),
        acl_group_ids=(GROUP_ID,),
    )
    authorized_context = replace(_context(), group_ids=frozenset({GROUP_ID}))
    built = build_snapshot(
        mode="full_snapshot_cag",
        context=authorized_context,
        sources=(restricted,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )
    assert built.snapshot is not None

    validation = validate_snapshot(
        built.snapshot,
        context=_context(),
        sources=(restricted,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert validation.valid is False
    assert validation.reason == "source_not_visible"


def test_unchanged_fresh_authoritative_state_validates() -> None:
    source = _source(1, page=1, text="alpha")
    built = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(source,),
        stable_policy_prefix="stable policy",
        workspace_prompt="workspace prompt",
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )
    assert built.snapshot is not None

    validation = validate_snapshot(
        built.snapshot,
        context=_context(),
        sources=(source,),
        stable_policy_prefix="stable policy",
        workspace_prompt="workspace prompt",
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert validation.valid is True
    assert validation.reason is None


@pytest.mark.parametrize(
    "change",
    ["new_source", "source_mutation", "version_promotion", "workspace_prompt", "route"],
)
def test_validation_rejects_fresh_source_or_configuration_drift(change: str) -> None:
    source = _source(1, page=1, text="alpha")
    built = build_snapshot(
        mode="full_snapshot_cag",
        context=_context(),
        sources=(source,),
        stable_policy_prefix="stable policy",
        workspace_prompt="workspace prompt",
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )
    assert built.snapshot is not None

    current_sources = (source,)
    workspace_prompt = "workspace prompt"
    policy = _policy()
    if change == "new_source":
        current_sources = (source, _source(2, page=2, text="newly visible"))
    elif change == "source_mutation":
        current_sources = (replace(source, text="mutated"),)
    elif change == "version_promotion":
        current_sources = (
            replace(source, version=2, content_hash="content-v2", text="version two"),
        )
    elif change == "workspace_prompt":
        workspace_prompt = "workspace prompt v2"
    elif change == "route":
        policy = replace(policy, route_id="other/openai/gpt-5.6-luna")

    validation = validate_snapshot(
        built.snapshot,
        context=_context(),
        sources=current_sources,
        stable_policy_prefix="stable policy",
        workspace_prompt=workspace_prompt,
        policy=policy,
        rendered_prefix_token_count=2_000,
    )

    assert validation.valid is False
    assert validation.reason == "snapshot_state_changed"
