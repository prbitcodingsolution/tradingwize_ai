"""
Trading-Analysis Evaluator

Rule-based engine that scores a student's chart drawings (Fibonacci, channels,
entry zones) against deterministic swing/structure analysis, then asks an LLM
to explain the result like a mentor.

Public entry point: `analysis_evaluator.evaluator.evaluate(...)`.
"""

# Silence the harmless `RequestsDependencyWarning` from `requests` when
# chardet/charset_normalizer is missing or has corrupt metadata. This MUST
# run before any other import that may transitively load `requests`.
import warnings as _warnings
_warnings.filterwarnings("ignore", message=r".*chardet.*")
_warnings.filterwarnings("ignore", message=r".*charset_normalizer.*")

from .evaluator import evaluate, evaluate_from_upstream  # noqa: E402

__all__ = ["evaluate", "evaluate_from_upstream"]
