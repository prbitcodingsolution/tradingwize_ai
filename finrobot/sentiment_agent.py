# -*- coding: utf-8 -*-
"""
FinRobot — Sentiment Agent (Agent 2)
Takes FinBERT output + news articles and produces structured sentiment intelligence.
Uses the existing OpenRouter pipeline via utils/model_config.py.
"""

import json
import re
from typing import Optional
from pydantic import BaseModel

from utils.model_config import get_client


class SentimentAgentResult(BaseModel):
    sentiment_score: float          # 0-100 (taken from FinBERT)
    sentiment_label: str            # "Positive" / "Negative" / "Neutral"
    theme_summary: str              # What topics are driving sentiment
    sentiment_momentum: str         # "Improving" / "Deteriorating" / "Stable"
    key_drivers: list[str]          # Top 3-5 specific sentiment drivers
    llm_commentary: str             # 2-3 sentence analyst paragraph
    anomalies_detected: list[str]   # Unusual signals (empty list if none)


def _safe_json_parse(raw: str) -> Optional[dict]:
    """Try multiple strategies to parse potentially malformed JSON from LLM."""
    # Strategy 1: direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract the outermost {...} block and retry
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        pass

    # Strategy 3: use regex to sanitize common issues (unescaped quotes inside strings)
    try:
        # Replace literal newlines inside JSON string values with \\n
        cleaned = re.sub(r'(?<=: ")(.*?)(?="[,\n}])', lambda m: m.group(0).replace('\n', '\\n').replace('"', '\\"'), raw, flags=re.DOTALL)
        start = cleaned.index("{")
        end = cleaned.rindex("}") + 1
        return json.loads(cleaned[start:end])
    except Exception:
        pass

    return None


def run_sentiment_agent(
    sentiment_data: dict,
    news_articles: list,
    raw_texts: Optional[dict] = None,
) -> SentimentAgentResult:
    """
    Produce structured sentiment intelligence from FinBERT output + raw texts.

    Args:
        sentiment_data: Full output dict from FinBERTSentimentAnalyzer.analyze_texts()
                        or the overall sentiment dict from sentiment_analyzer_adanos.
        news_articles:  List of article dicts (title, content, source, url).
        raw_texts:      Optional dict keyed by source name with lists of text strings.
    """
    client = get_client()

    score = sentiment_data.get("score") or sentiment_data.get("overall_score") or 50.0
    label = sentiment_data.get("label") or sentiment_data.get("overall_label") or "Neutral"
    confidence = sentiment_data.get("confidence", "N/A")
    breakdown = sentiment_data.get("breakdown", {})
    individual = sentiment_data.get("individual_results", [])[:10]

    # Build a text summary of the most representative snippets
    sample_texts = []
    if individual:
        for item in individual:
            sample_texts.append(
                f"[{item.get('label','?')} | conf={item.get('confidence',0):.2f}] {item.get('text','')[:150]}"
            )
    if news_articles:
        for art in news_articles[:8]:
            title = art.get("title", "")
            content = art.get("content", "")[:200]
            source = art.get("source", "")
            if title:
                sample_texts.append(f"[News/{source}] {title}: {content}")

    if raw_texts:
        for src, texts in raw_texts.items():
            for t in texts[:3]:
                sample_texts.append(f"[{src}] {t[:150]}")

    samples_block = "\n".join(sample_texts[:25]) or "No sample texts available."

    system_prompt = (
        "You are a senior financial market analyst specialising in sentiment analysis "
        "for Indian equities. Be concise, specific, and data-driven."
    )

    # Build multi-source context line if available
    news_score = sentiment_data.get("news_score")
    yahoo_score = sentiment_data.get("yahoo_score")
    twitter_score = sentiment_data.get("twitter_score")
    reddit_score = sentiment_data.get("reddit_score")
    multi_source_lines = []
    if yahoo_score is not None:
        multi_source_lines.append(f"  Yahoo Finance (analysts): {yahoo_score:.1f}/100")
    if news_score is not None:
        multi_source_lines.append(f"  News media:               {news_score:.1f}/100")
    if twitter_score is not None:
        multi_source_lines.append(f"  Twitter/X:                {twitter_score:.1f}/100")
    if reddit_score is not None:
        multi_source_lines.append(f"  Reddit:                   {reddit_score:.1f}/100")
    multi_source_block = (
        "Multi-source breakdown:\n" + "\n".join(multi_source_lines)
        if multi_source_lines else ""
    )

    user_prompt = f"""You have received sentiment analysis results for a stock along with sample texts.

Combined Score:   {score:.1f}/100
Combined Label:   {label}
Confidence:       {confidence}
FinBERT Breakdown: Positive={breakdown.get('positive',0)}  Negative={breakdown.get('negative',0)}  Neutral={breakdown.get('neutral',0)}
{multi_source_block}

Sample texts (labelled by FinBERT):
{samples_block}

Perform the following analysis:
1. Identify the 3-5 dominant sentiment themes (e.g. "earnings beat", "regulatory concern", "management change").
2. Detect any sentiment shifts or anomalies (sudden spike in negative/positive, contradictory signals, or disagreement between sources).
3. Flag extreme signals: score < 20 is strongly negative, score > 80 is strongly positive.
4. Assess momentum: is overall sentiment getting better ("Improving"), worse ("Deteriorating"), or staying the same ("Stable")?
5. Write a 2-3 sentence analyst-style paragraph (llm_commentary) that references the multi-source scores if available.

Return ONLY valid JSON with no trailing commas:
{{
  "sentiment_score": {score:.1f},
  "sentiment_label": "{label}",
  "theme_summary": "<what topics are driving sentiment>",
  "sentiment_momentum": "<Improving|Deteriorating|Stable>",
  "key_drivers": ["<driver1>", "<driver2>", "<driver3>"],
  "llm_commentary": "<2-3 sentences>",
  "anomalies_detected": []
}}

Use an empty list for anomalies_detected if none exist. Ensure all string values use properly escaped quotes."""

    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.15,
            max_tokens=900,
        )
        raw = response.choices[0].message.content.strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        data = _safe_json_parse(raw)
        if data is None:
            # Fallback: construct a minimal valid result from what we know
            return SentimentAgentResult(
                sentiment_score=float(score),
                sentiment_label=str(label),
                theme_summary="Unable to parse LLM response; sentiment based on FinBERT scores only.",
                sentiment_momentum="Stable",
                key_drivers=["FinBERT score: {:.1f}".format(float(score))],
                llm_commentary=(
                    f"FinBERT analysis yielded a {label} sentiment with a score of {score:.1f}/100. "
                    "The LLM commentary could not be generated due to a response parsing issue."
                ),
                anomalies_detected=[],
            )
        return SentimentAgentResult(**data)
    except Exception as e:
        # Return a graceful fallback instead of crashing
        return SentimentAgentResult(
            sentiment_score=float(score),
            sentiment_label=str(label),
            theme_summary="Sentiment agent encountered an error; falling back to FinBERT data.",
            sentiment_momentum="Stable",
            key_drivers=["FinBERT score: {:.1f}".format(float(score))],
            llm_commentary=(
                f"FinBERT analysis yielded a {label} sentiment with a score of {score:.1f}/100. "
                f"Extended analysis unavailable due to: {e}"
            ),
            anomalies_detected=[],
        )
