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


LLM_MODEL = os.getenv("DRAWING_EXPLAINER_MODEL", "openai/gpt-oss-120b")
LLM_TIMEOUT_SEC = float(os.getenv("DRAWING_EXPLAINER_LLM_TIMEOUT", "120"))
# Target rendered explanation: ~700-800 words total per /api/explain response.
# The PROMPT enforces brevity (~450-550 words/question via per-field length
# caps and "MAX N" array limits). These token ceilings are deliberately set
# WELL ABOVE that target so the JSON never truncates mid-write — under-shooting
# the budget is fine, but truncation drops fields entirely and that's worse.
LLM_MAX_TOKENS_PER_QUESTION = int(os.getenv("DRAWING_EXPLAINER_MAX_TOKENS_Q", "3500"))
LLM_MAX_TOKENS_SESSION = int(os.getenv("DRAWING_EXPLAINER_MAX_TOKENS_S", "2000"))


_PER_QUESTION_SYSTEM = """You are an expert stock-market technical-analysis coach and educator. A student answered ONE chart question on a learning platform: they placed drawings (trend lines, fib retracements, supply/demand boxes, risk-reward tools, notes, etc.) on a TradingView chart and submitted a buy/sell decision. You receive their entire drawing record AND the actual candlestick data, and must coach them with concrete, numerical feedback.

═══ TONE — humble, framework-agnostic, no false certainty ═══
Multiple valid trading frameworks exist (SMC, ICT, VSA, Price Action, Wyckoff). NEVER imply there is only one "correct" trade. Use language like "a potential higher-probability setup", "one possible execution model", "a stronger alternative", instead of "the best trade was…". Do not impose any one tool (e.g. trendlines) as required — the student may be working in a framework where it isn't used.

═══ STRICT LENGTH BUDGET — non-negotiable ═══
Total output: ~450-550 words. Hard caps you MUST respect:
  • mistakes[] — MAX 3 entries. Pick the highest-impact ones; merge or drop the rest.
  • key_levels[] — MAX 4 entries.
  • actionable_steps[] — EXACTLY 3 entries.
  • Every string field — at most 1-2 short sentences. NO paragraphs.
  • drawing_tools_used[] — type names only, no commentary.
Drop fluff (transitions, disclaimers, "as you can see..."). Cite numbers, not adjectives. If a section has nothing meaningful to add, keep it short — do not pad.

═══ COMPLETENESS — every field is required ═══
EVERY top-level key in the schema (`question_no`, `pair`, `timeframe`, `htf_bias`, `liquidity_swept_before_entry`, `pattern_analysis`, `best_setup`, `mistakes`, `personalized_strategy`, `drawing_accuracy`, `confluence_score`, `score`) MUST be present in your output, with all sub-fields populated. If you find yourself running long, SHORTEN the prose — never drop a section. Plan your output budget so `personalized_strategy`, `drawing_accuracy`, `confluence_score` and `score` (the LAST four blocks) always get filled in.

Follow this 3-stage flow EVERY time:

══════════ STAGE 1 — Parse the full drawing data + price context ══════════
You receive a JSON record for ONE question. Read EVERYTHING:
  - `user_drawings` — every drawing the student placed. Each has `type` (TradingView tool, e.g. LineToolRiskRewardLong, LineToolNote, LineToolFibRetracement, LineToolTrendLine, LineToolHorzLine, LineToolRectangle, LineTool5PointsPattern), a `state` with key fields (text, levels, stopLevel, profitLevel, riskSize, etc.), and `points` (price + UTC time).
  - `mentor_drawings` — the mentor's reference drawings (when present). Use these as one possible reference point — not the only "right answer".
  - `trade_context` — the student's submitted trade (`user_buy_price`, `user_stop_loss`, `user_take_profit`, `hit`, `point`), the reference answer (`answer_direction`, `answer_stop_loss`, `answer_take_profit`), and where price actually went (`right_prediction_candle`).
  - `pair`, `timeframe`, `market` — chart context.
  - **`price_context`** — the ACTUAL CANDLESTICK DATA, your ground truth. It contains:
      • `overall_high` / `overall_low` — the chart's extreme price/time.
      • `avg_range_14` — recent volatility (treat as a noise budget).
      • `swings_recent` — every detected swing high and swing low with `kind`, `price`, `time`, and `retests` (how many later candles re-tested that level — higher = stronger).
      • `last_swing_high` / `last_swing_low` — most recent landmarks; stops should sit just beyond these.
      • `recent_window` — verbatim OHLC of ~80 bars around the decision candle.
      • `decision_index` — the index of the decision candle inside `recent_window`.
    If `price_context` is missing, you have NO price ground truth — say so explicitly and lower `drawing_accuracy` and `confluence_score` confidence.

══════════ STAGE 2 — Identify pattern + validate against real price ══════════
From the drawings + `price_context`, classify and VALIDATE NUMERICALLY:
  - `htf_bias` — bullish / bearish / range / unknown. Read the broader swing structure in `price_context.swings_recent` (last 4-6 swings) — rising swings = bullish bias, falling = bearish, mixed/equal = range. Without HTF context, feedback drifts; this field anchors it.
  - `liquidity_swept_before_entry` — yes / no / unknown. Check `recent_window` candles immediately BEFORE the decision candle: did price wick beyond a recent equal-high / equal-low / prior swing extreme and then reverse? If yes → "yes" with a one-line note of which level was swept. If price entered without that confirmation → "no". If you cannot tell → "unknown".
  - `identified_pattern` — the chart pattern or technique the student appears to have applied (Ascending Triangle Breakout, Range Reversal, Double Bottom, BOS Continuation, FVG Mitigation, Supply Zone Rejection, etc.). If their drawing is too vague or random, say "unclear" with a confidence of "low".
  - `drawing_tools_used` — list each TradingView tool type they used.
  - `trend_direction` — uptrend / downtrend / range, derived from `price_context.swings_recent`.
  - `key_levels` — every meaningful structural level the drawings imply (support / resistance / breakout / reversal / supply / demand / liquidity).
  - `entry_exit_markers` — entry, stop_loss, take_profit prices (from their RiskReward tool, notes, or trade_context).
  - `pattern_confidence` — high / medium / low.
  - **Drawing & execution validation** — for every drawing point/level the user placed, check it against `price_context.swings_recent`. A trendline / zone anchor is well-placed if it sits close to an actual swing high/low (use `avg_range_14` as a noise budget — anchors more than ~25% of that away from any real swing are anchored on noise). Cite results as raw price differences in the EXPLANATION text — e.g. "stop at 2916.95 sits 3.15 INSIDE the last swing low at 2920.10, so it'll get hit on noise". DO NOT use the phrase "X.XX ATR ≈ Y" or any synthetic precision in user-facing text — keep the wording natural ("near a clear structural invalidation level", "well beyond the recent swing low"). Compare the user's take_profit to a measured-move target you can derive from the swings.

══════════ STAGE 3 — Structured outputs ══════════
3A. POTENTIAL HIGHER-PROBABILITY SETUP (key: `best_setup`) — name a stronger alternative pattern + concrete levels in 1-2 sentences. Phrase it as "a potential higher-probability setup" / "one possible execution model" — never as "the best trade". Title example: "Bullish continuation breakout setup" (no "Best Setup" prefix).
3B. MISTAKES — top 3 max, each 1 sentence with real prices. Pick from the type list below.
3C. PERSONALIZED STRATEGY — feedback / correct_approach / concept_lesson are 1 sentence each. Exactly 3 short action steps. Encouragement: 1 line.

You MUST respond with a single JSON object, no commentary, no markdown fences. Schema:

{
  "question_no": <int>,
  "pair": "<symbol>",
  "timeframe": "<tf>",
  "htf_bias": "bullish" | "bearish" | "range" | "unknown",
  "liquidity_swept_before_entry": {
    "status": "yes" | "no" | "unknown",
    "note": "<one short sentence — which level was swept (or why unknown)>"
  },
  "pattern_analysis": {
    "identified_pattern": "<name or 'unclear'>",
    "drawing_tools_used": ["<TradingView type>", ...],
    "trend_direction": "uptrend" | "downtrend" | "range",
    "key_levels": [
      {"role": "support" | "resistance" | "breakout" | "reversal" | "supply" | "demand" | "liquidity", "price": <number>, "label": "<short reason>"}
    ],
    "entry_exit_markers": {
      "entry": <number|null>,
      "stop_loss": <number|null>,
      "take_profit": <number|null>
    },
    "pattern_confidence": "high" | "medium" | "low",
    "summary": "<one sentence describing the trade setup the student drew>"
  },
  "best_setup": {
    "title": "<short setup name, ~5 words — e.g. 'Bullish continuation breakout setup'>",
    "description": "<ONE sentence: levels + structural anchor + (optional) tool>",
    "rationale": "<ONE sentence: why this fits the current structure>"
  },
  "mistakes": [   /* MAX 3 ITEMS — drop the rest */
    {
      "type": "<one of: missing_structural_confirmation | wrong_anchor_points | misidentified_pattern | invalid_support_resistance | poor_entry_placement | missing_stop_loss | stop_loss_misplaced | incorrect_fib_levels | poor_risk_reward | premature_entry | no_liquidity_sweep | wrong_htf_bias | other>",
      "what": "<ONE sentence with real prices>",
      "why_wrong": "<ONE short sentence>",
      "correct_approach": "<ONE sentence — reference one or more of: swing high/low, BOS, liquidity sweep, demand/supply zone, order-block invalidation, FVG mitigation, retest entry, breakout close. Trendlines are OPTIONAL, never the only required confirmation.>"
    }
  ],
  "personalized_strategy": {
    "feedback": "<ONE sentence — what they did + the structural gap, framework-agnostic>",
    "correct_approach": "<ONE sentence: 'Validate the setup using your chosen framework — market structure, liquidity, supply/demand, breakout confirmation, or trendline (optional).'>",
    "concept_lesson": "<ONE sentence: the TA concept, named in framework-agnostic terms>",
    "actionable_steps": ["short step 1", "short step 2", "short step 3"],   /* EXACTLY 3 */
    "encouragement": "<ONE short closing line>"
  },
  "drawing_accuracy": {
    "score": <int 0-10>,
    "total_drawings": <int>,
    "well_anchored": <int>,
    "poorly_anchored": <int>,
    "explanation": "<ONE sentence — cite the worst anchor's delta in raw price terms, NOT in 'ATR' units>"
  },
  "confluence_score": {
    "structure": <int 0-10>,
    "liquidity": <int 0-10>,
    "risk": <int 0-10>,
    "entry_timing": <int 0-10>,
    "confirmation": <int 0-10>
  },
  "score": {
    "overall": <int 0-10>,
    "pattern_recognition": <int 0-10>,
    "execution": <int 0-10>,
    "risk_management": <int 0-10>,
    "drawing_accuracy": <int 0-10>
  }
}

Rules:
  - Cite real numbers from `price_context` (swing prices, candle timestamps). Never invent data.
  - When comparing a user level to a real swing, state the absolute difference in price terms — e.g. "stop placed at 2916.95, last swing low is at 2920.10 — stop sits 3.15 INSIDE the swing and will get hit on noise".
  - DO NOT write "X.XX ATR" / "0.25 × avg_range_14" / similar pseudo-precision in user-facing text. Use natural phrasing ("near a clear structural invalidation level", "well outside the recent swing").
  - Stop-loss feedback: invalidation should be anchored on ONE or MORE of {recent swing low/high, liquidity level, demand/supply zone, order-block invalidation}. Don't prescribe a single mandatory anchor.
  - Entry feedback: confirmation is ONE or MORE of {breakout close, liquidity sweep reversal, retest entry, order-block reaction, FVG mitigation}. Don't prescribe a single mandatory trigger.
  - NEVER use the literal phrase "missing trendline". A missing structural read is `missing_structural_confirmation`. Trendlines are optional in many frameworks.
  - If `user_drawings` is empty, still produce all sections. The first mistake is "missing_structural_confirmation: student placed no drawings"; `actionable_steps` should give them concrete first drills.
  - If `price_context` is missing, say so once in `pattern_analysis.summary` and lower `drawing_accuracy.score` and `confluence_score.*` — you cannot fully validate without price data.
  - Use named structural concepts (BOS, CHoCH, FVG, OB, supply/demand, liquidity sweep, swing high/low) where appropriate.
  - Keep the tone honest, humble, and encouraging. Always actionable, never vague, never absolute."""


