"""Single source of truth for the LMS / mentor-API base URL.

Why this module exists
----------------------
Several modules across the project (drawing_explainer, analysis_evaluator,
api_chat_drawing, get_new_token, etc.) talk to the same upstream LMS host.
Historically each module had its OWN hardcoded fallback URL, sometimes with
its own env var name (`API_BASE_URL` vs `DRAWING_EXPLAINER_BASE_URL`), and
when pushing to a different environment the developer had to find-and-replace
the URL across multiple files.

Now there is ONE env var — `LMS_BASE_URL` — that every consumer reads via
`get_lms_base_url()`. Change it once in `.env` and every caller picks up the
new value on the next process restart.

Read order (first non-empty wins)
---------------------------------
  1. LMS_BASE_URL                  — canonical, set this in .env
  2. API_BASE_URL                  — legacy alias used by app_advanced.py,
                                     api_chat_drawing.py, chat_drawing_agent.py
  3. DRAWING_EXPLAINER_BASE_URL    — legacy alias used by drawing_explainer
  4. Hardcoded local-dev fallback  — only when nothing is configured
"""

from __future__ import annotations

import os

# Local-dev fallback — used ONLY when none of the env vars are set. This
# keeps developer machines working out-of-the-box; for any deployment the
# .env file should set LMS_BASE_URL explicitly.
LOCAL_DEV_FALLBACK = "http://192.168.0.122:8000"


# Order matters: LMS_BASE_URL takes precedence so a single edit in .env
# overrides every legacy alias. The legacy names are kept so existing
# deployments / docker-compose files / CI configs that already set
# `API_BASE_URL` keep working without code changes.
_BASE_URL_ENV_VARS = (
    "LMS_BASE_URL",
    "API_BASE_URL",
    "DRAWING_EXPLAINER_BASE_URL",
)


def get_lms_base_url() -> str:
    """Resolve the LMS base URL by reading env vars in canonical order.

    Returns a string with no trailing slash so callers can safely append
    paths like ``f"{base}/api/v1/learning/single-result/"``.
    """
    for name in _BASE_URL_ENV_VARS:
        val = os.getenv(name)
        if val and val.strip():
            return val.strip().rstrip("/")
    return LOCAL_DEV_FALLBACK


# Module-level constant for places that want it as `from utils.base_url import LMS_BASE_URL`.
# Note: this captures the value at IMPORT time. Pydantic models that need the
# value at REQUEST time should use `default_factory=get_lms_base_url` instead.
LMS_BASE_URL = get_lms_base_url()
