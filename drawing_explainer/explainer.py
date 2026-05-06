"""Top-level orchestrator: fetch session → fetch candles per question →
compact + enrich with price context → LLM explain → format.

Three entry points:

  - `explain_from_session(session_json, ...)` — when you already have the
    drawing JSON. Pass a `bearer_token` to also fetch candles for each
    question (so the LLM has price ground-truth to grade against). Without
    a token, we fall back to the no-candles flow.

  - `explain_from_api(...)` — calls `result-screenshot-view` for a chapter
    (every trade), then runs the same pipeline.

  - `explain_from_single_answer(...)` — calls `single-result` for ONE trade,
    wraps it as a one-question session, then runs the same pipeline.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple, Union

from .api_client import DEFAULT_BASE_URL, fetch_drawing_session, fetch_single_result
from .candle_fetcher import fetch_candles, isodate_to_ymd, market_for
from .drawing_extractor import compact_session
from .formatter import format_question, format_session
from .llm_explainer import explain_all
from .price_context import build_price_context

logger = logging.getLogger(__name__)


# How many candle-fetch HTTP calls we run in parallel. Each is a single GET
# so the bottleneck is the LMS, not our process.
CANDLE_FETCH_WORKERS = 5


def _attach_explanations(result: Dict[str, Any]) -> Dict[str, Any]:
    """Add ready-to-render markdown blobs so the frontend can drop them
    straight into a markdown component:

      - `result["questions"][i]["explanation"]` — markdown for ONE question
      - `result["explanation"]`                 — markdown for the WHOLE report
    """
    for q in result.get("questions") or []:
        if isinstance(q, dict):
            q["explanation"] = format_question(q)
    result["explanation"] = format_session(result)
    return result


def _decision_time_t(question: Dict[str, Any]) -> Optional[int]:
    """Pull the epoch-second timestamp of the decision candle out of a
    compacted question (`trade_context.decision_candle.time`)."""
    dc = (question.get("trade_context") or {}).get("decision_candle") or {}
    raw = dc.get("time")
    if isinstance(raw, str):
        # ISO string from the candle summary — parse it.
        from datetime import datetime
        try:
            return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    return None


def _enrich_question_with_price_context(
    question: Dict[str, Any],
    *,
    base_url: str,
    bearer_token: Optional[str],
    verify_ssl: bool,
) -> Dict[str, Any]:
    """Fetch candles for ONE question and attach a `price_context` summary.

    Mutates and returns `question`. On any failure we still return the
    question (without `price_context`) so a single dud question doesn't
    fail the whole session.
    """
    pair = question.get("pair")
    timeframe = question.get("timeframe")
    from_date = isodate_to_ymd(question.get("from_date") or "")
    to_date = isodate_to_ymd(question.get("to_date") or "")
    market = market_for(question.get("market"))

    if not (pair and timeframe and from_date and to_date):
        logger.info("Q%s: missing metadata, skipping candle fetch", question.get("question_no"))
        return question

    try:
        candles = fetch_candles(
            pair=pair,
            from_date=from_date,
            to_date=to_date,
            timeframe=timeframe,
            market=market,
            base_url=base_url,
            bearer_token=bearer_token,
            verify_ssl=verify_ssl,
        )
    except Exception as exc:
        logger.warning("Q%s candle fetch raised: %s", question.get("question_no"), exc)
        return question

    if not candles:
        logger.info("Q%s: no candles returned", question.get("question_no"))
        return question

    decision_t = _decision_time_t(question)
    ctx = build_price_context(candles, decision_time_t=decision_t)
    if ctx:
        question["price_context"] = ctx
    return question


def _enrich_with_price_context(
    compact: Dict[str, Any],
    *,
    base_url: str,
    bearer_token: Optional[str],
    verify_ssl: bool,
    max_workers: int = CANDLE_FETCH_WORKERS,
) -> Dict[str, Any]:
    """Fetch candles for every question in parallel and attach `price_context`."""
    questions: List[Dict[str, Any]] = compact.get("questions") or []
    if not questions:
        return compact

    workers = max(1, min(max_workers, len(questions)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _enrich_question_with_price_context,
                q,
                base_url=base_url,
                bearer_token=bearer_token,
                verify_ssl=verify_ssl,
            ): q
            for q in questions
        }
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as exc:  # belt-and-braces — _enrich already swallows
                logger.exception("Candle enrichment unexpectedly raised: %s", exc)

    enriched = sum(1 for q in questions if q.get("price_context"))
    logger.info(
        "Price-context: enriched %d/%d questions with candle data",
        enriched, len(questions),
    )
    return compact


def _question_has_actionable_data(q: Dict[str, Any]) -> bool:
    """A question is worth running through the LLM if at least ONE of:
      - the user actually drew something (`drawing_counts.user > 0`), OR
      - we have enough chart metadata to fetch candles (pair + timeframe), OR
      - candles were already enriched in a prior step (`price_context`), OR
      - the trade decision context has real values (buy/SL/TP, direction,
        hit/miss). The single-result endpoint typically returns *only* this
        last bucket, and the LLM can still produce useful feedback on the
        trade plan even without drawings or candles.
    Only when *all* of these are empty do we short-circuit with a
    `no data found` response so we don't pay for an LLM call that has
    nothing to grade.
    """
    if (q.get("drawing_counts") or {}).get("user", 0) > 0:
        return True
    if q.get("price_context"):
        return True
    if q.get("pair") and q.get("timeframe"):
        return True
    ctx = q.get("trade_context") or {}
    if any(
        ctx.get(k) not in (None, "", 0)
        for k in (
            "user_buy_price",
            "user_stop_loss",
            "user_take_profit",
            "answer_direction",
            "answer_stop_loss",
            "answer_take_profit",
            "hit",
        )
    ):
        return True
    return False


def _build_no_data_response(compact: Dict[str, Any]) -> Dict[str, Any]:
    """Friendly response for when none of the fetched questions have any
    drawings or chart metadata — typically `single-result` payloads that
    carry only the trade decision, not the TradingView drawings JSON."""
    questions = compact.get("questions") or []
    question_summaries = [
        {
            "id": q.get("id"),
            "question_no": q.get("question_no"),
            "user_drawings": (q.get("drawing_counts") or {}).get("user", 0),
            "has_chart_metadata": bool(q.get("pair") and q.get("timeframe")),
        }
        for q in questions
    ]
    message = (
        "No data found for the mentioned ID."
        if not questions
        else "No data found for the mentioned ID(s) — "
             "the LMS returned the trade record(s) but no drawings JSON or chart "
             "metadata. Use `chapter_id` + `date` instead of `answer_id` if you "
             "need TradingView drawings."
    )
    return {
        "success": False,
        "message": message,
        "session": {
            "session_id": compact.get("session_id"),
            "total_questions": len(questions),
        },
        "questions": question_summaries,
        "explanation": message,
    }


def explain_from_session(
    session_json: Dict[str, Any],
    *,
    max_questions: Optional[int] = None,
    max_workers: Optional[int] = None,
    bearer_token: Optional[str] = None,
    base_url: str = DEFAULT_BASE_URL,
    verify_ssl: bool = False,
    fetch_candles_for_grading: bool = True,
    analysis_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the explainer against an already-loaded session JSON.

    If `bearer_token` is provided (and `fetch_candles_for_grading` is True),
    candles are fetched for each question and added as `price_context` so
    the LLM can validate drawings against actual price action. Without a
    token we skip that step — the LLM still produces feedback, but it can't
    verify swing-anchor claims numerically.

    `analysis_type` (`"SMC"` / `"ICT"` / `"VSA"` / `"Patterns"` /
    `"Price Action"`, case-insensitive) selects a framework-specific lens
    for the LLM prompt. None / missing / empty falls back to the existing
    generic explanation.

    Returns a `{success: false, message, ...}` shape (no LLM call) when no
    question has any drawings or chart metadata to evaluate.
    """
    compact = compact_session(session_json, max_questions=max_questions)
    questions: List[Dict[str, Any]] = compact.get("questions") or []
    logger.info(
        "Compacted session %s: %d questions, %d total user drawings",
        compact.get("session_id"),
        len(questions),
        sum((q.get("drawing_counts") or {}).get("user", 0) for q in questions),
    )

    if not questions:
        logger.info("Empty session — returning no-data response.")
        return _build_no_data_response(compact)

    if fetch_candles_for_grading and bearer_token:
        _enrich_with_price_context(
            compact,
            base_url=base_url,
            bearer_token=bearer_token,
            verify_ssl=verify_ssl,
        )
    elif fetch_candles_for_grading and not bearer_token:
        logger.info("No bearer token — skipping candle fetch (LLM will lack price ground truth).")

    if not any(_question_has_actionable_data(q) for q in questions):
        logger.info(
            "Session has %d question(s) but none have drawings or chart metadata — "
            "returning no-data response without calling the LLM.",
            len(questions),
        )
        return _build_no_data_response(compact)

    result = explain_all(compact, max_workers=max_workers, analysis_type=analysis_type)
    return _attach_explanations(result)


