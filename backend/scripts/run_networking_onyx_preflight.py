#!/usr/bin/env python3
"""Evidence-only Onyx v4.6.0 eligibility check for the networking corpus."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ONYX_VERSION = "v4.6.0"
ONYX_COMMIT = "b4553eb55ceb2c6a561c57892a528c65bd8626b1"
MIN_CPU = 4
MIN_MEMORY_BYTES = 10 * 1024**3
MIN_DISK_BYTES = 32 * 1024**3
OFFICIAL_SOURCE = "https://docs.onyx.app/deployment/getting_started/resourcing"


def eligibility(*, cpus: int, memory_bytes: int, disk_bytes: int) -> dict[str, object]:
    failures = []
    if cpus < MIN_CPU:
        failures.append("cpu")
    if memory_bytes < MIN_MEMORY_BYTES:
        failures.append("memory")
    if disk_bytes < MIN_DISK_BYTES:
        failures.append("disk")
    return {
        "eligible": not failures,
        "failed_requirements": failures,
        "measured": {
            "cpus": cpus,
            "memory_bytes": memory_bytes,
            "disk_bytes": disk_bytes,
        },
        "required": {
            "cpus": MIN_CPU,
            "memory_bytes": MIN_MEMORY_BYTES,
            "disk_bytes": MIN_DISK_BYTES,
        },
        "memory_deficit_bytes": max(0, MIN_MEMORY_BYTES - memory_bytes),
    }


def _docker_int(template: str) -> int:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker executable not found")
    result = subprocess.run(  # noqa: S603
        [docker, "info", "--format", template],
        check=True,
        capture_output=True,
        text=True,
    )
    return int(result.stdout.strip())


def run(output: Path) -> Path:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    cpus = _docker_int("{{.NCPU}}")
    memory = _docker_int("{{.MemTotal}}")
    disk = shutil.disk_usage(output.parent).free
    result = eligibility(cpus=cpus, memory_bytes=memory, disk_bytes=disk)
    status = "eligible_not_executed" if result["eligible"] else "resource_gated"
    manifest = {
        "schema_version": 1,
        "runner_version": "1.0",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "system_id": "onyx",
        "version": ONYX_VERSION,
        "commit": ONYX_COMMIT,
        "track": "standard-native-search-preflight",
        "status": status,
        "resource_evidence": result,
        "official_requirements_source": OFFICIAL_SOURCE,
        "onyx_lite_excluded": (
            "Lite omits the vector/keyword index and background indexing workers"
        ),
        "provider_calls": 0,
        "quality_score_emitted": False,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if status == "resource_gated":
        (output / "failure.json").write_text(
            json.dumps(
                {
                    "status": status,
                    "stage": "pre_deployment",
                    "error_type": "InsufficientOfficialResources",
                    "failed_requirements": result["failed_requirements"],
                    "quality_score_emitted": False,
                    "provider_calls": 0,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    report = (
        f"# Onyx {ONYX_VERSION} networking benchmark preflight\n\n"
        f"- Status: `{status}`\n"
        f"- Docker CPU: `{cpus}`; required: `{MIN_CPU}`\n"
        f"- Docker RAM: `{memory}` bytes; required: `{MIN_MEMORY_BYTES}` bytes\n"
        f"- Free disk: `{disk}` bytes; required: `{MIN_DISK_BYTES}` bytes\n"
        f"- Quality score emitted: `false`\n\n"
        "Onyx Lite is not substituted because it omits the vector/keyword index "
        "and indexing workers required for a RAG comparison.\n\n"
        f"Official guidance: <{OFFICIAL_SOURCE}>\n"
    )
    (output / "summary.md").write_text(report, encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps({"output": str(run(args.output))}, sort_keys=True))


if __name__ == "__main__":
    main()
