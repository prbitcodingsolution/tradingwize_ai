"""Vercel serverless entrypoint.

The `@vercel/python` runtime detects an ASGI `app` exported from a file inside
`api/` and serves it as a serverless function. We simply re-export the unified
FastAPI app from `main`. Heavy optional sub-services (TA-Lib, cv2, langchain)
are wrapped in try/except inside `main.py`, so missing deps don't crash the
function — those endpoints just won't be registered.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root (one level up from /api) is on sys.path so
# `import main` resolves when Vercel invokes this file.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from main import app  # noqa: E402,F401
