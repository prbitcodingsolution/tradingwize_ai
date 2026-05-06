"""FastAPI HTTP server for the Drawing Explainer.

Two equivalent ways to run:

    # from project root
    uvicorn drawing_explainer.api_server:app --reload --port 5002

    # from inside the drawing_explainer/ folder (also works — see bootstrap below)
    uvicorn api_server:app --reload --port 5002

Endpoints:

    GET  /health
    POST /api/explain               — fetch session from LMS, then explain
    POST /api/explain-from-session  — explain an already-loaded session JSON
                                       (handy when the frontend already has it)
"""

from __future__ import annotations

# ── Self-bootstrap so this module loads whether uvicorn imports it as
#    `drawing_explainer.api_server` (parent on sys.path) or as a flat
#    `api_server` (CWD = drawing_explainer/, parent missing). When run flat,
#    we add the package's parent dir to sys.path and import siblings via the
#    absolute `drawing_explainer.*` path. ───────────────────────────────────
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
_PARENT = _os.path.dirname(_HERE)
if _PARENT not in _sys.path:
    _sys.path.insert(0, _PARENT)

import logging
import os
from typing import Any, Dict, List, Optional, Union

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from drawing_explainer.api_client import DEFAULT_BASE_URL
from drawing_explainer.explainer import (
    explain_from_api,
    explain_from_multiple_answers,
    explain_from_session,
    explain_from_single_answer,
)
from drawing_explainer.llm_explainer import (
    ALLOWED_ANALYSIS_TYPES,
    FRAMEWORK_NAMES,
    normalize_analysis_type,
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Drawing Explainer",
    description="LLM-powered explanation + ranking of TradingView drawings.",
    version="1.0.0",
)

# Permissive CORS so the local frontend (http://localhost:3000) can call this directly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ───────────────────────── request / response shapes ─────────────────────────


class ExplainRequest(BaseModel):
    """Request body for `/api/explain`.

    Pass EITHER `chapter_id` (explain every trade in the chapter) OR
    `answer_id` (explain just that one trade) — not both. The chapter path
    also requires `date`; the single-trade path ignores chapter-level fields.
    """

    date: Optional[str] = Field(
        None,
        description="Submit date — accepts `DD-MM-YYYY` or `YYYY-MM-DD`. Required when `chapter_id` is used.",
    )
    category: str = "practical demo"
    sub_category: str = "practical-demo-senior-question"
    type: str = "smart"
    chapter_id: Optional[Union[str, int]] = Field(
        None,
        description="Chapter id — explain every trade in the chapter via `result-screenshot-view`. Treat `0`/empty as absent.",
    )
    answer_id: Optional[Union[str, int, List[Union[str, int]]]] = Field(
        None,
        description=(
            "Trade id(s) — explain via `single-result`. Accepts a single value "
            "(`550`), a list (`[550, 551, 552]`), or a comma-separated string "
            "(`\"550,551,552\"`). Multiple ids are fetched in parallel and "
            "merged into one response. Mutually exclusive with `chapter_id`. "
            "Treat `0`/empty as absent."
        ),
    )
    user_type: str = "student"
    is_challenge_only: bool = False

    base_url: str = DEFAULT_BASE_URL
    bearer_token: Optional[str] = Field(
        None,
        description="LMS Bearer token. Falls back to DRAWING_EXPLAINER_BEARER_TOKEN env var.",
    )
    verify_ssl: bool = False

    max_questions: Optional[int] = Field(
        None, description="Cap the number of questions evaluated (handy for smoke tests)."
    )
    max_workers: Optional[int] = Field(
        None, description="Concurrent LLM calls (defaults to project's semaphore limit)."
    )
    analysis_type: Optional[str] = Field(
        None,
        description=(
            "Trading framework lens for the explanation. Accepted values "
            "(case-insensitive, aliases supported): `\"SMC\"` (Smart Money "
            "Concepts), `\"ICT\"` (Inner Circle Trader), `\"VSA\"` (Volume "
            "Spread Analysis), `\"Patterns\"` (Chart Pattern Analysis — "
            "H&S, flags, triangles, double tops, measured move targets), "
            "`\"Price Action\"` (raw candle behaviour, S/R, HH/HL "
            "structure, pin bars / engulfing). Omit / null → existing "
            "generic explanation."
        ),
    )


