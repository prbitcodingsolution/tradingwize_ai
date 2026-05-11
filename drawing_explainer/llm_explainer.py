"""Asks `openai/gpt-oss-120b` (via OpenRouter, through the project's
`guarded_llm_call`) to grade and explain each user drawing question by
question, then produce a session-level ranking.

We deliberately call the LLM **once per question** (and once for the session
summary) so that:
  - Each prompt stays under the model's effective context window even for
    sessions with many drawings.
  - A single failing question doesn't poison the whole report.
  - Per-question explanations can be streamed back to the UI as they finish.

Output is JSON parsed back into plain dicts. We ask the model for JSON in the
prompt and parse defensively (strips ```json fences, falls back to raw text).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Model used by the drawing-explainer ONLY. Other tasks in the project keep
# `openai/gpt-oss-120b` (set in `utils.model_config.guarded_llm_call`'s default)
# — this override applies only to `_call_llm` below.
#
# Why a different model here: this task requires precise extraction of nested
# JSON values (trade_context.user_buy_price, mentor drawing coordinates, etc.)
# without approximation. Open-weight models on OpenRouter (gpt-oss-120b in
# particular) tend to "round" or hallucinate prices when reading a deeply-
# nested TradingView drawing payload — we observed it inverting demand/supply
# zones and misreporting "TP set below entry" when TP was actually above
# entry. Claude Haiku 4.5 is meaningfully better at this specific pattern
# (precise JSON-field extraction → short structured output) and is still
# cheap enough for high-volume use.
#
# Override via env if your OpenRouter slug differs (some accounts see this
# model as `anthropic/claude-haiku-4-5` or with a date suffix).
LLM_MODEL = os.getenv("DRAWING_EXPLAINER_MODEL", "anthropic/claude-haiku-4.5")
LLM_TIMEOUT_SEC = float(os.getenv("DRAWING_EXPLAINER_LLM_TIMEOUT", "120"))
# Token ceiling for the per-question card. The card schema is 8 short fields
# (~200-300 words rendered) so we don't need a huge budget; setting it well
# above the target gives headroom for the LLM's reasoning preamble in
# response_format=json_object mode without truncating mid-output.
LLM_MAX_TOKENS_PER_QUESTION = int(os.getenv("DRAWING_EXPLAINER_MAX_TOKENS_Q", "1500"))


# `score_breakdown.scoring_note` policy:
#   AUDITOR_METADATA (model ignores) | OVERRIDE_INSTRUCTION (model applies)
# Set in `_build_score_breakdown()` in drawing_extractor.py.
# Current value: AUDITOR_METADATA — the rubric engine emits a static rule
# restatement that is already covered by Section 9 of the prompt, so the
# model is instructed to ignore the field to prevent leaking internal rubric
# language into student-facing card fields.
_PER_QUESTION_SYSTEM = """You are a professional trading mentor reviewing a student's trade.

You receive ONE question's pre-parsed input — `trade_facts`, `drawings_summary`,
`structural_observations`, `zone_roles`, `market_aftermath`, `score_breakdown`,
`price_context`, optional `style_alignment_warning`. Treat them as ground truth
in this priority order:
  1. `trade_facts`, `structural_observations`, `score_breakdown.base_score`
  2. `drawings_summary`, `zone_roles`, `market_aftermath`, `style_alignment_warning`
  3. `price_context` (raw OHLC, swings, decision_index)

Step 1 — Analyse the market OBJECTIVELY from the input:
  • market direction (HH+HL uptrend / LH+LL downtrend / range)
  • structure shifts (BOS / CHOCH) visible in `price_context.recent_window`
    and `swings_recent`
  • key support / resistance / demand / supply zones from `drawings_summary`
    and `zone_roles`
  • liquidity sweeps / wick rejections if present
  • what price did AFTER the student's entry — quote `market_aftermath` if set

Step 2 — Review the student's execution against that market:
  • Was the bias (long/short from `trade_facts.direction`) correct?
  • Was entry timing good — did they wait for retest / confirmation, or chase?
  • Was the stop loss logical — beyond a structural invalidation point, or in
    open space?
  • Was take profit realistic relative to the next opposing structure?
  • Did they enter too early, too late, or correctly?

Step 3 — Speak to the student like a mentor: short, clear, human. No filler,
no preachy disclaimers, no markdown formatting inside fields, no nested bullets.

PRICE CITATION RULE: every price you write must appear verbatim in
`trade_facts` or in `price_context.swings_recent[*].price`. No invented numbers.
When unsure, describe a level structurally ("just below the recent swing low")
without a number.

SCORING: set `overall_score` to `score_breakdown.base_score` verbatim. The only
permitted adjustment is ±1.0, and only when you observe a CHoCH / BOS
confirmation in `price_context.recent_window` that the rubric could not see —
note the reason in `student_review.mistake` if you adjust.

STYLE ALIGNMENT WARNING: if `style_alignment_warning` is present, quote or
paraphrase it inside `student_review.mistake`. Never silently drop it.

DID-WELL RULE: `student_review.did_well` is NEVER empty. Even on a losing or
low-score trade, credit one specific element from the input — direction matched
a drawn zone, used a Risk-Reward tool with explicit SL+TP, defined a target,
kept `stop_distance_pct` ≤ 2.0%, or placed structural drawings before
submitting. Generic praise ("good attempt") is forbidden.

OUTPUT — STRICT JSON, no markdown fences, no commentary outside the object,
no extra fields:

{
  "overall_score": <number 0.0-10.0, one decimal>,
  "market_analysis": "<2-3 short sentences. Direction + structure shift + key zone + what price did after entry. Real prices only.>",
  "student_review": {
    "did_well": "<1-2 short sentences. One specific element credited. Never empty.>",
    "mistake": "<1-2 short sentences. The single most impactful execution error, with real prices.>",
    "improve": "<1-2 short sentences. Concrete next-time approach — entry zone + confirmation + stop placement.>"
  },
  "mentor_note": "<1-2 sentences of short realistic mentor advice — direct, human, not preachy.>"
}

