"""FastAPI server exposing a single `POST /analyze` endpoint.

Run:
    uvicorn analysis_evaluator.api_server:app --host 0.0.0.0 --port 5002
"""

from __future__ import annotations

import logging
from typing import Union

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from .evaluator import evaluate, evaluate_from_upstream
from .models import AnalyzeResponse, ManualAnalyzeRequest, UpstreamAnalyzeRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Trading-Analysis Evaluator",
    description="Scores a student's chart drawings against rule-based swing/structure analysis.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/debug/drawings")
def debug_drawings(request: UpstreamAnalyzeRequest) -> dict:
    """Returns the raw LMS drawings response — use this when /analyze fails with
    'Drawings payload missing required metadata' to inspect the actual shape."""
    from .upstream import _headers
    url = f"{request.base_url.rstrip('/')}/api/v1/learning/result-screenshot-view/"
    params = {
        "category": request.category,
        "sub_category": request.sub_category,
        "type": request.type,
        "date": _normalize_date(request.date),
        "chapter_id": request.chapter_id,
        "user_type": request.user_type,
        "is_challenge_only": str(request.is_challenge_only).lower(),
    }
    try:
        resp = requests.get(url, params=params, headers=_headers(request.bearer_token, request.csrf_token), timeout=30)
    except requests.ConnectionError:
        raise HTTPException(
            status_code=502,
            detail=f"Upstream LMS at {request.base_url} is unreachable (connection refused).",
        )
    except requests.Timeout:
        raise HTTPException(
            status_code=504,
            detail=f"Upstream LMS at {request.base_url} did not respond in time.",
        )
    return {
        "status_code": resp.status_code,
        "url": resp.url,
        "top_level_type": type(resp.json()).__name__ if resp.headers.get("content-type", "").startswith("application/json") else "non-json",
        "top_level_keys": list(resp.json().keys()) if isinstance(resp.json(), dict) else None,
        "list_length": len(resp.json()) if isinstance(resp.json(), list) else None,
        "raw": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:2000],
    }


def _upstream_host(request_obj: object) -> str:
    """Best-effort hostname for upstream-error messages — strips secrets/params
    so the response detail is short and not a wall of stack trace."""
    base = getattr(request_obj, "base_url", None)
    return str(base) if base else "the LMS upstream"


def _normalize_date(raw: str) -> str:
    """Coerce `raw` into the LMS-required `DD-MM-YYYY` format.

    Accepts `DD-MM-YYYY` (passthrough), `YYYY-MM-DD`, `YYYY/MM/DD`, or
    `DD/MM/YYYY`. Raises HTTPException(400) on any other shape.
    """
    s = str(raw).strip()
    parts = s.replace("/", "-").split("-")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise HTTPException(
            status_code=400,
            detail=f"Unrecognised `date` value {raw!r}. Use DD-MM-YYYY or YYYY-MM-DD.",
        )
    a, b, c = parts
    if len(a) == 4:
        year, month, day = a, b, c
    elif len(c) == 4:
        day, month, year = a, b, c
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unrecognised `date` value {raw!r}. Use DD-MM-YYYY or YYYY-MM-DD.",
        )
    return f"{int(day):02d}-{int(month):02d}-{int(year):04d}"


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: Union[UpstreamAnalyzeRequest, ManualAnalyzeRequest]) -> AnalyzeResponse:
    """Single endpoint, two modes:

    1. **Upstream mode** — pass `chapter_id` + `date` + filters and the server pulls
       candles from `/api/v1/mentor/get-forex-data/` and student drawings from
       `/api/v1/learning/result-screenshot-view/`.

    2. **Manual mode** — pass `candles` + parsed `analysis` directly.

    FastAPI's union dispatch picks the right one by field shape.
    """
    try:
        if isinstance(request, UpstreamAnalyzeRequest):
            return evaluate_from_upstream(
                base_url=request.base_url,
                category=request.category,
                sub_category=request.sub_category,
                type=request.type,
                date=_normalize_date(request.date),
                chapter_id=request.chapter_id,
                user_type=request.user_type,
                is_challenge_only=request.is_challenge_only,
                question_id=request.question_id,
                bearer_token=request.bearer_token,
                csrf_token=request.csrf_token,
            )
        return evaluate(request.candles, request.analysis)

    except ValidationError as ve:
        raise HTTPException(status_code=422, detail=ve.errors())
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except requests.ConnectionError:
        host = _upstream_host(request)
        logger.warning("Upstream unreachable: %s", host)
        raise HTTPException(
            status_code=502,
            detail=f"Upstream LMS at {host} is unreachable (connection refused). "
                   "Check the LMS server is running and the `base_url` is correct.",
        )
    except requests.Timeout:
        host = _upstream_host(request)
        logger.warning("Upstream timed out: %s", host)
        raise HTTPException(
            status_code=504,
            detail=f"Upstream LMS at {host} did not respond in time.",
        )
    except requests.HTTPError as he:
        status = he.response.status_code if he.response is not None else 502
        body = (he.response.text[:300] if he.response is not None else "").replace("\n", " ")
        logger.warning("Upstream HTTP %s: %s", status, body)
        raise HTTPException(
            status_code=502,
            detail=f"Upstream LMS returned HTTP {status}. Body: {body!r}",
        )
    except Exception as e:
        logger.exception("Evaluation failed")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5002)