class ExplainFromSessionRequest(BaseModel):
    session: Dict[str, Any] = Field(..., description="Raw session JSON (chartData.json shape).")
    max_questions: Optional[int] = None
    max_workers: Optional[int] = None

    # Optional: pass these to also fetch real candle data for grading.
    # Without them, the LLM can still produce feedback, but it won't be able
    # to verify drawings against actual swing levels.
    bearer_token: Optional[str] = Field(
        None,
        description=(
            "LMS Bearer token. If supplied, candles are fetched from "
            "/api/v1/mentor/get-forex-data/ for each question and added as "
            "price_context so the LLM can validate drawings against real "
            "swings. Falls back to DRAWING_EXPLAINER_BEARER_TOKEN env var."
        ),
    )
    base_url: str = DEFAULT_BASE_URL
    verify_ssl: bool = False
    fetch_candles_for_grading: bool = Field(
        True,
        description="Set to false to skip candle fetch (faster, but the LLM has no price ground truth).",
    )
    analysis_type: Optional[str] = Field(
        None,
        description=(
            "Trading framework lens for the explanation. Accepted values "
            "(case-insensitive, aliases supported): `\"SMC\"`, `\"ICT\"`, "
            "`\"VSA\"`, `\"Patterns\"`, `\"Price Action\"`. Omit / null → "
            "existing generic explanation."
        ),
    )


# ───────────────────────────── helpers ───────────────────────────────────────


