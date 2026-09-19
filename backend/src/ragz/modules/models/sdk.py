"""Load the installed SDK without its optional network pricing-map fetch."""

import os
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def load_sdk() -> Any:
    # Catalog versions must describe their actual package, including on air-gapped installs.
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    import litellm

    return litellm
