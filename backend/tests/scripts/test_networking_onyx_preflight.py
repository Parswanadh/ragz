import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_networking_onyx_preflight import (  # noqa: E402
    MIN_DISK_BYTES,
    MIN_MEMORY_BYTES,
    eligibility,
)


def test_onyx_requires_all_official_resource_floors() -> None:
    gated = eligibility(cpus=22, memory_bytes=4 * 1024**3, disk_bytes=MIN_DISK_BYTES)
    assert gated["eligible"] is False
    assert gated["failed_requirements"] == ["memory"]
    assert gated["memory_deficit_bytes"] == 6 * 1024**3

    eligible = eligibility(cpus=4, memory_bytes=MIN_MEMORY_BYTES, disk_bytes=MIN_DISK_BYTES)
    assert eligible["eligible"] is True
    assert eligible["failed_requirements"] == []
