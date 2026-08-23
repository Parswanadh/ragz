import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_ragflow_cloud_preflight import classify  # noqa: E402


def test_cloud_preflight_classifies_reachability_and_credentials() -> None:
    assert classify(root_status=200, datasets_status=401, credential_present=False) == (
        "credential_gated"
    )
    assert classify(root_status=200, datasets_status=200, credential_present=True) == (
        "api_reachable_models_unverified"
    )
    assert classify(root_status=503, datasets_status=503, credential_present=False) == (
        "cloud_unreachable"
    )
