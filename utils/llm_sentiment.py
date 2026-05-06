# -*- coding: utf-8 -*-
"""
LLM-based Sentiment Analyzer.

Classifies financial texts (news headlines, snippets, tweets, Reddit
posts) using the project's standard LLM pipeline via
`utils.model_config.guarded_llm_call`. Replaces the previous FinBERT
(ProsusAI/finbert transformer) backend — no `transformers` or `torch`
dependency is required anymore.

Return shape produced by `analyze_texts(texts)`:

    {
        "score": float,           # 0-100 (50 = neutral)
        "label": str,             # "Positive" / "Negative" / "Neutral"
        "confidence": float,      # 0.0-1.0 (average across individual rows)
        "breakdown": {"positive": int, "negative": int, "neutral": int},
        "individual_results": [
            {"text": str, "label": str, "confidence": float, "score": float},
            ...
        ],
    }
"""

import json
import re
from typing import List, Dict


# ────────────────────────────────────────────────────────────────
# Configuration
# ────────────────────────────────────────────────────────────────

# How many texts to classify per LLM call. Tuned so the JSON output
# stays well inside the model's response token budget while minimising
# the number of round trips.
_BATCH_SIZE = 20

# Per-call token budget. Room for ~20 JSON rows of the shape
# {"i":N,"label":"X","score":N,"confidence":N.NN}.
_MAX_TOKENS = 1400

# Temperature kept very low so the classifier is deterministic-ish
# across runs of the same input.
_TEMPERATURE = 0.0

# Model fallback chain. The primary model (openai/gpt-oss-120b) is fast
# and accurate but occasionally returns empty content from OpenRouter —
# when that happens we retry once, then fall through to Gemini Flash,
# which has been reliable for structured-JSON classification. Without
# this chain, intermittent empty responses from the primary model cause
# every tweet / article to be labelled neutral (score=50), which is
# exactly what was showing up as "Twitter: 50.0/100 Neutral" for most
# stocks.
_MODEL_FALLBACK_CHAIN = [
    "openai/gpt-oss-120b",
    "google/gemini-2.0-flash-001",
    "meta-llama/llama-3.1-8b-instruct",
    "openai/gpt-oss-20b",
]


# ────────────────────────────────────────────────────────────────
# Prompt
# ────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are a precise financial sentiment classifier. "
    "You read short financial texts (news headlines, snippets, tweets, "
    "Reddit posts) and output a sentiment per text: Positive, Negative, "
    "or Neutral, with a 0-100 score (0 = strongly negative, 50 = neutral, "
    "100 = strongly positive) and a 0-1 confidence value. "
    "You MUST return ONLY a JSON array — no prose, no markdown fences, "
    "no commentary."
)


def _build_user_prompt(batch: List[str]) -> str:
    """Compose the user prompt for one batch of texts."""
    lines = ["Classify the sentiment of each text below. Return ONLY a JSON",
             "array of objects, one per input, in the same order.",
             "Each object must have these exact keys:",
             '  "i":          integer (matches the input index, 0-based)',
             '  "label":      "Positive" | "Negative" | "Neutral"',
             '  "score":      number 0-100 (50 = neutral)',
             '  "confidence": number 0-1 (how confident you are)',
             "",
             "Rules:",
             "• Base sentiment on financial impact for the company or stock.",
             "• Earnings beats, upgrades, positive guidance → Positive.",
             "• Misses, downgrades, scandals, layoffs, losses → Negative.",
             "• Routine updates with no clear financial direction → Neutral.",
             "• Scores near 50 for neutral; near 80-100 for strong positive;",
             "  near 0-20 for strong negative.",
             "",
             "Texts to classify:"]
    for i, text in enumerate(batch):
        # Clip very long texts so the prompt doesn't blow up the context.
        safe = (text or "").strip().replace("\n", " ")
        if len(safe) > 500:
            safe = safe[:500] + "…"
        lines.append(f"[{i}] {safe}")
    lines.append("")
    lines.append("Respond with ONLY the JSON array.")
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────
# JSON parsing
# ────────────────────────────────────────────────────────────────

def _extract_json_array(raw: str) -> list:
    """Pull the first JSON array out of a model response.

    Handles plain arrays, arrays inside ```json fences, and arrays
    inside noisy prose. Returns [] if nothing parseable is found.
    """
    if not raw:
        return []
    text = raw.strip()

    # Strip common code fences.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1)
        text = re.sub(r"\s*```\s*$", "", text, count=1)

    # First attempt: the whole thing parses as JSON.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except (ValueError, TypeError):
        pass

    # Fallback: find the first [...] block in the text.
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                return parsed
        except (ValueError, TypeError):
            pass
    return []


def _coerce_label(label_raw) -> str:
    """Normalise any of {positive, negative, neutral} (case / spacing)."""
    if not isinstance(label_raw, str):
        return "Neutral"
    low = label_raw.strip().lower()
    if low.startswith("pos"):
        return "Positive"
    if low.startswith("neg"):
        return "Negative"
    return "Neutral"


def _coerce_score(score_raw, label: str) -> float:
    """Parse an int/float/string score and clamp to 0-100."""
    try:
        score = float(score_raw)
    except (TypeError, ValueError):
        # Fall back to the label midpoint so downstream aggregation still
        # gets a directional signal from a malformed row.
        return {"Positive": 75.0, "Negative": 25.0}.get(label, 50.0)
    if score < 0:
        score = 0.0
    if score > 100:
        score = 100.0
    return score