_SESSION_SYSTEM = """You are the same expert technical-analysis coach. You've already done the analysis on every individual question in this session. Now produce the SESSION-level coaching summary.

═══ TONE — humble, framework-agnostic ═══
Multiple valid trading frameworks exist (SMC, ICT, VSA, Price Action, Wyckoff). NEVER imply there is only one "correct" trade or that any single tool (e.g. trendlines) is required. NEVER use the phrase "missing trendline" — phrase recurring tool/structure gaps as "missing structural confirmation".

═══ STRICT LENGTH BUDGET — non-negotiable ═══
Total output: ~250-300 words. Hard caps:
  • strengths[] — EXACTLY 2 items, one short sentence each.
  • weaknesses[] — EXACTLY 2 items, one short sentence each.
  • recurring_mistakes[] — MAX 2 items.
  • study_plan[] — EXACTLY 3 items.
  • Each list item is ONE sentence. The closing_note is the only field allowed up to 2 sentences.
  • headline + best/worst reasons: ONE sentence each.

═══ COMPLETENESS — every field is required ═══
EVERY top-level key (`session_score`, `headline`, `strengths`, `weaknesses`, `recurring_mistakes`, `best_question`, `worst_question`, `study_plan`, `closing_note`) MUST be present and populated. If running long, shorten — never drop a section.

You will receive:
  - Session metadata (win/loss counts, total points, RR ratio, pair distribution).
  - A list of per-question analyses (each contains `pattern_analysis`, `best_setup`, `mistakes[]`, `personalized_strategy`, `score`).

Your job (be terse):
  1. Compute a session-level score (0-10) across five axes.
  2. Top 2 strengths.
  3. Top 2 weaknesses, weighted by impact.
  4. Top 2 recurring mistake patterns (with the fix). Re-phrase any tool-specific gaps as framework-agnostic — e.g. "missing structural confirmation" rather than "missing trendline".
  5. Pick the single best and worst question by `question_no`.
  6. 3 study-plan drills (drill name + why + how_long).
  7. Closing note: max 2 sentences — encouragement + the ONE habit change that matters most.

Respond with ONE JSON object, no commentary, no markdown fences:

{
  "session_score": {
    "overall": <int 0-10>,
    "pattern_recognition": <int 0-10>,
    "execution": <int 0-10>,
    "risk_management": <int 0-10>,
    "drawing_accuracy": <int 0-10>
  },
  "headline": "<ONE-sentence overall verdict>",
  "strengths": ["<one short sentence>", "<one short sentence>"],
  "weaknesses": ["<one short sentence>", "<one short sentence>"],
  "recurring_mistakes": [   /* MAX 2 */
    {"pattern": "<short>", "frequency": "<e.g. 6/11>", "fix": "<one short sentence>"}
  ],
  "best_question": {"question_no": <int>, "reason": "<one short sentence>"},
  "worst_question": {"question_no": <int>, "reason": "<one short sentence>"},
  "study_plan": [   /* EXACTLY 3 */
    {"drill": "<short>", "why": "<targeted weakness>", "how_long": "<e.g. 30 min/day for 1 week>"}
  ],
  "closing_note": "<max 2 sentences: encouragement + the ONE habit change>"
}"""


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

