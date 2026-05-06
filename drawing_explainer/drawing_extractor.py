"""Compacts the LMS `result-screenshot-view` payload down to just the parts
the LLM needs to explain the user's drawings.

The raw upstream JSON is enormous (~700KB for one session) because it embeds
every TradingView chart-style configuration. We strip everything except:

  - Per-question metadata (pair, timeframe, dates, market, win/loss, RR)
  - The user's trade decision (`user_answer`) and the reference answer
    (`answer_buy_sell`, `stop_loss_price`, `take_profit_price`, `right_prediction`,
    the candle at decision time from `current_data.question`)
  - Each `LineTool*` drawing the user placed: id, type, the salient state
    fields (text / risk-reward levels / fib levels / pattern points), and
    the drawing's anchor points (price + UTC time)

The extractor never raises on missing fields — questions in the wild are
sometimes mid-edit and lack drawings entirely.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


# Fields on a drawing's `state` object worth surfacing to the LLM. Most of the
# remaining state is style (colors, fonts) which adds noise without information.
_STATE_FIELDS_BY_PREFIX = {
    "LineToolRiskReward": (
        "stopLevel", "profitLevel", "riskSize", "qty", "accountSize",
        "amountStop", "amountTarget", "riskDisplayMode",
    ),
    "LineToolNote": ("text",),
    "LineToolText": ("text",),
    "LineToolCallout": ("text",),
    "LineToolBalloon": ("text",),
    "LineToolFib": ("levels",),
    "LineToolTrendBasedFib": ("levels",),
    "LineToolGannFan": ("levels",),
    "LineToolPitchfork": ("style",),
    "LineToolHorzLine": ("text", "value"),
    "LineToolHorzRay": ("text", "value"),
    "LineToolVertLine": ("text",),
    "LineToolTrendLine": ("text",),
    "LineToolRay": ("text",),
    "LineToolExtended": ("text",),
    "LineToolRectangle": ("text",),
    "LineToolEllipse": ("text",),
    "LineToolPath": ("text",),
    "LineToolPolyline": ("text",),
    "LineTool5PointsPattern": ("text", "patternType"),
    "LineToolElliott": ("text", "degree"),
}


def _state_fields_for(tool_type: str) -> Iterable[str]:
    for prefix, fields in _STATE_FIELDS_BY_PREFIX.items():
        if tool_type.startswith(prefix):
            return fields
    return ("text",)


def _epoch_to_iso(time_t: Optional[int]) -> Optional[str]:
    if time_t is None:
        return None
    try:
        return datetime.fromtimestamp(int(time_t), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    except (TypeError, ValueError, OSError):
        return None


def _compact_point(p: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "price" in p:
        out["price"] = p["price"]
    t = p.get("time_t")
    if t is not None:
        out["time_t"] = t
        iso = _epoch_to_iso(t)
        if iso:
            out["time"] = iso
    return out


def _compact_fib_levels(levels_obj: Any) -> List[Dict[str, Any]]:
    """Fib levels live as `level1..levelN` in the state. Each is a tuple-ish
    list `[ratio, color, visible, ...]`. Keep just the ratio & visibility."""
    if not isinstance(levels_obj, dict):
        return []
    out: List[Dict[str, Any]] = []
    for k, v in sorted(levels_obj.items()):
        if not k.startswith("level"):
            continue
        if isinstance(v, list) and v:
            ratio = v[0] if len(v) > 0 else None
            visible = v[2] if len(v) > 2 else True
            out.append({"ratio": ratio, "visible": bool(visible)})
    return out


def _compact_drawing(source: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Compact one TradingView source to {id, type, state subset, points}.

    Returns None if it's not a `LineTool*` drawing (e.g. `MainSeries` or a
    study). We deliberately skip studies — those are not user drawings.
    """
    tool_type = source.get("type", "")
    if not isinstance(tool_type, str) or not tool_type.startswith("LineTool"):
        return None

    state = source.get("state") or {}
    interesting = {f: state[f] for f in _state_fields_for(tool_type) if f in state}

    # Fib-style tools store `level1`..`levelN` at the top of state, not in `levels`.
    if tool_type.startswith("LineToolFib") or tool_type.startswith("LineToolTrendBasedFib"):
        fib_levels = _compact_fib_levels({k: v for k, v in state.items() if k.startswith("level")})
        if fib_levels:
            interesting["levels"] = fib_levels

    points = [_compact_point(p) for p in (source.get("points") or []) if isinstance(p, dict)]

    return {
        "id": source.get("id"),
        "type": tool_type,
        "state": interesting,
        "points": points,
    }


