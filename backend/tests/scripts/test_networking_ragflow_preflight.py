import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_networking_ragflow_preflight import (  # noqa: E402
    COMPOSE_CONTAINER_MEMORY_LIMIT_BYTES,
    MIN_DISK_BYTES,
    MIN_EFFECTIVE_MEMORY_BYTES,
    MIN_VM_MAX_MAP_COUNT,
    eligibility,
)


def test_ragflow_requires_official_host_and_stack_resources() -> None:
    gated = eligibility(
        cpus=22,
        docker_memory_bytes=4 * 1000**3,
        host_memory_bytes=MIN_EFFECTIVE_MEMORY_BYTES,
        host_disk_bytes=MIN_DISK_BYTES,
        host_vm_max_map_count=MIN_VM_MAX_MAP_COUNT,
        daemon_disk_bytes=None,
        daemon_vm_max_map_count=None,
    )
    assert gated["eligible"] is False
    assert gated["failed_requirements"] == [
        "effective_runtime_memory",
        "docker_disk_unverified",
        "docker_vm.max_map_count_unverified",
    ]
    assert gated["effective_memory_deficit_bytes"] == (
        MIN_EFFECTIVE_MEMORY_BYTES - 4 * 1000**3
    )
    assert (
        gated["compose_container_memory_limit_bytes"]
        == COMPOSE_CONTAINER_MEMORY_LIMIT_BYTES
    )

    eligible = eligibility(
        cpus=4,
        docker_memory_bytes=MIN_EFFECTIVE_MEMORY_BYTES,
        host_memory_bytes=MIN_EFFECTIVE_MEMORY_BYTES,
        host_disk_bytes=MIN_DISK_BYTES,
        host_vm_max_map_count=MIN_VM_MAX_MAP_COUNT,
        daemon_disk_bytes=MIN_DISK_BYTES,
        daemon_vm_max_map_count=MIN_VM_MAX_MAP_COUNT,
    )
    assert eligible["eligible"] is True
    assert eligible["failed_requirements"] == []
