from dataclasses import replace
from uuid import UUID

from ragz.modules.chat.cag import (
    CagSnapshot,
    CagSource,
    SnapshotContext,
    SnapshotPolicy,
    build_snapshot,
    validate_snapshot,
)

ORG_A = UUID("a0000000-0000-4000-8000-000000000001")
ORG_B = UUID("a0000000-0000-4000-8000-000000000002")
WORKSPACE_A = UUID("b0000000-0000-4000-8000-000000000001")
WORKSPACE_B = UUID("b0000000-0000-4000-8000-000000000002")
USER_A = UUID("c0000000-0000-4000-8000-000000000001")
USER_B = UUID("c0000000-0000-4000-8000-000000000002")
GROUP_A = UUID("d0000000-0000-4000-8000-000000000001")
DOCUMENT = UUID("e0000000-0000-4000-8000-000000000001")


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


def _source(
    *,
    org_id: UUID,
    workspace_id: UUID,
    acl_group_ids: tuple[UUID, ...] | None = None,
) -> CagSource:
    return CagSource(
        org_id=org_id,
        workspace_id=workspace_id,
        document_id=DOCUMENT,
        content_hash="identical-content-hash",
        version=1,
        page=7,
        chunk_index=2,
        filename="same-name.md",
        section="same-section",
        text="identical source text",
        marker=1,
        acl_group_ids=acl_group_ids,
        security_revision=1,
        projected_security_revision=1,
        index_state="active",
        status="indexed",
        is_current=True,
        approved=True,
    )


def _context(
    *,
    org_id: UUID,
    workspace_id: UUID,
    principal_id: UUID,
    group_ids: frozenset[UUID] = frozenset(),
) -> SnapshotContext:
    return SnapshotContext(
        org_id=org_id,
        workspace_id=workspace_id,
        principal_id=principal_id,
        group_ids=group_ids,
        acl_bypass=False,
        permissions=frozenset({"chat.generate"}),
        workspace_ids=frozenset({workspace_id}),
    )


def _build(context: SnapshotContext, source: CagSource) -> CagSnapshot:
    decision = build_snapshot(
        mode="full_snapshot_cag",
        context=context,
        sources=(source,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )
    assert decision.snapshot is not None
    return decision.snapshot


def test_identical_content_never_shares_snapshot_across_organizations() -> None:
    first = _build(
        _context(org_id=ORG_A, workspace_id=WORKSPACE_A, principal_id=USER_A),
        _source(org_id=ORG_A, workspace_id=WORKSPACE_A),
    )
    second = _build(
        _context(org_id=ORG_B, workspace_id=WORKSPACE_A, principal_id=USER_A),
        _source(org_id=ORG_B, workspace_id=WORKSPACE_A),
    )

    assert first.snapshot_id != second.snapshot_id


def test_identical_content_never_shares_snapshot_across_workspaces() -> None:
    first = _build(
        _context(org_id=ORG_A, workspace_id=WORKSPACE_A, principal_id=USER_A),
        _source(org_id=ORG_A, workspace_id=WORKSPACE_A),
    )
    second = _build(
        _context(org_id=ORG_A, workspace_id=WORKSPACE_B, principal_id=USER_A),
        _source(org_id=ORG_A, workspace_id=WORKSPACE_B),
    )

    assert first.snapshot_id != second.snapshot_id


def test_restricted_snapshot_never_reuses_across_principals() -> None:
    source = _source(
        org_id=ORG_A,
        workspace_id=WORKSPACE_A,
        acl_group_ids=(GROUP_A,),
    )
    first = _build(
        _context(
            org_id=ORG_A,
            workspace_id=WORKSPACE_A,
            principal_id=USER_A,
            group_ids=frozenset({GROUP_A}),
        ),
        source,
    )
    second = _build(
        _context(
            org_id=ORG_A,
            workspace_id=WORKSPACE_A,
            principal_id=USER_B,
            group_ids=frozenset({GROUP_A}),
        ),
        source,
    )

    assert first.snapshot_id != second.snapshot_id


def test_acl_revision_committed_before_projection_invalidates_snapshot() -> None:
    context = _context(
        org_id=ORG_A,
        workspace_id=WORKSPACE_A,
        principal_id=USER_A,
        group_ids=frozenset({GROUP_A}),
    )
    source = _source(
        org_id=ORG_A,
        workspace_id=WORKSPACE_A,
        acl_group_ids=(GROUP_A,),
    )
    snapshot = _build(context, source)
    pending_projection = replace(
        source,
        security_revision=2,
        projected_security_revision=1,
        index_state="pending",
    )

    validation = validate_snapshot(
        snapshot,
        now_epoch_s=100,
        context=context,
        sources=(pending_projection,),
        stable_policy_prefix="stable policy",
        workspace_prompt=None,
        policy=_policy(),
        rendered_prefix_token_count=2_000,
    )

    assert validation.valid is False
    assert validation.reason == "security_projection_stale"