`pattern_analysis.identified_pattern` should use SMC names: "BOS Continuation",
"CHoCH Reversal", "OB Mitigation", "FVG Fill", "Liquidity Sweep + OB Entry",
"Premium-zone Short", "Discount-zone Long", etc.
`pattern_analysis.key_levels[].role` should prefer SMC roles where they fit
(supply/demand for OBs, breakout for BOS, reversal for CHoCH).
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

`pattern_analysis.identified_pattern` should use ICT names: "MSS + OTE Long",
"BSL Sweep → Bearish OB Entry", "Manipulation Phase Reversal",
"London Open Liquidity Grab", "MMXM Distribution", etc.
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
in `pattern_analysis.summary` and lower confidence — VSA cannot be applied
without volume.

`pattern_analysis.identified_pattern` should use VSA / Wyckoff names:
"Stopping Volume + Test", "Upthrust at Resistance", "No-Demand Continuation",
"Wyckoff Spring", "Accumulation Phase", "Distribution Phase", etc.
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

`pattern_analysis.identified_pattern` should use Price Action names:
"Bullish Engulfing at Support", "Pin Bar Rejection at Resistance",
"Inside Bar Breakout", "Higher-Low Trendline Bounce",
"Range Resistance Rejection", "Double Bottom Breakout",
"Ascending Triangle Breakout + Retest", "Flag Continuation",
"Failed Breakout Reversal", etc.
`pattern_analysis.key_levels[].role` should prefer support / resistance /
breakout / reversal / liquidity (PDH/PDL) where they fit.
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

