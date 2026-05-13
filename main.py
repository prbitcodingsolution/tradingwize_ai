"""Unified FastAPI server — runs every sub-service's endpoints from one process.

Run from the project root:

    uvicorn main_api:app --reload --host 0.0.0.0 --port 5002

Mounted services (each keeps its original URL path — no frontend changes):

    drawing_explainer   POST /api/explain
                        POST /api/explain-from-session

    analysis_evaluator  POST /analyze
                        POST /debug/drawings

    chat_drawing        GET  /api/v1/drawing/chat/examples
                        GET  /api/v1/drawing/chat/test
                        POST /api/v1/drawing/chat/

    news_summary        GET  /api/v1/news/summary
                        GET  /api/v1/news/list

Plus unified meta endpoints exposed by this file:

    GET /            — service catalog
    GET /health      — combined health probe
    GET /docs        — Swagger UI for ALL endpoints
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any, Dict, List

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("main_api")


# ─── import every sub-app ──────────────────────────────────────────────────
# Each module already defines a `FastAPI()` instance named `app`. We absorb
# their routes (minus `/` and `/health`, which the unified app provides) into
# this one app so a single uvicorn process serves all of them.

from drawing_explainer import api_server as drawing_explainer_app  # noqa: E402
from analysis_evaluator import api_server as analysis_evaluator_app  # noqa: E402
import api_chat_drawing as chat_drawing_app  # noqa: E402
import api_news_summary as news_summary_app  # noqa: E402


# ─── build the unified app ─────────────────────────────────────────────────

app = FastAPI(
    title="TradingWize Unified API",
    description=(
        "Single entry point combining four services: drawing explainer, "
        "rule-based analysis evaluator, chat-based drawing generator, and "
        "stock news summary."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── absorb sub-app routes ─────────────────────────────────────────────────

# Paths that every sub-app defines; the unified app provides its own versions.
# We also skip each sub-app's auto-generated docs routes so the unified
# `/docs` and `/openapi.json` aren't shadowed by whichever sub-app loads first.
_OVERRIDE_PATHS = {
    "/", "/health",
    "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc",
}

_SERVICES: List[Dict[str, Any]] = [
    {"name": "drawing_explainer",   "module": drawing_explainer_app,   "tag": "drawing_explainer"},
    {"name": "analysis_evaluator",  "module": analysis_evaluator_app,  "tag": "analysis_evaluator"},
    {"name": "chat_drawing",        "module": chat_drawing_app,        "tag": "chat_drawing"},
    {"name": "news_summary",        "module": news_summary_app,        "tag": "news_summary"},
]


def _absorb(sub_app: FastAPI, *, tag: str) -> List[str]:
    """Move every non-conflicting route from `sub_app` onto the unified app.

    Returns the list of paths that were actually merged (for logging + the
    `/` service catalog).
    """
    merged: List[str] = []
    for route in sub_app.router.routes:
        path = getattr(route, "path", None)
        if not path:
            continue
        if path in _OVERRIDE_PATHS:
            continue  # unified app supplies these
        # Tag for nice grouping in /docs (Swagger UI)
        existing_tags = list(getattr(route, "tags", []) or [])
        if tag not in existing_tags:
            existing_tags.append(tag)
            try:
                route.tags = existing_tags
            except Exception:
                pass  # not all route subclasses support tags assignment
        app.router.routes.append(route)
        merged.append(path)
    return merged


_MERGED_BY_SERVICE: Dict[str, List[str]] = {}
for svc in _SERVICES:
    paths = _absorb(svc["module"].app, tag=svc["tag"])
    _MERGED_BY_SERVICE[svc["name"]] = paths
    logger.info("Merged %s routes from %s: %s", len(paths), svc["name"], paths)


# ─── unified meta endpoints ────────────────────────────────────────────────

@app.get("/", tags=["meta"])
def root() -> Dict[str, Any]:
    """Service catalog — lists every endpoint grouped by sub-service."""
    return {
        "service": "TradingWize Unified API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "services": _MERGED_BY_SERVICE,
    }


@app.get("/health", tags=["meta"])
def health() -> Dict[str, Any]:
    """Liveness probe + per-sub-service status snapshot."""
    return {
        "status": "ok",
        "service": "tradingwize-unified-api",
        "timestamp": datetime.utcnow().isoformat(),
        "sub_services": [
            {"name": svc["name"], "routes": _MERGED_BY_SERVICE.get(svc["name"], [])}
            for svc in _SERVICES
        ],
    }


# ─── runnable as a script: `python main_api.py` ────────────────────────────

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("MAIN_API_HOST", "0.0.0.0")
    port = int(os.getenv("MAIN_API_PORT", "5002"))
    reload_flag = os.getenv("MAIN_API_RELOAD", "0") == "1"

    print("=" * 70)
    print("TradingWize Unified API")
    print("=" * 70)
    print(f"  URL : http://{host}:{port}")
    print(f"  Docs: http://{host}:{port}/docs")
    for svc in _SERVICES:
        print(f"  • {svc['name']}: {len(_MERGED_BY_SERVICE.get(svc['name'], []))} routes")
    print("=" * 70)

    uvicorn.run("main_api:app", host=host, port=port, reload=reload_flag)
