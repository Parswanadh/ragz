#!/usr/bin/env python3
"""Evidence-only RAGFlow v0.27.0 eligibility check for the networking corpus."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

RAGFLOW_VERSION = "v0.27.0"
RAGFLOW_COMMIT = "ec9c08d809f63ba2815090182fa225899d2437d5"
RAGFLOW_REPOSITORY = "https://github.com/infiniflow/ragflow"
MIN_CPU = 4
MIN_EFFECTIVE_MEMORY_BYTES = 16 * 1000**3
COMPOSE_CONTAINER_MEMORY_LIMIT_BYTES = 8_073_741_824
MIN_DISK_BYTES = 50 * 1000**3
MIN_VM_MAX_MAP_COUNT = 262_144
OFFICIAL_SOURCE = f"{RAGFLOW_REPOSITORY}/blob/{RAGFLOW_VERSION}/docs/quickstart.mdx"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536
GENERATION_MODEL = "gpt-5.4-mini"


def eligibility(
    *,
    cpus: int,
    docker_memory_bytes: int,
    host_memory_bytes: int,
    host_disk_bytes: int,
    host_vm_max_map_count: int,
    daemon_disk_bytes: int | None,
    daemon_vm_max_map_count: int | None,
) -> dict[str, object]:
    failures: list[str] = []
    if cpus < MIN_CPU:
        failures.append("cpu")
    effective_memory = min(host_memory_bytes, docker_memory_bytes)
    if effective_memory < MIN_EFFECTIVE_MEMORY_BYTES:
        failures.append("effective_runtime_memory")
    if daemon_disk_bytes is None:
        failures.append("docker_disk_unverified")
    elif daemon_disk_bytes < MIN_DISK_BYTES:
        failures.append("docker_disk")
    if daemon_vm_max_map_count is None:
        failures.append("docker_vm.max_map_count_unverified")
    elif daemon_vm_max_map_count < MIN_VM_MAX_MAP_COUNT:
        failures.append("docker_vm.max_map_count")
    return {
        "eligible": not failures,
        "failed_requirements": failures,
        "measured": {
            "cpus": cpus,
            "docker_memory_bytes": docker_memory_bytes,
            "host_memory_bytes": host_memory_bytes,
            "effective_runtime_memory_bytes": effective_memory,
            "host_disk_bytes": host_disk_bytes,
            "host_vm_max_map_count": host_vm_max_map_count,
            "daemon_disk_bytes": daemon_disk_bytes,
            "daemon_vm_max_map_count": daemon_vm_max_map_count,
        },
        "required": {
            "cpus": MIN_CPU,
            "effective_runtime_memory_bytes": MIN_EFFECTIVE_MEMORY_BYTES,
            "daemon_disk_bytes": MIN_DISK_BYTES,
            "daemon_vm_max_map_count": MIN_VM_MAX_MAP_COUNT,
        },
        "effective_memory_deficit_bytes": max(
            0, MIN_EFFECTIVE_MEMORY_BYTES - effective_memory
        ),
        "compose_container_memory_limit_bytes": COMPOSE_CONTAINER_MEMORY_LIMIT_BYTES,
        "namespace_note": (
            "host disk/sysctl are contextual only; eligibility requires explicit "
            "Docker-daemon/VM measurements"
        ),
    }


def _command(args: list[str], *, cwd: Path | None = None) -> str:
    executable = shutil.which(args[0])
    if executable is None:
        raise RuntimeError(f"{args[0]} executable not found")
    result = subprocess.run(  # noqa: S603
        [executable, *args[1:]],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _docker_int(template: str) -> int:
    return int(_command(["docker", "info", "--format", template]))


def _host_memory_bytes() -> int:
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("MemTotal is missing from /proc/meminfo")


def validate_checkout(checkout: Path) -> dict[str, str]:
    checkout = checkout.resolve()
    if not (checkout / ".git").exists():
        raise RuntimeError("RAGFlow checkout is missing its .git directory")
    commit = _command(["git", "rev-parse", "HEAD"], cwd=checkout)
    tag = _command(["git", "describe", "--tags", "--exact-match"], cwd=checkout)
    dirty = _command(["git", "status", "--porcelain"], cwd=checkout)
    if commit != RAGFLOW_COMMIT or tag != RAGFLOW_VERSION or dirty:
        raise RuntimeError("RAGFlow checkout is not the clean pinned v0.27.0 release")
    catalog = (checkout / "conf" / "models" / "openai.json").read_text(
        encoding="utf-8"
    )
    if EMBEDDING_MODEL not in catalog or GENERATION_MODEL not in catalog:
        raise RuntimeError("pinned RAGFlow OpenAI catalog lacks the parity models")
    return {"version": tag, "commit": commit}


def run(
    *,
    checkout: Path,
    output: Path,
    daemon_disk_bytes: int | None = None,
    daemon_vm_max_map_count: int | None = None,
) -> Path:
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    identity = validate_checkout(checkout)
    output.mkdir(parents=True)
    cpus = _docker_int("{{.NCPU}}")
    docker_memory = _docker_int("{{.MemTotal}}")
    host_memory = _host_memory_bytes()
    host_disk = shutil.disk_usage(output.parent).free
    host_vm_max_map_count = int(_command(["sysctl", "-n", "vm.max_map_count"]))
    result = eligibility(
        cpus=cpus,
        docker_memory_bytes=docker_memory,
        host_memory_bytes=host_memory,
        host_disk_bytes=host_disk,
        host_vm_max_map_count=host_vm_max_map_count,
        daemon_disk_bytes=daemon_disk_bytes,
        daemon_vm_max_map_count=daemon_vm_max_map_count,
    )
    status = "eligible_not_executed" if result["eligible"] else "resource_gated"
    manifest = {
        "schema_version": 1,
        "runner_version": "1.0",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "system_id": "ragflow",
        "version": identity["version"],
        "commit": identity["commit"],
        "repository": RAGFLOW_REPOSITORY,
        "track": "native-docker-networking-preflight",
        "status": status,
        "resource_evidence": result,
        "official_requirements_source": OFFICIAL_SOURCE,
        "intended_model_parity": {
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dimension": EMBEDDING_DIMENSION,
            "generation_model": GENERATION_MODEL,
            "provider": "openai",
        },
        "multi_query_capabilities": {
            "ordinary_public_retrieval": "single_question",
            "advanced_agentic_implementation_available": True,
            "stable_public_multi_query_api": False,
            "benchmark_note": (
                "native advanced/agentic and adapter fan-out must be separate rows"
            ),
        },
        "provider_calls": 0,
        "quality_score_emitted": False,
        "stack_started": False,
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
                    "provider_calls": 0,
                    "quality_score_emitted": False,
                    "stack_started": False,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    (output / "summary.md").write_text(
        f"# RAGFlow {RAGFLOW_VERSION} networking benchmark preflight\n\n"
        f"- Status: `{status}`\n"
        f"- Pinned commit: `{RAGFLOW_COMMIT}`\n"
        f"- Docker CPU: `{cpus}`; required: `{MIN_CPU}`\n"
        f"- Host RAM: `{host_memory}` bytes\n"
        f"- Docker RAM: `{docker_memory}` bytes\n"
        f"- Effective runtime RAM: `{min(host_memory, docker_memory)}` bytes; official "
        f"requirement: `{MIN_EFFECTIVE_MEMORY_BYTES}` bytes\n"
        f"- Pinned Compose per-container MEM_LIMIT: "
        f"`{COMPOSE_CONTAINER_MEMORY_LIMIT_BYTES}` bytes (configuration, not the "
        "official host/daemon RAM floor)\n"
        f"- Host free disk: `{host_disk}` bytes; Docker-daemon disk: "
        f"`{daemon_disk_bytes if daemon_disk_bytes is not None else 'unverified'}`\n"
        f"- Host vm.max_map_count: `{host_vm_max_map_count}`; Docker-daemon/VM value: "
        f"`{daemon_vm_max_map_count if daemon_vm_max_map_count is not None else 'unverified'}`\n"
        f"- Intended embedding: `{EMBEDDING_MODEL}` / `{EMBEDDING_DIMENSION}`d\n"
        f"- Intended generation model: `{GENERATION_MODEL}`\n"
        "- Provider calls: `0`; quality score emitted: `false`\n\n"
        "The full stack is not started when an official resource requirement fails. "
        "Unavailable is not scored as zero.\n\n"
        f"Official guidance: <{OFFICIAL_SOURCE}>\n",
        encoding="utf-8",
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--daemon-disk-bytes", type=int)
    parser.add_argument("--daemon-vm-max-map-count", type=int)
    args = parser.parse_args()
    print(
        json.dumps(
            {
                "output": str(
                    run(
                        checkout=args.checkout,
                        output=args.output,
                        daemon_disk_bytes=args.daemon_disk_bytes,
                        daemon_vm_max_map_count=args.daemon_vm_max_map_count,
                    )
                )
            }
        )
    )


if __name__ == "__main__":
    main()
