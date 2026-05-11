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

    `question_no` is stripped from every question AFTER the markdown is
    rendered: the formatter still uses it to build the "Question N" header,
    but the frontend doesn't want the raw key on the JSON card (it confuses
    the rendering layer that derives ordering from array position instead).
    Array order already matches `question_no` because `explain_all` sorted
    by it, so removing the key is information-preserving.
    """
    for q in result.get("questions") or []:
        if isinstance(q, dict):
            q["explanation"] = format_question(q)
    result["explanation"] = format_session(result)
    for q in result.get("questions") or []:
        if isinstance(q, dict):
            q.pop("question_no", None)
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
    carry only the trade decision, not the TradingView drawings JSON.

    Now reports per-`requested_answer_id` info so the caller can see WHICH
    of the requested ids resolved to which compacted question, and detect
    when the LMS returned the same wrapper for multiple ids (a known LMS
    quirk — see the de-duplication note in `explain_from_multiple_answers`)."""
    questions = compact.get("questions") or []
    question_summaries = [
        {
            "requested_answer_id": q.get("requested_answer_id"),
            "id": q.get("id"),
            "user_drawings": (q.get("drawing_counts") or {}).get("user", 0),
            "has_chart_metadata": bool(q.get("pair") and q.get("timeframe")),
        }
        for q in questions
    ]

    # If multiple distinct requested_answer_ids resolved to the SAME
    # underlying question (same id + same question_no), surface that — it's
    # the symptom of the LMS returning a chapter-wide wrapper for any
    # answer_id within the chapter, with no per-trade differentiation.
    fingerprints = {(q.get("id"), q.get("question_no")) for q in questions}
    requested_ids = [s.get("requested_answer_id") for s in question_summaries]
    requested_unique = [a for a in requested_ids if a is not None]
    duplicate_warning: Optional[str] = None
    if len(requested_unique) >= 2 and len(fingerprints) == 1:
        duplicate_warning = (
            f"All {len(requested_unique)} requested answer_id(s) "
            f"({requested_unique}) resolved to the same underlying record "
            f"(id={questions[0].get('id')}, question_no={questions[0].get('question_no')}). "
            "The LMS likely returned the chapter-wide wrapper without "
            "differentiating by answer_id. Use `chapter_id` + `date` to fetch "
            "all drawings, or check whether each answer_id corresponds to a "
            "distinct trade in the LMS."
        )

    if not questions:
        message = "No data found for the mentioned ID."
    else:
        message = (
            "No data found for the mentioned ID(s) — the LMS returned the "
            "trade record(s) but no drawings JSON or chart metadata. Use "
            "`chapter_id` + `date` instead of `answer_id` if you need "
            "TradingView drawings."
        )
        if duplicate_warning:
            message += " " + duplicate_warning

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
    user_profile: Optional[Dict[str, Any]] = None,
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

    `user_profile` is an optional dict with `trading_style`, `user_level`,
    `assests`, `year_of_experience` keys. When supplied, the LLM tailors
    explanation depth, terminology, and trade-management focus to that
    profile. Empty / missing fields are simply omitted.

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

    result = explain_all(
        compact,
        max_workers=max_workers,
        analysis_type=analysis_type,
        user_profile=user_profile,
    )
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
    user_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fetch the session from the LMS endpoint, also fetch candles per
    question, then explain everything.

    Auto-recovery for partial chapters: when the upstream session reports a
    higher `total_questions` than the `questions` array contains, that means
    the LMS filtered some trades server-side — almost always because of
    `is_challenge_only=true` (practice trades excluded). When we detect that
    mismatch we refetch once with `is_challenge_only=false` to pull in the
    missing trades, then run the explainer on the complete chapter so the
    frontend gets one explanation per trade rather than mysteriously missing
    cards.
    """
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

    if is_challenge_only:
        upstream_total = session_json.get("total_questions")
        returned = session_json.get("questions") or []
        if (
            isinstance(upstream_total, int)
            and upstream_total > len(returned)
            and len(returned) >= 0
        ):
            logger.info(
                "Chapter %s: LMS returned %d/%d questions with "
                "is_challenge_only=true — refetching without the filter so the "
                "explainer can produce one card per trade.",
                chapter_id, len(returned), upstream_total,
            )
            try:
                full_session = fetch_drawing_session(
                    category=category,
                    sub_category=sub_category,
                    type=type,
                    date=date,
                    chapter_id=chapter_id,
                    user_type=user_type,
                    is_challenge_only=False,
                    base_url=base_url,
                    bearer_token=bearer_token,
                    verify_ssl=verify_ssl,
                )
            except Exception as exc:
                logger.warning(
                    "Chapter %s: refetch without is_challenge_only failed (%s). "
                    "Falling back to the original %d-question session.",
                    chapter_id, exc, len(returned),
                )
            else:
                full_returned = full_session.get("questions") or []
                if len(full_returned) > len(returned):
                    session_json = full_session

    return explain_from_session(
        session_json,
        max_questions=max_questions,
        max_workers=max_workers,
        bearer_token=bearer_token,
        base_url=base_url,
        verify_ssl=verify_ssl,
        fetch_candles_for_grading=fetch_candles_for_grading,
        analysis_type=analysis_type,
        user_profile=user_profile,
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


def _normalize_single_result_question(
    payload: Dict[str, Any],
    *,
    answer_id: Optional[Union[int, str]] = None,
) -> Dict[str, Any]:
    """Normalise a single-result payload into the question shape used by
    `compact_question`. Mutates a shallow copy and returns it.

    `answer_id` (the trade id originally requested) is used to pick the
    correct `learning_user_answer` entry when that field is a LIST of
    multiple attempts on the same question. Without this, picking `lua[0]`
    every time meant two `answer_id`s that share a wrapper response (the
    LMS sometimes returns the chapter-wide payload for any answer_id within
    that chapter) would collapse to the same compacted question, producing
    duplicate cards and a "no data" error.
    """
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
    # singular `user_answer` object. Pick the entry whose `id` matches the
    # requested `answer_id` so two answer_ids that share a wrapper produce
    # different compacted questions. Falls back to [0] when no match (legacy
    # behaviour, with a log line so the operator can see the ambiguity).
    matched: Optional[Dict[str, Any]] = None
    if not isinstance(out.get("user_answer"), dict):
        lua = out.get("learning_user_answer")
        if isinstance(lua, list) and lua:
            if answer_id is not None:
                requested = str(answer_id)
                for entry in lua:
                    if isinstance(entry, dict) and str(entry.get("id")) == requested:
                        matched = entry
                        break
            if matched is None and isinstance(lua[0], dict):
                if answer_id is not None:
                    available_ids = [
                        e.get("id") for e in lua if isinstance(e, dict)
                    ]
                    logger.info(
                        "single-result: requested answer_id=%s, no matching "
                        "entry in learning_user_answer (available=%s); "
                        "defaulting to first entry. The LMS may not "
                        "differentiate this answer_id from others in the "
                        "same chapter wrapper.",
                        answer_id, available_ids,
                    )
                matched = lua[0]
        elif isinstance(lua, dict):
            matched = lua
        if matched is not None:
            out["user_answer"] = matched

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
    # to nest the drawing inside the matched `learning_user_answer` entry).
    # CRITICAL: when learning_user_answer is a list, we ONLY look inside
    # the matched entry — not the whole list — so two answer_ids sharing a
    # wrapper don't cross-contaminate drawings between trades.
    nested_candidates: List[Dict[str, Any]] = []
    if isinstance(matched, dict):
        nested_candidates.append(matched)
    if isinstance(ua, dict) and ua not in nested_candidates:
        nested_candidates.append(ua)

    for dst, source_names in _DRAWING_FIELD_SOURCES.items():
        if _is_tradingview_drawing_json(out.get(dst)):
            continue  # already populated (chartData passthrough)
        picked = _pick_drawing_field(payload, *nested_candidates, names=source_names)
        if picked is not None:
            out[dst] = picked

    # Stamp the requested answer_id onto the normalized question so the
    # compactor + `_build_no_data_response` can show which id produced this
    # entry (helps diagnose multi-answer flows where the LMS returns the
    # same wrapper for several ids).
    if answer_id is not None:
        out.setdefault("requested_answer_id", answer_id)

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


def _single_to_session_shape(
    payload: Any,
    *,
    answer_id: Optional[Union[int, str]] = None,
) -> Dict[str, Any]:
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

    `answer_id` is threaded through so when `learning_user_answer` is a list
    of multiple attempts, we can pick the matching entry by id rather than
    always defaulting to `[0]`.
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
            return _wrap_single_question(
                _normalize_single_result_question(inner, answer_id=answer_id),
                payload,
            )
        if isinstance(inner, list) and inner and isinstance(inner[0], dict):
            return {
                "questions": [
                    _normalize_single_result_question(q, answer_id=answer_id)
                    for q in inner if isinstance(q, dict)
                ]
            }

    normalized = _normalize_single_result_question(payload, answer_id=answer_id)
    has_answer = _is_tradingview_drawing_json(normalized.get("answer_analysis_json"))
    has_correction = _is_tradingview_drawing_json(normalized.get("correction_analysis_json"))
    has_mentor = _is_tradingview_drawing_json(normalized.get("mentor_analysis_json"))
    logger.info(
        "single-result for answer_id=%s: keys=%s; user_answer_present=%s; "
        "drawings: answer=%s correction=%s mentor=%s",
        answer_id, sorted(payload.keys()),
        isinstance(normalized.get("user_answer"), dict),
        has_answer, has_correction, has_mentor,
    )
    if not (has_answer or has_correction or has_mentor):
        logger.warning(
            "single-result for answer_id=%s (wrapper id=%s) contained no "
            "TradingView drawing JSON in any known field (`answer_analysis_json`, "
            "`your_analysis`, `mentor_analysis_json`, `correction_analysis_json`, "
            "`right_analysis`) at the top level OR inside the matched "
            "`learning_user_answer` entry, and a recursive scan also turned up "
            "nothing. The LMS may not embed drawings on this endpoint for this "
            "trade — use `chapter_id`+`date` instead.",
            answer_id, payload.get("id"),
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
    user_profile: Optional[Dict[str, Any]] = None,
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
        # Thread answer_id so each call picks the correct learning_user_answer
        # entry — without this two ids that share a wrapper produce duplicate
        # questions (the bug that caused "No data found" on legitimate inputs).
        session_shape = _single_to_session_shape(payload, answer_id=aid)
        for q in session_shape.get("questions") or []:
            if isinstance(q, dict):
                # Stamp the requested id onto every question we extract from
                # this payload (the normalizer already does it for the matched
                # entry, but `data`/`result` wrapper paths skip that step).
                q.setdefault("requested_answer_id", aid)
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
        user_profile=user_profile,
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
    user_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fetch ONE trade via `/api/v1/learning/single-result/` and run the
    same explainer pipeline against just that trade."""
    payload = fetch_single_result(
        answer_id=answer_id,
        base_url=base_url,
        bearer_token=bearer_token,
        verify_ssl=verify_ssl,
    )
    session_json = _single_to_session_shape(payload, answer_id=answer_id)
    return explain_from_session(
        session_json,
        max_questions=None,
        max_workers=max_workers,
        bearer_token=bearer_token,
        base_url=base_url,
        verify_ssl=verify_ssl,
        fetch_candles_for_grading=fetch_candles_for_grading,
        analysis_type=analysis_type,
        user_profile=user_profile,
    )
