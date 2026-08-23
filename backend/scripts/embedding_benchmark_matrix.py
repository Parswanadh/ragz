#!/usr/bin/env python3
"""Deterministic OpenAI embedding dimension matrix and LiteLLM preflight.

The matrix is deliberately kept outside the retrieval implementation.  A cell
is one immutable ``(model, dimension)`` pair, represented to downstream
clients by a LiteLLM alias whose configuration fixes the provider-side width.
RAGFlow and AnythingLLM can therefore send only ``model`` and ``input`` and
cannot accidentally create a collection with a different vector width.

This module is safe to import in tests and exposes an injectable ``httpx``
transport.  It never writes credentials or provider response bodies.  Running
the module without ``--preflight``/``--probe`` only emits a local manifest and
does not make a network request.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

SCHEMA_VERSION = 1
RUNNER_VERSION = "1.0"
DEFAULT_BASE_URL = "http://127.0.0.1:54000"
PROBE_INPUT = "ragz synthetic width probe"
PROVIDER_KEY_ENV_NAMES = ("OPENAI_API_KEY", "OPENAI_EMBEDDING_API_KEY")

SMALL_MODEL = "text-embedding-3-small"
LARGE_MODEL = "text-embedding-3-large"
SUPPORTED_MODEL_DIMENSIONS: Mapping[str, tuple[int, ...]] = {
    SMALL_MODEL: (1024, 1280, 1536),
    LARGE_MODEL: (1024, 1280, 1536, 1792, 2048, 2096, 3072),
}


class EmbeddingMatrixError(RuntimeError):
    """Base class for safe, typed matrix and preflight failures."""


class InvalidEmbeddingCellError(EmbeddingMatrixError, ValueError):
    """The requested model and dimension are not an allowed matrix cell."""


class CredentialUnavailableError(EmbeddingMatrixError):
    """A required LiteLLM or OpenAI provider credential is unavailable."""


class LiteLLMAPIError(EmbeddingMatrixError):
    """LiteLLM returned an unusable status or response shape."""


class AliasConflictError(EmbeddingMatrixError):
    """An alias exists but does not have this cell's immutable configuration."""


class VectorWidthProbeError(EmbeddingMatrixError):
    """The alias did not return exactly one vector at the expected width."""

    def __init__(
        self,
        message: str,
        *,
        expected_dimension: int,
        actual_dimension: int | None,
        vector_count: int,
    ) -> None:
        super().__init__(message)
        self.expected_dimension = expected_dimension
        self.actual_dimension = actual_dimension
        self.vector_count = vector_count


@dataclass(frozen=True, slots=True)
class EmbeddingCell:
    """One valid provider model/width pair and its stable external names."""

    model: str
    dimension: int

    def __post_init__(self) -> None:
        allowed = SUPPORTED_MODEL_DIMENSIONS.get(self.model)
        if allowed is None or self.dimension not in allowed:
            raise InvalidEmbeddingCellError(
                f"unsupported embedding cell: model={self.model!r}, "
                f"dimension={self.dimension!r}"
            )

    @property
    def model_slug(self) -> str:
        return self.model.replace("/", "-")

    @property
    def cell_id(self) -> str:
        return f"openai-{self.model_slug}-d{self.dimension}"

    @property
    def alias(self) -> str:
        return f"ragz-{self.cell_id}"


