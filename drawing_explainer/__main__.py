"""Boot the Drawing Explainer FastAPI server.

Run from the **project root** (not from inside `drawing_explainer/`):

    cd D:\\trader_agent_17_03
    python -m drawing_explainer

Env vars:
  DRAWING_EXPLAINER_HOST   default 0.0.0.0
  DRAWING_EXPLAINER_PORT   default 5002
  DRAWING_EXPLAINER_RELOAD set to "1" to enable autoreload
"""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.getenv("DRAWING_EXPLAINER_HOST", "0.0.0.0")
    port = int(os.getenv("DRAWING_EXPLAINER_PORT", "5002"))
    reload = os.getenv("DRAWING_EXPLAINER_RELOAD", "0") == "1"

    uvicorn.run(
        "drawing_explainer.api_server:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    main()