Every field is required. `null` is forbidden. No prose outside the JSON object.
"""


# Session-level summary was deprecated in favour of the per-question card
# format defined above (see `_PER_QUESTION_SYSTEM`). The frontend now renders
# only per-question cards — no session strengths/weaknesses block, no
# recurring-mistakes table, no study plan, no closing note. The function
# `explain_session` and the `session_summary` field on the response have both
# been removed; the response is just `session` (metadata) + `questions[]` (cards).


def _build_current_trade_preamble(question: Dict[str, Any]) -> str:
    """Generate a per-trade preamble that anchors the LLM to THIS instrument's
    actual numbers — pair, timeframe, asset class, direction, entry, SL, TP,
    R:R, and outcome. Prepended to the system prompt at LLM-call time so the
    static rules below it (which use abstract `<price>` placeholders) get
    instantiated against real values for THIS trade specifically.

    The static base prompt is intentionally instrument-agnostic — it talks in
    `<low>–<high>` placeholders, never specific stock prices, so the LLM
    isn't biased by training-time examples. This preamble is what makes the
    response actually about THIS pair: stocks priced in rupees read
    differently from forex pip-decimals or crypto dollar prices, and the
    LLM needs the live numbers up front to calibrate its tone.
    """
    facts = question.get("trade_facts") or {}
    pair = question.get("pair") or "(unknown instrument)"
    timeframe = question.get("timeframe") or "(unknown timeframe)"
    market = question.get("market") or "asset"
    direction = (facts.get("direction") or "").upper() or "(unknown direction)"

    lines: List[str] = [
        "═══ CURRENT TRADE — anchor your response to THIS instrument's numbers ═══",
        f"Instrument: {pair}  ·  Timeframe: {timeframe}  ·  Asset class: {market}",
        f"Direction: {direction}",
    ]

    entry = facts.get("entry_price")
    sl = facts.get("stop_loss")
    tp = facts.get("take_profit")
    rr_planned = facts.get("rr_planned")
    rr_realized = facts.get("rr_realized")
    risk_pct = facts.get("stop_distance_pct")
    reward_pct = facts.get("target_distance_pct")
    hit = facts.get("hit")

    if entry is not None:
        lines.append(f"Entry: {entry}")
    if sl is not None:
        risk_bit = f" ({risk_pct:.2f}% risk)" if isinstance(risk_pct, (int, float)) else ""
        lines.append(f"Stop loss: {sl}{risk_bit}")
    if tp is not None:
        reward_bit = f" ({reward_pct:.2f}% reward)" if isinstance(reward_pct, (int, float)) else ""
        lines.append(f"Take profit: {tp}{reward_bit}")
    if rr_planned is not None:
        lines.append(f"R:R planned: {rr_planned}:1")
    if rr_realized is not None:
        lines.append(f"R:R realised: {rr_realized}")
    if hit:
        outcome = {"stop_loss": "Stop-loss hit (loss)", "take_profit": "Take-profit hit (win)"}.get(hit, hit)
        lines.append(f"Outcome: {outcome}")

    # Zone summary — gives the LLM the actual zone bounds upfront so it can't
    # default to numbers from the prompt's training-time training distribution.
    zone_roles = question.get("zone_roles") or []
    if zone_roles:
        lines.append("")
        lines.append("Zones on this chart:")
        for z in zone_roles:
            lines.append(
                f"  • [{z.get('role', '?')}] {z.get('kind', 'zone')} "
                f"{z.get('low')}–{z.get('high')}  (drawn by {z.get('source', '?')})"
            )

    lines.append("")
    lines.append(
        "BIAS GUARD: every price you cite in your response MUST come from this "
        "trade's own input — `trade_facts`, `drawings_summary`, `zone_roles`, "
        "`market_aftermath`, `structural_observations`, or "
        "`price_context.swings_recent` for THIS trade. Do NOT carry over numbers "
        "from training data, prior conversations, or any other example. The "
        "instrument and price scale change per trade — what's a 'tight stop' on "
        "Forex (a few pips) is different from on a stock (a few rupees / "
        "dollars) or on crypto (hundreds of dollars). Calibrate your tone to "
        "the actual numbers of THIS trade, not to a generic template."
    )

    return "\n".join(lines) + "\n"


# The mentor card schema. Three top-level prose blocks plus a nested
# `student_review` dict with three sub-fields. Kept here so the schema lives
# in ONE place — formatter.py imports both tuples.
_SECTION_KEYS = (
    ("market_analysis", "Market Analysis 📊"),
    ("mentor_note",     "Mentor Note 🧠"),
)

# Sub-fields rendered as bullets under the "Student Review" header.
_STUDENT_REVIEW_KEYS = (
    ("did_well", "✅ What you did well"),
    ("mistake",  "❌ Biggest mistake"),
    ("improve",  "🎯 How to improve"),
)


def _build_few_shot_example(question: Dict[str, Any]) -> str:
    """Generate a dynamic few-shot example matched to the CURRENT trade.

    Builds a JSON sample using the same `trade_facts`, `zone_roles`, and
    `score_breakdown` the LLM is about to read — so the example reflects the
    real numbers and structure of this specific trade. The LLM is told to
    write its OWN mentor-style explanation in this format, not copy-paste —
    but having a matching template anchors depth + tone.

    Returns an empty string when input is too sparse to build a useful
    example (the prompt then degrades to spec rules only).
    """
    facts = question.get("trade_facts") or {}
    zone_roles = question.get("zone_roles") or []
    drawings = question.get("drawings_summary") or []
    aftermath = question.get("market_aftermath")
    style_warning = question.get("style_alignment_warning")
    sb = question.get("score_breakdown") or {}

    if not facts.get("entry_price"):
        return ""

    score = sb.get("base_score", 0)
    direction = facts.get("direction") or "buy"
    entry = facts.get("entry_price")
    rr = facts.get("rr_planned")

    entry_zone = next((z for z in zone_roles if z["role"] == "ENTRY_ZONE"), None)
    missed = next(
        (z for z in zone_roles
         if z["role"] in ("MISSED_DEMAND", "MISSED_SUPPLY")),
        None,
    )
    anti_struct = next(
        (z for z in zone_roles
         if z["role"] in ("DEMAND_ABOVE_ENTRY", "SUPPLY_BELOW_ENTRY")),
        None,
    )
    target = next(
        (z for z in zone_roles
         if z["role"] in ("TARGET_SUPPLY", "TARGET_DEMAND")),
        None,
    )

    # ── market_analysis ──
    direction_phrase = (
        "extending lower with LH+LL structure" if direction == "sell"
        else "extending higher with HH+HL structure"
    )
    zone_bit = ""
    if zone_roles:
        z0 = zone_roles[0]
        zone_bit = (
            f" Key {z0.get('kind', 'zone')} on the chart sits at "
            f"{z0.get('low')}–{z0.get('high')}."
        )
    aftermath_bit = (
        f" {aftermath}" if aftermath
        else " Price moved against the trade and resolved at the stop-loss."
    )
    market_analysis = (
        f"Market was {direction_phrase} into the decision candle.{zone_bit}"
        f"{aftermath_bit}"
    )

    # ── student_review.did_well ──
    if any("Risk-Reward" in d for d in drawings) and rr:
        did_well = (
            f"Used a Risk-Reward tool with an explicit {rr}:1 plan rather "
            "than entering blind — the planning discipline is in place."
        )
    elif zone_roles:
        z0 = zone_roles[0]
        did_well = (
            f"Identified the {z0.get('kind', 'zone')} at "
            f"{z0.get('low')}–{z0.get('high')} on the chart — the structural "
            "read was there even if the execution wasn't."
        )
    elif facts.get("take_profit") is not None:
        did_well = (
            "Defined an explicit take-profit before entering — having an "
            "exit plan is better than discretionary management."
        )
    else:
        did_well = (
            "Committed to a structured trade with a defined entry on a "
            "learning platform — engagement is step one."
        )

    # ── student_review.mistake ──
    if anti_struct:
        mistake = (
            f"Entry at {entry} sits on the wrong side of the "
            f"{anti_struct['kind']} zone "
            f"({anti_struct['low']}–{anti_struct['high']}) — the trade is "
            "fighting the structural signal."
        )
    elif missed:
        mistake = (
            f"Entry at {entry} preceded the {missed['kind']} zone "
            f"({missed['low']}–{missed['high']}); the zone was right but you "
            "didn't wait for the retest."
        )
    elif entry_zone:
        mistake = (
            "Entry was inside the structural zone, but there was no CHoCH "
            "or BOS confirmation visible at the decision candle."
        )
    else:
        mistake = (
            f"Entry at {entry} had no structural zone alignment — you "
            "entered in open space without a level to lean on."
        )
    if style_warning:
        mistake += f" {style_warning}"

    # ── student_review.improve ──
    if missed or anti_struct:
        ref = missed or anti_struct
        anchor_low = ref["low"]
        anchor_high = ref["high"]
        if direction == "buy":
            improve = (
                f"Wait for price to retrace INTO the {ref['kind']} zone "
                f"({anchor_low}–{anchor_high}), confirm a CHoCH on this "
                f"timeframe, then enter long with stop just below {anchor_low}."
            )
        else:
            improve = (
                f"Wait for price to retrace INTO the {ref['kind']} zone "
                f"({anchor_low}–{anchor_high}), confirm a CHoCH, then enter "
                f"short with stop just above {anchor_high}."
            )
        if target:
            improve += (
                f" Use the {target['kind']} zone "
                f"({target['low']}–{target['high']}) as the TP reference."
            )
    elif entry_zone:
        improve = (
            "Entry zone was correct — next time wait for an explicit "
            "CHoCH/BOS confirmation candle inside the zone before entering."
        )
    else:
        improve = (
            "Confirm BOS/CHoCH structural alignment before entry, and place "
            "the stop just beyond a structural level — not in open space."
        )

    # ── mentor_note ──
    if missed or anti_struct:
        mentor_note = (
            "Patience is the other half of the edge. Wait for price to come "
            "to your zone — don't chase the trade."
        )
    elif entry_zone:
        mentor_note = (
            "You read the structure — now build the habit of letting the "
            "confirmation candle close before pulling the trigger."
        )
    else:
        mentor_note = (
            "R:R alone is not an edge. Anchor every entry to a structural "
            "level so each trade has a reason beyond the math."
        )

    sample = {
        "overall_score": score,
        "market_analysis": market_analysis,
        "student_review": {
            "did_well": did_well,
            "mistake": mistake,
            "improve": improve,
        },
        "mentor_note": mentor_note,
    }

    return (
        "═══ FEW-SHOT EXAMPLE — DYNAMICALLY GENERATED FOR THIS TRADE ═══\n"
        "Below is a worked example built from THIS trade's own data. Match "
        "this JSON shape and depth. You MAY paraphrase it freely, but you "
        "MUST keep `overall_score` equal to `score_breakdown.base_score` and "
        "reference every zone in `zone_roles` somewhere in the card. Do not "
        "copy verbatim — produce your own sentence-level wording grounded in "
        "the same data.\n\n"
        + json.dumps(sample, indent=2, ensure_ascii=False)
        + "\n"
    )


def _empty_card(question: Dict[str, Any], *, error: str, summary: str) -> Dict[str, Any]:
    """Return an all-zero card so the frontend renders a graceful fallback when
    the LLM call (or response parse) fails. Carries `_error` + `_error_summary`
    so the formatter can show a "analysis failed" notice instead of an empty
    card."""
    card: Dict[str, Any] = {
        "question_no": question.get("question_no"),
        "pair": question.get("pair"),
        "timeframe": question.get("timeframe"),
        "overall_score": 0,
        "_error": error,
        "_error_summary": summary,
    }
    if question.get("requested_answer_id") is not None:
        card["requested_answer_id"] = question.get("requested_answer_id")
    for key, _ in _SECTION_KEYS:
        card[key] = "—"
    card["student_review"] = {key: "—" for key, _ in _STUDENT_REVIEW_KEYS}
    return card


# ─────────────────── analysis-type framework lenses ───────────────────
# When the caller passes `analysis_type` we prepend a framework-specific
# directive block to the per-question system prompt so the LLM applies that
# trading school's terminology and detection logic while still emitting the
# same JSON schema the formatter expects.
#
# The canonical strings ("Patterns", "Price Action") are mixed-case on
# purpose — the API contract published in
# `patterns_priceaction_implementation_guide.md` lists them that way and the
# response echoes them verbatim, so the frontend can render the right header
# without an extra mapping.

ALLOWED_ANALYSIS_TYPES = ("SMC", "ICT", "VSA", "Patterns", "Price Action")

FRAMEWORK_NAMES = {
    "SMC": "Smart Money Concepts",
    "ICT": "Inner Circle Trader",
    "VSA": "Volume Spread Analysis",
    "Patterns": "Chart Pattern Analysis",
    "Price Action": "Price Action Trading",
}

# Aliases users might pass — keys are lower-case for case-insensitive lookup,
# values are canonical mixed-case forms exposed by ALLOWED_ANALYSIS_TYPES.
_ANALYSIS_TYPE_ALIASES = {
    "smc": "SMC",
    "ict": "ICT",
    "vsa": "VSA",
    # Price Action — accept the legacy 3-letter "PA" code + every common spelling
    "pa": "Price Action",
    "price action": "Price Action",
    "price-action": "Price Action",
    "price_action": "Price Action",
    "priceaction": "Price Action",
    # Patterns — accept singular and plural, with/without separators
    "pattern": "Patterns",
    "patterns": "Patterns",
    "chart pattern": "Patterns",
    "chart patterns": "Patterns",
    "chart-pattern": "Patterns",
    "chart-patterns": "Patterns",
    "chart_patterns": "Patterns",
}

_SMC_LENS = """═══ ANALYSIS FRAMEWORK — SMART MONEY CONCEPTS (SMC) ═══
Analyse this chart strictly through the SMC lens — the framework that tracks
institutional "smart money" footprints. Use SMC terminology in EVERY field.

