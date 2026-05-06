"""
Lightweight per-phase timing instrumentation for the stock-analysis pipeline.

Usage
-----
1.  Wrap a block:

        from utils.timing import phase_timer
        with phase_timer("Dashboard Analysis", symbol="JIOFIN.NS"):
            run_analysis(...)

    On exit the block prints:

        ⏱  Dashboard Analysis [JIOFIN.NS] — 4.73s
            running total [JIOFIN.NS]: 4.73s

2.  Decorate a function (sync or async):

        from utils.timing import timed

        @timed("FinRobot Orchestrator")
        async def run_finrobot_analysis(company_data, ...):
            ...

    The decorator auto-detects async vs sync.

3.  Print the per-phase breakdown at any natural end-point:

        from utils.timing import print_summary
        print_summary(symbol="JIOFIN.NS")

    which emits something like:

        ============================================================
        ⏱  EXECUTION TIMING SUMMARY for JIOFIN.NS
        ============================================================
          Dashboard Analysis                        4.73s
          FII/DII Analysis                          2.11s
          Trade Ideas (TradingView)                 1.89s
          FinRobot Orchestrator                     12.04s
            ├─ Fundamental Agent                    2.30s
            ├─ Future-Outlook Agent                 3.88s
            └─ Reasoning Agent                      5.86s
          PPT Generation                            6.55s
        ------------------------------------------------------------
          TOTAL                                     27.32s
        ============================================================

Design notes
------------
*   Module-level state (`_timings`) survives Streamlit reruns because the
    Python process stays alive; per-symbol keys keep parallel sessions
    from clobbering each other.
*   Thread-safe — uses a lock around all mutations (Streamlit may run
    background futures concurrently via `ThreadPoolExecutor`).
*   Zero external dependencies. Prints go to stdout so they interleave
    naturally with the existing emoji logs.
"""

from __future__ import annotations

import asyncio
import functools
import sys
import threading
import time
from contextlib import contextmanager
from typing import Dict, List, Optional

# Windows' default cp1252 console can't encode the ⏱ emoji we prefer; try
# to switch stdout to utf-8 once at import time, then fall back to an
# ASCII marker if the reconfigure didn't stick.
_TIMER_ICON = "⏱"
try:  # pragma: no cover — depends on runtime environment
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _safe_print(msg: str) -> None:
    """Print with an ASCII fallback if the console can't encode it."""
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(msg.encode(enc, errors="replace").decode(enc, errors="replace"))

__all__ = [
    "phase_timer",
    "timed",
    "print_summary",
    "get_total",
    "reset",
    "DEFAULT_KEY",
]

# Key used when the caller doesn't pass an explicit symbol. Timings under
# this key are still useful for one-off scripts / tests.
DEFAULT_KEY = "_global_"

# ---------------------------------------------------------------------
#  State
# ---------------------------------------------------------------------
_lock = threading.Lock()

# _timings[symbol][phase_name] = [duration, duration, ...]
# Nested phases (e.g. FinRobot sub-agents) use a "Parent » Child" name so
# the summary can render them as a tree without complicating the schema.
_timings: Dict[str, Dict[str, List[float]]] = {}


# ---------------------------------------------------------------------
#  Internals
# ---------------------------------------------------------------------
def _key(symbol: Optional[str]) -> str:
    return symbol or DEFAULT_KEY


def _fmt(seconds: float) -> str:
    """Format seconds as `Nm NN.NNs` when ≥ 60s, else `N.NNs`."""
    if seconds < 0:
        seconds = 0.0
    if seconds >= 60:
        m, s = divmod(seconds, 60)
        return f"{int(m)}m {s:05.2f}s"
    return f"{seconds:.2f}s"


def _record(symbol_key: str, phase: str, duration: float) -> None:
    with _lock:
        _timings.setdefault(symbol_key, {}).setdefault(phase, []).append(duration)


def _print_phase_line(phase: str, duration: float, symbol_key: str) -> None:
    tag = f" [{symbol_key}]" if symbol_key != DEFAULT_KEY else ""
    _safe_print(f"{_TIMER_ICON}  {phase}{tag} — {_fmt(duration)}")
    # Running total shows cumulative time so far; only print if it differs
    # from the phase duration (i.e. more than one phase recorded).
    total = get_total(symbol_key)
    if total > 0 and abs(total - duration) > 1e-6:
        _safe_print(f"    running total{tag}: {_fmt(total)}")


# ---------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------
@contextmanager
def phase_timer(phase: str, symbol: Optional[str] = None, *, print_line: bool = True):
    """Context manager that times an arbitrary code block.

    Parameters
    ----------
    phase : str
        Human-readable name — appears in the output log and summary.
        Use "Parent » Child" notation for nested sub-phases (e.g.
        "FinRobot » Fundamental Agent") — the summary renders them as
        a tree.
    symbol : Optional[str]
        Per-stock bucket key. Typically the ticker (e.g. "JIOFIN.NS").
        Omit for ad-hoc / global timings.
    print_line : bool
        Emit the `⏱  Phase — duration` line on exit. Set False for
        aggregate-only timings where the caller wants silence.
    """
    symbol_key = _key(symbol)
    t0 = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - t0
        _record(symbol_key, phase, duration)
        if print_line:
            _print_phase_line(phase, duration, symbol_key)


