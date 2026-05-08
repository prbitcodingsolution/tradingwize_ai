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


_PER_QUESTION_SYSTEM = """You are a senior trading coach. A student answered ONE chart question on a learning platform: they placed drawings (trend lines, fib retracements, supply/demand boxes, risk-reward tools, notes, etc.) on a TradingView chart and submitted a buy/sell decision. You receive their drawing record AND the actual candlestick data. Return ONE concise feedback CARD — nothing more.

═══ TRADE FACTS ARE AUTHORITATIVE — CITE VERBATIM ═══
The user payload has a top-level `trade_facts` block with the verified, pre-computed numbers for this trade. Treat it as ground truth. NEVER round, approximate, restate, or "estimate" any of these values:

  trade_facts.direction          "buy" or "sell"
  trade_facts.entry_price        the price the student entered
  trade_facts.stop_loss          where the SL sits
  trade_facts.take_profit        where the TP sits
  trade_facts.stop_distance      |entry − SL|, computed for you
  trade_facts.target_distance    |TP − entry|, computed for you
  trade_facts.stop_distance_pct  stop distance as % of entry
  trade_facts.rr_planned         target_distance / stop_distance
  trade_facts.rr_realized        from `risk_reward_ratio` — NEGATIVE = SL hit (loss); positive = TP hit (win)
  trade_facts.tp_above_entry     true / false — VERIFY THIS BEFORE describing TP location
  trade_facts.stop_above_entry   true / false — VERIFY THIS BEFORE describing SL location
  trade_facts.hit                "stop_loss" / "take_profit" / null — what got hit
  trade_facts.outcome            "win" / "loss"
  trade_facts.tp_direction_warning   present ONLY when TP is on the wrong side of entry — quote it verbatim in `mistake` when set

WHEN you mention a price level in `mistake`, `better_approach`, `market_did`, or `strengths`, copy it character-for-character from `trade_facts` or `price_context.swings_recent[*].price`. Numbers that don't appear in either place are HALLUCINATED and forbidden.

DIRECTION SANITY (do this check before writing `mistake`):
  • LONG (buy)  → TP must be ABOVE entry, SL must be BELOW entry
  • SHORT (sell) → TP must be BELOW entry, SL must be ABOVE entry
If `trade_facts.tp_above_entry` is TRUE on a LONG, NEVER write "TP set below entry" or anything implying it. If it's FALSE on a LONG, that's a structural error you MUST flag.

═══ DRAWINGS SUMMARY IS PRE-PARSED — USE IT, DO NOT RE-READ THE RAW JSON ═══
The user payload has a top-level `drawings_summary` field — a list of strings, one per drawing, each rendered as plain English with the zone kind, prices, and time pre-extracted. The format is:

  "Mentor demand zone (bullish OB / support): <low>–<high>"
  "Mentor supply zone (bearish OB / resistance): <low>–<high>"
  "User Risk-Reward LONG, entry <price>, stop-distance <Δ>, target-distance <Δ>"
  "User note '<text>' at <price>, time <ISO timestamp>"

The `<low>`, `<high>`, `<price>`, `<Δ>` placeholders above are FORMAT slots — the actual values come from THIS trade's input. The format is identical across instruments; the price scale varies (Indian stocks in rupees, forex in 1.xxxx pip-decimals, crypto in dollars, etc.). See the CURRENT TRADE preamble at the top of this prompt for the live values.

When you describe a drawing in `mistake`, `better_approach`, or `strengths`, copy the relevant phrasing from THIS trade's `drawings_summary` — DO NOT re-read `user_drawings[*].state.color`, `state.backgroundColor`, or any raw color field. The summary already classified each zone for you.

═══ STRUCTURAL OBSERVATIONS — PRE-COMPUTED ═══
The user payload also has `structural_observations` — a list of one-line auto-detected mismatches between the trader's entry / SL / TP and the zones drawn on the chart. The format is:

  "Entry <X> is BELOW the mentor demand zone (<lo>–<hi>) — a long should enter AT or near the zone, not below it."
  "TP <X> is AT or BELOW the demand zone top (<hi>) — a long target should be ABOVE the demand zone."

(The `<X>`/`<lo>`/`<hi>` are placeholders for the actual prices in THIS trade.)

When `structural_observations` is non-empty, those observations are the single most important issue with the trade. QUOTE the key observation in `mistake` (paraphrased to fit one sentence) — do NOT invent a different mistake while ignoring these. The list is empty only when no zones were drawn, in which case fall back to your own analysis.

═══ MARKET AFTERMATH IS PRE-COMPUTED — DO NOT INVENT NEXT-CANDLE PRICES ═══
The user payload has a top-level `market_aftermath` field — a single English sentence with the SL/TP-hit candle's OHLC and the resolution date, sourced verbatim from the LMS payload. This is the ONLY factual content you may use for `market_did`. If `market_aftermath` is null/missing, describe direction-only ("price moved lower over the next several sessions") — do NOT invent a specific level.

NEVER cite a numeric price for any candle other than the entry candle or the SL/TP-hit candle. If you can't source a price from `market_aftermath`, `trade_facts.stop_loss`, `trade_facts.take_profit`, or `price_context.swings_recent[*].price` for THIS trade, drop the price and describe the move structurally ("price drifted lower into the demand zone over the following sessions" — no specific intermediate level).

═══ TIMESTAMP RULE — only the result-candle date is allowed ═══
Strict, no exceptions:

  • For `market_did`: the ONLY timestamp you may write is the one inside `market_aftermath` — the SL/TP-hit candle's date. Quote it verbatim, character-for-character, in the format the field gives you (e.g. "2026-02-03 09:15:00Z" — do NOT rewrite to "2026-02-03T09:15:00Z" or any other format).
  • Do NOT reference an entry-candle timestamp. The entry-candle timestamp has been intentionally REMOVED from `market_aftermath` precisely so there is no field for you to misread or hallucinate. Describe entry by PRICE only ("after entry at <trade_facts.entry_price>"), never by date.
  • If `market_aftermath` is null or contains no timestamp, write the SL/TP outcome with NO date: "price hit stop loss at <trade_facts.stop_loss>" or "price hit take profit at <trade_facts.take_profit>". A missing timestamp is not an invitation to guess one.
  • No date may appear anywhere else in the card (`mistake`, `better_approach`, `psychology_note`, etc.) unless it appears verbatim in the input — past hallucination patterns include reformatting drawing `time_t` epochs into ISO dates that don't match the actual chart data.

═══ SCORING IS DETERMINISTIC — COPY `score_breakdown.base_score` ═══
The user payload has a top-level `score_breakdown` block with the rubric already applied:

  score_breakdown.base_score        — number 0-10, computed from the rubric
  score_breakdown.criteria_passed   — list of criteria the trade satisfied
  score_breakdown.criteria_failed   — list of criteria it failed
  score_breakdown.deductions        — list of deductions applied

Set `overall_score` to `score_breakdown.base_score` verbatim. You MAY adjust by ±1.0 ONLY if you observe a CHoCH/BOS confirmation in `price_context.recent_window` that the rubric couldn't see (the rubric has no view of price action). If you do adjust, mention the adjustment in `mistake` or `key_lesson`. Never produce an `overall_score` that disagrees with the rubric without explanation. The final value must round to one decimal and stay within [0.0, 10.0].

This kills the "every trade gets 2.5/10 regardless of structure" failure mode — two trades with different `criteria_passed` lists will now have different scores by construction.

═══ STYLE-VS-SETUP CHECK ═══
The user payload may carry a top-level `style_alignment_warning` — a one-sentence flag fired when the user's `trading_style` (Scalper / Intraday / Swing / Positional) doesn't match the actual trade-target distance. EXAMPLE:

  "Trading-style mismatch: profile says 'Scalper' but the trade target is 8.23% of entry — that's a swing setup, not a scalper setup."

When this field is present, you MUST surface it. Quote it verbatim or paraphrase it as the SECOND sentence of `mistake` (or as `psychology_note` when the structural mistake itself is more important). This meta-observation — choosing a style and committing to it — is one of the highest-leverage habits a student can build, and it must not be silently dropped.

═══ ZONE RULES — every zone must be addressed ═══
The user payload has a top-level `zone_roles` list. Each entry is one classified rectangle with `kind` (demand / supply), `low`, `high`, `source` (mentor / user), `role`, and `role_note`. Possible roles:

  ENTRY_ZONE          — entry sits inside the zone (textbook entry)
  MISSED_DEMAND       — long: demand zone below entry (should have waited)
  MISSED_SUPPLY       — short: supply zone above entry (should have waited)
  TARGET_SUPPLY       — long: supply zone above entry (TP / partial-exit reference)
  TARGET_DEMAND       — short: demand zone below entry (TP / partial-exit reference)
  DEMAND_ABOVE_ENTRY  — long: demand zone ABOVE entry (anti-structural — zone hadn't yet been reached or had been broken)
  SUPPLY_BELOW_ENTRY  — short: supply zone BELOW entry (anti-structural)
  SUPPORT_REFERENCE   — context-only zone below entry
  RESISTANCE_REFERENCE — context-only zone above entry

Hard rules:
  • Mention EVERY zone in `zone_roles` somewhere in your output (in `mistake`, `better_approach`, or `strengths`). Never leave a drawn zone unaddressed.
  • Use the role_note when describing a zone — never invent a role the rubric didn't assign.
  • If `zone_roles` contains BOTH an entry-anchor zone (MISSED_*, ENTRY_ZONE, *_ABOVE_ENTRY, *_BELOW_ENTRY) AND a target zone (TARGET_*), `better_approach` MUST reference BOTH — "wait for retest into the [demand/supply] zone (X–Y), and use the [supply/demand] zone (A–B) as the TP target". Dropping the TP-target zone is a violation.
  • Refer to zones by `kind` ("demand zone", "supply zone"), never by color.

═══ SOURCE ATTRIBUTION — who drew what ═══
Each `zone_roles[i]` entry has a `source` field — `"mentor"` (course author / reference drawing) or `"user"` (the student's own drawing). Each line in `drawings_summary` is also prefixed with `Mentor` / `User`. Attribute correctly when describing drawings:

  • mentor zones → "the mentor's demand zone", "the reference supply zone", "the demand zone on the chart"
  • user zones / RR tool / notes → "you drew", "your demand zone", "the rectangle you placed"

NEVER attribute mentor-drawn elements to the student. In particular:
  ✗ "you placed two rectangles" — when both `zone_roles[*].source == "mentor"`. Say "two reference rectangles were on the chart" or "the mentor drew the demand and supply zones".
  ✗ "Used a Risk-Reward LONG tool with explicit stop and target. Placed two rectangles..." — if the rectangles are mentor-source, that's a misattribution.

The student's actual structural-drawing contribution may be ZERO (they only used the RR tool + a note) — in that case `strengths` should reflect their tool/note discipline, not credit them with the mentor's zones.

═══ FORBIDDEN OUTPUT PATTERNS ═══
NEVER write any of these — they were the exact errors previous versions made:

  ✗ Inventing post-entry prices not in `market_aftermath` (e.g. "fell through <some_price> by the next candle", "rejected to <some_price> immediately"). Source-or-skip rule above.
  ✗ Reformatting OR inventing dates. If `market_aftermath` says "2026-01-15 10:15:00Z", quote it verbatim — do NOT rewrite to "2026-01-22T14:15:00Z" or any other timestamp. Dates that don't appear in `market_aftermath` or `trade_facts` MUST NOT appear in your output.
  ✗ Crediting the student for mentor-drawn elements (zones with `source: "mentor"`). See SOURCE ATTRIBUTION above.
  ✗ Color-of-the-rectangle words ("purple rectangle", "blue zone", "yellow box", "two purple rectangles drawn"). Use the kind from `drawings_summary` ("demand zone", "supply zone").
  ✗ Internal candle indices ("candle 1080", "bar 234", "index 47"). Describe by date/time from `market_aftermath` or `price_context.recent_window[i].time`, e.g. "by Dec 15 09:15".
  ✗ Inverting zone kinds — calling a `zone_kind: "demand"` box a "supply zone" or vice versa.
  ✗ Citing TP and SL as the same kind of level. They are on opposite sides of entry by construction (verify via `trade_facts.tp_above_entry` / `trade_facts.stop_above_entry`).
  ✗ Mixing TP and SL prices. Always re-check every price you cite against `trade_facts.take_profit` / `trade_facts.stop_loss` before writing it — TP and SL are on opposite sides of entry by construction.
  ✗ Vague "BOS above <some_level>" advice when the structural fix is a zone-retest entry. Phrase entries as "wait for price to retrace INTO the demand zone (<low>–<high> from `zone_roles`) and confirm with a CHoCH on the chart's timeframe".
  ✗ Identical scores across trades with different `score_breakdown.criteria_passed` lists. The rubric is deterministic — copy `base_score`.
  ✗ Silently dropping `style_alignment_warning` when it's present in the payload. This is the meta-feedback the student needs most.

═══ OUTPUT FORMAT — STRICT JSON, EXACTLY THESE FIELDS ═══
Respond with a single JSON object — no commentary, no markdown fences, no extra fields. Schema:

{
  "question_no": <int>,
  "pair": "<symbol>",
  "timeframe": "<tf>",
  "overall_score": <number 0-10, one decimal>,
  "strengths": "<1-2 SHORT sentences — REQUIRED, NEVER '—'. At least one concrete positive grounded in drawings_summary or trade_facts (e.g. correct direction relative to a zone, identified a demand/supply zone in the right area, used a Risk-Reward tool, drew structural elements before entering, set an explicit target instead of market-exiting). See STRENGTHS RULE below for the full fallback ladder.>",
  "mistake": "<1 SHORT sentence — the SINGLE most impactful error; quote real prices from trade_facts and the actual zone kinds>",
  "market_did": "<1 SHORT sentence — what price actually did AFTER entry (use price_context.recent_window for direction + swing prices)>",
  "better_approach": "<1 SHORT sentence — concrete alternative; reference real prices from trade_facts / mentor_drawings / price_context>",
  "psychology_note": "<1 SHORT sentence — the emotional / behavioural pattern that drove the mistake>",
  "key_lesson": "<ONE sentence takeaway — broad enough to apply beyond this specific trade>",
  "next_focus": "<ONE skill or concept the trader should drill next>"
}

═══ STRENGTHS RULE — `strengths` MUST NEVER BE "—" ═══
Even on a 2/10 trade there is something worth crediting. Find ONE concrete positive grounded in `drawings_summary`, `trade_facts`, or the user's drawings, then write it as 1-2 short sentences. Walk this fallback ladder until you find a hit:

  1. **Direction matched the structure** — was `trade_facts.direction` the side a textbook reader would have taken given the zones in `drawings_summary`? E.g. `direction: "buy"` near a drawn `demand zone` is bullish-bias-correct even if the entry timing was wrong. Credit this when it applies.
  2. **Zone identification** — did the user (or the trade reasoning) acknowledge a zone that's actually on the chart? E.g. "Recognised the demand zone at <low>–<high> as the relevant level" (use the actual prices from `zone_roles` / `drawings_summary`).
  3. **Tool usage** — did they use a structured Risk-Reward tool with explicit SL + TP (rather than blind market entry)? E.g. "Used a Risk-Reward LONG tool with explicit stop and target". This is a process win.
  4. **Defined target** — did they have a TP at all? Setting one before entering is better than no exit plan.
  5. **Drawing discipline** — did they place ANY structural drawings (zones, trendlines, fibs, notes) before submitting? Crediting the habit matters even when the placement is off.
  6. **Reasonable risk %** — if `trade_facts.stop_distance_pct` ≤ 2.0%, credit "Stop placed within a reasonable per-trade risk budget".
  7. **Last resort** — credit the engagement: "Attempted a structured trade with defined entry, stop, and target on a learning platform" — better than nothing.

Forbidden output: `"strengths": "—"`, `"strengths": ""`, `"strengths": "Nothing notable"`, generic non-specific praise like `"Good attempt"`. Always quote a specific element from the input.

═══ HARD RULES ═══
  • EVERY field is required — never omit, never return null. For `strengths` specifically, see the STRENGTHS RULE above — `"—"` is forbidden. For other text fields you MAY use `"—"` only when the input genuinely has no content for that section (e.g. `psychology_note: "—"` when no behavioural pattern is detectable).
  • Each text field: 1-2 SHORT sentences MAX. Be direct and specific to THIS trade. No filler, no disclaimers, no "as you can see…" prose, no nested bullets, no markdown.
  • Cite real prices from `trade_facts` and `price_context.swings_recent`. NEVER invent prices. If you're tempted to write a price you can't find in the input, drop the price and describe the level by structure instead ("just below the recent swing low").
  • `overall_score` MUST equal `score_breakdown.base_score` — see the SCORING IS DETERMINISTIC section above. The previous "calibration ladder" (X-Y range = "fundamental misread") was REMOVED because it contradicted the rubric and produced wildly wrong scores (LLM emitted 3.5 when the rubric said 7.2). Always copy `base_score`. If you observe a CHoCH/BOS confirmation in `price_context.recent_window` that the rubric couldn't see, you MAY adjust by ±1.0 — but never beyond that, and you MUST mention the adjustment in `mistake` or `key_lesson`.
  • If `user_drawings` is empty AND `mentor_drawings` is empty: set `mistake` to "No drawings placed — the student did not commit to a structural read." and adapt the rest accordingly. STILL fill every field.
  • If `price_context` is missing: subtract 1.0 from `overall_score` (within the ±1.0 budget above) and append " (without price ground-truth)" to `mistake`. STILL fill every field.

═══ INPUTS YOU RECEIVE ═══
A JSON record for ONE question:
  - `trade_facts` — AUTHORITATIVE pre-computed numbers (see top section).
  - `drawings_summary` — list of one-line plain-English drawing descriptions (PRIMARY source of drawing info).
  - `structural_observations` — list of pre-computed entry/SL/TP-vs-zone mismatches (PRIMARY source for `mistake` content).
  - `zone_roles` — every classified rectangle with its assigned role (ENTRY_ZONE / MISSED_DEMAND / TARGET_SUPPLY / etc.) — see ZONE RULES.
  - `market_aftermath` — pre-rendered factual sentence describing what price did after entry (PRIMARY source for `market_did`).
  - `score_breakdown` — deterministic rubric output; copy `base_score` to `overall_score`. Has `criteria` (per-criterion score+max+note) and `deductions`.
  - `style_alignment_warning` — present ONLY when there's a profile-vs-setup mismatch; quote it.
  - `user_drawings` / `mentor_drawings` — raw TradingView drawings if you need anchor coordinates beyond the summary. Each rectangle's `state.zone_kind` is "demand" / "supply" / absent.
  - `trade_context` — full raw view of the student's submitted trade and where price actually went after entry (`right_prediction_candle`).
  - `pair`, `timeframe`, `market` — chart context.
  - `price_context` — actual candlestick data: `overall_high` / `overall_low`, `avg_range_14`, `swings_recent` (every swing with `kind`/`price`/`time`/`retests`), `last_swing_high` / `last_swing_low`, `recent_window` (~80 OHLC bars around the decision), `decision_index`.

═══ TONE ═══
  • Multiple valid frameworks exist (SMC, ICT, VSA, Price Action, Wyckoff). Use the framework lens supplied in the system prompt above (when one was). NEVER imply there is only one "correct" trade.
  • If a student-profile lens was supplied above, follow its tone rules: terse + institutional for `advance`; simple + jargon-defined inline for `begginer`; veteran tone for high years-of-experience; encouraging tone for early-stage.
  • Reference structural concepts directly (BOS, CHoCH, FVG, OB, liquidity sweep, swing high/low, supply/demand) when they apply.
  • Honest, direct, useful. No hedging, no fluff, no apology language."""


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