Detect and reference these concepts when filling out the schema:
  • Market Structure — BOS (Break of Structure) confirms trend continuation;
    CHoCH (Change of Character) is the FIRST break against the prevailing
    trend and signals a reversal.
  • Liquidity Sweep / Stop Hunt — wick exceeding equal highs (buy-side
    liquidity) or equal lows (sell-side liquidity) followed by sharp rejection.
  • Order Block (OB) — last opposite-colored candle before an impulsive
    displacement move. Bullish OB = last bearish candle before a strong
    up-move; bearish OB = last bullish candle before a strong down-move.
  • Fair Value Gap (FVG) / Imbalance — three-candle pattern where candle 1
    wick and candle 3 wick do NOT overlap. Bullish FVG: candle 3 low > candle
    1 high. Bearish FVG: candle 3 high < candle 1 low. Price often returns
    to fill these.
  • Premium / Discount Zone — using the swing high-to-low range, above 50%
    equilibrium = Premium (sell zone), below 50% = Discount (buy zone).
  • Displacement — large fast high-momentum candle marking institutional entry.
  • Inducement — minor liquidity grab that traps retail before the real move.

When grading: a stop placed inside an order block or just above/below a
liquidity pool is wrong. Entries should be at OB / FVG / discount zones in the
direction confirmed by BOS/CHoCH. Cite the specific SMC element (e.g. "stop
sits inside the bearish OB at 2918.4") instead of generic terms.

In the card fields, name the SMC structure directly: BOS / CHoCH / OB / FVG /
liquidity sweep / premium / discount / displacement. e.g. `student_review.mistake`: "Entered
inside a bearish OB at 2918.4 with no CHoCH confirmation"; `market_analysis`:
"Liquidity sweep above the equal highs at 2935 then bearish BOS through 2920";
`student_review.improve`: "Wait for CHoCH below 2920 and a retest of the resulting
bearish OB before shorting".
"""

_ICT_LENS = """═══ ANALYSIS FRAMEWORK — INNER CIRCLE TRADER (ICT) ═══
Analyse this chart through the ICT methodology developed by Michael J.
Huddleston — a precision institutional framework built on liquidity, time-based
kill zones, and market-maker models. Use ICT terminology in EVERY field.

Detect and reference these concepts when filling out the schema:
  • BSL / SSL — Buy-Side Liquidity rests above swing highs / equal highs /
    trendline highs; Sell-Side Liquidity rests below swing lows / equal lows /
    trendline lows. These are the targets institutions draw price toward.
  • Market Structure Shift (MSS) / CHoCH — close beyond the last significant
    swing point against the prevailing trend; first reversal confirmation.
  • Order Block (OB), Breaker Block, Mitigation Block — ICT emphasises the
    BODY of the last opposite candle before a strong move. A Breaker is a
    failed OB that flips polarity; a Mitigation Block is the candle that
    mitigated a prior imbalance before reversing.
  • Fair Value Gap (FVG) — same 3-candle imbalance logic as SMC.
  • Optimal Trade Entry (OTE) — Fibonacci 61.8%–78.6% retracement of a swing
    move, ideally combined with an FVG or OB. ICT's preferred precision entry.
  • Kill Zones — high-probability windows in EST: London Open KZ
    (02:00–05:00), New York Open KZ (07:00–10:00), London Close KZ
    (10:00–12:00). If candle/decision timestamps fall in one, flag it.
  • Power of 3 (PO3 / AMD) — daily phases of Accumulation (tight range, early
    session), Manipulation (false spike against true direction), Distribution
    (true move). State which phase the chart is showing.
  • Market Maker Model (MMXM) — the full narrative: reach for BSL/SSL →
    manipulation → institutional entry at OB/FVG → delivery to opposite pool.

When grading: an entry that is NOT in an OTE / OB / FVG, or a stop that does
NOT sit beyond a liquidity pool, is poorly placed. Cite the kill zone, the
PO3 phase, and which liquidity pool price is targeting.

In the card fields, use ICT terminology directly: BSL / SSL / MSS / OTE /
PO3 / MMXM / kill zone / breaker block / mitigation block. e.g. `market_analysis`:
"London Open kill zone swept BSL above 2945 then ran into the bearish OB at
2952"; `student_review.improve`: "Wait for MSS below 2940 and re-enter at the OTE
zone (61.8–78.6%) of the resulting bearish leg".
"""

_VSA_LENS = """═══ ANALYSIS FRAMEWORK — VOLUME SPREAD ANALYSIS (VSA) ═══
Analyse this chart through the Wyckoff/VSA lens (Tom Williams). Read the
three-dimensional relationship between Volume (effort), Spread (range), and
Close position (sentiment) on EVERY notable bar to detect hidden institutional
activity. Use VSA / Wyckoff terminology in EVERY field.

Detect and reference these signals when filling out the schema:
  • High Volume + Narrow Spread — professional absorption. On an up-bar =
    weakness (pros selling into retail buying); on a down-bar = strength (pros
    buying into retail selling).
  • High Volume + Wide Spread + Strong Close — effort = result, genuine
    institutional move in the close's direction.
  • Low Volume + Wide Spread — anomaly, move without participation; likely to
    reverse.
  • Stopping Volume / Climax — extreme volume on a wide-spread down-bar
    closing in the upper portion → selling climax / absorption.
  • No Supply Bar — narrow spread, low volume on an up-close → no selling
    pressure, likely continuation up.
  • No Demand Bar — narrow spread, low volume on a down-close → no buying
    pressure, likely continuation down.
  • Test — low-volume narrow-spread down-bar after a markup; if no supply
    appears, uptrend continues.
  • Upthrust — wide-spread up-bar closing near the low on high volume →
    professional selling disguised as strength. Bearish.
  • Pseudo Upthrust — same shape on lower volume; weaker but still bearish.
  • Shakeout — sharp move below support on high volume that quickly reverses;
    flushes weak retail longs.
  • Wyckoff Phases — Accumulation (sideways with shrinking volatility, Spring,
    Tests) vs. Distribution (sideways after uptrend, Upthrusts, no demand).
  • Effort vs. Result Law — large effort with small result = inefficiency;
    small effort with large result = running on fumes / reversal likely.

When grading: ground EVERY observation in volume + spread + close. If the
candles in `price_context.recent_window` lack a `volume` field, say so once
in `student_review.mistake` ("(without volume data)") and lower `overall_score` by 1.0 —
VSA cannot be applied without volume.

In the card fields, use VSA / Wyckoff terminology directly: Stopping Volume,
Upthrust, No Supply, No Demand, Test, Spring, Shakeout, Accumulation,
Distribution, effort vs result. e.g. `market_analysis`: "Upthrust at 2952 on
high volume closed near the low — professional selling"; `student_review.improve`:
"Wait for a low-volume Test of 2935 to confirm No Supply before the long".
"""

_PRICE_ACTION_LENS = """═══ ANALYSIS FRAMEWORK — PRICE ACTION TRADING ═══
Analyse this chart through a classic "naked chart" Price Action lens — no
indicators, no oscillators, no derived calculations. The student is expected
to read RAW candle behaviour and structure: individual candlestick formations,
horizontal support / resistance, trendlines, channels, and HH/HL / LH/LL
market structure. Use Price Action terminology in EVERY field, but remember
that other valid frameworks exist — never imply Price Action is the only
correct lens.

Detect and reference these concepts when filling out the schema:

  • Trend structure (mandatory) — call it explicitly:
      - Uptrend  = Higher Highs (HH) + Higher Lows (HL)
      - Downtrend = Lower Highs (LH) + Lower Lows (LL)
      - Range / sideways = no directional structure, equal swings
    Cite the swings from `price_context.swings_recent`.

  • Horizontal support & resistance — repeatedly tested price zones; more
    retests = stronger. Cite touch count. Note any Support-Turned-Resistance
    (broken support that flips into resistance on retest) or
    Resistance-Turned-Support flips — these are high-conviction signals.

  • Trendlines & channels —
      - Rising trendline along higher-lows, falling trendline along
        lower-highs. Validity needs at least 3 touches and a clean reaction.
      - Channels are two PARALLEL trendlines containing price.
      - A trendline anchored on noise (single touch / wick-only) is invalid.

  • Candlestick patterns — name them explicitly. Single-candle: Pin Bar
    (Pinocchio Bar), Hammer, Inverted Hammer, Hanging Man, Shooting Star,
    Doji (Long-Legged / Gravestone / Dragonfly), Marubozu, Spinning Top,
    Inside Bar, Outside Bar (Mother Bar). Multi-candle: Bullish/Bearish
    Engulfing, Bullish/Bearish Harami, Morning Star, Evening Star, Three
    White Soldiers, Three Black Crows, Tweezer Tops/Bottoms.
    State the buyer/seller psychology (e.g. "long lower wick = buyers
    rejected lower prices").

  • Confluence — best setups stack 2+ signals (S/R + reversal candle +
    trendline / HH-HL structure) at the same price.

  • Failed breakouts / false breaks — price briefly breaks a level then
    reverses, trapping breakout traders. High-probability move in the
    opposite direction.

  • Round numbers + Previous Day High/Low — psychological levels worth
    citing when the chart shows a reaction near them.

When grading:
  - An entry without ANY structural anchor (S/R, trendline touch, candle
    reversal at a level) is a `missing_structural_confirmation` mistake.
  - A stop placed in the middle of a range or inside the most recent swing
    is wrong — it should sit JUST BEYOND the rejection wick / structural
    invalidation point.
  - A target inside chop (no clean S/R between entry and TP) is weak —
    targets should aim at the next horizontal S/R level.
  - NEVER reference indicators / oscillators / moving averages / volume
    profiles / derived metrics. This framework reads price + candles only.

In the card fields, name the Price Action structure directly: pin bar,
bullish/bearish engulfing, inside bar, hammer, shooting star, double top /
bottom, HH+HL / LH+LL, S/R flip, false break. e.g. `market_analysis`: "Bullish
engulfing rejected the prior day low at 2935 — failed breakdown";
`student_review.improve`: "Wait for a pin-bar rejection of the 2935 swing low,
enter on the next candle close above the wick".
"""

_PATTERNS_LENS = """═══ ANALYSIS FRAMEWORK — CHART PATTERN ANALYSIS ═══
Analyse this chart through a classic Chart Pattern lens — recurring
multi-candle GEOMETRIC structures formed by price over time, predicting the
direction of the next breakout based on the psychological battle between
buyers and sellers. Use Chart Pattern terminology in EVERY field. Other
valid frameworks exist — never imply Chart Patterns are the only correct
lens.

Classify any pattern you identify into one of the three families:

  • CONTINUATION — trend pauses, then resumes:
      Bull Flag, Bear Flag, Bull Pennant, Bear Pennant, Ascending Triangle
      (flat resistance + rising support, bullish), Descending Triangle (flat
      support + falling resistance, bearish), Rectangle / Trading Range,
      Cup & Handle (bullish), Rising Wedge (continuation in downtrend,
      bearish), Falling Wedge (continuation in uptrend, bullish).

  • REVERSAL — trend ends and reverses:
      Head & Shoulders (3 peaks, head highest, neckline across the troughs;
      bearish on neckline break), Inverse Head & Shoulders (mirror image,
      bullish), Double Top (two equal highs, bearish on neckline break),
      Double Bottom (two equal lows, bullish on neckline break), Triple Top,
      Triple Bottom, Rounding Bottom (Saucer — slow accumulation),
      Rising Wedge (in uptrend, bearish reversal), Falling Wedge (in
      downtrend, bullish reversal).

  • BILATERAL — breakout direction unknown until it happens:
      Symmetrical Triangle (two converging trendlines, lower rising upper
      falling). Volume typically dries into the apex; the breakout direction
      is the signal.

When filling out the schema:

  1. PATTERN IDENTIFICATION — name the pattern explicitly. If price action
     is too vague to identify a clean pattern, set `identified_pattern` to
     "unclear" and `pattern_confidence` to "low".
  2. STRUCTURAL COMPONENTS — label the parts of the pattern in the
     `summary` and `key_levels`:
       - H&S type → left shoulder, head, right shoulder, neckline
       - Flag / Pennant → flagpole, consolidation channel, breakout zone
       - Triangle → upper trendline, lower trendline, apex
       - Double / Triple Top|Bottom → both/each peak or trough + neckline
       - Cup & Handle → cup rim (resistance), handle low
  3. NECKLINE / KEY LEVEL — list the specific breakout/breakdown level in
     `key_levels` with role "breakout" or "reversal".
  4. VOLUME CONFIRMATION — the standard expectation is volume DECREASES
     during consolidation and SPIKES on breakout. If candle data carries a
     `volume` field, comment on whether the pattern is volume-confirmed; if
     not, say so once and lower confidence.
  5. PRICE TARGET (MEASURED MOVE) — the canonical chart-pattern target is
     the pattern's HEIGHT projected from the breakout point:
       - H&S → height from head to neckline, projected DOWN from neckline.
       - Inverse H&S → mirror, projected UP.
       - Double Top → height from peaks to trough, projected DOWN from
         neckline.
       - Double Bottom → height from troughs to peak, projected UP.
       - Flag / Pennant → flagpole length added to breakout point.
       - Triangle → widest part of the triangle projected from breakout.
     State the computed target as a real price.
  6. PATTERN STATUS — is the pattern still forming, has the breakout
     already occurred, has it already hit target, or has it failed?
  7. STOP LOSS — typically just BEYOND the far end of the pattern
     (above the right shoulder for H&S, below the second bottom for double
     bottom, beyond the opposite trendline for triangles, etc.).

When grading (call these out by name in `student_review.mistake` when they apply):
  - An entry taken BEFORE neckline / breakout close-through → premature entry.
  - A stop inside the pattern body (e.g. between the two peaks of a Double
    Top) → misplaced stop.
  - A target that doesn't match the measured-move projection → poor R:R.
  - "Identified pattern but the structure doesn't actually fit" → misidentified
    pattern.

In the card fields, name the chart pattern directly: Head & Shoulders,
Inverse H&S, Double / Triple Top / Bottom, Bull / Bear Flag, Pennant,
Ascending / Descending / Symmetrical Triangle, Cup & Handle, Rising /
Falling Wedge, Rectangle, Rounding Bottom, etc. Quote the neckline /
breakout level and the measured-move target as real prices. e.g.
`market_analysis`: "H&S neckline at 2920 broke; measured move targets 2885";
`student_review.improve`: "Wait for a retest of the broken neckline at 2920,
enter short on rejection with stop above the right shoulder at 2945".
"""

_FRAMEWORK_LENSES = {
    "SMC": _SMC_LENS,
    "ICT": _ICT_LENS,
    "VSA": _VSA_LENS,
    "Patterns": _PATTERNS_LENS,
    "Price Action": _PRICE_ACTION_LENS,
}


# ─────────────────── student-profile fields ───────────────────
# Four optional fields the frontend can pass alongside `analysis_type` so the
# LLM tailors the explanation depth, terminology, and trade-management focus
# to the student. Canonical strings match the spelling published in the API
# spec (a few entries — `begginer`, `Comodity`, `Indeces` — are intentional
# typos because the user-facing UI labels carry them; aliases below accept
# correct spellings too so the API stays forgiving).

TRADING_STYLES = (
    "Scalper",
    "Intraday Trader",
    "Swing Trader",
    "Positional Trader",
)

USER_LEVELS = ("begginer", "advance")

ASSESTS = (
    "Forex",
    "Stocks",
    "Comodity",
    "Crypto",
    "Indeces",
)

YEARS_OF_EXPERIENCE = (
    "6 Month to 1 Year",
    "1 Year to 2 Year",
    "2 Year to 3 Year",
    "3 Year to 4 Year",
    "4 Year to 5 Year",
    "6 Year to 7 Year",
    "7 Year to 8 Year",
    "8 Year to 9 Year",
    "9 Year to 10 Year",
    "10 Year Above",
)

# Lower-case alias map → canonical form. Idempotent (canonical → itself) plus
# common spelling/spacing variants so a slightly off frontend value doesn't
# raise a 400.
_TRADING_STYLE_ALIASES = {
    "scalper": "Scalper",
    "scalp": "Scalper",
    "scalping": "Scalper",
    "intraday trader": "Intraday Trader",
    "intraday": "Intraday Trader",
    "intraday trading": "Intraday Trader",
    "day trader": "Intraday Trader",
    "day-trader": "Intraday Trader",
    "daytrader": "Intraday Trader",
    "swing trader": "Swing Trader",
    "swing": "Swing Trader",
    "swing trading": "Swing Trader",
    "positional trader": "Positional Trader",
    "positional": "Positional Trader",
    "position trader": "Positional Trader",
    "position": "Positional Trader",
    "long term": "Positional Trader",
    "long-term": "Positional Trader",
}

_USER_LEVEL_ALIASES = {
    "begginer": "begginer",
    "beginner": "begginer",
    "novice": "begginer",
    "new": "begginer",
    "advance": "advance",
    "advanced": "advance",
    "expert": "advance",
    "pro": "advance",
}

_ASSEST_ALIASES = {
    "forex": "Forex",
    "fx": "Forex",
    "currency": "Forex",
    "currencies": "Forex",
    "stocks": "Stocks",
    "stock": "Stocks",
    "equity": "Stocks",
    "equities": "Stocks",
    "shares": "Stocks",
    "comodity": "Comodity",
    "commodity": "Comodity",
    "commodities": "Comodity",
    "crypto": "Crypto",
    "cryptocurrency": "Crypto",
    "cryptocurrencies": "Crypto",
    "coin": "Crypto",
    "coins": "Crypto",
    "indeces": "Indeces",
    "indices": "Indeces",
    "index": "Indeces",
}

# Years-of-experience: build the alias map from the canonical list so the
# 10 entries don't have to be hand-listed below.
_YEARS_ALIASES = {y.lower().strip(): y for y in YEARS_OF_EXPERIENCE}
_YEARS_ALIASES.update({
    # Common shorthand the frontend (or a power user) may send.
    "10+ year": "10 Year Above",
    "10+ years": "10 Year Above",
    "10 years above": "10 Year Above",
    "10 years+": "10 Year Above",
    "10+": "10 Year Above",
    # Numeric `value` from the frontend dropdown — kept in lock-step with the
    # frontend's year_of_experience options list so either label or value is
    # accepted on the wire. Note: there is intentionally no "5 Year to 6 Year"
    # bracket — the frontend skips from value 5 (4→5) to value 6 (6→7).
    "1": "6 Month to 1 Year",
    "2": "1 Year to 2 Year",
    "3": "2 Year to 3 Year",
    "4": "3 Year to 4 Year",
    "5": "4 Year to 5 Year",
    "6": "6 Year to 7 Year",
    "7": "7 Year to 8 Year",
    "8": "8 Year to 9 Year",
    "9": "9 Year to 10 Year",
    "10": "10 Year Above",
})


def _normalize_field(
    raw: Optional[str], aliases: Dict[str, str], field_name: str,
    canonical_list: tuple,
) -> Optional[str]:
    """Generic normaliser shared by every student-profile field. Returns None
    for None / empty; raises ValueError for unknown values with a clear list
    of accepted canonical forms."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    key = " ".join(s.lower().split())  # collapse whitespace
    canonical = aliases.get(key)
    if canonical is None:
        raise ValueError(
            f"{field_name} must be one of: {', '.join(canonical_list)}"
        )
    return canonical


def normalize_trading_style(raw: Optional[str]) -> Optional[str]:
    return _normalize_field(raw, _TRADING_STYLE_ALIASES, "trading_style", TRADING_STYLES)


def normalize_user_level(raw: Optional[str]) -> Optional[str]:
    return _normalize_field(raw, _USER_LEVEL_ALIASES, "user_level", USER_LEVELS)


def normalize_assest(raw: Optional[str]) -> Optional[str]:
    return _normalize_field(raw, _ASSEST_ALIASES, "assests", ASSESTS)


def normalize_year_of_experience(raw: Optional[str]) -> Optional[str]:
    return _normalize_field(raw, _YEARS_ALIASES, "year_of_experience", YEARS_OF_EXPERIENCE)


def normalize_user_profile(profile: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """Normalise every field on the inbound user profile in one call.

    Returns a 4-key dict (always the same keys, values are canonical strings
    or None). Empty dict / None input → all-None dict (no-op for the lens
    builder downstream). Unknown values → ValueError, just like
    `normalize_analysis_type`.
    """
    if not profile:
        return {
            "trading_style": None,
            "user_level": None,
            "assests": None,
            "year_of_experience": None,
        }
    return {
        "trading_style": normalize_trading_style(profile.get("trading_style")),
        "user_level": normalize_user_level(profile.get("user_level")),
        # Accept both spellings as input — `assests` matches the published API
        # contract; `assets` is here for clients that auto-corrected the typo.
        "assests": normalize_assest(profile.get("assests") or profile.get("assets")),
        "year_of_experience": normalize_year_of_experience(profile.get("year_of_experience")),
    }


def _has_any_profile_field(profile: Optional[Dict[str, Optional[str]]]) -> bool:
    if not profile:
        return False
    return any(profile.get(k) for k in ("trading_style", "user_level", "assests", "year_of_experience"))


def build_user_profile_lens(profile: Optional[Dict[str, Optional[str]]]) -> str:
    """Compose a directive block that tells the LLM how to tailor the
    explanation to this student. Returns "" when no fields are populated so
    the prompt stays unchanged for callers who don't supply a profile."""
    if not _has_any_profile_field(profile):
        return ""

    lines: List[str] = [
        "═══ STUDENT PROFILE — TAILOR THE EXPLANATION ═══",
        "Use this profile to calibrate the depth, jargon, and trade-management",
        "focus of your explanation. Do NOT change the JSON schema — only how",
        "you fill the prose fields (`market_analysis`, `student_review.did_well`,",
        "`student_review.mistake`, `student_review.improve`, `mentor_note`).",
        "",
    ]

    style = profile.get("trading_style")
    if style:
        lines.append(f"  • Trading style: {style}")
        if style == "Scalper":
            lines.append(
                "    — Tick / sub-minute precision. Stress tight stops, fast"
                " execution, micro-structure (1m / 5m). De-emphasise multi-day"
                " holding context."
            )
        elif style == "Intraday Trader":
            lines.append(
                "    — Day-session focus. Stress session opens/closes, intraday"
                " momentum, no overnight risk. Reference 5m / 15m / 1H structure."
            )
        elif style == "Swing Trader":
            lines.append(
                "    — Multi-day to multi-week holds. Stress higher-timeframe"
                " structure (4H / 1D), pullback entries, swing failure exits,"
                " patience through pullbacks."
            )
        elif style == "Positional Trader":
            lines.append(
                "    — Weeks-to-months horizon. Stress 1D / 1W structure, the"
                " primary trend, fundamentals as confluence (earnings, macro)."
                " De-emphasise intraday noise."
            )

    level = profile.get("user_level")
    if level:
        lines.append(f"  • Experience level: {level}")
        if level == "begginer":
            lines.append(
                "    — Use plain English. The FIRST time you use any acronym"
                " (BOS, CHoCH, OB, FVG, OTE, MSS, etc.) define it inline in"
                " parentheses. Lean on the WHY (what the institutions did and"
                " why) more than the WHAT. Be encouraging — this person is"
                " building habits."
            )
        elif level == "advance":
            lines.append(
                "    — Skip basics. Use institutional terminology directly."
                " Be terse and direct. Critique execution flaws (entry timing,"
                " R:R ratios, partial-take logic) without softening. Assume"
                " they already know what BOS / CHoCH / OB / FVG mean."
            )

    years = profile.get("year_of_experience")
    if years:
        lines.append(f"  • Years trading: {years}")
        # Three brackets — early, middle, veteran — so the LLM knows how
        # tough/gentle to be without listing all 10 ranges.
        early = {"6 Month to 1 Year", "1 Year to 2 Year"}
        middle = {"2 Year to 3 Year", "3 Year to 4 Year", "4 Year to 5 Year"}
        if years in early:
            lines.append(
                "    — Early-stage trader. Talk about discipline, journaling,"
                " sticking to ONE setup, accepting losing-pattern reality."
                " Avoid ego-bruising critique; encourage process over outcome."
            )
        elif years in middle:
            lines.append(
                "    — Building consistency. Focus on edge refinement,"
                " R-multiple expectancy, eliminating recurring mistake types."
                " Direct critique is fine; they should be ready for it."
            )
        else:  # 6 Year to 7 Year and beyond
            lines.append(
                "    — Veteran trader. Skip basics entirely. Be blunt about"
                " execution flaws, hidden bias patterns, R-stacking issues."
                " Reference advanced concepts (correlation hedging, vol-adjusted"
                " sizing) when relevant. They want signal, not encouragement."
            )

    asset = profile.get("assests")
    if asset:
        lines.append(f"  • Asset class: {asset}")
        if asset == "Forex":
            lines.append(
                "    — Quote price moves in PIPS, not points. Mention session"
                " (London / NY) when timing matters. Reference leverage / lot"
                " sizing when discussing risk; spreads matter on scalping."
            )
        elif asset == "Stocks":
            lines.append(
                "    — Quote moves in points or % of price. Mention earnings"
                " windows / news risk when entry timing crosses them. Volume"
                " confirms stock breakouts more than forex breakouts."
            )
        elif asset == "Comodity":
            lines.append(
                "    — Mention contract specs when relevant (gold / oil tick"
                " value, futures expiry, contango/backwardation). Commodities"
                " trend strongly — pullback entries beat breakouts."
            )
        elif asset == "Crypto":
            lines.append(
                "    — 24/7 market, no overnight gap risk but weekend volatility"
                " is real. Reference funding rates / liquidation clusters as"
                " liquidity pools when relevant. Wider stops than equities."
            )
        elif asset == "Indeces":
            lines.append(
                "    — Index futures structure, gap risk on the open, strong"
                " correlations across SPX/NDX/DJI. Reference VIX context when"
                " volatility regime matters for stop sizing."
            )

    lines.append("")
    lines.append(
        "Apply ALL the above simultaneously. If the profile pulls in different"
        " directions (e.g. begginer + advance years), let `user_level` win for"
        " jargon density and `year_of_experience` win for tone."
    )
    return "\n".join(lines) + "\n"


def normalize_analysis_type(analysis_type: Optional[str]) -> Optional[str]:
    """Resolve an `analysis_type` input to one of the canonical
    `ALLOWED_ANALYSIS_TYPES` strings (case-insensitive, with aliases).

    Returns None for None / empty input; raises ValueError on unknown values.
    Accepts e.g. `"smc"`, `"price_action"`, `"PA"`, `"chart patterns"`.
    """
    if analysis_type is None:
        return None
    s = str(analysis_type).strip().lower()
    if not s:
        return None
    canonical = _ANALYSIS_TYPE_ALIASES.get(s)
    if canonical is None:
        raise ValueError(
            f"analysis_type must be one of: {', '.join(ALLOWED_ANALYSIS_TYPES)}"
        )
    return canonical


def build_analysis_system_prompt(
    analysis_type: Optional[str],
    base_prompt: Optional[str] = None,
    user_profile: Optional[Dict[str, Optional[str]]] = None,
) -> str:
    """Return the per-question system prompt, optionally prefixed with a
    student-profile block AND a framework-specific lens block.

    Composition order (outer → inner):
      1. STUDENT PROFILE — who is the trader, how to talk to them
      2. FRAMEWORK LENS — which trading school's terminology to use
      3. BASE PROMPT — the structured task + JSON schema

    `analysis_type` should already be normalised by `normalize_analysis_type`;
    `user_profile` should already be normalised by `normalize_user_profile`.
    Either may be None / empty — that piece is simply omitted from the prompt.
    """
    base = base_prompt if base_prompt is not None else _PER_QUESTION_SYSTEM
    parts: List[str] = []

    profile_lens = build_user_profile_lens(user_profile)
    if profile_lens:
        parts.append(profile_lens)

    if analysis_type:
        framework_lens = _FRAMEWORK_LENSES.get(analysis_type)
        if framework_lens:
            parts.append(framework_lens)

    parts.append(base)
    return "\n".join(parts)


_FENCED = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _parse_json(text: str) -> Dict[str, Any]:
    """Tolerantly parse the LLM output as JSON.

    Handles four cases:
      1. Clean JSON.
      2. ` ```json ... ``` ` code fences.
      3. JSON object embedded in prose (extracts the outermost `{...}`).
      4. Truncated JSON (output cut off by `max_tokens`) — auto-closes any
         unclosed strings, brackets, and braces and re-parses.
    """
    if not text:
        return {"_raw": "", "_parse_error": True}

    stripped = text.strip()
    m = _FENCED.match(stripped)
    if m:
        stripped = m.group(1).strip()

    # 1. Clean parse
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # 2. Outermost-object slice
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            pass

    # 3. Truncation recovery — close whatever the model left open.
    if start != -1:
        repaired = _close_open_json(stripped[start:])
        if repaired is not None:
            try:
                obj = json.loads(repaired)
                if isinstance(obj, dict):
                    obj["_truncated"] = True
                return obj
            except json.JSONDecodeError:
                pass

    logger.warning("Could not parse LLM JSON; first 200 chars: %s", stripped[:200])
    return {"_raw": stripped[:500], "_parse_error": True}


def _close_open_json(s: str) -> Optional[str]:
    """Best-effort repair for JSON that was truncated mid-output.

    Walks the string char-by-char, recording every position that's a "safe
    cut" — meaning we could chop the string there, append the right closers
    for whatever brackets are still open at that moment, and end up with
    parseable JSON. We then try those candidates from latest to earliest
    and return the first one `json.loads` accepts. Drops the trailing
    half-written value/key (e.g. `..."explanation": "The entry`) automatically.
    """
    if not s:
        return None

    in_string = False
    escape = False
    stack: List[str] = []
    # Each candidate is (cut_position, stack_snapshot_at_that_position)
    candidates: List[tuple] = [(0, [])]

    for i, ch in enumerate(s):
        if escape:
            escape = False
            continue
        if in_string:
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
                # cut after a complete string is safe
                candidates.append((i + 1, list(stack)))
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            stack.append("}")
            continue
        if ch == "[":
            stack.append("]")
            continue
        if ch in "}]":
            if stack:
                stack.pop()
            candidates.append((i + 1, list(stack)))
            continue
        if ch == ",":
            # safe to cut just BEFORE the comma
            candidates.append((i, list(stack)))
            continue

    # Try latest cut first.
    for cut, snap in reversed(candidates):
        prefix = s[:cut].rstrip(" \t\n\r,:")
        if not prefix:
            continue
        # Drop a dangling `"key":` pattern (no value yet) — find the last
        # unbalanced `"key":` and chop it off.
        prefix = _drop_trailing_dangling_key(prefix)
        candidate = prefix + "".join(reversed(snap))
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    return None


_DANGLING_KEY_RE = re.compile(r',?\s*"[^"\\]*(?:\\.[^"\\]*)*"\s*:\s*$')


def _drop_trailing_dangling_key(s: str) -> str:
    """Strip a trailing `"key":` (or `, "key":`) that has no value attached.

    A truncation that happens right after a colon leaves the prefix in a
    state json.loads will reject ('Expecting value'). Removing the orphan
    key restores it to a valid waiting state.
    """
    return _DANGLING_KEY_RE.sub("", s).rstrip(" \t\n\r,:")


def _call_llm(system: str, user_payload: Dict[str, Any], max_tokens: int) -> str:
    """Two-attempt LLM call with parse-validation retry.

    Attempt 1 uses `response_format=json_object` for strict JSON. We RETRY
    when ANY of these happen:
      • SDK exception (model rejected the flag, network blip, OpenRouter
        returned an HTML error page, etc.)
      • SDK raised `json.JSONDecodeError` from `response.json()` (the body
        wasn't valid JSON at the transport layer — truncation, SSE leak).
      • The HTTP call succeeded but `message.content` is unparseable garbage.
        This is the failure mode `openai/gpt-oss-120b` hits intermittently —
        the model emits something like `{"": "Invalid: 1"}.}1740\\n}` and
        our caller turned it into a score-zero "_parse_error" card with no
        retry. We now run the parser BEFORE returning so we can recover.

    Attempt 2 is plain completion mode on a fresh round-robin API key (see
    `get_client()` in `utils.model_config`) — different key + different
    response shape often clears whatever made attempt 1 misbehave.
    """
    from utils.model_config import guarded_llm_call

    base_kwargs = dict(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload, default=str, ensure_ascii=False)},
        ],
        model=LLM_MODEL,
        temperature=0.2,
        max_tokens=max_tokens,
        timeout=LLM_TIMEOUT_SEC,
    )

    # Attempt 1 — strict JSON mode.
    try:
        resp = guarded_llm_call(
            **base_kwargs,
            response_format={"type": "json_object"},
        )
        text = (resp.choices[0].message.content or "").strip()
        # Validate parseability BEFORE returning. If the body parses cleanly
        # we're done; otherwise fall through to the retry. _parse_json is
        # tolerant (handles fences, truncation, embedded prose) so a
        # _parse_error here means the content really is unrecoverable garbage.
        if text and not _parse_json(text).get("_parse_error"):
            return text
        logger.warning(
            "LLM (json mode) returned unparseable content (%d chars); "
            "retrying without response_format. Sample: %r",
            len(text), text[:120],
        )
    except Exception as exc:
        msg = str(exc).lower()
        if "response_format" in msg or "json_object" in msg or "unsupported" in msg:
            logger.info("Model rejected response_format; retrying without JSON mode.")
        elif isinstance(exc, json.JSONDecodeError) or "expecting value" in msg:
            logger.warning(
                "LLM (json mode) response failed to decode at the SDK layer "
                "(%s); retrying without response_format on a fresh key.",
                exc.__class__.__name__,
            )
        else:
            logger.warning(
                "First LLM call failed (%s: %s); retrying once without "
                "response_format.",
                exc.__class__.__name__,
                str(exc)[:200],
            )

    # Attempt 2 — plain mode, fresh API key (round-robin in get_client).
    resp = guarded_llm_call(**base_kwargs)
    text = (resp.choices[0].message.content or "").strip()
    if not text or _parse_json(text).get("_parse_error"):
        # Log the second-attempt body too — gives operators a clear signal
        # that the model itself is misbehaving, not just one transient call.
        logger.warning(
            "LLM (plain mode) also returned unparseable content (%d chars). "
            "Caller will fall back to the error card. Sample: %r",
            len(text), text[:120],
        )
    return text


