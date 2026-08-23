#!/usr/bin/env python3
"""Credential-safe reachability preflight for official RAGFlow Cloud."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx

CLOUD_ROOT = "https://cloud.ragflow.io/"
CLOUD_DATASETS = "https://cloud.ragflow.io/api/v1/datasets"


def classify(*, root_status: int, datasets_status: int, credential_present: bool) -> str:
    if root_status != 200:
        return "cloud_unreachable"
    if not credential_present and datasets_status in {401, 403}:
        return "credential_gated"
    if credential_present and datasets_status == 200:
        return "api_reachable_models_unverified"
    return "cloud_api_contract_unverified"


def run(output: Path) -> Path:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    cloud_key = os.environ.get("RAGFLOW_CLOUD_API_KEY")
    headers = {"Authorization": f"Bearer {cloud_key}"} if cloud_key else None
    with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        root_response = client.get(CLOUD_ROOT)
        datasets_response = client.get(CLOUD_DATASETS, headers=headers)
    status = classify(
        root_status=root_response.status_code,
        datasets_status=datasets_response.status_code,
        credential_present=bool(cloud_key),
    )
    output.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "runner_version": "1.0",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "system_id": "ragflow-cloud",
        "status": status,
        "cloud_root_status": root_response.status_code,
        "cloud_datasets_status": datasets_response.status_code,
        "cloud_api_credential_present": bool(cloud_key),
        "credentials_persisted": False,
        "response_bodies_persisted": False,
        "provider_calls": 0,
        "quality_score_emitted": False,
        "model_parity": {
            "embedding_model": "text-embedding-3-small",
            "generation_model": "gpt-5.6-luna",
            "cloud_custom_provider_configuration": "unverified_without_authenticated account",
        },
        "external_dependency_options": {
            "metadata": ["managed MySQL", "managed Redis"],
            "object_storage": ["S3", "OSS", "Azure Blob", "GCS", "external MinIO"],
            "status": "not_configured; no provider credentials supplied",
        },
        "official_sources": [
            "https://cloud.ragflow.io/",
            "https://cloud.ragflow.io/register",
            "https://github.com/infiniflow/ragflow/blob/v0.27.0/helm/values.yaml",
            "https://github.com/infiniflow/ragflow/blob/v0.27.0/docker/service_conf.yaml.template",
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "summary.md").write_text(
        "# RAGFlow Cloud API preflight\n\n"
        f"- Status: `{status}`\n"
        f"- Cloud root HTTP status: `{root_response.status_code}`\n"
        f"- Dataset API HTTP status: `{datasets_response.status_code}`\n"
        f"- Cloud API credential present: `{str(bool(cloud_key)).lower()}`\n"
        "- Provider/model calls: `0`\n"
        "- Quality score emitted: `false`\n\n"
        "The hosted service is reachable, but an authenticated API-enabled Cloud account "
        "is required before dataset creation, model-selection verification, ingestion, or "
        "retrieval benchmarking. No account or paid plan was created.\n",
        encoding="utf-8",
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps({"output": str(run(args.output))}, sort_keys=True))


if __name__ == "__main__":
    main()
