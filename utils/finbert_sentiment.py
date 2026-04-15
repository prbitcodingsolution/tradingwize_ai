# -*- coding: utf-8 -*-
"""
FinBERT Sentiment Analyzer — ProsusAI/finbert wrapper.
Singleton pattern: model is loaded once per process and reused.
Input texts are truncated to 512 tokens (FinBERT's context limit).
"""

import os
from typing import List, Dict


class FinBERTSentimentAnalyzer:
    """
    Singleton wrapper around ProsusAI/finbert.
    Use get_instance() to access the shared instance — never instantiate directly.
    """
    _instance = None
    _pipeline = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "FinBERTSentimentAnalyzer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_model(self) -> bool:
        """Lazily load the FinBERT pipeline on first call. Returns True on success."""
        if self._pipeline is not None:
            return True
        try:
            from transformers import pipeline as hf_pipeline
        except ImportError:
            print("transformers not installed — FinBERT unavailable.")
            return False

        # Detect GPU availability
        try:
            import torch
            has_cuda = torch.cuda.is_available()
        except ImportError:
            has_cuda = False

        print("Loading ProsusAI/finbert model (first call only)...")

        # Try GPU if available
        # NOTE: top_k=None makes the pipeline return the full probability
        # distribution (positive/negative/neutral) per text instead of only
        # the top label. We need that so near-neutral predictions still
        # contribute a directional score via (p_pos - p_neg) — without it,
        # anything FinBERT labels "neutral" gets pegged at exactly 50 and
        # tweet/Reddit averages collapse to ~50 every time.
        if has_cuda:
            try:
                self.__class__._pipeline = hf_pipeline(
                    "text-classification",
                    model="ProsusAI/finbert",
                    device=0,
                    truncation=True,
                    max_length=512,
                    top_k=None,
                )
                print("FinBERT model loaded on GPU.")
                return True
            except Exception as gpu_err:
                print(f"GPU load failed ({gpu_err}), falling back to CPU...")

        # CPU path
        try:
            self.__class__._pipeline = hf_pipeline(
                "text-classification",
                model="ProsusAI/finbert",
                device=-1,
                truncation=True,
                max_length=512,
                top_k=None,
            )
            print("FinBERT model loaded on CPU.")
            return True
        except Exception as e:
            print(f"FinBERT model load failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Score mapping helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _probs_to_score(p_pos: float, p_neg: float) -> float:
        """
        Map FinBERT class probabilities to a 0-100 sentiment score.

        Uses the *differential* (p_pos - p_neg) rather than only the top
        class. This way a text that FinBERT classifies as "neutral" with a
        small positive lean (e.g., pos=0.30, neu=0.55, neg=0.15) still
        produces a score > 50 instead of being pegged flat at 50.
        """
        # (p_pos - p_neg) ranges from -1 (all negative) to +1 (all positive).
        # Scale to 0-100 with 50 as neutral midpoint.
        return 50.0 + (p_pos - p_neg) * 50.0

    @staticmethod
    def _score_to_label(score: float) -> str:
        if score >= 60:
            return "Positive"
        elif score <= 40:
            return "Negative"
        else:
            return "Neutral"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def analyze_texts(self, texts: List[str]) -> Dict:
        """
        Analyze a list of financial texts with FinBERT.

        Args:
            texts: List of raw text strings (headlines, snippets, posts).

        Returns:
            {
                "score": float,           # 0-100 (50 = neutral)
                "label": str,             # "Positive" / "Negative" / "Neutral"
                "confidence": float,      # 0.0-1.0 (average)
                "breakdown": {
                    "positive": int,
                    "negative": int,
                    "neutral": int,
                },
                "individual_results": [
                    {"text": str, "label": str, "confidence": float, "score": float}
                ],
            }
        """
        if not texts:
            return self._empty_result()

        if not self._load_model():
            raise RuntimeError("FinBERT model could not be loaded.")

        # Truncate texts to avoid token limit issues before pipeline sees them
        clean_texts = [t[:2000] for t in texts if t and t.strip()]
        if not clean_texts:
            return self._empty_result()

        try:
            raw_results = self._pipeline(clean_texts, batch_size=16)
        except Exception as e:
            raise RuntimeError(f"FinBERT inference failed: {e}") from e

        individual_results = []
        breakdown = {"positive": 0, "negative": 0, "neutral": 0}
        total_score = 0.0
        total_confidence = 0.0

        for text, res in zip(clean_texts, raw_results):
            # With top_k=None the pipeline returns a list of {label, score}
            # dicts per input (one entry per class). Older configurations
            # return a single dict with the top label — handle both.
            if isinstance(res, list):
                probs = {
                    item["label"].lower(): float(item["score"])
                    for item in res
                }
            else:
                # Single top-label fallback: treat as one-hot.
                probs = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
                probs[res["label"].lower()] = float(res["score"])

            p_pos = probs.get("positive", 0.0)
            p_neg = probs.get("negative", 0.0)
            p_neu = probs.get("neutral", 0.0)

            # Score uses the full probability distribution so near-neutral
            # predictions still register directional sentiment.
            score = self._probs_to_score(p_pos, p_neg)

            # Top-class label (still used for the breakdown counts).
            top_label = max(probs.items(), key=lambda kv: kv[1])[0]
            top_conf = probs[top_label]

            breakdown[top_label] = breakdown.get(top_label, 0) + 1
            total_score += score
            total_confidence += top_conf

            individual_results.append({
                "text": text[:200],
                "label": top_label.capitalize(),
                "confidence": round(top_conf, 4),
                "score": round(score, 2),
            })

        n = len(individual_results)
        avg_score = total_score / n
        avg_confidence = total_confidence / n

        return {
            "score": round(avg_score, 2),
            "label": self._score_to_label(avg_score),
            "confidence": round(avg_confidence, 4),
            "breakdown": breakdown,
            "individual_results": individual_results,
        }

    @staticmethod
    def _empty_result() -> Dict:
        return {
            "score": 50.0,
            "label": "Neutral",
            "confidence": 0.0,
            "breakdown": {"positive": 0, "negative": 0, "neutral": 0},
            "individual_results": [],
        }


# Module-level convenience function
def analyze_texts_with_finbert(texts: List[str]) -> Dict:
    """Convenience wrapper — uses the global FinBERT singleton."""
    return FinBERTSentimentAnalyzer.get_instance().analyze_texts(texts)