def _clean_id(raw: Optional[Union[str, int]]) -> Optional[str]:
    """Normalise an id field. Swagger UI auto-fills empty integer/string
    fields with `0` / `""`, so we treat those as 'absent' rather than as a
    real id of 0."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s == "0":
        return None
    return s


def _clean_id_list(raw: Optional[Union[str, int, List[Union[str, int]]]]) -> List[str]:
    """Normalise `answer_id` into a list of cleaned ids.

    Accepts:
      - `None`, `""`, `0`, `"0"` → `[]`
      - A single value (`550` / `"550"`) → `["550"]`
      - A list (`[550, 551]` / `["550","551"]`) → `["550","551"]`
      - A comma-separated string (`"550,551,552"`) → three entries
    Empty / `0` entries inside a list/string are dropped (so a Swagger-defaulted
    `0` mixed with real ids doesn't poison the request).
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        items: List[Union[str, int]] = list(raw)
    elif isinstance(raw, str) and "," in raw:
        items = [part for part in raw.split(",")]
    else:
        items = [raw]

    cleaned: List[str] = []
    for item in items:
        c = _clean_id(item)
        if c is not None:
            cleaned.append(c)
    return cleaned


def _validate_analysis_type(raw: Optional[str]) -> Optional[str]:
    """Uppercase + validate. None / empty → None. Unknown → HTTP 400."""
    try:
        return normalize_analysis_type(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _attach_framework_echo(
    result: Dict[str, Any], analysis_type: Optional[str]
) -> Dict[str, Any]:
    """Echo the resolved framework on the response so the frontend can render
    the right header / colour. No-op when `analysis_type` is None."""
    if analysis_type and isinstance(result, dict):
        result.setdefault("analysis_type", analysis_type)
        result.setdefault("framework_name", FRAMEWORK_NAMES.get(analysis_type))
    return result


def _normalize_date(raw: Optional[str]) -> Optional[str]:
    """Coerce a date string into the LMS-required `DD-MM-YYYY` format.

    Accepts: `DD-MM-YYYY` (passthrough), `YYYY-MM-DD`, `YYYY/MM/DD`,
    `DD/MM/YYYY`. Returns None for None/empty. Raises HTTPException(400)
    on an unrecognised shape so the caller sees a clear error instead of
    the LMS's `Invalid date format` rejection further down.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    parts = s.replace("/", "-").split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise HTTPException(
            status_code=400,
            detail=f"Unrecognised `date` value {raw!r}. Use DD-MM-YYYY or YYYY-MM-DD.",
        )

    a, b, c = parts
    if len(a) == 4:                     # YYYY-MM-DD or YYYY/MM/DD
        year, month, day = a, b, c
    elif len(c) == 4:                   # DD-MM-YYYY or DD/MM/YYYY
        day, month, year = a, b, c
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unrecognised `date` value {raw!r}. Use DD-MM-YYYY or YYYY-MM-DD.",
        )

    return f"{int(day):02d}-{int(month):02d}-{int(year):04d}"


# ───────────────────────────── endpoints ─────────────────────────────────────


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "drawing_explainer",
        "model": os.getenv("DRAWING_EXPLAINER_MODEL", "openai/gpt-oss-120b"),
    }


@app.post("/api/explain")
def explain_endpoint(req: ExplainRequest) -> Dict[str, Any]:
    """Fetch the session JSON from the LMS, then run the LLM pipeline.

    All parameters are passed as a **JSON body** (see `ExplainRequest`).
    Routes by which id the caller supplied:
      - `answer_id` → `single-result` (one trade)
      - `chapter_id` → `result-screenshot-view` (every trade in the chapter)
    """
    chapter_id_clean = _clean_id(req.chapter_id)
    answer_ids_clean = _clean_id_list(req.answer_id)
    date_clean = _normalize_date(req.date)
    analysis_type_clean = _validate_analysis_type(req.analysis_type)

    if chapter_id_clean and answer_ids_clean:
        raise HTTPException(
            status_code=400,
            detail="Provide either `chapter_id` or `answer_id`, not both.",
        )
    if not chapter_id_clean and not answer_ids_clean:
        raise HTTPException(
            status_code=400,
            detail="One of `chapter_id` or `answer_id` is required.",
        )

    try:
        if answer_ids_clean:
            if len(answer_ids_clean) == 1:
                result = explain_from_single_answer(
                    answer_id=answer_ids_clean[0],
                    base_url=req.base_url,
                    bearer_token=req.bearer_token,
                    verify_ssl=req.verify_ssl,
                    max_workers=req.max_workers,
                    analysis_type=analysis_type_clean,
                )
            else:
                result = explain_from_multiple_answers(
                    answer_ids=answer_ids_clean,
                    base_url=req.base_url,
                    bearer_token=req.bearer_token,
                    verify_ssl=req.verify_ssl,
                    max_workers=req.max_workers,
                    analysis_type=analysis_type_clean,
                )
            return _attach_framework_echo(result, analysis_type_clean)

        if not date_clean:
            raise HTTPException(
                status_code=400,
                detail="`date` is required when using `chapter_id`.",
            )
        result = explain_from_api(
            date=date_clean,
            category=req.category,
            sub_category=req.sub_category,
            type=req.type,
            chapter_id=chapter_id_clean,
            user_type=req.user_type,
            is_challenge_only=req.is_challenge_only,
            base_url=req.base_url,
            bearer_token=req.bearer_token,
            verify_ssl=req.verify_ssl,
            max_questions=req.max_questions,
            max_workers=req.max_workers,
            analysis_type=analysis_type_clean,
        )
        return _attach_framework_echo(result, analysis_type_clean)
    except HTTPException:
        raise
    except requests.ConnectionError:
        logger.warning("Upstream unreachable: %s", req.base_url)
        raise HTTPException(
            status_code=502,
            detail=f"Upstream LMS at {req.base_url} is unreachable (connection refused). "
                   "Check the LMS server is running and the `base_url` is correct.",
        )
    except requests.Timeout:
        logger.warning("Upstream timed out: %s", req.base_url)
        raise HTTPException(
            status_code=504,
            detail=f"Upstream LMS at {req.base_url} did not respond in time.",
        )
    except requests.HTTPError as he:
        status = he.response.status_code if he.response is not None else 502
        body = (he.response.text[:300] if he.response is not None else "").replace("\n", " ")
        logger.warning("Upstream HTTP %s: %s", status, body)
        raise HTTPException(
            status_code=502,
            detail=f"Upstream LMS returned HTTP {status}. Body: {body!r}",
        )
    except Exception as exc:
        logger.exception("explain_endpoint failed")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/explain-from-session")
def explain_from_session_endpoint(req: ExplainFromSessionRequest) -> Dict[str, Any]:
    """Bypass the LMS session fetch — caller posts the session JSON directly.

    If `bearer_token` is supplied, candles are still fetched per question
    from `/api/v1/mentor/get-forex-data/` so the LLM can validate drawings
    against real price action.
    """
    analysis_type_clean = _validate_analysis_type(req.analysis_type)
    try:
        result = explain_from_session(
            req.session,
            max_questions=req.max_questions,
            max_workers=req.max_workers,
            bearer_token=req.bearer_token,
            base_url=req.base_url,
            verify_ssl=req.verify_ssl,
            fetch_candles_for_grading=req.fetch_candles_for_grading,
            analysis_type=analysis_type_clean,
        )
        return _attach_framework_echo(result, analysis_type_clean)
    except requests.ConnectionError:
        logger.warning("Upstream unreachable while fetching candles: %s", req.base_url)
        raise HTTPException(
            status_code=502,
            detail=f"Upstream LMS at {req.base_url} is unreachable (connection refused).",
        )
    except requests.Timeout:
        logger.warning("Upstream timed out while fetching candles: %s", req.base_url)
        raise HTTPException(
            status_code=504,
            detail=f"Upstream LMS at {req.base_url} did not respond in time.",
        )
    except Exception as exc:
        logger.exception("explain_from_session_endpoint failed")
        raise HTTPException(status_code=500, detail=str(exc))
