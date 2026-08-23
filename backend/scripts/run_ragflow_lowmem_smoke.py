#!/usr/bin/env python3
"""Run a guarded, low-memory RAGFlow v0.27 container smoke test.

This runner deliberately does not benchmark answer quality.  It starts only the
RAGFlow application and the dependency closure declared by the pinned Compose
file, samples host/container pressure, and records enough evidence to explain an
early stop.  Local model services (TEI, deepdoc, rerankers, and embedding model
containers) are rejected rather than silently started.

The runner never invokes destructive project teardown or volume deletion.  An
emergency stop is scoped to the caller-provided Compose project and uses the
Compose stop operation only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

RAGFLOW_VERSION = "v0.27.0"
RAGFLOW_COMMIT = "ec9c08d809f63ba2815090182fa225899d2437d5"
RAGFLOW_REPOSITORY = "https://github.com/infiniflow/ragflow"
DEFAULT_MEMORY_LIMIT_BYTES = 3_000_000_000
DEFAULT_HOST_MIN_AVAILABLE_BYTES = 512 * 1024**2
DEFAULT_MAX_SWAP_GROWTH_BYTES = 512 * 1024**2
DEFAULT_MAX_PSI_AVG10 = 20.0
DEFAULT_SAMPLE_INTERVAL_SECONDS = 5.0
DEFAULT_CONTAINER_PORT = 80
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
FORBIDDEN_SERVICE_TERMS = ("tei", "deepdoc", "rerank", "embedding")
APP_SERVICE_NAMES = ("ragflow-cpu", "ragflow", "ragflow-server", "ragflow_server")
DOC_ENGINE_SERVICES = {"elasticsearch": "es01", "infinity": "infinity"}
EMPTY_COMPOSE_OVERRIDE = "services: {}\n"
PORT_TARGETS = {
    "ragflow-cpu": (80, 443, 9380, 9381, 9382, 9384, 9383),
    "ragflow": (80, 443, 9380, 9381, 9382, 9384, 9383),
    "ragflow-server": (80, 443, 9380, 9381, 9382, 9384, 9383),
    "ragflow_server": (80, 443, 9380, 9381, 9382, 9384, 9383),
    "mysql": (3306,),
    "minio": (9000, 9001),
    "redis": (6379,),
    "es01": (9200,),
    "infinity": (23817, 23820, 5432),
}


class SmokeError(RuntimeError):
    """Expected preflight or smoke failure which should be persisted safely."""


@dataclass(frozen=True)
class Thresholds:
    host_min_available_bytes: int = DEFAULT_HOST_MIN_AVAILABLE_BYTES
    max_swap_growth_bytes: int = DEFAULT_MAX_SWAP_GROWTH_BYTES
    max_psi_avg10: float = DEFAULT_MAX_PSI_AVG10
    max_container_memory_ratio: float = 0.95
    max_oom_kills: int = 0
    max_restarts: int = 0


@dataclass(frozen=True)
class ComposeSpec:
    checkout: Path
    compose_file: Path
    override_file: Path
    project: str
    env_file: Path | None
    host_port: int
    container_port: int
    memory_limit_bytes: int
    doc_engine: str = "elasticsearch"
    docker_host: str | None = None


@dataclass(frozen=True)
class HostSample:
    timestamp_utc: str
    mem_available_bytes: int | None
    swap_total_bytes: int | None
    swap_free_bytes: int | None
    swap_used_bytes: int | None
    psi_memory_some_avg10: float | None
    psi_memory_full_avg10: float | None


@dataclass(frozen=True)
class ContainerSample:
    name: str
    status: str | None
    memory_used_bytes: int | None
    memory_limit_bytes: int | None
    memory_ratio: float | None
    oom_killed: bool | None
    restart_count: int | None


@dataclass(frozen=True)
class Sample:
    sequence: int
    timestamp_utc: str
    host: HostSample
    containers: tuple[ContainerSample, ...]
    swap_baseline_used_bytes: int | None = None
    swap_growth_bytes: int | None = None


CommandRunner = Callable[[Sequence[str], Path | None], str]


def validate_project(project: str) -> str:
    if not PROJECT_RE.fullmatch(project):
        raise ValueError(
            "project must be 1-63 chars of lowercase letters, digits, '_' or '-'; "
            "pass a dedicated project such as ragflow-smoke-20260823"
        )
    return project


def validate_docker_host(docker_host: str | None) -> str | None:
    if docker_host is None:
        return None
    if not docker_host or any(char.isspace() for char in docker_host) or "@" in docker_host:
        raise ValueError(
            "docker host must be a non-secret endpoint without whitespace or credentials"
        )
    return docker_host


def validate_external_env_file(env_file: Path | None) -> None:
    """Reject active local-model selection while allowing inert official variables."""
    if env_file is None:
        return
    if not env_file.is_file():
        raise SmokeError("the explicit Compose env file does not exist")
    forbidden_terms = (*FORBIDDEN_SERVICE_TERMS, "gpu")
    truthy = {"1", "true", "yes", "on", "enabled"}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip().upper()
        value = stripped.split("=", 1)[1].strip().strip('"').strip("'")
        normalized = value.lower()
        if key == "COMPOSE_PROFILES":
            profiles = {item.strip() for item in normalized.split(",")}
            if any(
                any(term in profile for term in forbidden_terms) for profile in profiles
            ):
                raise SmokeError("env file enables a forbidden local-model profile")
        elif key == "DEVICE" and normalized == "gpu":
            raise SmokeError("env file enables the GPU device")
        elif key.endswith("_PROFILE") and any(
            term in normalized for term in forbidden_terms
        ):
            raise SmokeError(f"env file enables a forbidden profile through {key}")
        elif (
            ("ENABLE" in key or key.endswith("_ENABLED"))
            and any(term in key for term in FORBIDDEN_SERVICE_TERMS + ("LOCAL",))
            and normalized in truthy
        ):
            raise SmokeError(f"env file enables a local model through {key}")


def assert_port_available(port: int) -> None:
    """Fail before Compose if the dedicated loopback port is already occupied."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise SmokeError(f"dedicated host port {port} is unavailable") from exc


