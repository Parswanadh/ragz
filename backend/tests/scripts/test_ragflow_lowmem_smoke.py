import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_ragflow_lowmem_smoke import (  # noqa: E402
    EMPTY_COMPOSE_OVERRIDE,
    ComposeSpec,
    HostSample,
    Sample,
    Thresholds,
    build_app_start_command,
    build_project_snapshot_command,
    build_stop_command,
    compose_base_args,
    docker_command,
    make_override,
    parse_container_samples,
    parse_project_container_ids,
    sample_host,
    select_service_closure,
    threshold_failures,
    validate_docker_host,
    validate_external_env_file,
    validate_project,
)


def test_inert_compose_override_keeps_services_a_mapping() -> None:
    assert EMPTY_COMPOSE_OVERRIDE == "services: {}\n"


def _spec(tmp_path: Path) -> ComposeSpec:
    return ComposeSpec(
        checkout=tmp_path,
        compose_file=tmp_path / "docker-compose.yml",
        override_file=tmp_path / "override.yml",
        project="ragflow-smoke-test",
        env_file=tmp_path / "provider.env",
        host_port=18080,
        container_port=80,
        memory_limit_bytes=3_000_000_000,
    )


def test_compose_commands_are_project_scoped_and_never_down_or_volumes(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    args = compose_base_args(spec)
    assert args[:3] == ["docker", "compose", "--project-name"]
    assert "provider.env" in " ".join(args)
    app = build_app_start_command(spec, "ragflow")
    stop = build_stop_command(spec)
    assert app[-4:] == ["up", "--detach", "--wait", "ragflow"]
    assert stop[-1] == "stop"
    assert "down" not in stop
    assert "-v" not in stop


def test_explicit_docker_host_is_carried_by_compose_and_docker_commands(tmp_path: Path) -> None:
    spec = replace(_spec(tmp_path), docker_host="unix:///var/run/docker.sock")
    compose = compose_base_args(spec)
    assert compose[:5] == [
        "docker",
        "--host",
        "unix:///var/run/docker.sock",
        "compose",
        "--project-name",
    ]
    assert docker_command(spec, "info", "--format", "{{json .}}")[:3] == [
        "docker",
        "--host",
        "unix:///var/run/docker.sock",
    ]
    with pytest.raises(ValueError):
        validate_docker_host("tcp://user:secret@example.invalid:2375")


def test_project_snapshot_is_read_only_and_omits_generated_override(tmp_path: Path) -> None:
    command = build_project_snapshot_command(_spec(tmp_path))
    assert command[-3:] == ["ps", "--all", "-q"]
    assert str(tmp_path / "override.yml") not in command
    assert parse_project_container_ids("") == ()
    assert parse_project_container_ids("0123456789abcdef\n") == (
        "0123456789abcdef",
    )
    with pytest.raises(RuntimeError, match="unexpected container"):
        parse_project_container_ids("warning from compose\n")


def test_project_name_rejects_shell_metacharacters() -> None:
    assert validate_project("ragflow-smoke-20260823") == "ragflow-smoke-20260823"
    with pytest.raises(ValueError):
        validate_project("ragflow-smoke;docker-down")
    with pytest.raises(ValueError):
        validate_project("RAGFLOW")


def test_official_inert_local_model_variables_are_allowed_but_enablement_is_not(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "official.env"
    env_file.write_text(
        "TEI_IMAGE_CPU=infiniflow/text-embeddings-inference:cpu-1.8\n"
        "TEI_MODEL=Qwen/Qwen3-Embedding-0.6B\n"
        "DEEPDOC_IMAGE=deepdoc_oss:latest\n"
        "COMPOSE_PROFILES=infinity,cpu,metadata-mysql\n"
        "DEVICE=cpu\n",
        encoding="utf-8",
    )
    validate_external_env_file(env_file)

    for value in ("tei-cpu,cpu", "deepdoc,cpu", "gpu,cpu"):
        env_file.write_text(f"COMPOSE_PROFILES={value}\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="profile"):
            validate_external_env_file(env_file)
    env_file.write_text("DEVICE=gpu\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="GPU"):
        validate_external_env_file(env_file)


def test_override_uses_non_conflicting_loopback_port_and_app_memory_limit(
    tmp_path: Path,
) -> None:
    override = make_override(_spec(tmp_path), "ragflow-server")
    assert "mem_limit: 1380000000b" in override
    assert '127.0.0.1:18080:80' in override
    assert "password" not in override.lower()


def test_three_gb_budget_gives_mysql_startup_headroom(tmp_path: Path) -> None:
    override = make_override(
        _spec(tmp_path),
        "ragflow-cpu",
        ("mysql", "minio", "redis", "es01", "ragflow-cpu"),
    )

    assert "mem_limit: 450000000b" in override
    assert "mem_limit: 930000000b" in override


def test_service_selection_starts_only_dependency_closure_and_rejects_local_models() -> None:
    config = {
        "services": {
            "mysql": {},
            "minio": {},
            "redis": {},
            "es01": {"profiles": ["elasticsearch"]},
            "tei": {},
            "deepdoc": {"profiles": ["deepdoc"]},
            "ragflow-cpu": {
                "profiles": ["cpu"],
                "depends_on": {"mysql": {"condition": "service_healthy"}},
            },
        }
    }
    app, dependencies = select_service_closure(config, "elasticsearch")
    assert app == "ragflow-cpu"
    assert dependencies == ("mysql", "minio", "redis", "es01")
    config["services"]["ragflow-cpu"]["depends_on"]["tei"] = {}
    with pytest.raises(RuntimeError, match="forbidden local-model"):
        select_service_closure(config, "elasticsearch")


def test_actual_runtime_override_replaces_ports_and_caps_every_selected_service(
    tmp_path: Path,
) -> None:
    spec = _spec(tmp_path)
    selected = ("mysql", "minio", "redis", "es01", "ragflow-cpu")
    override = make_override(spec, "ragflow-cpu", selected)
    assert "ports: !override" in override
    assert override.count('restart: "no"') == len(selected)
    assert override.count("mem_limit:") == len(selected)
    for port_name in (
        "SVR_WEB_HTTP_PORT",
        "SVR_WEB_HTTPS_PORT",
        "SVR_HTTP_PORT",
        "ADMIN_SVR_HTTP_PORT",
        "SVR_MCP_PORT",
        "GO_HTTP_PORT",
        "GO_ADMIN_PORT",
        "EXPOSE_MYSQL_PORT",
        "MINIO_PORT",
        "MINIO_CONSOLE_PORT",
        "REDIS_PORT",
        "ES_PORT",
    ):
        assert f"{port_name}:" in override
    assert "COMPOSE_PROFILES" in override
    assert "tei" not in override.lower()


def test_infinity_override_uses_reduced_config_and_replaces_mount(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    spec = replace(spec, doc_engine="infinity")
    override = make_override(
        spec,
        "ragflow-cpu",
        ("mysql", "minio", "redis", "infinity", "ragflow-cpu"),
    )
    assert "volumes: !override" in override
    assert "infinity.lowmem.toml:/infinity_conf.toml:ro" in override


def test_low_memory_infinity_config_keeps_required_resource_section(
    tmp_path: Path,
) -> None:
    from run_ragflow_lowmem_smoke import write_infinity_config

    path = tmp_path / "infinity.lowmem.toml"
    write_infinity_config(path)

    assert "[resource]" in path.read_text(encoding="utf-8")


def test_host_sample_parses_memavailable_swap_and_psi() -> None:
    sample = sample_host(
        meminfo_text="MemAvailable: 1024 kB\nSwapTotal: 2 MB\nSwapFree: 1 MB\n",
        psi_text="some avg10=12.50 avg60=1.00 avg300=0.10 total=4\n"
        "full avg10=0.25 avg60=0.00 avg300=0.00 total=1\n",
        timestamp_utc="2026-08-23T00:00:00+00:00",
    )
    assert sample.mem_available_bytes == 1024 * 1024
    assert sample.swap_used_bytes == 1_000_000
    assert sample.psi_memory_some_avg10 == 12.5
    assert sample.psi_memory_full_avg10 == 0.25


def test_container_sampling_and_resource_thresholds_are_atomic() -> None:
    containers = parse_container_samples(
        inspect_rows=[
            {
                "Id": "0123456789abcdef0123456789abcdef",
                "Name": "/ragflow-smoke-ragflow-1",
                "State": {"Status": "running", "OOMKilled": True, "RestartCount": 2},
            }
        ],
        stats_rows=[
            {"Name": "ragflow-smoke-ragflow-1", "MemUsage": "2.9GiB / 3GiB"}
        ],
    )
    assert containers[0].memory_ratio == pytest.approx(2.9 / 3)
    assert containers[0].oom_killed is True
    assert containers[0].restart_count == 2
    host = HostSample(
        timestamp_utc="2026-08-23T00:00:00+00:00",
        mem_available_bytes=100,
        swap_total_bytes=10,
        swap_free_bytes=0,
        swap_used_bytes=10,
        psi_memory_some_avg10=30,
        psi_memory_full_avg10=0,
    )
    failures = threshold_failures(
        Sample(
            0,
            host.timestamp_utc,
            host,
            containers,
            swap_baseline_used_bytes=0,
            swap_growth_bytes=10,
        ),
        Thresholds(
            host_min_available_bytes=200,
            max_swap_growth_bytes=5,
            max_psi_avg10=20,
        ),
    )
    assert "host_mem_available_below_floor" in failures
    assert "swap_growth_above_ceiling" in failures
    assert "memory_some_psi_avg10_above_ceiling" in failures
    assert "container_oom_kills_above_ceiling" in failures
    assert "container_restarts_above_ceiling:ragflow-smoke-ragflow-1" in failures


def test_high_preexisting_swap_is_allowed_when_usage_is_stable() -> None:
    host = HostSample(
        timestamp_utc="2026-08-23T00:00:00+00:00",
        mem_available_bytes=8 * 1024**3,
        swap_total_bytes=32 * 1024**3,
        swap_free_bytes=10 * 1024**3,
        swap_used_bytes=22 * 1024**3,
        psi_memory_some_avg10=0,
        psi_memory_full_avg10=0,
    )
    stable = Sample(
        0,
        host.timestamp_utc,
        host,
        (),
        swap_baseline_used_bytes=22 * 1024**3,
        swap_growth_bytes=0,
    )
    assert threshold_failures(stable, Thresholds(max_swap_growth_bytes=512 * 1024**2)) == []

    growing = Sample(
        1,
        host.timestamp_utc,
        replace(host, swap_used_bytes=23 * 1024**3),
        (),
        swap_baseline_used_bytes=22 * 1024**3,
        swap_growth_bytes=1024**3,
    )
    assert "swap_growth_above_ceiling" in threshold_failures(
        growing,
        Thresholds(max_swap_growth_bytes=512 * 1024**2),
    )


def test_smoke_run_persists_privacy_safe_manifest_and_samples(tmp_path: Path) -> None:
    checkout = tmp_path / "ragflow"
    (checkout / "docker").mkdir(parents=True)
    (checkout / ".git").mkdir()
    (checkout / "docker" / "docker-compose.yml").write_text("services: {}\n")
    output = tmp_path / "result"
    calls: list[list[str]] = []
    project_snapshot_count = 0

    def fake_runner(args: list[str] | tuple[str, ...], cwd: Path | None = None) -> str:
        nonlocal project_snapshot_count
        calls.append(list(args))
        if args[:2] == ["git", "rev-parse"]:
            return "ec9c08d809f63ba2815090182fa225899d2437d5\n"
        if args[:3] == ["git", "describe", "--tags"]:
            return "v0.27.0\n"
        if args[:3] == ["git", "status", "--porcelain"]:
            return ""
        if args[:2] == ["docker", "info"]:
            return json.dumps(
                {
                    "ID": "native-daemon-id",
                    "Name": "native",
                    "ServerVersion": "29.0.0",
                    "OperatingSystem": "Linux",
                    "KernelVersion": "6.8",
                    "MemTotal": 16_246_616_064,
                    "NCPU": 22,
                }
            )
        if "config" in args:
            return json.dumps(
                {
                        "services": {
                            "mysql": {"image": "mysql:8"},
                            "minio": {"image": "minio:latest"},
                            "redis": {"image": "redis:7"},
                            "es01": {"image": "elasticsearch:8"},
                            "ragflow-cpu": {
                                "image": "ragflow:cpu",
                                "depends_on": {"mysql": {}},
                            },
                        }
                    }
                )
        if "image" in args and "inspect" in args:
            return "\n".join(
                json.dumps(
                    {
                        "Id": f"sha256:{image.replace(':', '-')}",
                        "RepoDigests": [f"repo/{image.split(':')[0]}@sha256:{'a' * 64}"],
                        "Size": 123,
                    }
                )
                for image in args[args.index("{{json .}}") + 1 :]
            )
        if args[-3:] == ["ps", "--all", "-q"]:
            project_snapshot_count += 1
            return (
                "0123456789abcdef0123456789abcdef\n"
                if project_snapshot_count > 2
                else ""
            )
        if args[:3] == ["docker", "inspect", "--format"]:
            return json.dumps(
                {
                    "Name": "/ragflow-smoke-ragflow-1",
                    "Id": "0123456789abcdef0123456789abcdef",
                    "State": {"Status": "running", "OOMKilled": False, "RestartCount": 0},
                }
            )
        if args[:3] == ["docker", "stats", "--no-stream"]:
            return json.dumps(
                {"Name": "ragflow-smoke-ragflow-1", "MemUsage": "10MiB / 3GiB"}
            )
        return ""

    from run_ragflow_lowmem_smoke import run

    run(
        checkout=checkout,
        output=output,
        project="ragflow-smoke-test",
        duration_seconds=0.001,
        sample_interval_seconds=0.001,
        thresholds=Thresholds(
            host_min_available_bytes=0,
            max_swap_growth_bytes=10**18,
            max_psi_avg10=10**6,
        ),
        runner=fake_runner,
        sleep=lambda _seconds: None,
        port_checker=lambda _port: None,
    )
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "smoke_passed"
    assert manifest["stack_left_running"] is True
    assert manifest["classification"] == "smoke_only"
    assert manifest["benchmark_eligible"] is False
    assert manifest["provider_calls"] == 0
    assert manifest["credentials_persisted"] is False
    assert manifest["docker_daemon"]["memory_bytes"] == 16_246_616_064
    assert manifest["docker_daemon"]["cpus"] == 22
    assert manifest["preflight_existing_container_ids"] == []
    assert len(manifest["image_provenance"]) == 5
    assert manifest["image_provenance"][0]["image_id"].startswith("sha256:")
    assert manifest["generated_files"]["compose_override"]["path"] == (
        "compose.lowmem.override.yml"
    )
    assert len(manifest["generated_files"]["compose_override"]["sha256"]) == 64
    assert len(manifest["docker_daemon"]["fingerprint_sha256"]) == 64
    assert (output / "samples.jsonl").read_text().strip()
    assert not any("down" in " ".join(call) for call in calls)
    assert "-v" not in " ".join(" ".join(call) for call in calls)


def test_existing_project_refuses_before_any_write_or_stop(tmp_path: Path) -> None:
    checkout = tmp_path / "ragflow"
    (checkout / "docker").mkdir(parents=True)
    (checkout / ".git").mkdir()
    (checkout / "docker" / "docker-compose.yml").write_text("services: {}\n")
    output = tmp_path / "collision"
    calls: list[list[str]] = []

    def runner(args: list[str] | tuple[str, ...], cwd: Path | None = None) -> str:
        del cwd
        call = list(args)
        calls.append(call)
        if call[:2] == ["git", "rev-parse"]:
            return "ec9c08d809f63ba2815090182fa225899d2437d5\n"
        if call[:3] == ["git", "describe", "--tags"]:
            return "v0.27.0\n"
        if call[:3] == ["git", "status", "--porcelain"]:
            return ""
        if call[-3:] == ["ps", "--all", "-q"]:
            return "0123456789abcdef0123456789abcdef\n"
        raise AssertionError(f"unexpected Docker operation after collision: {call}")

    from run_ragflow_lowmem_smoke import run

    with pytest.raises(RuntimeError, match="already owns containers"):
        run(
            checkout=checkout,
            output=output,
            project="ragflow-collision",
            runner=runner,
        )

    assert not any(call[-1:] == ["stop"] for call in calls)
    assert not (output / "compose.lowmem.override.yml").exists()
    manifest = json.loads((output / "manifest.json").read_text())
    failure = json.loads((output / "failure.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["preflight_existing_container_ids"] == [
        "0123456789abcdef0123456789abcdef"
    ]
    assert failure["error_type"] == "ComposeProjectCollision"
    assert failure["stop_scope"] == "not_started"


def test_reuse_project_is_not_an_available_run_option(tmp_path: Path) -> None:
    checkout = tmp_path / "ragflow"
    (checkout / "docker").mkdir(parents=True)
    (checkout / ".git").mkdir()
    (checkout / "docker" / "docker-compose.yml").write_text("services: {}\n")
    output = tmp_path / "reuse"
    from run_ragflow_lowmem_smoke import run

    with pytest.raises(TypeError, match="reuse_project"):
        run(checkout=checkout, output=output, project="ragflow-reuse", reuse_project=True)


@pytest.mark.parametrize("fail_on_up", [1, 2], ids=["dependency-start", "app-start"])
def test_partial_start_failure_stops_touched_project(
    tmp_path: Path, fail_on_up: int
) -> None:
    checkout = tmp_path / "ragflow"
    (checkout / "docker").mkdir(parents=True)
    (checkout / ".git").mkdir()
    (checkout / "docker" / "docker-compose.yml").write_text("services: {}\n")
    output = tmp_path / "result"
    calls: list[list[str]] = []
    up_count = 0

    def failing_runner(args: list[str] | tuple[str, ...], cwd: Path | None = None) -> str:
        nonlocal up_count
        del cwd
        call = list(args)
        calls.append(call)
        if call[:2] == ["git", "rev-parse"]:
            return "ec9c08d809f63ba2815090182fa225899d2437d5\n"
        if call[:3] == ["git", "describe", "--tags"]:
            return "v0.27.0\n"
        if call[:3] == ["git", "status", "--porcelain"]:
            return ""
        if call[:2] == ["docker", "info"]:
            return json.dumps({"ID": "native", "MemTotal": 16_000_000_000, "NCPU": 8})
        if "config" in call:
            return json.dumps(
                {
                    "services": {
                        "mysql": {"image": "mysql:8"},
                        "minio": {"image": "minio:latest"},
                        "redis": {"image": "redis:7"},
                        "es01": {"image": "elasticsearch:8"},
                        "ragflow-cpu": {
                            "image": "ragflow:cpu",
                            "depends_on": {"mysql": {}},
                        },
                    }
                }
            )
        if "image" in call and "inspect" in call:
            return "\n".join(
                json.dumps(
                    {
                        "Id": f"sha256:{image.replace(':', '-')}",
                        "RepoDigests": [f"repo/{image.split(':')[0]}@sha256:{'a' * 64}"],
                        "Size": 123,
                    }
                )
                for image in call[call.index("{{json .}}") + 1 :]
            )
        if "up" in call:
            up_count += 1
            if up_count == fail_on_up:
                raise RuntimeError("simulated partial start failure")
        if call[-3:] == ["ps", "--all", "-q"]:
            return ""
        return ""

    from run_ragflow_lowmem_smoke import run

    with pytest.raises(RuntimeError, match="partial start"):
        run(
            checkout=checkout,
            output=output,
            project="ragflow-smoke-test",
            duration_seconds=0.001,
            runner=failing_runner,
            port_checker=lambda _port: None,
        )
    stop_calls = [call for call in calls if call[-1:] == ["stop"]]
    assert len(stop_calls) == 1
    assert "--project-name" in stop_calls[0]
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["stack_left_running"] is False