def timed(phase: str, *, symbol_arg: Optional[str] = None, print_line: bool = True):
    """Function decorator — wraps a sync or async callable in `phase_timer`.

    Parameters
    ----------
    phase : str
        Human-readable phase name.
    symbol_arg : Optional[str]
        Name of the keyword argument that carries the per-stock symbol.
        When set, the decorator reads the corresponding argument at call
        time and uses it as the bucket key. Omit for global timing.
    print_line : bool
        Same as `phase_timer`.
    """
    def _decorator(fn):
        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def _async_wrapper(*args, **kwargs):
                sym = kwargs.get(symbol_arg) if symbol_arg else None
                with phase_timer(phase, sym, print_line=print_line):
                    return await fn(*args, **kwargs)
            return _async_wrapper

        @functools.wraps(fn)
        def _sync_wrapper(*args, **kwargs):
            sym = kwargs.get(symbol_arg) if symbol_arg else None
            with phase_timer(phase, sym, print_line=print_line):
                return fn(*args, **kwargs)
        return _sync_wrapper

    return _decorator


def get_total(symbol: Optional[str] = None) -> float:
    """Sum of all recorded durations for this symbol (seconds)."""
    symbol_key = _key(symbol)
    with _lock:
        data = _timings.get(symbol_key, {})
        return sum(sum(durations) for durations in data.values())


def reset(symbol: Optional[str] = None) -> None:
    """Drop all recorded timings for this symbol."""
    symbol_key = _key(symbol)
    with _lock:
        _timings.pop(symbol_key, None)


def print_summary(symbol: Optional[str] = None, *, reset_after: bool = False) -> None:
    """Print a per-phase breakdown + grand total for this symbol.

    Children with "Parent » Child" names render as a tree beneath their
    parent. If the parent itself wasn't timed we still show the children
    under a synthetic "(children)" header.
    """
    symbol_key = _key(symbol)
    with _lock:
        data = _timings.get(symbol_key, {}).copy()
    if not data:
        return

    # Build tree — root phases first (no " » "), then children grouped
    # by parent name.
    roots: List[str] = [p for p in data if " » " not in p]
    children_by_parent: Dict[str, List[str]] = {}
    for p in data:
        if " » " in p:
            parent, _ = p.split(" » ", 1)
            children_by_parent.setdefault(parent, []).append(p)

    # Orphan children — parents with timed sub-phases but the parent
    # itself wasn't wrapped.
    for parent in list(children_by_parent.keys()):
        if parent not in roots:
            roots.append(parent)

    tag = f" for {symbol_key}" if symbol_key != DEFAULT_KEY else ""
    line = "=" * 64
    sub = "-" * 64
    _safe_print("")
    _safe_print(line)
    _safe_print(f"{_TIMER_ICON}  EXECUTION TIMING SUMMARY{tag}")
    _safe_print(line)

    grand = 0.0
    for parent in roots:
        durations = data.get(parent, [])
        parent_total = sum(durations) if durations else 0.0
        parent_count = len(durations)

        # Parent row — only counts toward grand total if the parent was
        # timed directly (not an orphan assembled from children).
        if durations:
            grand += parent_total
            count_sfx = f" (x{parent_count})" if parent_count > 1 else ""
            _safe_print(f"  {parent:<42} {_fmt(parent_total):>12}{count_sfx}")
        else:
            _safe_print(f"  {parent + ' (children)':<42}")

        # Render children
        kids = sorted(children_by_parent.get(parent, []))
        for i, kid_key in enumerate(kids):
            kid_name = kid_key.split(" » ", 1)[1]
            kid_durations = data.get(kid_key, [])
            kid_total = sum(kid_durations)
            # If parent wasn't timed, count child durations toward grand total
            # so the summary still reflects real elapsed work.
            if not durations:
                grand += kid_total
            branch = "└─" if i == len(kids) - 1 else "├─"
            kid_count = len(kid_durations)
            kid_sfx = f" (x{kid_count})" if kid_count > 1 else ""
            _safe_print(f"    {branch} {kid_name:<38} {_fmt(kid_total):>12}{kid_sfx}")

    _safe_print(sub)
    _safe_print(f"  {'TOTAL':<42} {_fmt(grand):>12}")
    _safe_print(line)
    _safe_print("")

    if reset_after:
        reset(symbol)


# ---------------------------------------------------------------------
#  CLI smoke test
# ---------------------------------------------------------------------
if __name__ == "__main__":
    with phase_timer("Phase A", symbol="DEMO"):
        time.sleep(0.3)
    with phase_timer("Phase B", symbol="DEMO"):
        time.sleep(0.15)
        with phase_timer("Phase B » Sub 1", symbol="DEMO"):
            time.sleep(0.05)
        with phase_timer("Phase B » Sub 2", symbol="DEMO"):
            time.sleep(0.10)
    with phase_timer("Phase C", symbol="DEMO"):
        time.sleep(0.08)
    print_summary(symbol="DEMO", reset_after=True)