def compose_base_args(spec: ComposeSpec) -> list[str]:
    """Return only non-secret Compose global arguments in deterministic order."""
    return _compose_project_args(spec, include_override=True)


def _compose_project_args(spec: ComposeSpec, *, include_override: bool) -> list[str]:
    """Build project-scoped Compose arguments.

    The preflight project snapshot intentionally omits the generated override:
    it must run before the runner writes anything into the result directory.
    """
    args = ["docker"]
    if spec.docker_host is not None:
        args.extend(("--host", validate_docker_host(spec.docker_host) or ""))
    args.extend(
        [
            "compose",
            "--project-name",
            validate_project(spec.project),
            "--file",
            str(spec.compose_file),
        ]
    )
    if include_override:
        args.extend(("--file", str(spec.override_file)))
    if spec.env_file is not None:
        args.extend(("--env-file", str(spec.env_file)))
    # Explicit profiles prevent a caller's default profile selection from
    # pulling in GPU/TEI/deepdoc services.  The service list passed to ``up``
    # remains the authoritative runtime closure.
    doc_engine = spec.doc_engine
    if doc_engine not in DOC_ENGINE_SERVICES:
        raise ValueError(f"unsupported document engine: {doc_engine}")
    args.extend(("--profile", "cpu", "--profile", "mysql"))
    args.extend(("--profile", doc_engine))
    return args


def compose_command(spec: ComposeSpec, *subcommand: str) -> list[str]:
    if not subcommand:
        raise ValueError("a Compose subcommand is required")
    return [*compose_base_args(spec), *subcommand]


def build_project_snapshot_command(spec: ComposeSpec) -> list[str]:
    """List all containers owned by this Compose project before any writes."""
    return [*_compose_project_args(spec, include_override=False), "ps", "--all", "-q"]


def parse_project_container_ids(text: str) -> tuple[str, ...]:
    """Parse the machine-readable IDs returned by ``compose ps --all -q``."""
    lines = tuple(line.strip() for line in text.splitlines() if line.strip())
    invalid = tuple(line for line in lines if not re.fullmatch(r"[0-9a-fA-F]{12,64}", line))
    if invalid:
        raise SmokeError(
            "docker compose ps --all -q returned an unexpected container identifier"
        )
    return lines


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _generated_file_provenance(
    path: Path, *, runtime_mount_path: str | None = None
) -> dict[str, Any]:
    """Describe a generated file without persisting a host-specific path.

    ``path`` is used only to read the file.  The manifest records its output
    directory-relative name and content hash, while ``runtime_mount_path``
    makes the container-side bind mount explicit for Infinity.
    """
    return {
        "path": path.name,
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
        "runtime_mount_path": runtime_mount_path,
    }


def build_config_command(spec: ComposeSpec) -> list[str]:
    return compose_command(spec, "config", "--format", "json")


def build_dependency_start_command(spec: ComposeSpec, services: Sequence[str]) -> list[str]:
    if not services:
        raise ValueError("dependency start requires at least one service")
    return compose_command(spec, "up", "--detach", "--wait", *services)


def build_app_start_command(spec: ComposeSpec, app_service: str) -> list[str]:
    if not app_service or _forbidden_service(app_service):
        raise ValueError(f"refusing forbidden app service: {app_service!r}")
    return compose_command(spec, "up", "--detach", "--wait", app_service)


def build_stop_command(spec: ComposeSpec) -> list[str]:
    """Stop only this project; intentionally no destructive teardown."""
    return compose_command(spec, "stop")


def docker_command(spec: ComposeSpec, *arguments: str) -> list[str]:
    command = ["docker"]
    if spec.docker_host is not None:
        command.extend(("--host", validate_docker_host(spec.docker_host) or ""))
    command.extend(arguments)
    return command


