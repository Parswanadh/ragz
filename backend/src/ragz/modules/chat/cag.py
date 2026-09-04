"""Pure, provider-neutral identities for authorized CAG snapshots.

This module has no database, cache, provider, or worker dependency.  It builds
immutable values that those boundaries can validate before any generation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from typing import Literal
from uuid import UUID

from ragz.modules.chat.prompting import PromptSource, render_data_blocks

type CagMode = Literal["full_snapshot_cag", "cached_rag_prefix"]


@dataclass(frozen=True, slots=True)
class CagSource:
    org_id: UUID
    workspace_id: UUID
    document_id: UUID
    content_hash: str
    version: int
    page: int
    chunk_index: int
    filename: str
    section: str | None
    text: str
    marker: int
    acl_group_ids: tuple[UUID, ...] | None
    security_revision: int
    projected_security_revision: int
    index_state: str
    status: str
    is_current: bool
    approved: bool


@dataclass(frozen=True, slots=True)
class SnapshotContext:
    org_id: UUID
    workspace_id: UUID
    principal_id: UUID | None
    group_ids: frozenset[UUID]
    acl_bypass: bool
    permissions: frozenset[str]
    workspace_ids: frozenset[UUID]


@dataclass(frozen=True, slots=True)
class SnapshotPolicy:
    template_version: str
    fit_policy_version: str
    model_id: str
    route_id: str
    tokenizer_id: str
    tokenizer_version: str
    context_budget: int
    history_reserve_tokens: int
    question_reserve_tokens: int
    tool_reserve_tokens: int
    output_reserve_tokens: int
    minimum_cacheable_prefix_tokens: int
    configuration_version: str
    ttl_seconds: int
    require_approved: bool = False


@dataclass(frozen=True, slots=True)
class CagSnapshot:
    snapshot_id: str
    mode: CagMode
    org_id: UUID
    workspace_id: UUID
    sources: tuple[CagSource, ...]
    rendered_prefix: str
    token_count: int
    visibility_scope: Literal["unrestricted", "principal"]
    authorization_fingerprint: str
    source_manifest_fingerprint: str
    policy_fingerprint: str
    workspace_prompt_hash: str


@dataclass(frozen=True, slots=True)
class SnapshotDecision:
    eligible: bool
    reason: str | None
    snapshot: CagSnapshot | None


@dataclass(frozen=True, slots=True)
class SnapshotValidation:
    valid: bool
    reason: str | None


type CanonicalValue = (
    None | bool | int | str | UUID | list[object] | tuple[object, ...] | dict[str, object]
)


def _frame(tag: bytes, payload: bytes) -> bytes:
    return tag + len(payload).to_bytes(8, "big") + payload


def _canonical(value: CanonicalValue) -> bytes:
    """Typed, length-delimited serialization used only as SHA-256 input."""
    if value is None:
        return _frame(b"n", b"")
    if isinstance(value, bool):
        return _frame(b"b", b"1" if value else b"0")
    if isinstance(value, int):
        return _frame(b"i", str(value).encode("ascii"))
    if isinstance(value, UUID):
        return _frame(b"u", value.bytes)
    if isinstance(value, str):
        return _frame(b"s", value.encode("utf-8"))
    if isinstance(value, (list, tuple)):
        payload = len(value).to_bytes(8, "big") + b"".join(
            _canonical(item) for item in value  # type: ignore[arg-type]
        )
        return _frame(b"l", payload)
    if isinstance(value, dict):
        items = sorted(value.items())
        payload = len(items).to_bytes(8, "big") + b"".join(
            _canonical(key) + _canonical(item)  # type: ignore[arg-type]
            for key, item in items
        )
        return _frame(b"d", payload)
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _digest(value: CanonicalValue) -> str:
    return sha256(_canonical(value)).hexdigest()


def _source_order(source: CagSource) -> tuple[str, int, int, int]:
    return (str(source.document_id), source.version, source.page, source.chunk_index)


def _ordered_sources(mode: CagMode, sources: tuple[CagSource, ...]) -> tuple[CagSource, ...]:
    ordered = sorted(sources, key=_source_order) if mode == "full_snapshot_cag" else sources
    return tuple(
        replace(source, marker=marker)
        for marker, source in enumerate(ordered, start=1)
    )


def _source_identity(source: CagSource) -> dict[str, object]:
    return {
        "org_id": source.org_id,
        "workspace_id": source.workspace_id,
        "document_id": source.document_id,
        "content_hash": source.content_hash,
        "version": source.version,
        "page": source.page,
        "chunk_index": source.chunk_index,
        "filename": source.filename,
        "section": source.section,
        "text_hash": sha256(source.text.encode("utf-8")).hexdigest(),
        "marker": source.marker,
        "acl_group_ids": (
            None
            if source.acl_group_ids is None
            else tuple(sorted(source.acl_group_ids, key=str))
        ),
        "security_revision": source.security_revision,
        "projected_security_revision": source.projected_security_revision,
        "index_state": source.index_state,
        "status": source.status,
        "is_current": source.is_current,
        "approved": source.approved,
    }


def build_snapshot(
    *,
    mode: CagMode,
    context: SnapshotContext,
    sources: tuple[CagSource, ...],
    stable_policy_prefix: str,
    workspace_prompt: str | None,
    policy: SnapshotPolicy,
    rendered_prefix_token_count: int,
) -> SnapshotDecision:
    """Build one canonical immutable snapshot from already-authorized input."""
    if not sources:
        return SnapshotDecision(
            eligible=False,
            reason="empty_snapshot",
            snapshot=None,
        )
    if context.workspace_id not in context.workspace_ids:
        return SnapshotDecision(
            eligible=False,
            reason="workspace_not_authorized",
            snapshot=None,
        )
    if any(
        source.org_id != context.org_id or source.workspace_id != context.workspace_id
        for source in sources
    ):
        return SnapshotDecision(
            eligible=False,
            reason="mixed_org_or_workspace",
            snapshot=None,
        )
    source_identities = [_source_order(source) for source in sources]
    if len(source_identities) != len(set(source_identities)):
        return SnapshotDecision(
            eligible=False,
            reason="duplicate_source",
            snapshot=None,
        )
    if "chat.generate" not in context.permissions:
        return SnapshotDecision(
            eligible=False,
            reason="generation_not_authorized",
            snapshot=None,
        )
    if any(source.status != "indexed" for source in sources):
        return SnapshotDecision(
            eligible=False,
            reason="source_not_indexed",
            snapshot=None,
        )
    if any(not source.is_current for source in sources):
        return SnapshotDecision(
            eligible=False,
            reason="source_not_current",
            snapshot=None,
        )
    if policy.require_approved and any(not source.approved for source in sources):
        return SnapshotDecision(
            eligible=False,
            reason="source_not_approved",
            snapshot=None,
        )
    if any(
        source.index_state != "active"
        or source.projected_security_revision != source.security_revision
        for source in sources
    ):
        return SnapshotDecision(
            eligible=False,
            reason="security_projection_stale",
            snapshot=None,
        )
    if any(source.acl_group_ids == () for source in sources):
        return SnapshotDecision(
            eligible=False,
            reason="invalid_empty_acl",
            snapshot=None,
        )
    if context.principal_id is None and any(
        source.acl_group_ids is not None for source in sources
    ):
        return SnapshotDecision(
            eligible=False,
            reason="principal_required_for_restricted_snapshot",
            snapshot=None,
        )
    if any(
        source.acl_group_ids is not None
        and not context.acl_bypass
        and not (set(source.acl_group_ids) & context.group_ids)
        for source in sources
    ):
        return SnapshotDecision(
            eligible=False,
            reason="source_not_visible",
            snapshot=None,
        )
    reserved_tokens = (
        policy.history_reserve_tokens
        + policy.question_reserve_tokens
        + policy.tool_reserve_tokens
        + policy.output_reserve_tokens
    )
    if rendered_prefix_token_count > policy.context_budget - reserved_tokens:
        return SnapshotDecision(
            eligible=False,
            reason="context_budget_exceeded",
            snapshot=None,
        )
    if rendered_prefix_token_count < policy.minimum_cacheable_prefix_tokens:
        return SnapshotDecision(
            eligible=False,
            reason="below_minimum_cacheable_prefix",
            snapshot=None,
        )
    canonical_sources = _ordered_sources(mode, sources)
    visibility_scope: Literal["unrestricted", "principal"] = (
        "unrestricted"
        if all(source.acl_group_ids is None for source in canonical_sources)
        else "principal"
    )
    authorization_identity: dict[str, object] = {
        "org_id": context.org_id,
        "workspace_id": context.workspace_id,
        "visibility_scope": visibility_scope,
        "can_generate": "chat.generate" in context.permissions,
    }
    if visibility_scope == "principal":
        authorization_identity.update(
            {
                "principal_id": context.principal_id,
                "group_ids": tuple(sorted(context.group_ids, key=str)),
                "acl_bypass": context.acl_bypass,
                "permissions": tuple(sorted(context.permissions)),
            }
        )
    authorization_fingerprint = _digest(authorization_identity)
    source_manifest_fingerprint = _digest(
        [_source_identity(source) for source in canonical_sources]
    )
    policy_fingerprint = _digest(asdict(policy))
    workspace_prompt_hash = sha256((workspace_prompt or "").encode("utf-8")).hexdigest()
    prompt_sources = tuple(
        PromptSource(
            marker=source.marker,
            filename=source.filename,
            page=source.page,
            text=source.text,
            section=source.section,
        )
        for source in canonical_sources
    )
    rendered_prefix = f"{stable_policy_prefix}\n\n{render_data_blocks(prompt_sources)}"
    snapshot_identity: dict[str, object] = {
        "format": "ragz-cag-snapshot-v1",
        "mode": mode,
        "authorization": authorization_fingerprint,
        "sources": source_manifest_fingerprint,
        "stable_policy_hash": sha256(stable_policy_prefix.encode("utf-8")).hexdigest(),
        "workspace_prompt_hash": workspace_prompt_hash,
        "policy": policy_fingerprint,
        "rendered_prefix_token_count": rendered_prefix_token_count,
    }
    snapshot = CagSnapshot(
        snapshot_id=_digest(snapshot_identity),
        mode=mode,
        org_id=context.org_id,
        workspace_id=context.workspace_id,
        sources=canonical_sources,
        rendered_prefix=rendered_prefix,
        token_count=rendered_prefix_token_count,
        visibility_scope=visibility_scope,
        authorization_fingerprint=authorization_fingerprint,
        source_manifest_fingerprint=source_manifest_fingerprint,
        policy_fingerprint=policy_fingerprint,
        workspace_prompt_hash=workspace_prompt_hash,
    )
    return SnapshotDecision(eligible=True, reason=None, snapshot=snapshot)


def validate_snapshot(
    snapshot: CagSnapshot,
    *,
    context: SnapshotContext,
    sources: tuple[CagSource, ...],
    stable_policy_prefix: str,
    workspace_prompt: str | None,
    policy: SnapshotPolicy,
    rendered_prefix_token_count: int,
) -> SnapshotValidation:
    """Rebuild from fresh authoritative state and reject every mismatch."""
    current = build_snapshot(
        mode=snapshot.mode,
        context=context,
        sources=sources,
        stable_policy_prefix=stable_policy_prefix,
        workspace_prompt=workspace_prompt,
        policy=policy,
        rendered_prefix_token_count=rendered_prefix_token_count,
    )
    if not current.eligible:
        return SnapshotValidation(valid=False, reason=current.reason)
    if current.snapshot is None or current.snapshot.snapshot_id != snapshot.snapshot_id:
        return SnapshotValidation(valid=False, reason="snapshot_state_changed")
    return SnapshotValidation(valid=True, reason=None)