def explain_from_api(
    *,
    date: str,
    category: str = "practical demo",
    sub_category: str = "practical-demo-senior-question",
    type: str = "smart",
    chapter_id: str = "",
    user_type: str = "student",
    is_challenge_only: bool = False,
    base_url: str = DEFAULT_BASE_URL,
    bearer_token: Optional[str] = None,
    verify_ssl: bool = False,
    max_questions: Optional[int] = None,
    max_workers: Optional[int] = None,
    fetch_candles_for_grading: bool = True,
    analysis_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch the session from the LMS endpoint, also fetch candles per
    question, then explain everything."""
    session_json = fetch_drawing_session(
        category=category,
        sub_category=sub_category,
        type=type,
        date=date,
        chapter_id=chapter_id,
        user_type=user_type,
        is_challenge_only=is_challenge_only,
        base_url=base_url,
        bearer_token=bearer_token,
        verify_ssl=verify_ssl,
    )
    return explain_from_session(
        session_json,
        max_questions=max_questions,
        max_workers=max_workers,
        bearer_token=bearer_token,
        base_url=base_url,
        verify_ssl=verify_ssl,
        fetch_candles_for_grading=fetch_candles_for_grading,
        analysis_type=analysis_type,
    )


# `single-result` and `result-screenshot-view` describe the same trade with
# different field names. Map single-result → chartData/session names so
# `compact_question` finds what it expects.
_SINGLE_RESULT_QUESTION_ALIASES = {
    "question_number": "question_no",
    "your_analysis": "answer_analysis_json",
    "right_analysis": "correction_analysis_json",
}

# Question-level metadata that may live one nesting level down in single-result
# (under `learning_user_answer[0]`). Promote them to the question root so the
# candle-fetch path picks them up.
_QUESTION_METADATA_FIELDS = (
    "pair",
    "timeframe",
    "from_date",
    "to_date",
    "market_name",
    "is_drawing_only",
    "is_single_timeframe",
    "win_loss",
    "risk_reward_ratio",
)

# Drawing-JSON destination → priority list of source field names where the
# LMS may park the same data. The first non-empty match wins. Each name is
# tried at the top level AND inside `learning_user_answer[0]`.
_DRAWING_FIELD_SOURCES = {
    "answer_analysis_json": (
        "answer_analysis_json", "your_analysis", "user_analysis_json",
        "user_answer_json", "analysis_json",
    ),
    "correction_analysis_json": (
        "correction_analysis_json", "right_analysis", "correct_analysis_json",
        "correction_json",
    ),
    "mentor_analysis_json": (
        "mentor_analysis_json", "mentor_analysis", "mentor_json",
    ),
}


def _is_tradingview_drawing_json(value: Any) -> bool:
    """A TradingView drawing JSON looks like `{charts: [{panes: [...]}]}`.
    Strings (even non-empty ones like `""`) are not drawings."""
    if not isinstance(value, dict):
        return False
    charts = value.get("charts")
    if not isinstance(charts, list) or not charts:
        return False
    first = charts[0]
    return isinstance(first, dict) and isinstance(first.get("panes"), list)


def _find_drawing_json(payload: Any, *, max_depth: int = 4) -> Optional[Dict[str, Any]]:
    """Best-effort recursive search for a TradingView drawing JSON anywhere
    in `payload`. Returns the first match or None. Depth-limited so we don't
    walk into giant flat arrays of candles."""
    if max_depth < 0:
        return None
    if _is_tradingview_drawing_json(payload):
        return payload  # type: ignore[return-value]
    if isinstance(payload, dict):
        for v in payload.values():
            found = _find_drawing_json(v, max_depth=max_depth - 1)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_drawing_json(item, max_depth=max_depth - 1)
            if found is not None:
                return found
    return None


def _pick_drawing_field(
    *sources: Dict[str, Any], names: tuple,
) -> Optional[Dict[str, Any]]:
    """Return the first valid drawing-JSON value found across `sources` for
    any of the given field `names`. Skips empty strings, None, and anything
    that doesn't look like a TradingView drawing."""
    for src in sources:
        if not isinstance(src, dict):
            continue
        for name in names:
            val = src.get(name)
            if _is_tradingview_drawing_json(val):
                return val
    return None


def _normalize_single_result_question(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a single-result payload into the question shape used by
    `compact_question`. Mutates a shallow copy and returns it."""
    out: Dict[str, Any] = dict(payload)

    # Copy non-drawing field aliases (only when the destination is missing,
    # so chartData payloads — which already have both keys — pass through).
    for src, dst in _SINGLE_RESULT_QUESTION_ALIASES.items():
        if src in _DRAWING_FIELD_SOURCES.get(dst, ()):
            continue  # drawing fields handled separately below
        if dst not in out or out.get(dst) in (None, ""):
            val = payload.get(src)
            if val not in (None, ""):
                out[dst] = val

    # `learning_user_answer` is an array on single-result; chartData uses a
    # singular `user_answer` object. Take the first entry.
    if not isinstance(out.get("user_answer"), dict):
        lua = out.get("learning_user_answer")
        if isinstance(lua, list) and lua and isinstance(lua[0], dict):
            out["user_answer"] = lua[0]
        elif isinstance(lua, dict):
            out["user_answer"] = lua

    # Promote question-level metadata that may be embedded inside the
    # user_answer dict (single-result tends to nest pair/timeframe there).
    ua = out.get("user_answer") if isinstance(out.get("user_answer"), dict) else {}
    for fld in _QUESTION_METADATA_FIELDS:
        if not out.get(fld) and ua.get(fld):
            out[fld] = ua[fld]

    # Resolve drawing-JSON fields. The LMS parks the same drawing under
    # different names depending on the endpoint (chartData uses
    # `*_analysis_json` at the question root; single-result has been seen
    # to use `your_analysis` / `right_analysis` at the top, and sometimes
    # to nest the drawing inside `learning_user_answer[0]`). Try each
    # known alias at the top level, then inside the user_answer dict.
    lua_list = payload.get("learning_user_answer")
    nested_candidates: List[Dict[str, Any]] = []
    if isinstance(lua_list, list):
        nested_candidates.extend(x for x in lua_list if isinstance(x, dict))
    elif isinstance(lua_list, dict):
        nested_candidates.append(lua_list)
    if isinstance(ua, dict) and ua not in nested_candidates:
        nested_candidates.append(ua)

    for dst, source_names in _DRAWING_FIELD_SOURCES.items():
        if _is_tradingview_drawing_json(out.get(dst)):
            continue  # already populated (chartData passthrough)
        picked = _pick_drawing_field(payload, *nested_candidates, names=source_names)
        if picked is not None:
            out[dst] = picked

    # Last-resort fallback: the LMS sometimes uses an unexpected field name
    # (e.g. `answer_json`, `submission_json`). Recursively scan the payload
    # for ANY TradingView-shaped dict and use it as the user's answer when
    # we still don't have one — better one drawing than none.
    if not _is_tradingview_drawing_json(out.get("answer_analysis_json")):
        scanned = _find_drawing_json(payload)
        if scanned is not None:
            logger.info(
                "single-result for id=%s: drawing JSON found via recursive scan "
                "(no known alias matched). Using it as `answer_analysis_json`.",
                payload.get("id"),
            )
            out["answer_analysis_json"] = scanned

    return out


def _single_to_session_shape(payload: Any) -> Dict[str, Any]:
    """Normalise a `single-result` response into the session shape that
    `compact_session` expects (`{questions: [...]}` + optional metadata).

    The upstream shape isn't strictly documented, so we tolerate three
    common layouts:
      1. Already a session-shaped dict (has `questions` array) — pass through.
      2. A thin wrapper (`{data: ...}` or `{result: ...}`) — unwrap once.
      3. A bare question dict — wrap into a one-question session.
    Single-result uses different field names than chartData; in cases (2) and
    (3) we run the question through `_normalize_single_result_question` so
    `question_no`/`user_answer`/`answer_analysis_json` end up populated.
    """
    if not isinstance(payload, dict):
        return {"questions": []}

    if isinstance(payload.get("questions"), list):
        return payload

    for wrapper in ("data", "result"):
        inner = payload.get(wrapper)
        if isinstance(inner, dict):
            if isinstance(inner.get("questions"), list):
                return inner
            return _wrap_single_question(_normalize_single_result_question(inner), payload)
        if isinstance(inner, list) and inner and isinstance(inner[0], dict):
            return {
                "questions": [
                    _normalize_single_result_question(q) for q in inner if isinstance(q, dict)
                ]
            }

    normalized = _normalize_single_result_question(payload)
    has_answer = _is_tradingview_drawing_json(normalized.get("answer_analysis_json"))
    has_correction = _is_tradingview_drawing_json(normalized.get("correction_analysis_json"))
    has_mentor = _is_tradingview_drawing_json(normalized.get("mentor_analysis_json"))
    logger.info(
        "single-result keys=%s; user_answer_present=%s; "
        "drawings: answer=%s correction=%s mentor=%s",
        sorted(payload.keys()),
        isinstance(normalized.get("user_answer"), dict),
        has_answer, has_correction, has_mentor,
    )
    if not (has_answer or has_correction or has_mentor):
        logger.warning(
            "single-result for answer_id=%s contained no TradingView drawing JSON "
            "in any known field (`answer_analysis_json`, `your_analysis`, "
            "`mentor_analysis_json`, `correction_analysis_json`, `right_analysis`) "
            "at the top level OR inside `learning_user_answer[]`, and a recursive "
            "scan also turned up nothing. The LMS may not embed drawings on this "
            "endpoint for this trade — use `chapter_id`+`date` instead.",
            payload.get("id"),
        )
    return _wrap_single_question(normalized, payload)


def _wrap_single_question(question: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap one normalized question into a session-shaped dict, lifting
    session-level fields (`category`, `sub_category`, `submit_date`, ...) from
    the source payload when present."""
    return {
        "id": source.get("session_id") or source.get("id"),
        "category": source.get("category"),
        "sub_category": source.get("sub_category"),
        "type": source.get("type"),
        "submit_date": source.get("submit_date"),
        "win": source.get("win"),
        "loss": source.get("loss"),
        "total_points": source.get("total_points") or source.get("points"),
        "total_questions": source.get("total_questions"),
        "win_loss_ratio": source.get("win_loss_ratio"),
        "questions": [question],
    }


def explain_from_multiple_answers(
    *,
    answer_ids: List[Union[int, str]],
    base_url: str = DEFAULT_BASE_URL,
    bearer_token: Optional[str] = None,
    verify_ssl: bool = False,
    max_workers: Optional[int] = None,
    fetch_candles_for_grading: bool = True,
    analysis_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch MULTIPLE trades via `/api/v1/learning/single-result/` in parallel,
    merge them into a single session, and run the explainer pipeline once.

    The result has the same shape as `explain_from_session` — a top-level
    session dict with `questions: [...]` (one entry per `answer_id`) plus
    per-question `explanation` markdown and a session-level `explanation`.
    """
    if not answer_ids:
        raise ValueError("answer_ids must contain at least one id")

    # Fetch single-result payloads in parallel — each is a single GET so the
    # bottleneck is the LMS, not our process.
    workers = max(1, min(CANDLE_FETCH_WORKERS, len(answer_ids)))
    payloads: List[Tuple[Union[int, str], Optional[Any], Optional[Exception]]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {
            pool.submit(
                fetch_single_result,
                answer_id=aid,
                base_url=base_url,
                bearer_token=bearer_token,
                verify_ssl=verify_ssl,
            ): aid
            for aid in answer_ids
        }
        for fut in as_completed(future_map):
            aid = future_map[fut]
            try:
                payloads.append((aid, fut.result(), None))
            except Exception as exc:
                logger.warning("single-result fetch failed for answer_id=%s: %s", aid, exc)
                payloads.append((aid, None, exc))

    # Restore the caller's original order — `as_completed` returns whichever
    # future finished first, but the response should match input order.
    order = {aid: i for i, aid in enumerate(answer_ids)}
    payloads.sort(key=lambda t: order.get(t[0], 0))

    questions: List[Dict[str, Any]] = []
    fetch_errors: List[Dict[str, Any]] = []
    for aid, payload, exc in payloads:
        if exc is not None or payload is None:
            fetch_errors.append({"answer_id": aid, "error": str(exc) if exc else "no payload"})
            continue
        session_shape = _single_to_session_shape(payload)
        for q in session_shape.get("questions") or []:
            if isinstance(q, dict):
                questions.append(q)

    if not questions:
        logger.warning(
            "No valid trades fetched from %d answer_id(s); errors: %s",
            len(answer_ids), fetch_errors,
        )
        return {
            "success": False,
            "message": "No data found for the mentioned ID(s).",
            "answer_ids": [str(a) for a in answer_ids],
            "fetch_errors": fetch_errors,
            "explanation": "No data found for the mentioned ID(s).",
        }

    session_json: Dict[str, Any] = {
        "id": None,
        "submit_date": None,
        "total_questions": len(questions),
        "questions": questions,
    }

    result = explain_from_session(
        session_json,
        max_questions=None,
        max_workers=max_workers,
        bearer_token=bearer_token,
        base_url=base_url,
        verify_ssl=verify_ssl,
        fetch_candles_for_grading=fetch_candles_for_grading,
        analysis_type=analysis_type,
    )
    if fetch_errors:
        result["fetch_errors"] = fetch_errors
    return result


def explain_from_single_answer(
    *,
    answer_id: Union[int, str],
    base_url: str = DEFAULT_BASE_URL,
    bearer_token: Optional[str] = None,
    verify_ssl: bool = False,
    max_workers: Optional[int] = None,
    fetch_candles_for_grading: bool = True,
    analysis_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch ONE trade via `/api/v1/learning/single-result/` and run the
    same explainer pipeline against just that trade."""
    payload = fetch_single_result(
        answer_id=answer_id,
        base_url=base_url,
        bearer_token=bearer_token,
        verify_ssl=verify_ssl,
    )
    session_json = _single_to_session_shape(payload)
    return explain_from_session(
        session_json,
        max_questions=None,
        max_workers=max_workers,
        bearer_token=bearer_token,
        base_url=base_url,
        verify_ssl=verify_ssl,
        fetch_candles_for_grading=fetch_candles_for_grading,
        analysis_type=analysis_type,
    )