def _daemon_info(runner: CommandRunner, spec: ComposeSpec) -> dict[str, Any]:
    text = runner(
        docker_command(spec, "info", "--format", "{{json .}}"),
        spec.checkout,
    )
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SmokeError("docker info did not return valid JSON") from exc
    if not isinstance(raw, Mapping):
        raise SmokeError("docker info JSON was not an object")
    public = {
        key: raw.get(key)
        for key in ("ID", "Name", "ServerVersion", "OperatingSystem", "KernelVersion")
    }
    fingerprint = hashlib.sha256(
        json.dumps(public, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    memory = raw.get("MemTotal")
    cpus = raw.get("NCPU")
    return {
        "endpoint": spec.docker_host or "current-context",
        "fingerprint_sha256": fingerprint,
        "memory_bytes": int(memory) if memory is not None else None,
        "cpus": int(cpus) if cpus is not None else None,
    }


def _default_command_runner(args: Sequence[str], cwd: Path | None = None) -> str:
    executable = shutil.which(args[0])
    if executable is None:
        raise SmokeError(f"{args[0]} executable not found")
    try:
        result = subprocess.run(  # noqa: S603
            [executable, *args[1:]],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()[:500]
        raise SmokeError(f"command failed ({args[0]}): {detail}") from exc
    return result.stdout.strip()


def validate_checkout(
    checkout: Path, runner: CommandRunner = _default_command_runner
) -> dict[str, str]:
    checkout = checkout.resolve()
    if not checkout.is_dir() or not (checkout / ".git").exists():
        raise SmokeError("RAGFlow checkout must be an existing Git checkout")
    commit = runner(["git", "rev-parse", "HEAD"], checkout).strip()
    tag = runner(["git", "describe", "--tags", "--exact-match"], checkout).strip()
    dirty = runner(["git", "status", "--porcelain"], checkout).strip()
    if commit != RAGFLOW_COMMIT or tag != RAGFLOW_VERSION or dirty:
        raise SmokeError("checkout is not the clean pinned RAGFlow v0.27.0 release")
    compose_file = checkout / "docker" / "docker-compose.yml"
    if not compose_file.exists():
        compose_file = checkout / "docker" / "docker-compose.yaml"
    if not compose_file.exists():
        raise SmokeError("pinned checkout has no docker/docker-compose.yml")
    return {"version": tag, "commit": commit}


def _service_memory_limits(
    spec: ComposeSpec, app_service: str, selected: Sequence[str]
) -> dict[str, int]:
    """Allocate the caller's low-memory budget across every selected service."""
    doc_service = DOC_ENGINE_SERVICES[spec.doc_engine]
    weights = {
        app_service: 0.46,
        doc_service: 0.31,
        "mysql": 0.15,
        "minio": 0.05,
        "redis": 0.03,
    }
    result: dict[str, int] = {}
    for name in selected:
        weight = weights.get(name, 0.05)
        result[name] = max(64 * 1024**2, int(spec.memory_limit_bytes * weight))
    return result


def _port_environment(selected: Sequence[str], host_port: int) -> dict[str, int]:
    env_names = {
        "ragflow-cpu": (
            "SVR_WEB_HTTP_PORT",
            "SVR_WEB_HTTPS_PORT",
            "SVR_HTTP_PORT",
            "ADMIN_SVR_HTTP_PORT",
            "SVR_MCP_PORT",
            "GO_HTTP_PORT",
            "GO_ADMIN_PORT",
        ),
        "ragflow": (
            "SVR_WEB_HTTP_PORT",
            "SVR_WEB_HTTPS_PORT",
            "SVR_HTTP_PORT",
            "ADMIN_SVR_HTTP_PORT",
            "SVR_MCP_PORT",
            "GO_HTTP_PORT",
            "GO_ADMIN_PORT",
        ),
        "ragflow-server": (
            "SVR_WEB_HTTP_PORT",
            "SVR_WEB_HTTPS_PORT",
            "SVR_HTTP_PORT",
            "ADMIN_SVR_HTTP_PORT",
            "SVR_MCP_PORT",
            "GO_HTTP_PORT",
            "GO_ADMIN_PORT",
        ),
        "ragflow_server": (
            "SVR_WEB_HTTP_PORT",
            "SVR_WEB_HTTPS_PORT",
            "SVR_HTTP_PORT",
            "ADMIN_SVR_HTTP_PORT",
            "SVR_MCP_PORT",
            "GO_HTTP_PORT",
            "GO_ADMIN_PORT",
        ),
        "mysql": ("EXPOSE_MYSQL_PORT",),
        "minio": ("MINIO_PORT", "MINIO_CONSOLE_PORT"),
        "redis": ("REDIS_PORT",),
        "es01": ("ES_PORT",),
        "infinity": ("INFINITY_THRIFT_PORT", "INFINITY_HTTP_PORT", "INFINITY_PSQL_PORT"),
    }
    result: dict[str, int] = {}
    next_port = host_port
    for service in selected:
        for name in env_names.get(service, ()):
            result[name] = next_port
            next_port += 1
    return result


def _yaml_scalar(value: object) -> str:
    return json.dumps(str(value))


def make_override(
    spec: ComposeSpec,
    app_service: str,
    selected_services: Sequence[str] | None = None,
) -> str:
    """Create a credential-free override replacing ports and capping all services."""
    selected = tuple(selected_services or (app_service,))
    if app_service not in selected:
        raise ValueError("selected services must include the application")
    if spec.doc_engine not in DOC_ENGINE_SERVICES:
        raise ValueError(f"unsupported document engine: {spec.doc_engine}")
    ports = _port_environment(selected, spec.host_port)
    profiles = f"{spec.doc_engine},cpu,mysql,metadata-mysql"
    limits = _service_memory_limits(spec, app_service, selected)
    lines = ["services:"]
    for service in selected:
        lines.extend(
            [
                f"  {service}:",
                f"    mem_limit: {limits[service]}b",
                '    restart: "no"',
                "    environment:",
                f"      DOC_ENGINE: {_yaml_scalar(spec.doc_engine)}",
                "      DEVICE: \"cpu\"",
                "      METADATA_DB_PROFILE: \"mysql\"",
                f"      COMPOSE_PROFILES: {_yaml_scalar(profiles)}",
                f"      MEM_LIMIT: {_yaml_scalar(limits[service])}",
            ]
        )
        for env_name, value in ports.items():
            lines.append(f"      {env_name}: {value}")
        targets = PORT_TARGETS.get(service, ())
        if targets:
            # The values are allocated in service order above; consume only
            # this service's target count while preserving all internal ports.
            env_names_for_service = {
                "ragflow-cpu": (
                    "SVR_WEB_HTTP_PORT", "SVR_WEB_HTTPS_PORT", "SVR_HTTP_PORT",
                    "ADMIN_SVR_HTTP_PORT", "SVR_MCP_PORT", "GO_HTTP_PORT", "GO_ADMIN_PORT",
                ),
                "ragflow": (
                    "SVR_WEB_HTTP_PORT", "SVR_WEB_HTTPS_PORT", "SVR_HTTP_PORT",
                    "ADMIN_SVR_HTTP_PORT", "SVR_MCP_PORT", "GO_HTTP_PORT", "GO_ADMIN_PORT",
                ),
                "ragflow-server": (
                    "SVR_WEB_HTTP_PORT", "SVR_WEB_HTTPS_PORT", "SVR_HTTP_PORT",
                    "ADMIN_SVR_HTTP_PORT", "SVR_MCP_PORT", "GO_HTTP_PORT", "GO_ADMIN_PORT",
                ),
                "ragflow_server": (
                    "SVR_WEB_HTTP_PORT", "SVR_WEB_HTTPS_PORT", "SVR_HTTP_PORT",
                    "ADMIN_SVR_HTTP_PORT", "SVR_MCP_PORT", "GO_HTTP_PORT", "GO_ADMIN_PORT",
                ),
                "mysql": ("EXPOSE_MYSQL_PORT",),
                "minio": ("MINIO_PORT", "MINIO_CONSOLE_PORT"),
                "redis": ("REDIS_PORT",),
                "es01": ("ES_PORT",),
                "infinity": ("INFINITY_THRIFT_PORT", "INFINITY_HTTP_PORT", "INFINITY_PSQL_PORT"),
            }.get(service, ())
            lines.append("    ports: !override")
            for env_name, target in zip(env_names_for_service, targets, strict=True):
                lines.append(f'      - "127.0.0.1:{ports[env_name]}:{target}"')
        if service == "infinity":
            infinity_config = spec.override_file.parent / "infinity.lowmem.toml"
            lines.extend(
                [
                    "    volumes: !override",
                    f'      - "{infinity_config}:/infinity_conf.toml:ro"',
                ]
            )
    return "\n".join(lines) + "\n"


def write_infinity_config(path: Path) -> None:
    path.write_text(
        "[general]\nversion = \"0.7.3\"\ntime_zone = \"utc-8\"\n\n"
        "[network]\nserver_address = \"0.0.0.0\"\npostgres_port = 5432\n"
        "http_port = 23820\nclient_port = 23817\nconnection_pool_size = 16\n\n"
        "[log]\nlog_to_stdout = true\nlog_level = \"warning\"\n\n"
        "[storage]\npersistence_dir = \"/var/infinity/persistence\"\n"
        "data_dir = \"/var/infinity/data\"\noptimize_interval = \"60s\"\n"
        "cleanup_interval = \"300s\"\ncompact_interval = \"600s\"\n"
        "storage_type = \"local\"\nmem_index_capacity = 8192\n\n"
        "[buffer]\nbuffer_manager_size = \"512MB\"\nlru_num = 3\n"
        "temp_dir = \"/var/infinity/tmp\"\nresult_cache = \"off\"\n"
        "memindex_memory_quota = \"128MB\"\n\n[wal]\nwal_dir = \"/var/infinity/wal\""
        "\n\n[resource]\n",
        encoding="utf-8",
    )


def _forbidden_service(name: str) -> bool:
    lowered = name.lower()
    return any(term in lowered for term in FORBIDDEN_SERVICE_TERMS)


def _service_dependencies(raw: object) -> tuple[str, ...]:
    if isinstance(raw, Mapping):
        return tuple(str(item) for item in raw)
    if isinstance(raw, list):
        return tuple(str(item) for item in raw)
    return ()


def select_service_closure(
    config: Mapping[str, Any], doc_engine: str = "elasticsearch"
) -> tuple[str, tuple[str, ...]]:
    """Choose the explicit RAGFlow runtime closure, rejecting local models."""
    services_obj = config.get("services")
    if not isinstance(services_obj, Mapping):
        raise SmokeError("docker compose config did not contain a services object")
    services = {str(name): value for name, value in services_obj.items()}
    app = next((name for name in APP_SERVICE_NAMES if name in services), None)
    if app is None:
        raise SmokeError("compose config has no recognized RAGFlow application service")
    doc_service = DOC_ENGINE_SERVICES.get(doc_engine)
    if doc_service is None:
        raise SmokeError(f"unsupported document engine: {doc_engine}")
    required_roots = (app, "mysql", "minio", "redis", doc_service)

    closure: set[str] = set()
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name in closure:
            return
        if name in visiting:
            raise SmokeError(f"cycle in required Compose dependencies at {name}")
        if _forbidden_service(name):
            raise SmokeError(f"RAGFlow app depends on forbidden local-model service {name}")
        service = services.get(name)
        if not isinstance(service, Mapping):
            raise SmokeError(f"compose dependency {name!r} is missing")
        visiting.add(name)
        for dependency in _service_dependencies(service.get("depends_on")):
            if dependency not in services:
                raise SmokeError(f"compose dependency {dependency!r} is missing")
            visit(dependency)
        visiting.remove(name)
        closure.add(name)

    for root in required_roots:
        visit(root)

    ordered: list[str] = []

    def order(name: str) -> None:
        service = services[name]
        if isinstance(service, Mapping):
            for dependency in _service_dependencies(service.get("depends_on")):
                if dependency in closure:
                    order(dependency)
        if name not in ordered:
            ordered.append(name)

    for root in required_roots:
        order(root)
    dependencies = tuple(name for name in ordered if name != app)
    return app, dependencies


def _parse_meminfo(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, separator, rest = line.partition(":")
        if not separator:
            continue
        fields = rest.split()
        if not fields:
            continue
        try:
            value = int(fields[0])
        except ValueError:
            continue
        unit = fields[1].lower() if len(fields) > 1 else "b"
        # Linux exposes /proc/meminfo in KiB despite spelling the unit ``kB``.
        multiplier = 1024 if unit == "kb" else _UNIT_MULTIPLIERS.get(unit, 1)
        values[key] = value * multiplier
    return values


def _parse_psi(text: str) -> tuple[float | None, float | None]:
    values: dict[str, float] = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        for field in fields[1:]:
            key, separator, value = field.partition("=")
            if separator and key == "avg10":
                try:
                    values[fields[0]] = float(value)
                except ValueError:
                    pass
    return values.get("some"), values.get("full")


def sample_host(
    *,
    meminfo_text: str | None = None,
    psi_text: str | None = None,
    timestamp_utc: str | None = None,
) -> HostSample:
    if meminfo_text is None:
        meminfo_text = Path("/proc/meminfo").read_text(encoding="utf-8")
    if psi_text is None:
        psi_path = Path("/proc/pressure/memory")
        psi_text = psi_path.read_text(encoding="utf-8") if psi_path.exists() else ""
    values = _parse_meminfo(meminfo_text)
    swap_total = values.get("SwapTotal")
    swap_free = values.get("SwapFree")
    swap_used = (
        max(0, swap_total - swap_free)
        if swap_total is not None and swap_free is not None
        else None
    )
    some, full = _parse_psi(psi_text)
    return HostSample(
        timestamp_utc=timestamp_utc or datetime.now(UTC).isoformat(),
        mem_available_bytes=values.get("MemAvailable"),
        swap_total_bytes=swap_total,
        swap_free_bytes=swap_free,
        swap_used_bytes=swap_used,
        psi_memory_some_avg10=some,
        psi_memory_full_avg10=full,
    )


_UNIT_MULTIPLIERS = {
    "b": 1,
    "kb": 1000,
    "kib": 1024,
    "mb": 1000**2,
    "mib": 1024**2,
    "gb": 1000**3,
    "gib": 1024**3,
}


def parse_byte_count(value: str) -> int:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]+)\s*", value)
    if match is None:
        raise ValueError(f"invalid byte count: {value!r}")
    return int(float(match.group(1)) * _UNIT_MULTIPLIERS[match.group(2).lower()])


def parse_stats_memory(value: str) -> tuple[int, int]:
    used, separator, limit = value.partition("/")
    if not separator:
        raise ValueError(f"invalid Docker memory usage: {value!r}")
    return parse_byte_count(used), parse_byte_count(limit)


def parse_container_samples(
    *, inspect_rows: Iterable[Mapping[str, Any]], stats_rows: Iterable[Mapping[str, Any]]
) -> tuple[ContainerSample, ...]:
    stats: dict[str, tuple[int, int]] = {}
    for row in stats_rows:
        name = str(row.get("Name") or row.get("name") or "")
        usage = str(row.get("MemUsage") or row.get("mem_usage") or "")
        if name and usage:
            try:
                stats[name] = parse_stats_memory(usage)
            except (KeyError, ValueError):
                continue
    samples: list[ContainerSample] = []
    for row in inspect_rows:
        name = str(row.get("Name") or "").lstrip("/")
        state = row.get("State")
        host_config = row.get("HostConfig")
        if not isinstance(state, Mapping):
            state = {}
        if not isinstance(host_config, Mapping):
            host_config = {}
        used, limit = stats.get(name, (None, None))
        samples.append(
            ContainerSample(
                name=name,
                status=str(state.get("Status")) if state.get("Status") is not None else None,
                memory_used_bytes=used,
                memory_limit_bytes=limit,
                memory_ratio=(used / limit if used is not None and limit else None),
                oom_killed=(
                    bool(state.get("OOMKilled")) if "OOMKilled" in state else None
                ),
                restart_count=(
                    int(state.get("RestartCount", 0))
                    if state.get("RestartCount") is not None
                    else None
                ),
            )
        )
    return tuple(samples)


def threshold_failures(
    sample: Sample,
    thresholds: Thresholds,
    baseline_swap_used_bytes: int | None = None,
) -> list[str]:
    failures: list[str] = []
    host = sample.host
    if (
        host.mem_available_bytes is not None
        and host.mem_available_bytes < thresholds.host_min_available_bytes
    ):
        failures.append("host_mem_available_below_floor")
    baseline = (
        baseline_swap_used_bytes
        if baseline_swap_used_bytes is not None
        else sample.swap_baseline_used_bytes
    )
    current_swap = host.swap_used_bytes
    if baseline is not None and current_swap is not None:
        growth = current_swap - baseline
        if growth > thresholds.max_swap_growth_bytes:
            failures.append("swap_growth_above_ceiling")
    for label, value in (
        ("memory_some_psi_avg10", host.psi_memory_some_avg10),
        ("memory_full_psi_avg10", host.psi_memory_full_avg10),
    ):
        if value is not None and value > thresholds.max_psi_avg10:
            failures.append(f"{label}_above_ceiling")
    oom_kills = 0
    for container in sample.containers:
        if (
            container.memory_ratio is not None
            and container.memory_ratio > thresholds.max_container_memory_ratio
        ):
            failures.append(f"container_memory_ratio_above_ceiling:{container.name}")
        if container.oom_killed:
            oom_kills += 1
        if (
            container.restart_count is not None
            and container.restart_count > thresholds.max_restarts
        ):
            failures.append(f"container_restarts_above_ceiling:{container.name}")
    if oom_kills > thresholds.max_oom_kills:
        failures.append("container_oom_kills_above_ceiling")
    return failures


def _safe_json_write(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_jsonl(file: TextIO, value: Mapping[str, Any]) -> None:
    file.write(json.dumps(value, sort_keys=True) + "\n")
    file.flush()


def _compose_json(runner: CommandRunner, spec: ComposeSpec) -> Mapping[str, Any]:
    text = runner(build_config_command(spec), spec.checkout)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SmokeError("docker compose config did not return valid JSON") from exc
    if not isinstance(value, Mapping):
        raise SmokeError("docker compose config JSON was not an object")
    return value


def _service_image(config: Mapping[str, Any], service_name: str) -> str:
    services = config.get("services")
    if not isinstance(services, Mapping):
        raise SmokeError("docker compose config did not contain a services object")
    service = services.get(service_name)
    if not isinstance(service, Mapping):
        raise SmokeError(f"compose service {service_name!r} is missing")
    image = service.get("image")
    if not isinstance(image, str) or not image.strip():
        raise SmokeError(
            f"compose service {service_name!r} has no resolved image for provenance"
        )
    return image.strip()


def _parse_image_inspect(text: str) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SmokeError("docker image inspect did not return valid JSON") from exc
        if isinstance(value, list):
            values = value
        else:
            values = [value]
        for item in values:
            if not isinstance(item, Mapping):
                raise SmokeError("docker image inspect JSON contained a non-object")
            rows.append(item)
    if not rows:
        raise SmokeError("docker image inspect returned no image metadata")
    return tuple(rows)


def _image_digest(row: Mapping[str, Any]) -> str | None:
    direct = row.get("Digest")
    if isinstance(direct, str) and direct:
        return direct
    descriptor = row.get("Descriptor")
    if isinstance(descriptor, Mapping):
        digest = descriptor.get("digest")
        if isinstance(digest, str) and digest:
            return digest
    repo_digests = row.get("RepoDigests")
    if isinstance(repo_digests, list):
        for value in repo_digests:
            if isinstance(value, str) and "@" in value:
                return value.rsplit("@", 1)[1]
    return None


def _image_provenance(
    runner: CommandRunner,
    spec: ComposeSpec,
    config: Mapping[str, Any],
    *,
    app_service: str,
    dependencies: Sequence[str],
) -> list[dict[str, Any]]:
    """Resolve every image that will execute, before Compose starts anything."""
    document_service = DOC_ENGINE_SERVICES[spec.doc_engine]
    service_roles: list[tuple[str, str]] = [("app", app_service)]
    service_roles.append(("document", document_service))
    service_roles.extend(
        ("dependency", name)
        for name in dependencies
        if name != document_service
    )

    images = [_service_image(config, service) for _, service in service_roles]
    unique_images = tuple(dict.fromkeys(images))
    inspect_text = runner(
        docker_command(
            spec,
            "image",
            "inspect",
            "--format",
            "{{json .}}",
            *unique_images,
        ),
        spec.checkout,
    )
    inspected = _parse_image_inspect(inspect_text)
    if len(inspected) != len(unique_images):
        raise SmokeError(
            "docker image inspect returned metadata for a different number of images"
        )
    by_image = dict(zip(unique_images, inspected, strict=True))

    provenance: list[dict[str, Any]] = []
    for role, service in service_roles:
        image = _service_image(config, service)
        row = by_image[image]
        raw_id = row.get("Id") or row.get("ID")
        image_id = str(raw_id) if raw_id is not None else None
        raw_size = row.get("Size")
        try:
            size_bytes = int(raw_size) if raw_size is not None else None
        except (TypeError, ValueError) as exc:
            raise SmokeError(f"docker image inspect returned invalid size for {image!r}") from exc
        repo_digests = row.get("RepoDigests")
        digest_values = (
            [str(value) for value in repo_digests if isinstance(value, str)]
            if isinstance(repo_digests, list)
            else []
        )
        provenance.append(
            {
                "role": role,
                "service": service,
                "image": image,
                "name": image,
                "id": image_id,
                "image_id": image_id,
                "digest": _image_digest(row),
                "repo_digests": digest_values,
                "size_bytes": size_bytes,
            }
        )
    return provenance


def _container_snapshot(
    runner: CommandRunner, spec: ComposeSpec
) -> tuple[ContainerSample, ...]:
    ids_text = runner(compose_command(spec, "ps", "--all", "-q"), spec.checkout)
    ids = [item for item in ids_text.splitlines() if re.fullmatch(r"[0-9a-fA-F]{12,64}", item)]
    if not ids:
        return ()
    inspect_text = runner(
        docker_command(spec, "inspect", "--format", "{{json .}}", *ids),
        spec.checkout,
    )
    rows: list[Mapping[str, Any]] = []
    for line in inspect_text.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            rows.append(value)
    stats_rows: list[Mapping[str, Any]] = []
    running_ids = [
        str(row["Id"])
        for row in rows
        if row.get("Id") and isinstance(row.get("State"), Mapping)
        and row["State"].get("Status") == "running"
    ]
    if running_ids:
        stats_text = runner(
            [
                *docker_command(
                    spec,
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{json .}}",
                    *running_ids,
                ),
            ],
            spec.checkout,
        )
        for line in stats_text.splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, Mapping):
                stats_rows.append(value)
    return parse_container_samples(inspect_rows=rows, stats_rows=stats_rows)


def sample(
    *,
    sequence: int,
    runner: CommandRunner,
    spec: ComposeSpec,
    baseline_swap_used_bytes: int | None = None,
) -> Sample:
    host = sample_host()
    containers = _container_snapshot(runner, spec)
    return Sample(
        sequence=sequence,
        timestamp_utc=host.timestamp_utc,
        host=host,
        containers=containers,
        swap_baseline_used_bytes=baseline_swap_used_bytes,
        swap_growth_bytes=(
            host.swap_used_bytes - baseline_swap_used_bytes
            if host.swap_used_bytes is not None and baseline_swap_used_bytes is not None
            else None
        ),
    )


def run(
    *,
    checkout: Path,
    output: Path,
    project: str,
    env_file: Path | None = None,
    docker_host: str | None = None,
    doc_engine: str = "elasticsearch",
    host_port: int = 18080,
    container_port: int = DEFAULT_CONTAINER_PORT,
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
    duration_seconds: float = 30.0,
    sample_interval_seconds: float = DEFAULT_SAMPLE_INTERVAL_SECONDS,
    thresholds: Thresholds | None = None,
    runner: CommandRunner = _default_command_runner,
    sleep: Callable[[float], None] = time.sleep,
    port_checker: Callable[[int], None] = assert_port_available,
) -> Path:
    """Run the guarded smoke and persist manifest, samples, and failure evidence."""
    output = output.resolve()
    thresholds = thresholds or Thresholds()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    if duration_seconds <= 0 or sample_interval_seconds <= 0:
        raise ValueError("duration and sample interval must be positive")
    validate_project(project)
    validate_docker_host(docker_host)
    validate_external_env_file(env_file)
    if doc_engine not in DOC_ENGINE_SERVICES:
        raise ValueError(f"unsupported document engine: {doc_engine}")
    if not 1024 <= host_port <= 65520 or not 1 <= container_port <= 65535:
        raise ValueError("host port must be between 1024 and 65520; container port 1-65535")
    if memory_limit_bytes <= 0:
        raise ValueError("memory limit must be positive")

    identity = validate_checkout(checkout, runner)
    compose_file = checkout / "docker" / "docker-compose.yml"
    if not compose_file.exists():
        compose_file = checkout / "docker" / "docker-compose.yaml"
    spec = ComposeSpec(
        checkout=checkout.resolve(),
        compose_file=compose_file.resolve(),
        override_file=(output / "compose.lowmem.override.yml").resolve(),
        project=project,
        env_file=env_file.resolve() if env_file is not None else None,
        host_port=host_port,
        container_port=container_port,
        memory_limit_bytes=memory_limit_bytes,
        doc_engine=doc_engine,
        docker_host=docker_host,
    )
    # This must be the first Docker operation and must happen before creating
    # the result directory or generated Compose override.  A non-empty project
    # is unsafe to touch by default because ``stop`` is project-scoped.
    preflight_container_ids = parse_project_container_ids(
        runner(build_project_snapshot_command(spec), spec.checkout)
    )
    project_collision = bool(preflight_container_ids)

    output.mkdir(parents=True)
    baseline_host = sample_host()
    baseline_swap_used_bytes = baseline_host.swap_used_bytes
    app_service = "unknown"
    samples_path = output / "samples.jsonl"
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "runner_version": "1.0",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "system_id": "ragflow",
        "version": identity["version"],
        "commit": identity["commit"],
        "repository": RAGFLOW_REPOSITORY,
        "run_kind": "low_memory_smoke",
        "status": "starting",
        "classification": "smoke_only",
        "benchmark_eligible": False,
        "benchmark_eligibility_reasons": [
            "smoke_has_no_corpus_quality_measurement",
            "smoke_does_not_compare_embedding_dimensions",
            "smoke_does_not_measure_rag_stage_latency",
        ],
        "model_mode": "external_api_only",
        "document_engine": doc_engine,
        "docker_daemon": {
            "endpoint": docker_host or "current-context",
            "fingerprint_sha256": None,
            "memory_bytes": None,
            "cpus": None,
        },
        "local_model_services_started": False,
        "provider_calls": 0,
        "credentials_persisted": False,
        "response_bodies_persisted": False,
        "stack_left_running": None,
        "compose_project": project,
        "preflight_existing_container_ids": list(preflight_container_ids),
        "host_port": host_port,
        "memory_limit_bytes": memory_limit_bytes,
        "thresholds": asdict(thresholds),
        "swap_guard": {
            "mode": "relative_growth",
            "baseline_swap_used_bytes": baseline_swap_used_bytes,
            "max_growth_bytes": thresholds.max_swap_growth_bytes,
        },
        "samples_file": samples_path.name,
    }
    if project_collision:
        failure = {
            "status": "failed",
            "stage": "preflight",
            "error_type": "ComposeProjectCollision",
            "error": (
                f"Compose project {project!r} already owns containers; "
                "use a new dedicated project name; project reuse is refused"
            ),
            "compose_project": project,
            "existing_container_ids": list(preflight_container_ids),
            "provider_calls": 0,
            "credentials_persisted": False,
            "stop_scope": "not_started",
        }
        _safe_json_write(output / "failure.json", failure)
        manifest["status"] = "failed"
        manifest["stack_started"] = False
        manifest["stack_left_running"] = None
        _safe_json_write(output / "manifest.json", manifest)
        raise SmokeError(failure["error"])

    _safe_json_write(output / "manifest.json", manifest)
    # Keep the first config merge inert: the service name is discovered from
    # the checkout, so a placeholder must not accidentally add a second app.
    (output / "compose.lowmem.override.yml").write_text(
        EMPTY_COMPOSE_OVERRIDE, encoding="utf-8"
    )

    project_touched = False
    try:
        port_checker(host_port)
        daemon = _daemon_info(runner, spec)
        manifest["docker_daemon"] = daemon
        _safe_json_write(output / "manifest.json", manifest)
        config = _compose_json(runner, spec)
        app_service, dependencies = select_service_closure(config, doc_engine)
        selected_services = (*dependencies, app_service)
        spec_override = make_override(spec, app_service, selected_services)
        spec.override_file.write_text(spec_override, encoding="utf-8")
        generated_files: dict[str, Any] = {
            "compose_override": _generated_file_provenance(spec.override_file)
        }
        if doc_engine == "infinity":
            infinity_config = output / "infinity.lowmem.toml"
            write_infinity_config(infinity_config)
            generated_files["infinity_config"] = _generated_file_provenance(
                infinity_config, runtime_mount_path="/infinity_conf.toml"
            )
        image_provenance = _image_provenance(
            runner,
            spec,
            config,
            app_service=app_service,
            dependencies=dependencies,
        )
        manifest["app_service"] = app_service
        manifest["dependency_services"] = list(dependencies)
        manifest["document_engine"] = doc_engine
        manifest["selected_services"] = list(selected_services)
        manifest["generated_files"] = generated_files
        manifest["image_provenance"] = image_provenance
        _safe_json_write(output / "manifest.json", manifest)

        # The project must remain empty after config generation as well as at
        # initial preflight.  This closes the race in which another Compose
        # invocation creates a container before this runner's first ``up``.
        prestart_container_ids = parse_project_container_ids(
            runner(build_project_snapshot_command(spec), spec.checkout)
        )
        if prestart_container_ids:
            raise SmokeError(
                f"Compose project {project!r} acquired containers before start; "
                "project reuse is refused"
            )
        project_touched = True
        runner(build_dependency_start_command(spec, dependencies), spec.checkout)
        runner(build_app_start_command(spec, app_service), spec.checkout)
        manifest["status"] = "running"
        manifest["stack_started"] = True
        manifest["stack_left_running"] = True
        _safe_json_write(output / "manifest.json", manifest)

        deadline = time.monotonic() + duration_seconds
        with samples_path.open("w", encoding="utf-8") as samples_file:
            sequence = 0
            while True:
                current = sample(
                    sequence=sequence,
                    runner=runner,
                    spec=spec,
                    baseline_swap_used_bytes=baseline_swap_used_bytes,
                )
                _append_jsonl(samples_file, asdict(current))
                failures = threshold_failures(
                    current,
                    thresholds,
                    baseline_swap_used_bytes=baseline_swap_used_bytes,
                )
                if failures:
                    runner(build_stop_command(spec), spec.checkout)
                    failure = {
                        "status": "aborted_threshold",
                        "stage": "sampling",
                        "error_type": "ResourceThresholdExceeded",
                        "failures": failures,
                        "sample_sequence": sequence,
                        "compose_project": project,
                        "swap_baseline_used_bytes": baseline_swap_used_bytes,
                        "swap_current_used_bytes": current.host.swap_used_bytes,
                        "swap_growth_bytes": current.swap_growth_bytes,
                        "provider_calls": 0,
                        "credentials_persisted": False,
                        "stop_scope": "compose_project_only",
                    }
                    _safe_json_write(output / "failure.json", failure)
                    manifest["status"] = "aborted_threshold"
                    manifest["stack_left_running"] = False
                    _safe_json_write(output / "manifest.json", manifest)
                    return output
                if time.monotonic() >= deadline:
                    break
                sequence += 1
                sleep(min(sample_interval_seconds, max(0.0, deadline - time.monotonic())))
        manifest["status"] = "smoke_passed"
        _safe_json_write(output / "manifest.json", manifest)
        return output
    except Exception as exc:
        stop_error_type: str | None = None
        stop_succeeded = False
        if project_touched:
            try:
                runner(build_stop_command(spec), spec.checkout)
                stop_succeeded = True
            except Exception as stop_error:
                stop_error_type = type(stop_error).__name__
        failure = {
            "status": "failed",
            "stage": "runtime",
            "error_type": type(exc).__name__,
            "compose_project": project,
            "provider_calls": 0,
            "credentials_persisted": False,
            "stop_scope": "compose_project_only" if project_touched else "not_started",
            "stop_error_type": stop_error_type,
        }
        _safe_json_write(output / "failure.json", failure)
        manifest["status"] = "failed"
        manifest["stack_left_running"] = False if stop_succeeded else None
        _safe_json_write(output / "manifest.json", manifest)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--docker-host",
        help="optional Docker daemon endpoint, e.g. unix:///var/run/docker.sock",
    )
    parser.add_argument(
        "--doc-engine",
        choices=tuple(DOC_ENGINE_SERVICES),
        default="elasticsearch",
        help="RAGFlow document engine service to include in the explicit runtime closure",
    )
    parser.add_argument("--host-port", type=int, default=18080)
    parser.add_argument("--container-port", type=int, default=DEFAULT_CONTAINER_PORT)
    parser.add_argument("--memory-limit-bytes", type=int, default=DEFAULT_MEMORY_LIMIT_BYTES)
    parser.add_argument("--duration-seconds", type=float, default=30.0)
    parser.add_argument(
        "--sample-interval-seconds", type=float, default=DEFAULT_SAMPLE_INTERVAL_SECONDS
    )
    parser.add_argument(
        "--host-min-available-bytes", type=int, default=DEFAULT_HOST_MIN_AVAILABLE_BYTES
    )
    parser.add_argument(
        "--max-swap-growth-bytes",
        type=int,
        default=DEFAULT_MAX_SWAP_GROWTH_BYTES,
        help="abort only when swap usage grows this many bytes beyond the pre-start baseline",
    )
    parser.add_argument("--max-psi-avg10", type=float, default=DEFAULT_MAX_PSI_AVG10)
    parser.add_argument("--max-container-memory-ratio", type=float, default=0.95)
    parser.add_argument("--max-oom-kills", type=int, default=0)
    parser.add_argument("--max-restarts", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        result = run(
            checkout=args.checkout,
            output=args.output,
            project=args.project,
            env_file=args.env_file,
            docker_host=args.docker_host,
            doc_engine=args.doc_engine,
            host_port=args.host_port,
            container_port=args.container_port,
            memory_limit_bytes=args.memory_limit_bytes,
            duration_seconds=args.duration_seconds,
            sample_interval_seconds=args.sample_interval_seconds,
            thresholds=Thresholds(
                host_min_available_bytes=args.host_min_available_bytes,
                max_swap_growth_bytes=args.max_swap_growth_bytes,
                max_psi_avg10=args.max_psi_avg10,
                max_container_memory_ratio=args.max_container_memory_ratio,
                max_oom_kills=args.max_oom_kills,
                max_restarts=args.max_restarts,
            ),
        )
    except (SmokeError, FileExistsError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"output": str(result)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