def explain_question(
    question: Dict[str, Any],
    *,
    analysis_type: Optional[str] = None,
    user_profile: Optional[Dict[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    """Run the 3-stage analysis on ONE compacted question (from `compact_question`).

    `analysis_type` (already normalised by the caller) selects an
    SMC / ICT / VSA / Patterns / Price Action framework lens that gets
    prepended to the per-question system prompt. None → existing generic
    explanation.

    `user_profile` (already normalised by the caller via
    `normalize_user_profile`) tailors explanation depth, terminology, and
    trade-management focus to the student's trading style, experience level,
    asset class, and years of experience. None / all-empty → no tailoring.

    Returns the mentor card shape (`overall_score`, `market_analysis`,
    `student_review.{did_well, mistake, improve}`, `mentor_note`). On LLM
    failure or unparseable output, returns the same shape with `_error` /
    `_parse_error` flags set so the frontend can render a graceful fallback
    instead of a blank card.
    """
    system_prompt = build_analysis_system_prompt(analysis_type, user_profile=user_profile)

    # Detect a "Scalper submitting a swing setup" / "Swing Trader on a 0.3%
    # target" mismatch between the user's profile and the trade structure,
    # then inject the warning into the question payload so the LLM can quote
    # it. compact_question() can't compute this — it doesn't know the user's
    # profile — so we layer it in here at LLM-call time.
    #
    # When a mismatch fires we ALSO patch `score_breakdown` to include the
    # -0.5 style-deduction (the breakdown was computed at compact-time
    # without knowing the user profile). This keeps `base_score` consistent
    # with the spec rubric in `explain_api_enhancement_task.md`.
    if user_profile:
        from .drawing_extractor import _build_style_alignment
        warning = _build_style_alignment(
            user_profile.get("trading_style"),
            question.get("trade_facts") or {},
        )
        if warning:
            question = {**question, "style_alignment_warning": warning}
            sb = question.get("score_breakdown")
            if isinstance(sb, dict):
                # Avoid double-application if compact_question already
                # included the deduction (it currently doesn't, but be safe).
                already = any(
                    "style" in (d.get("reason") or "").lower()
                    for d in sb.get("deductions", []) if isinstance(d, dict)
                )
                if not already:
                    new_sb = {**sb}
                    new_sb["deductions"] = list(sb.get("deductions", [])) + [{
                        "reason": "Trading style vs setup mismatch",
                        "delta": -0.5,
                    }]
                    new_sb["base_score"] = max(
                        0.0, min(10.0, round(float(sb.get("base_score", 0)) - 0.5, 1))
                    )
                    question = {**question, "score_breakdown": new_sb}

    # Prepend a CURRENT TRADE preamble that anchors the LLM to THIS
    # instrument's pair / prices / direction / outcome. The static base
    # prompt is intentionally instrument-agnostic (uses `<price>`
    # placeholders) so the LLM isn't biased by hardcoded ITC/ONGC numbers;
    # this preamble is what fills those placeholders with the live values
    # for THIS trade. Without it, every trade looks the same to the model.
    preamble = _build_current_trade_preamble(question)
    if preamble:
        system_prompt = f"{preamble}\n{system_prompt}"

    # Build a dynamic few-shot example matched to THIS trade and append it to
    # the system prompt (Problem 5 in the enhancement task). The example is
    # generated from the same pre-extracted context the LLM is reading, so
    # numbers/zones/score in the example are consistent with the actual
    # input — the LLM can paraphrase but can't drift on the values.
    few_shot = _build_few_shot_example(question)
    if few_shot:
        system_prompt = f"{system_prompt}\n\n{few_shot}"

    try:
        text = _call_llm(system_prompt, question, LLM_MAX_TOKENS_PER_QUESTION)
    except Exception as exc:
        logger.exception("LLM call failed for question %s", question.get("question_no"))
        return _empty_card(question, error=str(exc), summary=f"LLM call failed: {exc}")

    parsed = _parse_json(text)
    # Identity fields (question_no, pair, timeframe) are FORCED back to the
    # input question's values — never trusted from the LLM output. We saw the
    # model occasionally hallucinate `question_no` (e.g. emitting `3` while
    # processing the 4th question because it had seen the 1/2/3 pattern in
    # the prompt). When two cards share the same question_no, the frontend
    # dedupes them on render — so Q4 silently disappears from the user's
    # view despite the array containing 4 entries. Hard-overriding the
    # identity here makes that class of drop impossible.
    parsed["question_no"] = question.get("question_no")
    parsed["pair"] = question.get("pair")
    parsed["timeframe"] = question.get("timeframe")
    # When the multi-answer flow stamped a requested_answer_id on this
    # question, surface it on the final card so the frontend knows which
    # trade each card maps to (essential when the user passed answer_id=[A,B]).
    if question.get("requested_answer_id") is not None:
        parsed["requested_answer_id"] = question.get("requested_answer_id")
    # Make sure every card field exists so the frontend never sees `undefined`.
    parsed.setdefault("overall_score", 0)
    for key, _ in _SECTION_KEYS:
        parsed.setdefault(key, "—")
    sr = parsed.get("student_review")
    if not isinstance(sr, dict):
        sr = {}
        parsed["student_review"] = sr
    for key, _ in _STUDENT_REVIEW_KEYS:
        sr.setdefault(key, "—")

    # Defense-in-depth for SCORING IS DETERMINISTIC: the LLM is told to copy
    # `score_breakdown.base_score` (with at most ±1.0 CHoCH/BOS adjustment),
    # but in practice it sometimes ignores the rubric and emits a score from
    # its own narrative judgment — e.g. 3.5/10 for an ITC trade where the
    # rubric said 7.2. When that happens the user sees a number that
    # disagrees with `score_breakdown` itself, which is incoherent. Clamp
    # the LLM's score to within ±1.0 of `base_score` and flag the override.
    if not parsed.get("_parse_error"):
        sb = question.get("score_breakdown") or {}
        base = sb.get("base_score")
        if isinstance(base, (int, float)):
            try:
                llm_score = float(parsed.get("overall_score", base))
            except (TypeError, ValueError):
                llm_score = float(base)
            if abs(llm_score - float(base)) > 1.0:
                parsed["overall_score"] = float(base)
                parsed["_score_overridden"] = True
                parsed["_score_override_note"] = (
                    f"LLM emitted overall_score={llm_score} but the deterministic "
                    f"rubric base_score={base}. Difference exceeds the allowed "
                    f"±1.0 CHoCH/BOS adjustment — overall_score has been clamped "
                    f"to base_score."
                )
                logger.warning(
                    "Score override on Q%s: LLM=%s, base_score=%s",
                    question.get("question_no"), llm_score, base,
                )

    if parsed.get("_parse_error"):
        parsed.setdefault(
            "_error_summary",
            "LLM output could not be parsed as JSON — likely truncated. "
            "Try increasing DRAWING_EXPLAINER_MAX_TOKENS_Q.",
        )
    return parsed


def explain_all(
    compact_session_data: Dict[str, Any],
    *,
    max_workers: Optional[int] = None,
    analysis_type: Optional[str] = None,
    user_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run per-question explanations (in parallel) then the session summary.

    `max_workers` defaults to the project's LLM concurrency limit (set by the
    semaphore in `utils.model_config`); higher values just queue on it.
    `analysis_type` (SMC / ICT / VSA / Patterns / Price Action,
    case-insensitive — also accepts aliases like "PA", "price_action",
    "chart patterns") selects the framework lens; None falls through to
    the existing generic prompt.

    `user_profile` is a dict with optional `trading_style`, `user_level`,
    `assests`, `year_of_experience` keys. Each is normalised here, so the
    caller can pass raw frontend strings — empty / missing fields are simply
    omitted from the prompt.
    """
    from concurrent.futures import ThreadPoolExecutor

    normalized_type = normalize_analysis_type(analysis_type)
    normalized_profile = normalize_user_profile(user_profile)

    questions = compact_session_data.get("questions") or []
    # Treat 0/negative max_workers as "use the default" (Swagger UI auto-fills 0).
    workers = max_workers if (max_workers and max_workers > 0) else min(6, max(1, len(questions)))

    per_question: List[Dict[str, Any]] = [None] * len(questions)  # type: ignore[list-item]
    if questions:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    explain_question, q,
                    analysis_type=normalized_type,
                    user_profile=normalized_profile,
                ): i
                for i, q in enumerate(questions)
            }
            for fut in futures:
                idx = futures[fut]
                try:
                    per_question[idx] = fut.result()
                except Exception as exc:
                    logger.exception("explain_question raised")
                    per_question[idx] = _empty_card(
                        questions[idx],
                        error=str(exc),
                        summary=f"Worker raised: {exc}",
                    )

    # Defense-in-depth: every input question MUST produce an output card so the
    # frontend always renders the same number of cards as the session reports.
    # If a slot is somehow still None at this point (a bug here, not in
    # explain_question), patch it with an _empty_card placeholder rather than
    # leaving a hole that downstream code (or the frontend) might silently
    # drop. Also force the identity fields on every card so the eventual
    # `sort` + frontend dedupe by question_no can never collapse two trades.
    for i, card in enumerate(per_question):
        if not isinstance(card, dict):
            logger.error(
                "explain_all: question slot %s came back as %r — patching with "
                "an empty card so the frontend still sees %d cards.",
                i, card, len(questions),
            )
            per_question[i] = _empty_card(
                questions[i],
                error="missing_result",
                summary="Internal error: no card was produced for this question.",
            )
        else:
            # Force identity fields one more time (defense-in-depth — the LLM
            # could have nulled them post-override on a parse-recovery path).
            card["question_no"] = questions[i].get("question_no")
            card["pair"] = questions[i].get("pair")
            card["timeframe"] = questions[i].get("timeframe")

    # Order results by question_no for stable output.
    per_question.sort(key=lambda r: (r or {}).get("question_no") or 0)

    # Final invariant: never silently emit fewer cards than the input had.
    # If this ever trips, we want a loud log line so the bug is obvious in
    # the server logs rather than the user discovering missing trades.
    if len(per_question) != len(questions):
        logger.error(
            "explain_all: produced %d cards for %d input questions — count "
            "mismatch! Input question_nos=%s, output question_nos=%s",
            len(per_question), len(questions),
            [q.get("question_no") for q in questions],
            [c.get("question_no") for c in per_question if isinstance(c, dict)],
        )

    # The session-level coaching summary (strengths / weaknesses / recurring
    # mistakes / study plan / closing note) was deprecated when the response
    # format moved to the per-question card. The frontend now renders only
    # per-question cards plus the session metadata block below.

    # Reconcile session-level metadata with what the LMS actually returned in
    # the `questions` array. The chapter endpoint reports the unfiltered chapter
    # total in `total_questions` even when server-side filters (most commonly
    # `is_challenge_only=true`, but also `is_skip` exclusions) trim the
    # `questions` array — that's why a session showing `total_questions: 4`
    # can come back with only 3 trades. The frontend then renders 3 cards
    # next to a header that promises 4, which is what users notice.
    #
    # Fix: surface the upstream-reported total under a separate key
    # (`session_total_questions`) and report `total_questions` as the count
    # we actually analyzed. The two only differ when the LMS filtered the
    # array — we log a loud warning so the discrepancy is visible.
    upstream_total = compact_session_data.get("total_questions")
    actual_total = len(per_question)
    if upstream_total is not None and upstream_total != actual_total:
        logger.warning(
            "Session %s: LMS reported total_questions=%s but only %s "
            "question(s) came back in the array (likely filtered server-side "
            "by is_challenge_only / is_skip). Reporting total_questions=%s in "
            "the response so it matches the cards we analyzed; pass "
            "`is_challenge_only=false` to fetch every trade in the chapter.",
            compact_session_data.get("session_id"),
            upstream_total, actual_total, actual_total,
        )

    result: Dict[str, Any] = {
        "session": {
            "session_id": compact_session_data.get("session_id"),
            "content_title": compact_session_data.get("content_title"),
            "submit_date": compact_session_data.get("submit_date"),
            "win": compact_session_data.get("win"),
            "loss": compact_session_data.get("loss"),
            "total_points": compact_session_data.get("total_points"),
            "total_questions": actual_total,
            "session_total_questions": upstream_total,
            "win_loss_ratio": compact_session_data.get("win_loss_ratio"),
        },
        "questions": per_question,
    }
    if normalized_type:
        result["analysis_type"] = normalized_type
        result["framework_name"] = FRAMEWORK_NAMES.get(normalized_type)
    if _has_any_profile_field(normalized_profile):
        result["user_profile"] = normalized_profile
    return result
