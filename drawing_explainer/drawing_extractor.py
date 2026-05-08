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

    # Rectangles: surface the fill color + the inferred zone kind so the LLM
    # doesn't have to read raw rgba strings (and won't invert demand/supply).
    if tool_type.startswith("LineToolRectangle"):
        bg = state.get("backgroundColor")
        if bg:
            interesting["backgroundColor"] = bg
        zone_kind = _classify_zone_color(state)
        if zone_kind:
            interesting["zone_kind"] = zone_kind

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


def _to_float(v: Any) -> Optional[float]:
    """Best-effort numeric coercion. Returns None when `v` isn't a real number
    (e.g. None / "" / "N/A") so downstream logic can branch on it cleanly."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _build_trade_facts(
    user_answer: Dict[str, Any], question: Dict[str, Any]
) -> Dict[str, Any]:
    """Pre-compute a flat, authoritative trade-facts block for the LLM.

    The LLM is told to cite these fields VERBATIM (see the prompt in
    `llm_explainer._PER_QUESTION_SYSTEM`). This prevents the hallucination
    pattern we saw on `openai/gpt-oss-120b` — e.g. reporting "TP set below
    entry" when TP was 5 points ABOVE entry, or quoting a 4× wrong stop
    distance — by removing arithmetic and nested-field-extraction from the
    model's job.

    Computed fields (so the model doesn't do math):
      - `stop_distance` / `target_distance`         absolute price deltas
      - `stop_distance_pct` / `target_distance_pct` % of entry
      - `rr_planned`                                target_distance / stop_distance
      - `rr_realized`                               from `risk_reward_ratio` (negative = SL hit)
      - `tp_above_entry` / `stop_above_entry`       direction sanity flags
      - `tp_direction_warning`                      set when TP is on the wrong side of entry
    """
    direction = user_answer.get("answer_buy_sell")  # "buy" / "sell"
    entry = _to_float(user_answer.get("buy_price"))

    # The LMS exposes SL/TP in two parallel shapes. Prefer the validated
    # `*_price` fields when present; fall back to the nested `.close` ones
    # so we still produce facts on legacy payloads.
    sl_answer = _to_float(user_answer.get("stop_loss_price"))
    tp_answer = _to_float(user_answer.get("take_profit_price"))
    sl_close = _to_float((user_answer.get("stop_loss") or {}).get("close"))
    tp_close = _to_float((user_answer.get("take_profit") or {}).get("close"))
    sl = sl_answer if sl_answer is not None else sl_close
    tp = tp_answer if tp_answer is not None else tp_close

    facts: Dict[str, Any] = {
        "direction": direction,
        "entry_price": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "hit": user_answer.get("hit"),
        "outcome": question.get("win_loss"),
        "result_points": user_answer.get("point"),
    }

    if entry is not None and sl is not None:
        facts["stop_distance"] = round(abs(entry - sl), 6)
        if entry != 0:
            facts["stop_distance_pct"] = round(abs(entry - sl) / abs(entry) * 100, 4)
        facts["stop_above_entry"] = sl > entry

    if entry is not None and tp is not None:
        facts["target_distance"] = round(abs(tp - entry), 6)
        if entry != 0:
            facts["target_distance_pct"] = round(abs(tp - entry) / abs(entry) * 100, 4)
        facts["tp_above_entry"] = tp > entry

    if (
        entry is not None and sl is not None and tp is not None
        and abs(entry - sl) > 1e-9
    ):
        facts["rr_planned"] = round(abs(tp - entry) / abs(entry - sl), 4)

    facts["rr_realized"] = _to_float(question.get("risk_reward_ratio"))

    # Direction sanity check — long with TP <= entry, or short with TP >= entry,
    # is structurally invalid. Surface this as a warning the LLM is told to quote.
    if entry is not None and tp is not None and direction:
        if direction == "buy" and tp <= entry:
            facts["tp_direction_warning"] = (
                f"TP {tp} is at or below entry {entry} on a LONG — "
                "structurally invalid: target must be above entry on a buy."
            )
        elif direction == "sell" and tp >= entry:
            facts["tp_direction_warning"] = (
                f"TP {tp} is at or above entry {entry} on a SHORT — "
                "structurally invalid: target must be below entry on a sell."
            )

    return facts


# ─────────────────── zone-color → kind tagging ───────────────────
# TradingView's stock palette uses well-known fills for supply/demand
# rectangles. Tagging each rectangle here means the LLM never has to read raw
# rgba strings — it sees `state.zone_kind: "demand"` / `"supply"` directly,
# which removes the inverted-zone hallucination we saw on gpt-oss-120b
# (calling a green ₹242 box a "supply zone" when it was clearly drawn as
# demand by the mentor).

_GREEN_HINTS = (
    "4caf50",       # Material green
    "089981",       # TradingView default bull
    "76, 175, 80",  # rgba Material green
    "8, 153, 129",  # rgba TV bull
    "00c853",       # bright green
    "26a69a",       # teal-green
)
_RED_HINTS = (
    "f23645",       # TV default bear
    "242, 54, 69",  # rgba TV bear
    "ef5350",       # coral-red
    "f44336",       # Material red
    "244, 67, 54",  # rgba Material red
)


def _classify_zone_color(state: Dict[str, Any]) -> Optional[str]:
    """Map a rectangle's fill color to a `demand` / `supply` tag, or None
    for neutral / unrecognised colors so we never mislabel."""
    bg = state.get("backgroundColor") or state.get("color")
    if not isinstance(bg, str):
        return None
    bg_lower = bg.lower()
    if any(h in bg_lower for h in _GREEN_HINTS):
        return "demand"
    if any(h in bg_lower for h in _RED_HINTS):
        return "supply"
    return None


# ─────────────────── plain-English drawings summary ───────────────────
# The LLM kept hallucinating colors ("two purple rectangles drawn") even with
# `state.zone_kind` available, because it was reading the raw drawing JSON
# field-by-field. Pre-rendering each drawing as a single English line — with
# the kind, prices, and time pre-extracted — eliminates that whole class of
# error: there's no `state.color` for the LLM to misread because we don't
# include it in the summary.

def _fmt_price(p: Any) -> Optional[str]:
    """Compact price formatter — drops trailing zeros, keeps 4 decimals max."""
    f = _to_float(p)
    if f is None:
        return None
    s = f"{f:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _short_time(time_t: Optional[int]) -> Optional[str]:
    """`2025-12-12 11:15Z` short form for the summary text. Compatible with
    `_epoch_to_iso` output which is `YYYY-MM-DD HH:MM:SSZ` — we just trim the
    seconds since intra-day candles align to minute boundaries."""
    iso = _epoch_to_iso(time_t)
    if not iso:
        return None
    return iso[:16] + "Z" if len(iso) >= 16 else iso


def _summarise_drawing(d: Dict[str, Any], who: str) -> Optional[str]:
    """Render one compacted drawing as a single line of English. `who` is
    "User" / "Mentor" / "Correction" so the LLM knows whose drawing it is."""
    tool = d.get("type", "")
    state = d.get("state") or {}
    points = d.get("points") or []
    text = (state.get("text") or "").strip().replace("\n", " ").replace("\r", " ")

    if tool.startswith("LineToolRectangle"):
        prices = [_to_float(p.get("price")) for p in points]
        prices = [p for p in prices if p is not None]
        if not prices:
            return None
        lo = _fmt_price(min(prices))
        hi = _fmt_price(max(prices))
        kind = state.get("zone_kind")
        if kind == "demand":
            return f"{who} demand zone (bullish OB / support): {lo}–{hi}" + (f"  [note: {text!r}]" if text else "")
        if kind == "supply":
            return f"{who} supply zone (bearish OB / resistance): {lo}–{hi}" + (f"  [note: {text!r}]" if text else "")
        return f"{who} rectangle: {lo}–{hi} (zone kind unknown)" + (f"  [note: {text!r}]" if text else "")

    if tool.startswith("LineToolRiskReward"):
        # Long / short variant, plus stopLevel / profitLevel deltas in state.
        is_long = "Long" in tool
        entry = _fmt_price(points[0].get("price")) if points else None
        stop_level = _fmt_price(state.get("stopLevel"))
        profit_level = _fmt_price(state.get("profitLevel"))
        side = "LONG" if is_long else "SHORT"
        bits = [f"{who} Risk-Reward {side}"]
        if entry:
            bits.append(f"entry {entry}")
        if stop_level:
            bits.append(f"stop-distance {stop_level}")
        if profit_level:
            bits.append(f"target-distance {profit_level}")
        return ", ".join(bits)

    if tool in {"LineToolNote", "LineToolText", "LineToolCallout", "LineToolBalloon"}:
        if not points:
            return None
        price = _fmt_price(points[0].get("price"))
        when = _short_time(points[0].get("time_t"))
        label = text or "(empty)"
        loc = f"at {price}" if price else "(no price)"
        return f"{who} {tool.replace('LineTool', '').lower()} {label!r} {loc}" + (f", time {when}" if when else "")

    if tool.startswith("LineToolFib") or tool.startswith("LineToolTrendBasedFib"):
        if len(points) < 2:
            return None
        a = _fmt_price(points[0].get("price"))
        b = _fmt_price(points[1].get("price"))
        return f"{who} Fibonacci retracement: {a} → {b}"

    if tool in {"LineToolTrendLine", "LineToolRay", "LineToolExtended"}:
        if len(points) < 2:
            return None
        a_p, b_p = _fmt_price(points[0].get("price")), _fmt_price(points[1].get("price"))
        a_t, b_t = _short_time(points[0].get("time_t")), _short_time(points[1].get("time_t"))
        line = f"{who} {tool.replace('LineTool', '').lower()}: {a_p} ({a_t}) → {b_p} ({b_t})"
        return line + (f"  [{text}]" if text else "")

    if tool in {"LineToolHorzLine", "LineToolHorzRay"}:
        price = _fmt_price(state.get("value")) or (_fmt_price(points[0].get("price")) if points else None)
        if not price:
            return None
        return f"{who} horizontal line at {price}" + (f"  [{text}]" if text else "")

    # Generic fallback — just record that the drawing exists with its anchor prices.
    if points:
        prices = [_fmt_price(p.get("price")) for p in points if p.get("price") is not None]
        prices = [p for p in prices if p]
        if prices:
            return f"{who} {tool.replace('LineTool', '').lower()}: anchors {', '.join(prices)}"
    return f"{who} {tool}"


def _build_drawings_summary(
    user_drawings: List[Dict[str, Any]],
    mentor_drawings: List[Dict[str, Any]],
    correction_drawings: List[Dict[str, Any]],
) -> List[str]:
    """Pre-render every drawing as a single English line. The LLM is told to
    use this list as ground truth and never describe drawings by raw color
    (which is where the "two purple rectangles" hallucination came from)."""
    out: List[str] = []
    for d in mentor_drawings or []:
        s = _summarise_drawing(d, "Mentor")
        if s:
            out.append(s)
    for d in correction_drawings or []:
        s = _summarise_drawing(d, "Correction")
        if s:
            out.append(s)
    for d in user_drawings or []:
        s = _summarise_drawing(d, "User")
        if s:
            out.append(s)
    return out


def _zone_bounds(d: Dict[str, Any]) -> Optional[tuple]:
    """For a rectangle drawing, return (low, high) of its price anchors."""
    if not d.get("type", "").startswith("LineToolRectangle"):
        return None
    prices = [_to_float(p.get("price")) for p in (d.get("points") or [])]
    prices = [p for p in prices if p is not None]
    if not prices:
        return None
    return (min(prices), max(prices))


def _build_structural_observations(
    trade_facts: Dict[str, Any],
    mentor_drawings: List[Dict[str, Any]],
    user_drawings: List[Dict[str, Any]],
) -> List[str]:
    """Auto-detect structural mismatches between the trader's entry/SL/TP and
    the zones drawn on the chart. Each item is a one-line observation the LLM
    can quote. Only fires when we have the data to be confident — no zones
    or no entry → empty list."""
    obs: List[str] = []
    direction = trade_facts.get("direction")
    entry = trade_facts.get("entry_price")
    sl = trade_facts.get("stop_loss")
    tp = trade_facts.get("take_profit")
    if entry is None:
        return obs

    # Build a list of (kind, lo, hi, source) for every classified rectangle.
    zones: List[tuple] = []
    for d in (mentor_drawings or []) + (user_drawings or []):
        bounds = _zone_bounds(d)
        if bounds is None:
            continue
        kind = (d.get("state") or {}).get("zone_kind")
        if kind not in ("demand", "supply"):
            continue
        source = "mentor" if d in (mentor_drawings or []) else "user"
        zones.append((kind, bounds[0], bounds[1], source))

    if not zones:
        return obs

    demand_zones = [(lo, hi, src) for kind, lo, hi, src in zones if kind == "demand"]
    supply_zones = [(lo, hi, src) for kind, lo, hi, src in zones if kind == "supply"]

    def _in_zone(price: float, lo: float, hi: float) -> bool:
        return lo <= price <= hi

    # Long-trade structural checks — entry should land IN or just above the
    # demand zone (the bounce level), stop just below the demand low, TP at
    # or below the next supply zone.
    if direction == "buy":
        for lo, hi, src in demand_zones:
            if entry < lo:
                obs.append(
                    f"Entry {_fmt_price(entry)} is BELOW the {src} demand zone "
                    f"({_fmt_price(lo)}–{_fmt_price(hi)}) — a long should enter "
                    f"AT or near the zone, not below it. The trade has no "
                    f"structural support from this OB."
                )
            elif _in_zone(entry, lo, hi):
                obs.append(
                    f"Entry {_fmt_price(entry)} is INSIDE the {src} demand zone "
                    f"({_fmt_price(lo)}–{_fmt_price(hi)}) — this is the textbook "
                    f"entry location for a long, provided a CHoCH/BOS confirms."
                )
            elif entry > hi:
                obs.append(
                    f"Entry {_fmt_price(entry)} is ABOVE the {src} demand zone "
                    f"({_fmt_price(lo)}–{_fmt_price(hi)}) — chasing the move; "
                    f"better to wait for a retest into the zone."
                )

            if sl is not None and _in_zone(sl, lo, hi):
                obs.append(
                    f"Stop {_fmt_price(sl)} is INSIDE the {src} demand zone "
                    f"({_fmt_price(lo)}–{_fmt_price(hi)}) — stop should sit "
                    f"BELOW {_fmt_price(lo)} so a wick into the zone doesn't "
                    f"flush the trade."
                )

            if tp is not None and tp <= hi:
                obs.append(
                    f"TP {_fmt_price(tp)} is AT or BELOW the demand zone top "
                    f"({_fmt_price(hi)}) — a long target should be ABOVE the "
                    f"demand zone, ideally at the next supply level."
                )

        for lo, hi, src in supply_zones:
            if tp is not None and _in_zone(tp, lo, hi):
                obs.append(
                    f"TP {_fmt_price(tp)} is INSIDE the {src} supply zone "
                    f"({_fmt_price(lo)}–{_fmt_price(hi)}) — taking profit at "
                    f"resistance is reasonable, but consider scaling out at "
                    f"the zone's low rather than mid-zone."
                )

    # Short-trade mirror checks.
    elif direction == "sell":
        for lo, hi, src in supply_zones:
            if entry > hi:
                obs.append(
                    f"Entry {_fmt_price(entry)} is ABOVE the {src} supply zone "
                    f"({_fmt_price(lo)}–{_fmt_price(hi)}) — a short should enter "
                    f"AT or near the zone, not above it."
                )
            elif _in_zone(entry, lo, hi):
                obs.append(
                    f"Entry {_fmt_price(entry)} is INSIDE the {src} supply zone "
                    f"({_fmt_price(lo)}–{_fmt_price(hi)}) — textbook short entry "
                    f"location, provided a CHoCH/BOS confirms."
                )
            elif entry < lo:
                obs.append(
                    f"Entry {_fmt_price(entry)} is BELOW the {src} supply zone "
                    f"({_fmt_price(lo)}–{_fmt_price(hi)}) — chasing the move; "
                    f"better to wait for a retest into the zone."
                )

            if sl is not None and _in_zone(sl, lo, hi):
                obs.append(
                    f"Stop {_fmt_price(sl)} is INSIDE the {src} supply zone "
                    f"({_fmt_price(lo)}–{_fmt_price(hi)}) — stop should sit "
                    f"ABOVE {_fmt_price(hi)}."
                )

    return obs


# ─────────────────── post-entry market aftermath ───────────────────
# The LLM keeps inventing specific next-candle prices ("fell through 236.37",
# "rejected to 323.2") to make the narrative concrete. We pre-render exactly
# what the LMS knows happened — entry candle, where the SL/TP got hit, hit
# date — so the model has factual content to paraphrase rather than imagine.

def _build_market_aftermath(user_answer: Dict[str, Any]) -> Optional[str]:
    """Render a one-line factual summary of what price did after entry, using
    only fields present in `user_answer`. Returns None when there's nothing
    sourceable — caller will let the LLM describe direction-only in that case.

    DESIGN — entry-candle timestamp is intentionally excluded:
      • The LLM was reformatting / hallucinating the entry timestamp
        (writing 2026-01-22T14:15:00Z when the source said 2026-01-15
        10:15:00Z). The fix is to remove the entry-candle time entirely so
        there's no field for the model to misread, and to enforce a
        prompt-side rule (TIMESTAMP RULE in `llm_explainer._PER_QUESTION_SYSTEM`)
        that "entry is described by price only — no entry timestamp".
      • We also stopped quoting `decision.close` as "Entry candle close: X" —
        that conflated the candle close with the trader's execution price
        (`buy_price`). Entry is now anchored on `buy_price` from `trade_facts`
        (the LLM has it there); aftermath only lists end-of-trade data.

    Result-candle timestamp + OHLC IS retained — that's the verified hit
    moment from `right_prediction` and is the only date the LLM is allowed
    to cite in `market_did`.
    """
    aftermath = user_answer.get("right_prediction") or {}
    hit = user_answer.get("hit")
    points = _to_float(user_answer.get("point"))

    bits: List[str] = []

    # Where the trade resolved — open / low / high of the SL/TP-hit candle.
    a_open = _to_float(aftermath.get("open"))
    a_high = _to_float(aftermath.get("high"))
    a_low = _to_float(aftermath.get("low"))
    a_close = _to_float(aftermath.get("close"))
    a_time = aftermath.get("timestamp") or _epoch_to_iso(
        (aftermath.get("time") or 0) // 1000 if aftermath.get("time") else None
    )
    if any(v is not None for v in (a_open, a_high, a_low, a_close)):
        ohlc_bits = []
        if a_open is not None:
            ohlc_bits.append(f"open {_fmt_price(a_open)}")
        if a_high is not None:
            ohlc_bits.append(f"high {_fmt_price(a_high)}")
        if a_low is not None:
            ohlc_bits.append(f"low {_fmt_price(a_low)}")
        if a_close is not None:
            ohlc_bits.append(f"close {_fmt_price(a_close)}")
        outcome_label = {
            "stop_loss": "Stop-loss hit",
            "take_profit": "Take-profit hit",
        }.get(hit or "", "Trade resolved")
        when = f" on {a_time}" if a_time else ""
        bits.append(f"{outcome_label}{when}: {', '.join(ohlc_bits)}")

    if points is not None:
        bits.append(f"Result: {points:+g} points")

    return ". ".join(bits) + "." if bits else None


# ─────────────────── deterministic score breakdown ───────────────────
# Two trades with different structure should NOT get the same score. The LLM
# was scoring narratively, which produced ONGC (no demand zone touched, bad
# R:R, SL hit) and ITC (drawn demand zone, 2.35:1 R:R, SL hit) both at 2.5/10.
# We now apply a points rubric deterministically so the score reflects the
# objective structural quality of the setup.

def _extract_classified_zones(
    mentor_drawings: List[Dict[str, Any]], user_drawings: List[Dict[str, Any]]
) -> List[tuple]:
    """Return every classified rectangle as `(kind, lo, hi, source)` so scoring,
    role-classification, and observation builders share the same source of
    truth. `kind` ∈ {'demand', 'supply'}, `source` ∈ {'mentor', 'user'}."""
    out: List[tuple] = []
    for d in (mentor_drawings or []):
        bounds = _zone_bounds(d)
        if bounds is None:
            continue
        kind = (d.get("state") or {}).get("zone_kind")
        if kind not in ("demand", "supply"):
            continue
        out.append((kind, bounds[0], bounds[1], "mentor"))
    for d in (user_drawings or []):
        bounds = _zone_bounds(d)
        if bounds is None:
            continue
        kind = (d.get("state") or {}).get("zone_kind")
        if kind not in ("demand", "supply"):
            continue
        out.append((kind, bounds[0], bounds[1], "user"))
    return out


def _classify_zone_roles(
    zones: List[tuple], trade_facts: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Assign a contextual role to every classified zone relative to the trade
    direction and entry price. Output is one dict per zone with `role`,
    `role_note`, and the original geometry — the LLM is told to mention
    EVERY entry of this list (Problem 4 — "explanation ignores the upper /
    secondary zone").

    Role taxonomy (matches the spec at
    `drawing_explainer/explain_api_enhancement_task.md`, with two extra
    cases for zones that sit on the broken side of the trade):

      ENTRY_ZONE          — entry sits inside the zone (textbook entry)
      MISSED_DEMAND       — long: demand zone below entry (should have waited)
      MISSED_SUPPLY       — short: supply zone above entry
      TARGET_SUPPLY       — long: supply zone above entry (TP / partial exit)
      TARGET_DEMAND       — short: demand zone below entry
      DEMAND_ABOVE_ENTRY  — long: demand zone above entry (anti-structural —
                            entry preceded the zone or zone was breached)
      SUPPLY_BELOW_ENTRY  — short: supply zone below entry
      SUPPORT_REFERENCE   — context-only zone below entry (long / short)
      RESISTANCE_REFERENCE— context-only zone above entry
      UNCLASSIFIED        — direction unknown / inputs incomplete
    """
    direction = trade_facts.get("direction")
    entry = _to_float(trade_facts.get("entry_price"))
    if entry is None:
        return [
            {"kind": k, "low": lo, "high": hi, "source": src,
             "role": "UNCLASSIFIED",
             "role_note": "No entry price — role cannot be classified."}
            for k, lo, hi, src in zones
        ]

    enriched: List[Dict[str, Any]] = []
    for kind, lo, hi, src in zones:
        mid = (lo + hi) / 2

        if lo <= entry <= hi:
            role = "ENTRY_ZONE"
            note = (
                f"Entry {_fmt_price(entry)} sits INSIDE this {kind} zone — "
                "valid structural entry location."
            )
        elif direction == "buy":
            if mid < entry:                      # zone below entry
                if kind == "demand":
                    role = "MISSED_DEMAND"
                    note = (
                        f"Demand zone ({_fmt_price(lo)}–{_fmt_price(hi)}) sits "
                        f"below entry — should have waited for retest into "
                        "this zone before entering long."
                    )
                else:                             # supply below entry
                    role = "SUPPORT_REFERENCE"
                    note = (
                        f"Supply zone ({_fmt_price(lo)}–{_fmt_price(hi)}) below "
                        "entry — context only (price already broke through)."
                    )
            else:                                 # zone above entry
                if kind == "supply":
                    role = "TARGET_SUPPLY"
                    note = (
                        f"Supply zone ({_fmt_price(lo)}–{_fmt_price(hi)}) above "
                        "entry — TP reference / partial-exit level for the long."
                    )
                else:                             # demand above entry
                    role = "DEMAND_ABOVE_ENTRY"
                    note = (
                        f"Demand zone ({_fmt_price(lo)}–{_fmt_price(hi)}) sits "
                        "ABOVE entry — entry preceded the zone, anti-structural "
                        "for a long (price hadn't yet reached or had broken "
                        "through the zone)."
                    )
        elif direction == "sell":
            if mid > entry:                      # zone above entry
                if kind == "supply":
                    role = "MISSED_SUPPLY"
                    note = (
                        f"Supply zone ({_fmt_price(lo)}–{_fmt_price(hi)}) sits "
                        "above entry — should have waited for retest into this "
                        "zone before entering short."
                    )
                else:                             # demand above entry
                    role = "RESISTANCE_REFERENCE"
                    note = (
                        f"Demand zone ({_fmt_price(lo)}–{_fmt_price(hi)}) above "
                        "entry — context only (price already broke through)."
                    )
            else:                                 # zone below entry
                if kind == "demand":
                    role = "TARGET_DEMAND"
                    note = (
                        f"Demand zone ({_fmt_price(lo)}–{_fmt_price(hi)}) below "
                        "entry — TP reference / partial-exit level for the short."
                    )
                else:                             # supply below entry
                    role = "SUPPLY_BELOW_ENTRY"
                    note = (
                        f"Supply zone ({_fmt_price(lo)}–{_fmt_price(hi)}) below "
                        "entry — entry preceded the zone, anti-structural for "
                        "a short."
                    )
        else:
            role = "UNCLASSIFIED"
            note = "Direction unknown — review zone placement manually."

        enriched.append({
            "kind": kind,
            "low": lo,
            "high": hi,
            "source": src,
            "role": role,
            "role_note": note,
        })

    return enriched


def _build_score_breakdown(
    trade_facts: Dict[str, Any],
    drawings_summary: List[str],
    structural_observations: List[str],
    zones: List[tuple],
    has_style_mismatch: bool = False,
) -> Dict[str, Any]:
    """Compute a points-based score using the rubric in
    `explain_api_enhancement_task.md` Problem 2. The LLM is told to copy
    `base_score` verbatim into `overall_score` (and may optionally adjust by
    ±1.0 if it observes a CHoCH/BOS confirmation that this rubric can't see).

    Rubric (each criterion max 2.0 → 10.0 max base):

      1. Direction        TP hit = +2.0  ·  SL hit = +0.5
      2. Zone identification    2+ drawn = +2.0  ·  1 = +1.0  ·  0 = +0.0
      3. Entry precision  inside same-kind zone = +2.0  ·  near (<2% of
                          entry) = partial 0.5–1.5  ·  else = +0.0
      4. Risk management  RR≥3 = +2.0  ·  ≥2 = +1.5  ·  ≥1 = +0.5  ·  else 0
      5. Process discipline   RR tool +0.7 + SL +0.7 + TP +0.6 (max 2.0)

    Deductions (applied AFTER the criteria sum):
       - Anti-structural entry (entry on broken side of same-kind zone):  -1.5
       - TP on wrong side of entry (`tp_direction_warning`):              -2.0
       - Trading-style mismatch (Scalper-with-swing setup etc.):          -0.5

    Final score is clamped to [0.0, 10.0].
    """
    direction = trade_facts.get("direction")
    entry = _to_float(trade_facts.get("entry_price"))
    rr_planned = _to_float(trade_facts.get("rr_planned"))
    hit = trade_facts.get("hit")

    same_kind_zones = [
        (lo, hi) for kind, lo, hi, _src in zones
        if (direction == "buy" and kind == "demand")
        or (direction == "sell" and kind == "supply")
    ]

    criteria: List[Dict[str, Any]] = []
    score = 0.0

    # 1. Direction (max 2.0)
    if hit == "take_profit":
        criteria.append({"criterion": "Direction", "score": 2.0, "max": 2.0,
                         "note": "Take-profit hit — direction was correct"})
        score += 2.0
    else:
        # SL hit OR no resolution — direction may have been right but timing failed
        criteria.append({"criterion": "Direction", "score": 0.5, "max": 2.0,
                         "note": "Stop-loss hit — direction or timing was off"})
        score += 0.5

    # 2. Zone identification (max 2.0)
    zone_count = len(zones)
    if zone_count >= 2:
        criteria.append({"criterion": "Zone identification", "score": 2.0, "max": 2.0,
                         "note": f"{zone_count} structural zones drawn"})
        score += 2.0
    elif zone_count == 1:
        criteria.append({"criterion": "Zone identification", "score": 1.0, "max": 2.0,
                         "note": "Only 1 zone drawn"})
        score += 1.0
    else:
        criteria.append({"criterion": "Zone identification", "score": 0.0, "max": 2.0,
                         "note": "No structural zones drawn"})

    # 3. Entry precision (max 2.0)
    entry_pts = 0.0
    entry_note = "Entry placement vs zones inconclusive"
    entry_anti_structural = False
    if entry is not None and same_kind_zones:
        in_zone = any(lo <= entry <= hi for lo, hi in same_kind_zones)
        if in_zone:
            entry_pts = 2.0
            entry_note = "Entry inside a valid same-kind zone — textbook structural entry"
        else:
            distances = []
            for lo, hi in same_kind_zones:
                if entry > hi:
                    distances.append(("above", entry - hi, lo, hi))
                elif entry < lo:
                    distances.append(("below", lo - entry, lo, hi))
            if distances:
                side, dist, near_lo, near_hi = min(distances, key=lambda d: d[1])
                dist_pct = (dist / entry) * 100 if entry > 0 else 100.0
                # Anti-structural = entry on the broken side of the same-kind
                # zone (long below demand, short above supply). Triggers a
                # deduction below — no partial credit here either.
                if (direction == "buy" and side == "below") \
                        or (direction == "sell" and side == "above"):
                    entry_anti_structural = True
                    entry_note = (
                        f"Entry placed on the WRONG side of the zone "
                        f"(zone {near_lo}–{near_hi} was breached)"
                    )
                elif dist_pct < 2.0:
                    entry_pts = max(0.5, round(2.0 - dist_pct / 2.0, 1))
                    entry_note = (
                        f"Entry {dist_pct:.2f}% {side} the nearest valid zone "
                        f"({near_lo}–{near_hi}) — too early or too late"
                    )
                else:
                    entry_note = (
                        f"Entry {dist_pct:.2f}% {side} the nearest valid zone "
                        f"({near_lo}–{near_hi}) — outside the 2% tolerance"
                    )
    elif not same_kind_zones and zones:
        entry_note = "No same-kind zone drawn for the trade direction"
    criteria.append({"criterion": "Entry precision", "score": entry_pts, "max": 2.0, "note": entry_note})
    score += entry_pts

    # 4. Risk management (max 2.0)
    if rr_planned is None:
        rr_pts, rr_note = 0.0, "R:R not computable"
    elif rr_planned >= 3.0:
        rr_pts, rr_note = 2.0, f"R:R {rr_planned}:1 — excellent"
    elif rr_planned >= 2.0:
        rr_pts, rr_note = 1.5, f"R:R {rr_planned}:1 — acceptable"
    elif rr_planned >= 1.0:
        rr_pts, rr_note = 0.5, f"R:R {rr_planned}:1 — below minimum 2:1"
    else:
        rr_pts, rr_note = 0.0, f"R:R {rr_planned}:1 — negative or invalid"
    criteria.append({"criterion": "Risk management", "score": rr_pts, "max": 2.0, "note": rr_note})
    score += rr_pts

    # 5. Process discipline (max 2.0)
    has_rr_tool = any("Risk-Reward" in s for s in (drawings_summary or []))
    has_sl = trade_facts.get("stop_loss") is not None
    has_tp = trade_facts.get("take_profit") is not None
    process_pts = (0.7 if has_rr_tool else 0.0) + (0.7 if has_sl else 0.0) + (0.6 if has_tp else 0.0)
    process_pts = round(min(2.0, process_pts), 1)
    process_bits: List[str] = []
    if has_rr_tool:
        process_bits.append("R:R tool used")
    if has_sl:
        process_bits.append("SL defined")
    if has_tp:
        process_bits.append("TP defined")
    criteria.append({
        "criterion": "Process discipline",
        "score": process_pts, "max": 2.0,
        "note": " + ".join(process_bits) or "No structured entry tools used",
    })
    score += process_pts

    # ── Deductions ──
    deductions: List[Dict[str, Any]] = []
    if entry_anti_structural:
        score -= 1.5
        deductions.append({
            "reason": "Entry on broken side of same-kind zone (anti-structural)",
            "delta": -1.5,
        })
    if "tp_direction_warning" in trade_facts:
        score -= 2.0
        deductions.append({
            "reason": "TP on wrong side of entry (structurally invalid)",
            "delta": -2.0,
        })
    if has_style_mismatch:
        score -= 0.5
        deductions.append({
            "reason": "Trading style vs setup mismatch",
            "delta": -0.5,
        })

    base_score = max(0.0, min(10.0, round(score, 1)))

    return {
        "rubric_max": 10.0,
        "criteria": criteria,
        "deductions": deductions,
        "base_score": base_score,
        "scoring_note": (
            "Copy `base_score` to `overall_score` verbatim. You MAY adjust by "
            "±1.0 if you observe a CHoCH/BOS confirmation in price_context "
            "(this rubric can't see structural breaks). Final `overall_score` "
            "must stay within [0.0, 10.0]."
        ),
    }


# ─────────────────── trading-style vs setup mismatch ───────────────────
# A user identifying as "Scalper" but submitting a 26-point target on a ₹325
# stock is doing a swing setup in a scalper's account. Detecting this is more
# valuable feedback than just criticising the stop width in isolation.

# Typical target-distance bands per trading style (% of entry).
# Calibrated to common Indian-market trade sizes; same rough ratios work for
# forex/crypto when used as a relative scale. Lower bound is generous so
# tighter-than-typical setups don't false-fire.
_STYLE_TARGET_PCT_BANDS = {
    "Scalper":           (0.0, 0.7),
    "Intraday Trader":   (0.2, 2.5),
    "Swing Trader":      (1.5, 12.0),
    "Positional Trader": (4.0, 60.0),
}


def _implied_style_for_pct(pct: float) -> str:
    """Reverse-map a target % back to the trading style that fits it best."""
    if pct < 0.7:
        return "scalp"
    if pct < 2.5:
        return "intraday"
    if pct < 12.0:
        return "swing"
    return "positional"


def _build_style_alignment(
    trading_style: Optional[str], trade_facts: Dict[str, Any]
) -> Optional[str]:
    """Return a one-sentence warning when the trade's target % is way out of
    band for the user's stated trading style. None when no profile or no
    mismatch."""
    if not trading_style:
        return None
    pct = _to_float(trade_facts.get("target_distance_pct"))
    if pct is None:
        return None
    band = _STYLE_TARGET_PCT_BANDS.get(trading_style)
    if not band:
        return None
    lo, hi = band
    if pct > hi:
        implied = _implied_style_for_pct(pct)
        return (
            f"Trading-style mismatch: profile says '{trading_style}' but "
            f"the trade target is {pct:.2f}% of entry — that's a {implied} "
            f"setup, not a {trading_style.lower()} setup. Decide your style "
            f"BEFORE entry; {trading_style}s should be using tighter stops "
            f"and smaller targets."
        )
    if pct < lo and lo > 0:
        return (
            f"Trading-style mismatch: profile says '{trading_style}' but "
            f"the trade target is only {pct:.2f}% of entry — that's tighter "
            f"than a typical {trading_style.lower()} setup. Either widen the "
            f"target to match the timeframe or commit to a faster style."
        )
    return None


def compact_question(question: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce one question record (from `session["questions"]`) to a small
    LLM-ready dict containing all data needed to evaluate the user's drawings."""
    user_answer = question.get("user_answer") or {}

    user_drawings = extract_drawings(question.get("answer_analysis_json"))
    correction_drawings = extract_drawings(question.get("correction_analysis_json"))
    mentor_drawings = extract_drawings(question.get("mentor_analysis_json"))

    trade_facts = _build_trade_facts(user_answer, question)
    drawings_summary = _build_drawings_summary(
        user_drawings, mentor_drawings, correction_drawings,
    )
    structural_observations = _build_structural_observations(
        trade_facts, mentor_drawings, user_drawings,
    )
    zones = _extract_classified_zones(mentor_drawings, user_drawings)
    zone_roles = _classify_zone_roles(zones, trade_facts)

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
        # Authoritative pre-computed numbers — the LLM is instructed to cite
        # these verbatim (see `_PER_QUESTION_SYSTEM` "TRADE FACTS" section)
        # so it never has to do arithmetic or extract nested fields itself.
        "trade_facts": trade_facts,
        # Plain-English single-line summary of EVERY drawing on the chart.
        # This is the ONLY source of drawing info the LLM should describe —
        # raw `state.color` is intentionally not surfaced as a top-level field
        # so the model can't hallucinate "purple rectangle" descriptions.
        "drawings_summary": drawings_summary,
        # Auto-detected structural mismatches between trade levels and zones
        # (entry below demand zone, stop inside zone, TP at resistance, etc.).
        # The LLM is told to quote any non-empty observations directly in
        # `mistake` rather than re-deriving them.
        "structural_observations": structural_observations,
        # Per-zone role classification (ENTRY_ZONE / MISSED_DEMAND /
        # TARGET_SUPPLY / DEMAND_ABOVE_ENTRY / etc.). The LLM is told to
        # mention EVERY zone in this list — see ZONE RULES in the prompt —
        # so the secondary / upper zone never gets dropped from the
        # explanation (Problem 4 in the enhancement task).
        "zone_roles": zone_roles,
        # Pre-computed factual narrative of what price did after entry —
        # entry-candle close + the SL/TP-hit candle's OHLC. The LLM is told
        # to paraphrase from this rather than invent next-candle prices.
        "market_aftermath": _build_market_aftermath(user_answer),
        # Deterministic points-based score so two trades with different
        # structural quality don't end up with the same overall_score. The
        # LLM copies `base_score` into `overall_score` (with optional ±1.0
        # CHoCH/BOS adjustment).
        "score_breakdown": _build_score_breakdown(
            trade_facts, drawings_summary, structural_observations, zones,
        ),
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
        # Preserve the answer_id that the multi-answer flow stamped on this
        # question so the final card can carry it back to the frontend (the
        # frontend needs to know which trade each card maps to when the user
        # passed multiple answer_ids).
        "requested_answer_id": question.get("requested_answer_id"),
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