def _coerce_confidence(conf_raw) -> float:
    """Parse confidence and clamp to 0-1."""
    try:
        conf = float(conf_raw)
    except (TypeError, ValueError):
        return 0.5
    if conf < 0:
        conf = 0.0
    # Some models return percentages instead of a 0-1 fraction.
    if conf > 1.0:
        conf = min(conf / 100.0, 1.0)
    return conf


# ────────────────────────────────────────────────────────────────
# Analyzer
# ────────────────────────────────────────────────────────────────

class LLMSentimentAnalyzer:
    """LLM-backed sentiment classifier. Use `get_instance()` to share the
    singleton across the process (keeps cache behaviour consistent with
    the rest of the app).
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "LLMSentimentAnalyzer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _score_to_label(score: float) -> str:
        if score >= 60:
            return "Positive"
        if score <= 40:
            return "Negative"
        return "Neutral"

    @staticmethod
    def _empty_result() -> Dict:
        return {
            "score": 50.0,
            "label": "Neutral",
            "confidence": 0.0,
            "breakdown": {"positive": 0, "negative": 0, "neutral": 0},
            "individual_results": [],
        }

    # ------------------------------------------------------------
    # One LLM classification pass over a single batch of texts
    # ------------------------------------------------------------
    def _classify_batch(self, batch: List[str]) -> List[Dict]:
        """Return one per-text result dict per input.

        Tries the model-fallback chain until one returns parseable JSON.
        Only falls back to neutral entries if EVERY model in the chain
        fails (empty content, unparseable JSON, or exception) so the
        caller always gets `len(batch)` rows back.
        """
        fallback = [
            {"text": t, "label": "Neutral", "confidence": 0.0, "score": 50.0}
            for t in batch
        ]

        try:
            from utils.model_config import guarded_llm_call
        except Exception as e:
            print(f"⚠️ LLM client unavailable, falling back to neutral: {e}")
            return fallback

        parsed: list = []
        for model_name in _MODEL_FALLBACK_CHAIN:
            try:
                resp = guarded_llm_call(
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": _build_user_prompt(batch)},
                    ],
                    model=model_name,
                    temperature=_TEMPERATURE,
                    max_tokens=_MAX_TOKENS,
                )
                raw = resp.choices[0].message.content if resp and resp.choices else ""
            except Exception as e:
                print(f"⚠️ LLM sentiment: model {model_name} raised {e} — trying next")
                continue

            if not raw or not raw.strip():
                print(f"⚠️ LLM sentiment: model {model_name} returned empty content — trying next")
                continue

            parsed = _extract_json_array(raw)
            if parsed:
                # Success — no need to try further models.
                print(f"✅ LLM sentiment classified {len(batch)} texts via {model_name}")
                break
            print(f"⚠️ LLM sentiment: model {model_name} returned unparseable JSON — trying next")

        if not parsed:
            print("⚠️ All LLM sentiment models failed or returned no parseable JSON — defaulting to neutral.")
            return fallback

        # Build an index-keyed lookup so out-of-order responses still match.
        by_index: dict[int, dict] = {}
        for row in parsed:
            if not isinstance(row, dict):
                continue
            try:
                idx = int(row.get("i"))
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(batch):
                by_index[idx] = row

        results: List[Dict] = []
        for i, text in enumerate(batch):
            row = by_index.get(i)
            if not row:
                results.append(fallback[i])
                continue
            label = _coerce_label(row.get("label"))
            score = _coerce_score(row.get("score"), label)
            conf = _coerce_confidence(row.get("confidence"))

            # If the label and the score disagree (e.g. label="Positive"
            # but score=20), trust the numeric score and re-label.
            derived_label = self._score_to_label(score)
            if derived_label != label and abs(score - 50) >= 10:
                label = derived_label

            results.append({
                "text": text[:200],
                "label": label,
                "confidence": round(conf, 4),
                "score": round(score, 2),
            })

        return results

    # ------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------
    def analyze_texts(self, texts: List[str]) -> Dict:
        """Classify a list of financial texts and return an aggregated
        dict with per-text breakdown plus the averaged score / label.
        """
        if not texts:
            return self._empty_result()

        clean_texts = [t[:2000] for t in texts if t and isinstance(t, str) and t.strip()]
        if not clean_texts:
            return self._empty_result()

        individual_results: List[Dict] = []
        for start in range(0, len(clean_texts), _BATCH_SIZE):
            batch = clean_texts[start:start + _BATCH_SIZE]
            individual_results.extend(self._classify_batch(batch))

        if not individual_results:
            return self._empty_result()

        breakdown = {"positive": 0, "negative": 0, "neutral": 0}
        total_score = 0.0
        total_conf = 0.0
        for r in individual_results:
            key = r["label"].lower()
            breakdown[key] = breakdown.get(key, 0) + 1
            total_score += r["score"]
            total_conf += r["confidence"]

        n = len(individual_results)
        avg_score = total_score / n
        avg_conf = total_conf / n

        return {
            "score": round(avg_score, 2),
            "label": self._score_to_label(avg_score),
            "confidence": round(avg_conf, 4),
            "breakdown": breakdown,
            "individual_results": individual_results,
        }


# ────────────────────────────────────────────────────────────────
# Module-level convenience wrapper
# ────────────────────────────────────────────────────────────────

def analyze_texts_with_llm(texts: List[str]) -> Dict:
    """One-shot helper that reuses the singleton analyzer."""
    return LLMSentimentAnalyzer.get_instance().analyze_texts(texts)