def extract_drawings(analysis_json: Any) -> List[Dict[str, Any]]:
    """Pull every `LineTool*` source out of an `*_analysis_json` payload."""
    if not isinstance(analysis_json, dict):
        return []
    drawings: List[Dict[str, Any]] = []
    for chart in analysis_json.get("charts") or []:
        for pane in chart.get("panes") or []:
            for source in pane.get("sources") or []:
                d = _compact_drawing(source)
                if d:
                    drawings.append(d)
    return drawings


def _candle_summary(candle: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(candle, dict):
        return None
    return {
        "open": candle.get("open"),
        "high": candle.get("high"),
        "low": candle.get("low"),
        "close": candle.get("close"),
        "time": candle.get("timestamp") or _epoch_to_iso(
            (candle.get("time") or 0) // 1000 if candle.get("time") else None
        ),
    }


def compact_question(question: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce one question record (from `session["questions"]`) to a small
    LLM-ready dict containing all data needed to evaluate the user's drawings."""
    user_answer = question.get("user_answer") or {}

    user_drawings = extract_drawings(question.get("answer_analysis_json"))
    correction_drawings = extract_drawings(question.get("correction_analysis_json"))
    mentor_drawings = extract_drawings(question.get("mentor_analysis_json"))

    return {
        "id": question.get("id"),
        "question_no": question.get("question_no"),
        "pair": question.get("pair"),
        "timeframe": question.get("timeframe"),
        "market": question.get("market_name"),
        "from_date": question.get("from_date"),
        "to_date": question.get("to_date"),
        "is_drawing_only": question.get("is_drawing_only"),
        "is_single_timeframe": question.get("is_single_timeframe"),
        "win_loss": question.get("win_loss"),
        "risk_reward_ratio": question.get("risk_reward_ratio"),
        "trade_context": {
            "decision_candle": _candle_summary((user_answer.get("current_data") or {}).get("question")),
            "user_buy_price": user_answer.get("buy_price"),
            "user_stop_loss": (user_answer.get("stop_loss") or {}).get("close"),
            "user_take_profit": (user_answer.get("take_profit") or {}).get("close"),
            "user_quantity": user_answer.get("quantity"),
            "hit": user_answer.get("hit"),
            "point": user_answer.get("point"),
            "answer_direction": user_answer.get("answer_buy_sell"),
            "answer_stop_loss": user_answer.get("stop_loss_price"),
            "answer_take_profit": user_answer.get("take_profit_price"),
            "right_prediction_candle": _candle_summary(user_answer.get("right_prediction")),
        },
        "user_drawings": user_drawings,
        "correction_drawings": correction_drawings,
        "mentor_drawings": mentor_drawings,
        "drawing_counts": {
            "user": len(user_drawings),
            "corrections": len(correction_drawings),
            "mentor": len(mentor_drawings),
        },
    }


def compact_session(session: Dict[str, Any], *, max_questions: Optional[int] = None) -> Dict[str, Any]:
    """Reduce the full session JSON to the bare minimum needed by the LLM."""
    questions = session.get("questions") or []
    # Treat 0/negative as "no limit" — Swagger UI auto-fills integer fields
    # with 0 when the user doesn't clear them, which would otherwise truncate
    # the entire questions array.
    if max_questions is not None and max_questions > 0:
        questions = questions[:max_questions]

    return {
        "session_id": session.get("id"),
        "content_title": session.get("content_title"),
        "submit_date": session.get("submit_date"),
        "type": session.get("type"),
        "category": session.get("category"),
        "sub_category": session.get("sub_category"),
        "win": session.get("win"),
        "loss": session.get("loss"),
        "total_points": session.get("total_points"),
        "total_questions": session.get("total_questions"),
        "win_loss_ratio": session.get("win_loss_ratio"),
        "total_risk_reward_ratio": session.get("total_risk_reward_ratio"),
        "questions": [compact_question(q) for q in questions if isinstance(q, dict)],
    }