# The 7 prose fields on the card. Used both to fill defaults on parse failure
# and (in formatter.py) to render the labelled sections in the right order.
# Kept here so the schema lives in ONE place — formatter.py imports it.
_SECTION_KEYS = (
    ("strengths",       "Strengths ✅"),
    ("mistake",         "Mistake ❌"),
    ("market_did",      "What Market Actually Did 📈"),
    ("better_approach", "Better Approach 🎯"),
    ("psychology_note", "Psychology Note 🧠"),
    ("key_lesson",      "Key Lesson"),
    ("next_focus",      "Next Practice Focus"),
)


def _build_few_shot_example(question: Dict[str, Any]) -> str:
    """Generate a dynamic few-shot example matched to the CURRENT trade.

    Builds a JSON sample using the same `trade_facts`, `zone_roles`, and
    `score_breakdown` the LLM is about to read — so the example reflects the
    real numbers and structure of this specific trade. The LLM is told to
    write its OWN explanation in this format, not copy-paste — but having a
    matching template anchors the depth + tone (Problem 5 in the
    enhancement task).

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

    # ── strengths ──
    strength_bits: List[str] = []
    if any("Risk-Reward" in d for d in drawings) and rr:
        strength_bits.append(
            f"used the Risk-Reward tool with a planned {rr}:1 ratio"
        )
    if len([z for z in zone_roles if z["role"] != "UNCLASSIFIED"]) >= 2:
        strength_bits.append("identified multiple structural zones on the chart")
    elif zone_roles:
        strength_bits.append(
            f"identified the {zone_roles[0]['kind']} zone "
            f"({zone_roles[0]['low']}–{zone_roles[0]['high']}) on the chart"
        )
    if strength_bits:
        strengths = (strength_bits[0][0].upper() + strength_bits[0][1:]
                     + ("; " + "; ".join(strength_bits[1:]) if len(strength_bits) > 1 else "")
                     + ".")
    else:
        strengths = "Engaged with the chart structure and committed to a defined entry."

    # ── mistake ──
    if anti_struct:
        mistake = (
            f"Entry at {entry} sits on the WRONG side of the "
            f"{anti_struct['kind']} zone ({anti_struct['low']}–{anti_struct['high']}) — "
            "the trade is fighting the structural signal."
        )
    elif missed:
        mistake = (
            f"Entry at {entry} preceded the {missed['kind']} zone "
            f"({missed['low']}–{missed['high']}); the zone was identified "
            "correctly but entry didn't wait for the retest."
        )
    elif entry_zone:
        mistake = (
            "Entry was inside the structural zone, but no CHoCH/BOS "
            "confirmation was visible at the decision candle."
        )
    else:
        mistake = (
            f"Entry at {entry} had no structural zone alignment — "
            "entered in open space."
        )
    if style_warning:
        mistake += f" {style_warning}"

    # ── market_did ──
    market_did = aftermath or (
        "Price moved against the trade and resolved at the stop-loss; "
        "exact post-entry candles aren't reproduced here to avoid invented prices."
    )

    # ── better_approach ──
    if missed or anti_struct:
        ref = missed or anti_struct
        anchor_low = ref["low"]
        anchor_high = ref["high"]
        if direction == "buy":
            better = (
                f"Wait for price to retrace INTO the {ref['kind']} zone "
                f"({anchor_low}–{anchor_high}), confirm a CHoCH on the chart "
                f"timeframe, then enter long with stop just below {anchor_low}."
            )
        else:
            better = (
                f"Wait for price to retrace INTO the {ref['kind']} zone "
                f"({anchor_low}–{anchor_high}), confirm a CHoCH, then enter "
                f"short with stop just above {anchor_high}."
            )
        if target:
            better += (
                f" Use the {target['kind']} zone "
                f"({target['low']}–{target['high']}) as the TP reference."
            )
    elif entry_zone:
        better = (
            "Entry zone was correct — next time wait for an explicit CHoCH/BOS "
            "confirmation candle inside the zone before entering."
        )
    else:
        better = (
            "Confirm BOS/CHoCH structural alignment before entry; ensure stop "
            "sits beyond a structural level, not in open space."
        )

    # ── psychology_note ──
    has_opps = any("opp" in d.lower() for d in drawings)
    if has_opps:
        psychology = (
            "The 'opps' annotation on the chart suggests post-entry regret — "
            "the trade lacked conviction. Build a pre-entry checklist so "
            "structure is verified BEFORE pulling the trigger."
        )
    elif anti_struct or missed:
        psychology = (
            "Entry was placed before structural confirmation. Build the habit "
            "of waiting for a CHoCH inside the zone — proximity to a level is "
            "not the same as a confirmed reaction."
        )
    else:
        psychology = (
            "Trades placed without structural confirmation tend to feel rushed. "
            "Slow the decision down — the chart will still be there after a "
            "confirmation candle closes."
        )

    # ── key_lesson + next_focus ──
    if missed or anti_struct:
        key_lesson = (
            "Zone identification is only half the edge — the other half is "
            "patience. Wait for price to come to your zone, not for the trade "
            "to come to you."
        )
        next_focus = (
            "Before every entry, ask: is price currently INSIDE my drawn "
            "demand or supply zone? If not, wait. Log every entry outside a "
            "zone as a 'patience violation'."
        )
    else:
        key_lesson = (
            "Structural alignment (entry at a confirmed OB/FVG with CHoCH) "
            "is required before entering. R:R alone is not an edge."
        )
        next_focus = (
            "Drill CHoCH identification: mark every BOS on a recent chart, "
            "then mark where the CHoCH against it occurred. Only enter after "
            "CHoCH confirmation."
        )

    sample = {
        "question_no": question.get("question_no"),
        "pair": question.get("pair"),
        "timeframe": question.get("timeframe"),
        "overall_score": score,
        "strengths": strengths,
        "mistake": mistake,
        "market_did": market_did,
        "better_approach": better,
        "psychology_note": psychology,
        "key_lesson": key_lesson,
        "next_focus": next_focus,
    }

    return (
        "═══ FEW-SHOT EXAMPLE — DYNAMICALLY GENERATED FOR THIS TRADE ═══\n"
        "Below is a worked example built from THIS trade's own data. Match "
        "this format and depth precisely. You MAY paraphrase it freely, but "
        "you MUST keep `overall_score` equal to `score_breakdown.base_score` "
        "and reference every zone in `zone_roles`. Do not copy verbatim — "
        "produce your own sentence-level wording grounded in the same data.\n\n"
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
    return card


# ─────────────────── strengths fallback (defense-in-depth) ───────────────────
# The system prompt tells the LLM to never emit "—" for `strengths`, but we've
# observed it doing so anyway on bad trades. This fallback runs over the
# parsed card and replaces empty / dash strengths with a concrete one
# generated from the same input the prompt walked. Mirrors the prompt's
# fallback ladder so the user-facing rendering stays consistent.

_EMPTY_STRENGTH_TOKENS = {"", "—", "-", "—.", "n/a", "none", "nothing notable"}


def _is_empty_strengths(value: Any) -> bool:
    """Detect placeholder / empty `strengths` values the LLM occasionally
    emits despite the prompt rule."""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    s = value.strip().lower()
    return s in _EMPTY_STRENGTH_TOKENS or len(s) < 4


def _auto_strengths(question: Dict[str, Any]) -> str:
    """Generate a fallback `strengths` string from the compacted question
    payload. Walks the same ladder the prompt describes (direction-vs-zone,
    tool usage, risk %, drawing presence, last-resort engagement credit) so
    the auto-filled value reads consistently with normal LLM output."""
    facts = question.get("trade_facts") or {}
    drawings = question.get("drawings_summary") or []
    direction = facts.get("direction")

    has_demand = any("demand zone" in line for line in drawings)
    has_supply = any("supply zone" in line for line in drawings)

    # 1. Direction matches a drawn zone.
    if direction == "buy" and has_demand:
        # Pull the first demand-zone line so we can quote concrete prices.
        for line in drawings:
            if "demand zone" in line:
                # Extract the "242.44–243.77" range from the summary line.
                _, _, tail = line.partition(":")
                zone_text = tail.split("[")[0].strip()
                return (
                    f"Direction (long) was structurally aligned with the drawn "
                    f"demand zone ({zone_text}) — bullish bias was correct "
                    f"relative to the chart structure even if entry timing wasn't."
                )
    if direction == "sell" and has_supply:
        for line in drawings:
            if "supply zone" in line:
                _, _, tail = line.partition(":")
                zone_text = tail.split("[")[0].strip()
                return (
                    f"Direction (short) was structurally aligned with the drawn "
                    f"supply zone ({zone_text}) — bearish bias was correct "
                    f"relative to the chart structure even if entry timing wasn't."
                )

    # 2. Used a Risk-Reward tool with explicit SL + TP.
    if any("Risk-Reward" in line for line in drawings):
        return (
            "Used a Risk-Reward tool with explicit stop and target rather than "
            "entering blind — process discipline is in place."
        )

    # 3. Reasonable risk % (≤ 2.0% of entry).
    risk_pct = facts.get("stop_distance_pct")
    if isinstance(risk_pct, (int, float)) and 0 < risk_pct <= 2.0:
        return (
            f"Stop placed within a reasonable per-trade risk budget "
            f"({risk_pct:.2f}% of entry) — risk sizing was responsible."
        )

    # 4. Set an explicit target (separate from R:R tool — could be a horz line / note).
    if facts.get("take_profit") is not None:
        return (
            "Defined an explicit take-profit before entering — having a target "
            "set in advance is better than relying on a discretionary exit."
        )

    # 5. Drew structural elements at all.
    if drawings:
        return (
            f"Placed {len(drawings)} structural element(s) on the chart before "
            "submitting — the drawing-discipline habit is in place."
        )

    # 6. Last resort — credit engagement.
    return (
        "Attempted a structured trade with a defined entry on a learning "
        "platform — engagement is the first step toward consistency."
    )


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
liquidity sweep / premium / discount / displacement. e.g. `mistake`: "Entered
inside a bearish OB at 2918.4 with no CHoCH confirmation"; `market_did`:
"Liquidity sweep above the equal highs at 2935 then bearish BOS through 2920";
`better_approach`: "Wait for CHoCH below 2920 and a retest of the resulting
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
PO3 / MMXM / kill zone / breaker block / mitigation block. e.g. `market_did`:
"London Open kill zone swept BSL above 2945 then ran into the bearish OB at
2952"; `better_approach`: "Wait for MSS below 2940 and re-enter at the OTE
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
in `mistake` ("(without volume data)") and lower `overall_score` by 1.0 —
VSA cannot be applied without volume.

In the card fields, use VSA / Wyckoff terminology directly: Stopping Volume,
Upthrust, No Supply, No Demand, Test, Spring, Shakeout, Accumulation,
Distribution, effort vs result. e.g. `market_did`: "Upthrust at 2952 on
high volume closed near the low — professional selling"; `better_approach`:
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
bottom, HH+HL / LH+LL, S/R flip, false break. e.g. `market_did`: "Bullish
engulfing rejected the prior day low at 2935 — failed breakdown";
`better_approach`: "Wait for a pin-bar rejection of the 2935 swing low,
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

When grading (call these out by name in `mistake` when they apply):
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
`market_did`: "H&S neckline at 2920 broke; measured move targets 2885";
`better_approach`: "Wait for a retest of the broken neckline at 2920,
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
        "you fill the prose fields (`strengths`, `mistake`, `market_did`,",
        "`better_approach`, `psychology_note`, `key_lesson`, `next_focus`).",
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

    Returns the 8-field card shape (`overall_score`, `strengths`, `mistake`,
    `market_did`, `better_approach`, `psychology_note`, `key_lesson`,
    `next_focus`). On LLM failure or unparseable output, returns the same
    shape with `_error` / `_parse_error` flags set so the frontend can
    render a graceful fallback instead of a blank card.
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
    parsed.setdefault("question_no", question.get("question_no"))
    parsed.setdefault("pair", question.get("pair"))
    parsed.setdefault("timeframe", question.get("timeframe"))
    # When the multi-answer flow stamped a requested_answer_id on this
    # question, surface it on the final card so the frontend knows which
    # trade each card maps to (essential when the user passed answer_id=[A,B]).
    if question.get("requested_answer_id") is not None:
        parsed.setdefault("requested_answer_id", question.get("requested_answer_id"))
    # Make sure every card field exists so the frontend never sees `undefined`.
    parsed.setdefault("overall_score", 0)
    for key, _ in _SECTION_KEYS:
        parsed.setdefault(key, "—")

    # Defense-in-depth: even with the STRENGTHS RULE in the system prompt, the
    # LLM occasionally still emits "—" for `strengths` on bad trades. Replace
    # any empty / dash value with a generated fallback grounded in the same
    # input the prompt walked (direction-vs-zone, RR tool usage, risk %, etc.).
    if not parsed.get("_parse_error") and _is_empty_strengths(parsed.get("strengths")):
        parsed["strengths"] = _auto_strengths(question)
        parsed["_strengths_auto_filled"] = True

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

    # The session-level coaching summary (strengths / weaknesses / recurring
    # mistakes / study plan / closing note) was deprecated when the response
    # format moved to the per-question card. The frontend now renders only
    # per-question cards plus the session metadata block below.

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
        "questions": per_question,
    }
    if normalized_type:
        result["analysis_type"] = normalized_type
        result["framework_name"] = FRAMEWORK_NAMES.get(normalized_type)
    if _has_any_profile_field(normalized_profile):
        result["user_profile"] = normalized_profile
    return result