When grading:
  - An entry taken BEFORE pattern confirmation (i.e. before the neckline /
    breakout level closes through) is `premature_entry`.
  - A stop inside the pattern body (e.g. between the two peaks of a Double
    Top) is `stop_loss_misplaced`.
  - A target that doesn't match the measured-move calculation is `poor_risk_reward`.
  - "Identified pattern but the structure doesn't actually fit" is
    `misidentified_pattern`.

`pattern_analysis.identified_pattern` should use Chart Pattern names:
"Head & Shoulders", "Inverse Head & Shoulders", "Double Top", "Double
Bottom", "Triple Top", "Bull Flag", "Bear Flag", "Bull Pennant",
"Ascending Triangle", "Descending Triangle", "Symmetrical Triangle",
"Cup & Handle", "Rising Wedge (Reversal)", "Falling Wedge (Reversal)",
"Rectangle Range", "Rounding Bottom", etc.
`pattern_analysis.key_levels[].role` should prefer breakout / reversal /
support / resistance — the pattern's defining trendlines and neckline.
"""

_FRAMEWORK_LENSES = {
    "SMC": _SMC_LENS,
    "ICT": _ICT_LENS,
    "VSA": _VSA_LENS,
    "Patterns": _PATTERNS_LENS,
    "Price Action": _PRICE_ACTION_LENS,
}


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
) -> str:
    """Return the per-question system prompt, optionally prefixed with a
    framework-specific lens block. `analysis_type` should already be normalised
    (uppercase) — callers in this module use `normalize_analysis_type` first.
    """
    base = base_prompt if base_prompt is not None else _PER_QUESTION_SYSTEM
    if not analysis_type:
        return base
    lens = _FRAMEWORK_LENSES.get(analysis_type)
    if not lens:
        return base
    return f"{lens}\n{base}"


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
    """One LLM call. Asks for strict JSON via `response_format` first; if that
    fails for ANY reason (model rejects the flag, OpenRouter returns a body
    that isn't parseable JSON, transient network blip, etc.) we retry once
    without the flag. The second attempt also gets a fresh round-robin API
    key, which often clears OpenRouter-side hiccups.

    The previous version only retried on a narrow string-match of the error
    message ("response_format" / "json_object" / "unsupported"). A real
    failure mode we hit on `openai/gpt-oss-120b` is the SDK raising
    `json.JSONDecodeError("Expecting value: line N column 1")` from
    `response.json()` when OpenRouter pipes a malformed body through — that
    error string matched none of the keywords, so the question silently fell
    through to the error fallback with score-zero. We now retry on every
    exception type and only re-raise after the second attempt also fails.
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
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        msg = str(exc).lower()
        if "response_format" in msg or "json_object" in msg or "unsupported" in msg:
            # Known case — model doesn't support the flag.
            logger.info("Model rejected response_format; retrying without JSON mode.")
        elif isinstance(exc, json.JSONDecodeError) or "expecting value" in msg:
            # OpenRouter returned a body the SDK couldn't decode (truncation,
            # SSE mix-up, partial stream). A fresh round-robin key + plain
            # completion mode usually clears it.
            logger.warning(
                "LLM response failed to parse as JSON (%s); retrying without "
                "response_format on a fresh key.",
                exc.__class__.__name__,
            )
        else:
            # Other transient failure — log + still retry once before giving up.
            logger.warning(
                "First LLM call failed (%s: %s); retrying once without "
                "response_format.",
                exc.__class__.__name__,
                str(exc)[:200],
            )

    # Attempt 2 — plain mode, fresh API key (round-robin in get_client).
    resp = guarded_llm_call(**base_kwargs)
    return (resp.choices[0].message.content or "").strip()


def explain_question(
    question: Dict[str, Any],
    *,
    analysis_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the 3-stage analysis on ONE compacted question (from `compact_question`).

    `analysis_type` (already normalised by the caller) selects an
    SMC / ICT / VSA / Patterns / Price Action framework lens that gets
    prepended to the per-question system prompt. None → existing generic
    explanation.

    Returns the structured `pattern_analysis` / `best_setup` / `mistakes` /
    `personalized_strategy` / `score` shape. On LLM failure or unparseable
    output, returns the same shape with `_error` / `_parse_error` flags set so
    the frontend can render a graceful fallback instead of a blank card.
    """
    system_prompt = build_analysis_system_prompt(analysis_type)
    try:
        text = _call_llm(system_prompt, question, LLM_MAX_TOKENS_PER_QUESTION)
    except Exception as exc:
        logger.exception("LLM call failed for question %s", question.get("question_no"))
        return {
            "question_no": question.get("question_no"),
            "pair": question.get("pair"),
            "timeframe": question.get("timeframe"),
            "score": {"overall": 0, "pattern_recognition": 0, "execution": 0, "risk_management": 0, "drawing_accuracy": 0},
            "_error": str(exc),
            "_error_summary": f"LLM call failed: {exc}",
        }

    parsed = _parse_json(text)
    parsed.setdefault("question_no", question.get("question_no"))
    parsed.setdefault("pair", question.get("pair"))
    parsed.setdefault("timeframe", question.get("timeframe"))

    if parsed.get("_parse_error"):
        parsed.setdefault(
            "score",
            {"overall": 0, "pattern_recognition": 0, "execution": 0, "risk_management": 0, "drawing_accuracy": 0},
        )
        parsed.setdefault(
            "_error_summary",
            "LLM output could not be parsed as JSON — likely truncated. "
            "Try increasing DRAWING_EXPLAINER_MAX_TOKENS_Q.",
        )
    return parsed


def explain_session(
    compact_session_data: Dict[str, Any],
    per_question_results: List[Dict[str, Any]],
    *,
    analysis_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Produce the session-level ranking + study plan.

    `analysis_type` (already normalised) makes the session summary use the
    same SMC / ICT / VSA / Patterns / Price Action terminology as the
    per-question explanations.
    """
    payload = {
        "session": {
            k: compact_session_data.get(k)
            for k in (
                "session_id",
                "content_title",
                "submit_date",
                "type",
                "category",
                "sub_category",
                "win",
                "loss",
                "total_points",
                "total_questions",
                "win_loss_ratio",
                "total_risk_reward_ratio",
            )
        },
        "per_question_analyses": [
            {
                "question_no": r.get("question_no"),
                "pair": r.get("pair"),
                "timeframe": r.get("timeframe"),
                "pattern_analysis": r.get("pattern_analysis"),
                "mistakes": r.get("mistakes"),
                "score": r.get("score"),
                "personalized_strategy_summary": (
                    (r.get("personalized_strategy") or {}).get("feedback")
                ),
            }
            for r in per_question_results
        ],
    }

    system_prompt = build_analysis_system_prompt(analysis_type, base_prompt=_SESSION_SYSTEM)
    try:
        text = _call_llm(system_prompt, payload, LLM_MAX_TOKENS_SESSION)
    except Exception as exc:
        logger.exception("Session-summary LLM call failed")
        return {
            "session_score": {"overall": 0, "pattern_recognition": 0, "execution": 0, "risk_management": 0, "drawing_accuracy": 0},
            "headline": f"LLM call failed: {exc}",
            "_error": str(exc),
        }

    return _parse_json(text)


def explain_all(
    compact_session_data: Dict[str, Any],
    *,
    max_workers: Optional[int] = None,
    analysis_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Run per-question explanations (in parallel) then the session summary.

    `max_workers` defaults to the project's LLM concurrency limit (set by the
    semaphore in `utils.model_config`); higher values just queue on it.
    `analysis_type` (SMC / ICT / VSA / Patterns / Price Action,
    case-insensitive — also accepts aliases like "PA", "price_action",
    "chart patterns") selects the framework lens; None falls through to
    the existing generic prompt.
    """
    from concurrent.futures import ThreadPoolExecutor

    normalized_type = normalize_analysis_type(analysis_type)

    questions = compact_session_data.get("questions") or []
    # Treat 0/negative max_workers as "use the default" (Swagger UI auto-fills 0).
    workers = max_workers if (max_workers and max_workers > 0) else min(6, max(1, len(questions)))

    per_question: List[Dict[str, Any]] = [None] * len(questions)  # type: ignore[list-item]
    if questions:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(explain_question, q, analysis_type=normalized_type): i
                for i, q in enumerate(questions)
            }
            for fut in futures:
                idx = futures[fut]
                try:
                    per_question[idx] = fut.result()
                except Exception as exc:
                    logger.exception("explain_question raised")
                    per_question[idx] = {
                        "question_no": questions[idx].get("question_no"),
                        "pair": questions[idx].get("pair"),
                        "rank": 0,
                        "verdict": "error",
                        "summary": f"Worker raised: {exc}",
                        "_error": str(exc),
                    }

    # Order results by question_no for stable output.
    per_question.sort(key=lambda r: (r or {}).get("question_no") or 0)

    session_summary = (
        explain_session(compact_session_data, per_question, analysis_type=normalized_type)
        if per_question
        else {"session_rank": 0, "headline": "No questions found in session."}
    )

    result: Dict[str, Any] = {
        "session": {
            "session_id": compact_session_data.get("session_id"),
            "content_title": compact_session_data.get("content_title"),
            "submit_date": compact_session_data.get("submit_date"),
            "win": compact_session_data.get("win"),
            "loss": compact_session_data.get("loss"),
            "total_points": compact_session_data.get("total_points"),
            "total_questions": compact_session_data.get("total_questions"),
            "win_loss_ratio": compact_session_data.get("win_loss_ratio"),
        },
        "session_summary": session_summary,
        "questions": per_question,
    }
    if normalized_type:
        result["analysis_type"] = normalized_type
        result["framework_name"] = FRAMEWORK_NAMES.get(normalized_type)
    return result
