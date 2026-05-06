"""CLI: `python -m drawing_explainer.cli ...`.

Two modes:

  # 1. Local file (e.g. analysis_evaluator/chartData.json)
  python -m drawing_explainer.cli --file analysis_evaluator/chartData.json

  # 2. Live API
  python -m drawing_explainer.cli \
      --date 23-04-2026 \
      --bearer eyJhbGciOiJI... \
      --base-url http://192.168.0.122:8000

Output is JSON written to stdout (or `--output PATH`).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any, Dict

from .explainer import explain_from_api, explain_from_session


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="drawing_explainer", description=__doc__)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="Path to a local session JSON file (chartData.json shape)")
    src.add_argument("--date", help="Submit date (DD-MM-YYYY) — fetch via the LMS API")

    p.add_argument("--category", default="practical demo")
    p.add_argument("--sub-category", default="practical-demo-senior-question")
    p.add_argument("--type", default="smart")
    p.add_argument("--chapter-id", default="")
    p.add_argument("--user-type", default="student")
    p.add_argument("--is-challenge-only", action="store_true")
    p.add_argument(
        "--base-url",
        default=os.getenv("DRAWING_EXPLAINER_BASE_URL", "http://192.168.0.122:8000"),
    )
    p.add_argument("--bearer", default=os.getenv("DRAWING_EXPLAINER_BEARER_TOKEN"))
    p.add_argument("--verify-ssl", action="store_true")

    p.add_argument("--max-questions", type=int, default=None,
                   help="Cap the number of questions evaluated (handy for smoke tests)")
    p.add_argument("--max-workers", type=int, default=None,
                   help="Concurrent LLM calls (defaults to project's semaphore limit)")

    p.add_argument("--output", "-o", help="Write JSON output here instead of stdout")
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def _run(args: argparse.Namespace) -> Dict[str, Any]:
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            session_json = json.load(f)
        return explain_from_session(
            session_json,
            max_questions=args.max_questions,
            max_workers=args.max_workers,
        )

    return explain_from_api(
        date=args.date,
        category=args.category,
        sub_category=args.sub_category,
        type=args.type,
        chapter_id=args.chapter_id,
        user_type=args.user_type,
        is_challenge_only=args.is_challenge_only,
        base_url=args.base_url,
        bearer_token=args.bearer,
        verify_ssl=args.verify_ssl,
        max_questions=args.max_questions,
        max_workers=args.max_workers,
    )


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    result = _run(args)
    output = json.dumps(result, indent=2, ensure_ascii=False, default=str)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
