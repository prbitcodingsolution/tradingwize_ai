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
        if has_cuda:
            try:
                self.__class__._pipeline = hf_pipeline(
                    "text-classification",
                    model="ProsusAI/finbert",
                    device=0,
                    truncation=True,
                    max_length=512,
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
    def _label_to_score(label: str, confidence: float) -> float:
        """Map FinBERT label + confidence to 0-100 score."""
        label = label.lower()
        if label == "positive":
            return 50 + confidence * 50
        elif label == "negative":
            return 50 - confidence * 50
        else:  # neutral
            return 50.0

    @staticmethod
    def _score_to_label(score: float) -> str:
        if score >= 70:
            return "Positive"
        elif score <= 30:
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
            label = res["label"].lower()
            confidence = float(res["score"])
            score = self._label_to_score(label, confidence)

            breakdown[label] = breakdown.get(label, 0) + 1
            total_score += score
            total_confidence += confidence

            individual_results.append({
                "text": text[:200],
                "label": label.capitalize(),
                "confidence": round(confidence, 4),
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