@dataclass(frozen=True, slots=True)
class AliasAction:
    """Non-secret result of checking or creating one LiteLLM alias."""

    cell_id: str
    alias: str
    model: str
    dimension: int
    status: Literal["present", "created", "would_create"]
    proxy_calls: int


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Non-secret result of a one-vector alias width probe."""

    cell_id: str
    alias: str
    expected_dimension: int
    actual_dimension: int
    vector_count: int
    provider_calls: int = 1


def cells() -> tuple[EmbeddingCell, ...]:
    """Return all supported cells in stable model-then-dimension order."""

    return tuple(
        EmbeddingCell(model=model, dimension=dimension)
        for model, dimensions in SUPPORTED_MODEL_DIMENSIONS.items()
        for dimension in dimensions
    )


def cell_for(model: str, dimension: int) -> EmbeddingCell:
    """Validate and return one matrix cell."""

    return EmbeddingCell(model=model, dimension=dimension)


def _base_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("LiteLLM base URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("LiteLLM base URL must not contain credentials, query, or fragment")
    return value.rstrip("/")


def _master_key(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    key = source.get("RAGZ_LITELLM_MASTER_KEY") or source.get("LITELLM_MASTER_KEY")
    if not key:
        raise CredentialUnavailableError(
            "LiteLLM master key is unavailable; set RAGZ_LITELLM_MASTER_KEY"
        )
    return key


def _provider_key(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    for name in PROVIDER_KEY_ENV_NAMES:
        key = source.get(name)
        if key:
            return key
    names = " or ".join(PROVIDER_KEY_ENV_NAMES)
    raise CredentialUnavailableError(f"OpenAI provider key is unavailable; set {names}")


def _client(
    base_url: str,
    key: str,
    transport: httpx.BaseTransport | None,
) -> httpx.Client:
    return httpx.Client(
        base_url=_base_url(base_url),
        headers={"Authorization": f"Bearer {key}"},
        timeout=httpx.Timeout(30.0, connect=10.0),
        transport=transport,
    )


def _json_response(response: httpx.Response, operation: str) -> Any:
    if response.status_code < 200 or response.status_code >= 300:
        raise LiteLLMAPIError(f"LiteLLM {operation} failed with HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise LiteLLMAPIError(f"LiteLLM {operation} returned invalid JSON") from exc


def _alias_payload(cell: EmbeddingCell, provider_key: str) -> dict[str, object]:
    """Build the provider config that fixes width behind the alias."""

    return {
        "model_name": cell.alias,
        "litellm_params": {
            "model": f"openai/{cell.model}",
            "api_key": provider_key,
            "dimensions": cell.dimension,
        },
        "model_info": {
            "id": cell.cell_id,
            "ragz_cell_id": cell.cell_id,
            "ragz_dimension": cell.dimension,
            "ragz_underlying_model": cell.model,
        },
    }


def _model_info(response: httpx.Response) -> dict[str, Mapping[str, object]]:
    body = _json_response(response, "model info")
    if not isinstance(body, Mapping) or not isinstance(body.get("data"), list):
        raise LiteLLMAPIError("LiteLLM model info has an invalid response shape")
    result: dict[str, Mapping[str, object]] = {}
    for item in body["data"]:
        if not isinstance(item, Mapping):
            continue
        name = item.get("model_name") or item.get("model")
        if isinstance(name, str):
            result[name] = item
    return result


def _configured_pair(item: Mapping[str, object]) -> tuple[str | None, int | None]:
    params = item.get("litellm_params")
    if not isinstance(params, Mapping):
        params = {}
    model = params.get("model")
    model_value = model if isinstance(model, str) else None
    dimensions = params.get("dimensions")
    try:
        dimension_value = int(dimensions) if dimensions is not None else None
    except (TypeError, ValueError):
        dimension_value = None
    return model_value, dimension_value


def preflight_aliases(
    requested_cells: Sequence[EmbeddingCell],
    *,
    base_url: str = DEFAULT_BASE_URL,
    env: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    dry_run: bool = False,
) -> tuple[AliasAction, ...]:
    """Check/create aliases idempotently, never replacing a conflict.

    ``dry_run`` performs no HTTP request, including the model-info GET.  In a
    real preflight, the LiteLLM master key and OpenAI provider key are read
    only from the environment.  The provider key is sent to LiteLLM only when
    creating an alias, and is never returned, logged, or persisted here.
    """

    unique = tuple(requested_cells)
    if len({cell.alias for cell in unique}) != len(unique):
        raise ValueError("requested embedding cells contain duplicate aliases")
    if dry_run:
        return tuple(
            AliasAction(
                cell_id=cell.cell_id,
                alias=cell.alias,
                model=cell.model,
                dimension=cell.dimension,
                status="would_create",
                proxy_calls=0,
            )
            for cell in unique
        )
    key = _master_key(env)
    provider_key = _provider_key(env)
    with _client(base_url, key, transport) as client:
        existing = _model_info(client.get("/model/info"))
        actions: list[AliasAction] = []
        for cell in unique:
            current = existing.get(cell.alias)
            if current is not None:
                configured_model, configured_dimension = _configured_pair(current)
                expected_model = f"openai/{cell.model}"
                if configured_model != expected_model or configured_dimension != cell.dimension:
                    raise AliasConflictError(
                        f"LiteLLM alias {cell.alias!r} has a conflicting immutable configuration"
                    )
                actions.append(
                    AliasAction(
                        cell_id=cell.cell_id,
                        alias=cell.alias,
                        model=cell.model,
                        dimension=cell.dimension,
                        status="present",
                        proxy_calls=1,
                    )
                )
                continue
            create_body = _json_response(
                client.post("/model/new", json=_alias_payload(cell, provider_key)),
                "alias create",
            )
            if isinstance(create_body, Mapping):
                create_status = str(create_body.get("status", "")).lower()
                if create_status in {"error", "failed", "failure"}:
                    raise LiteLLMAPIError("LiteLLM alias create reported failure")
            actions.append(
                AliasAction(
                    cell_id=cell.cell_id,
                    alias=cell.alias,
                    model=cell.model,
                    dimension=cell.dimension,
                    status="created",
                    proxy_calls=2,
                )
            )
    return tuple(actions)


def probe_vector_width(
    cell: EmbeddingCell,
    *,
    base_url: str = DEFAULT_BASE_URL,
    env: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> ProbeResult:
    """Make one real alias embedding request and verify exactly one width."""

    key = _master_key(env)
    with _client(base_url, key, transport) as client:
        response = client.post(
            "/v1/embeddings",
            json={"model": cell.alias, "input": [PROBE_INPUT]},
        )
        body = _json_response(response, "embedding width probe")
    data = body.get("data") if isinstance(body, Mapping) else None
    if not isinstance(data, list):
        raise VectorWidthProbeError(
            "embedding width probe returned no vector data",
            expected_dimension=cell.dimension,
            actual_dimension=None,
            vector_count=0,
        )
    vector_count = len(data)
    if vector_count != 1 or not isinstance(data[0], Mapping):
        raise VectorWidthProbeError(
            f"embedding width probe expected one vector, got {vector_count}",
            expected_dimension=cell.dimension,
            actual_dimension=None,
            vector_count=vector_count,
        )
    vector = data[0].get("embedding")
    actual_dimension = len(vector) if isinstance(vector, list) else None
    if actual_dimension != cell.dimension:
        raise VectorWidthProbeError(
            f"embedding width probe expected {cell.dimension} dimensions, got "
            f"{actual_dimension if actual_dimension is not None else 'invalid vector'}",
            expected_dimension=cell.dimension,
            actual_dimension=actual_dimension,
            vector_count=vector_count,
        )
    return ProbeResult(
        cell_id=cell.cell_id,
        alias=cell.alias,
        expected_dimension=cell.dimension,
        actual_dimension=actual_dimension,
        vector_count=vector_count,
    )


def build_manifest(
    requested_cells: Sequence[EmbeddingCell],
    *,
    status: Literal[
        "planned",
        "dry_run",
        "alias_ready",
        "not_attested",
        "completed",
        "failed",
    ] = "planned",
    provider_calls: int = 0,
    proxy_calls: int = 0,
    alias_status: Mapping[str, str] | None = None,
    probe_status: Mapping[str, str] | None = None,
    actual_dimensions: Mapping[str, int] | None = None,
    proxy_fingerprint: str | None = None,
) -> dict[str, object]:
    """Build the privacy-safe manifest contract for a matrix run."""

    if proxy_fingerprint is not None and (
        len(proxy_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in proxy_fingerprint)
    ):
        raise ValueError("proxy fingerprint must be a lowercase SHA-256")
    aliases = alias_status or {}
    probes = probe_status or {}
    measured_dimensions = actual_dimensions or {}
    if status == "completed":
        if any(
            probes.get(cell.alias) != "passed"
            or measured_dimensions.get(cell.alias) != cell.dimension
            for cell in requested_cells
        ):
            raise ValueError("completed matrix requires a passing measured probe for every cell")
    default_probe_status = (
        "not_attested" if status in {"alias_ready", "not_attested"} else "not_run"
    )
    records = [
        {
            "cell_id": cell.cell_id,
            "alias": cell.alias,
            "model": cell.model,
            "dimension": cell.dimension,
            "provider": "openai",
            "embedding_proxy_fingerprint_sha256": proxy_fingerprint,
            "alias_status": aliases.get(cell.alias, "not_run"),
            "probe_status": probes.get(cell.alias, default_probe_status),
            "actual_dimension": measured_dimensions.get(cell.alias),
            "client_sends_dimensions": False,
        }
        for cell in requested_cells
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "runner_version": RUNNER_VERSION,
        "benchmark_kind": "openai-embedding-model-dimension-matrix",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": status,
        "cells": records,
        "alias_contract": {
            "fixed_dimensions_in_litellm": True,
            "client_sends_dimensions": False,
            "provider_key_source": "environment_only",
        },
        "provider_calls": provider_calls,
        "proxy_calls": proxy_calls,
        "embedding_proxy_fingerprint_sha256": proxy_fingerprint,
        "credentials_persisted": False,
        "probe_input_persisted": False,
        "response_bodies_persisted": False,
    }


def write_manifest(output: Path, manifest: Mapping[str, object]) -> Path:
    """Write ``manifest.json`` without overwriting an existing artifact."""

    output = output.resolve()
    if output.exists() and not output.is_dir():
        raise FileExistsError(f"output path is not a directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "manifest.json"
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite {destination}")
    destination.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("RAGZ_LITELLM_BASE_URL", DEFAULT_BASE_URL),
    )
    parser.add_argument("--preflight", action="store_true", help="check/create LiteLLM aliases")
    parser.add_argument("--probe", action="store_true", help="probe one vector width per alias")
    parser.add_argument(
        "--proxy-fingerprint",
        help="non-secret SHA-256 identity of the LiteLLM instance used by every cell",
    )
    parser.add_argument("--dry-run", action="store_true", help="emit a no-network planned manifest")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.dry_run and (args.preflight or args.probe):
        raise ValueError("--dry-run cannot be combined with provider actions")
    if (args.preflight or args.probe) and not args.proxy_fingerprint:
        raise ValueError("provider actions require --proxy-fingerprint")
    selected = cells()
    alias_results: tuple[AliasAction, ...] = ()
    probe_results: list[ProbeResult] = []
    status: Literal["planned", "dry_run", "alias_ready", "not_attested", "completed"] = (
        "planned"
    )
    if args.dry_run:
        alias_results = preflight_aliases(selected, dry_run=True)
        status = "dry_run"
    elif args.preflight:
        alias_results = preflight_aliases(selected, base_url=args.base_url)
        status = "alias_ready"
    probe_status: dict[str, str] = {}
    actual_dimensions: dict[str, int] = {}
    if args.probe:
        for cell in selected:
            try:
                result = probe_vector_width(cell, base_url=args.base_url)
            except VectorWidthProbeError:
                # Preserve a manifest proving that aliases may exist while
                # this provider width remains un-attested; never call it
                # completed.  Remaining cells are also left not_attested.
                probe_status[cell.alias] = "failed"
                status = "not_attested"
                break
            else:
                probe_results.append(result)
                probe_status[result.alias] = "passed"
                actual_dimensions[result.alias] = result.actual_dimension
        else:
            status = "completed"
    manifest = build_manifest(
        selected,
        status=status,
        provider_calls=sum(result.provider_calls for result in probe_results),
        proxy_calls=(
            (1 if alias_results else 0)
            + sum(action.status == "created" for action in alias_results)
        ),
        alias_status={action.alias: action.status for action in alias_results},
        probe_status=probe_status,
        actual_dimensions=actual_dimensions,
        proxy_fingerprint=args.proxy_fingerprint,
    )
    destination = write_manifest(args.output, manifest)
    print(json.dumps({"manifest": str(destination), "status": status}, sort_keys=True))


if __name__ == "__main__":
    main()
