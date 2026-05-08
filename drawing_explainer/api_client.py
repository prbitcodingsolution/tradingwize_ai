"""Fetches the user's drawing JSON from the LMS.

Two endpoints are supported:

  - `result-screenshot-view` returns every trade in a chapter:
        GET {base}/api/v1/learning/result-screenshot-view/
            ?category=...&sub_category=...&type=...&date=DD-MM-YYYY
            &chapter_id=...&user_type=student&is_challenge_only=false

  - `single-result` returns ONE trade by id:
        GET {base}/api/v1/learning/single-result/?answer_id=<id>

Both require `Authorization: Bearer <token>`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Union

import requests

from utils.base_url import get_lms_base_url

logger = logging.getLogger(__name__)


# Canonical resolution: reads `LMS_BASE_URL` first, then legacy
# `API_BASE_URL` / `DRAWING_EXPLAINER_BASE_URL`, then a local-dev fallback.
# Change the URL in ONE place — `.env` — to switch between local and server.
DEFAULT_BASE_URL = get_lms_base_url()


def _headers(bearer_token: Optional[str]) -> Dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    return headers


def fetch_drawing_session(
    *,
    category: str = "practical demo",
    sub_category: str = "practical-demo-senior-question",
    type: str = "smart",
    date: str,
    chapter_id: str = "",
    user_type: str = "student",
    is_challenge_only: bool = False,
    base_url: str = DEFAULT_BASE_URL,
    bearer_token: Optional[str] = None,
    timeout: int = 30,
    verify_ssl: bool = False,
) -> Dict[str, Any]:
    """Fetch the full session JSON (the same payload as `chartData.json`).

    `date` must be in `DD-MM-YYYY` form, matching the upstream API.

    Returns the raw JSON dict (top level is the session object with `questions`).
    Raises `requests.HTTPError` on non-2xx, `ValueError` if response is not JSON.
    """
    url = f"{base_url.rstrip('/')}/api/v1/learning/result-screenshot-view/"
    params = {
        "category": category,
        "sub_category": sub_category,
        "type": type,
        "date": date,
        "chapter_id": chapter_id,
        "user_type": user_type,
        "is_challenge_only": str(is_challenge_only).lower(),
    }

    bearer_token = bearer_token or os.getenv("DRAWING_EXPLAINER_BEARER_TOKEN")
    if not bearer_token:
        logger.warning("No bearer token supplied — request will likely 401.")

    logger.info("GET %s params=%s", url, params)
    resp = requests.get(
        url,
        params=params,
        headers=_headers(bearer_token),
        timeout=timeout,
        verify=verify_ssl,
    )
    resp.raise_for_status()

    try:
        return resp.json()
    except ValueError as exc:
        snippet = resp.text[:200].replace("\n", " ")
        raise ValueError(f"Upstream did not return JSON. Body starts with: {snippet!r}") from exc


def fetch_single_result(
    *,
    answer_id: Union[int, str],
    base_url: str = DEFAULT_BASE_URL,
    bearer_token: Optional[str] = None,
    timeout: int = 30,
    verify_ssl: bool = False,
) -> Dict[str, Any]:
    """Fetch ONE trade record from `/api/v1/learning/single-result/`.

    Used when the frontend wants an explanation for a specific trade rather
    than every trade in a chapter. Returns the raw JSON dict — the explainer
    pipeline normalises it into the same session shape as the chapter feed.
    """
    url = f"{base_url.rstrip('/')}/api/v1/learning/single-result/"
    params = {"answer_id": str(answer_id)}

    bearer_token = bearer_token or os.getenv("DRAWING_EXPLAINER_BEARER_TOKEN")
    if not bearer_token:
        logger.warning("No bearer token supplied — request will likely 401.")

    logger.info("GET %s params=%s", url, params)
    resp = requests.get(
        url,
        params=params,
        headers=_headers(bearer_token),
        timeout=timeout,
        verify=verify_ssl,
    )
    resp.raise_for_status()

    try:
        return resp.json()
    except ValueError as exc:
        snippet = resp.text[:200].replace("\n", " ")
        raise ValueError(f"Upstream did not return JSON. Body starts with: {snippet!r}") from exc
