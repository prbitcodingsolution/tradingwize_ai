# Implementation Brief: FinBERT + FinRobot Integration into TradingWize

## Overview

This document describes two additions to the existing TradingWize system:

1. **FinBERT** — Replace the current VADER/Adanos sentiment scoring with ProsusAI's FinBERT model, which is trained specifically on financial language for significantly higher accuracy (~89%+)
2. **FinRobot Agent Layer** — Add a three-agent orchestration layer (Fundamental Agent, Sentiment Agent, Reasoning Agent) on top of the existing data pipeline, following the FinRobot multi-agent pattern

> FinRobot does **not** provide its own data. Both additions consume data that the system already fetches: `CompanyData` from yfinance + screener.in, news from Tavily, and sentiment texts from Reddit/Twitter/Yahoo Finance.

---

## Current State (What Exists Today)

| Component | Current Implementation |
|-----------|----------------------|
| Sentiment scoring | `utils/sentiment_analyzer_adanos.py` → Adanos API (VADER-based, generic NLP) |
| Reddit sentiment | `utils/reddit_sentiment.py` → VADER `SentimentIntensityAnalyzer` |
| Fundamental data | `tools.py` → yfinance + screener.in → `CompanyData` Pydantic model |
| News/search | `utils/stock_news_analyzer.py` → Tavily API |
| LLM calls | `utils/model_config.py` → OpenRouter |
| Agent tools | `agent1.py` → pydantic-ai tools returning `ToolResponse` |

---

## Task 1: Replace VADER with FinBERT

### 1.1 New File — `utils/finbert_sentiment.py`

Create this file from scratch. It is the core FinBERT wrapper used by all sentiment components.

**Model**: `ProsusAI/finbert` from HuggingFace  
**Library**: `transformers.pipeline("text-classification", model="ProsusAI/finbert")`

**Requirements** (add to `requirements.txt`):
```
transformers>=4.36.0
torch>=2.0.0
```

**Class design**:

```python
class FinBERTSentimentAnalyzer:
    _instance = None  # Singleton — load model once only

    def analyze_texts(self, texts: list[str]) -> dict:
        """
        Input:  list of raw text strings (news headlines, article snippets, reddit posts)
        Output: {
            "score": float,          # 0–100 (50 = neutral, >50 = positive, <50 = negative)
            "label": str,            # "Positive" / "Negative" / "Neutral"
            "confidence": float,     # 0.0–1.0
            "breakdown": {
                "positive": int,     # count of positive-classified texts
                "negative": int,
                "neutral": int
            },
            "individual_results": [  # per-text results
                {"text": str, "label": str, "confidence": float, "score": float}
            ]
        }
        """
```

**Score mapping formula**:
- `positive` → `50 + (confidence × 50)`
- `negative` → `50 - (confidence × 50)`
- `neutral`  → `50`
- Final aggregate score = weighted average of all individual scores

**Constraints**:
- Truncate each input text to **512 tokens** max (FinBERT's context limit)
- Load model lazily — only on first call, not at import time
- Batch process all texts in a single pipeline call for efficiency
- Catch `torch.cuda.OutOfMemoryError` and fall back to CPU

---

### 1.2 Modify `utils/sentiment_analyzer_adanos.py`

**What to keep**: All data-fetching logic — the scraping of news, Yahoo Finance, Twitter/X. These are data sources, not scoring.

**What to change**: After raw texts are collected from each source, pass them through `FinBERTSentimentAnalyzer` instead of the old scoring method.

**Add a config flag at the top of the file**:
```python
USE_FINBERT = os.getenv("FINBERT_ENABLED", "true").lower() == "true"
```

**Fallback behaviour**: If FinBERT fails (model not loaded, OOM, import error), fall back to the existing Adanos API call. Do not delete the Adanos path.

**Source weighting for final score aggregation** (apply after scoring each source):
```
News articles:    40%
Yahoo Finance:    20%
Reddit:           25%
Twitter/X:        15%
```

---

### 1.3 Modify `utils/reddit_sentiment.py`

- Remove any `SentimentIntensityAnalyzer` (VADER) imports and usage
- Import `FinBERTSentimentAnalyzer` from `utils/finbert_sentiment.py`
- Pass collected Reddit post texts through FinBERT instead of VADER
- Return the same output structure as before so callers are unaffected

---

### 1.4 Update `requirements.txt`

Add:
```
transformers>=4.36.0
torch>=2.0.0
```

> **Note for deployment**: If the server is CPU-only, `torch` will still work but inference will be slower (~2–5 seconds per batch). The model file is ~440MB and requires ~2GB RAM when loaded. The singleton pattern ensures it is loaded only once per process lifetime.

---

## Task 2: Add FinRobot Multi-Agent Layer

### 2.1 New Directory Structure

Create a new top-level directory `finrobot/`:

```
finrobot/
├── __init__.py
├── fundamental_agent.py       # Agent 1: Analyses CompanyData financials
├── sentiment_agent.py         # Agent 2: Analyses FinBERT output + news texts
├── reasoning_agent.py         # Agent 3: Synthesises both agents into final report
└── finrobot_orchestrator.py   # Entry point — runs all three agents in sequence
```

> **Important**: Do NOT install the FinRobot GitHub library as a dependency. Implement the agent patterns directly using the existing LLM pipeline (`utils/model_config.py` → OpenRouter). The patterns are prompting strategies, not library calls.

---

### 2.2 `finrobot/fundamental_agent.py`

**Input**: `CompanyData` object (already populated — passed in, not fetched)

**What it uses from `CompanyData`**:
- `financials` — P/E, P/B, EPS, revenue, margins, debt-to-equity, operating cash flow
- `swot` — strengths, weaknesses, opportunities, threats
- `market_data` — current price, 52-week high/low, promoter/FII/DII holdings
- `snapshot` — sector, industry
- `market_data.competitors` — peer company list

**LLM call**: Send structured financial data to LLM via `utils/model_config.py` with a system prompt that instructs it to reason like a buy-side fundamental analyst. The prompt must explicitly ask for:
- Valuation assessment (is the stock cheap, fair, or expensive vs sector)
- Financial health (debt levels, cash flow quality, margin trends)
- Growth quality (revenue consistency, EPS trend)
- Red flags (any concerning ratios or SWOT weaknesses)

**Output Pydantic model** (define in this file):
```python
class FundamentalAnalysisResult(BaseModel):
    valuation_score: float        # 0–100
    financial_health_score: float # 0–100
    growth_score: float           # 0–100
    overall_fundamental_score: float  # 0–100 (weighted average of above)
    reasoning: str                # Chain-of-thought text from LLM
    key_positives: list[str]      # Top 3–5 bullish fundamental points
    key_risks: list[str]          # Top 3–5 fundamental risk factors
```

---

### 2.3 `finrobot/sentiment_agent.py`

**Input**:
- `sentiment_data: dict` — the full output dict from `FinBERTSentimentAnalyzer.analyze_texts()` including `individual_results`
- `news_articles: list[dict]` — from `CompanyData.news` and Tavily results
- `raw_texts: dict` — keyed by source (`"reddit"`, `"twitter"`, `"news"`, `"yahoo"`) with lists of raw text strings

**What it does**:
- Takes FinBERT's numerical scores and per-text results
- Sends to LLM with a prompt instructing it to:
  - Identify dominant sentiment themes (e.g., "earnings beat", "regulatory concern", "management change")
  - Detect sentiment shifts or anomalies (e.g., sudden spike in negative after being neutral)
  - Flag any extreme signals (score < 20 or > 80)
  - Assess sentiment momentum (is it getting better or worse recently)

**Output Pydantic model**:
```python
class SentimentAgentResult(BaseModel):
    sentiment_score: float         # 0–100 (taken directly from FinBERT)
    sentiment_label: str           # "Positive" / "Negative" / "Neutral"
    theme_summary: str             # What topics are driving the sentiment
    sentiment_momentum: str        # "Improving" / "Deteriorating" / "Stable"
    key_drivers: list[str]         # Top 3–5 specific sentiment drivers
    llm_commentary: str            # Analyst-style 2–3 sentence paragraph
    anomalies_detected: list[str]  # Any unusual signals found (empty list if none)
```

---

### 2.4 `finrobot/reasoning_agent.py`

This is the **synthesis layer** — like a senior analyst reviewing two junior analysts' reports. It runs last and receives outputs from both previous agents.

**Input**:
- `fundamental_result: FundamentalAnalysisResult`
- `sentiment_result: SentimentAgentResult`
- `company_name: str`
- `sector: str`
- `tavily_news_summary: str` (from `utils/stock_news_analyzer.py` — already available)

**LLM prompt structure** — instruct the model to:
1. State the fundamental picture in one sentence
2. State the sentiment picture in one sentence
3. Identify any contradiction between them (e.g., strong fundamentals but deteriorating sentiment)
4. Reason step-by-step about what the combination means for the stock
5. Arrive at a final recommendation with confidence level

**Output Pydantic model**:
```python
class ReasoningResult(BaseModel):
    final_score: float             # 0–100 (synthesised overall score)
    recommendation: str            # "Strong Buy" / "Buy" / "Hold" / "Sell" / "Strong Sell"
    confidence: str                # "High" / "Medium" / "Low"
    chain_of_thought: str          # Full step-by-step reasoning text
    summary: str                   # 2–3 sentence executive summary
    contradictions_noted: str      # If fundamental vs sentiment conflict — describe it. Empty string if no conflict.
    time_horizon: str              # "Short-term" / "Medium-term" / "Long-term" — which horizon this applies to
```

---

### 2.5 `finrobot/finrobot_orchestrator.py`

Single entry point for the entire FinRobot pipeline.

```python
async def run_finrobot_analysis(
    company_data: CompanyData,
    sentiment_data: dict,           # From FinBERT
    raw_sentiment_texts: dict,      # Keyed by source
    tavily_news_summary: str
) -> FinRobotReport
```

**Execution order**: Fundamental Agent → Sentiment Agent → Reasoning Agent (sequential — each feeds the next)

**Output Pydantic model**:
```python
class FinRobotReport(BaseModel):
    fundamental: Optional[FundamentalAnalysisResult]
    sentiment: Optional[SentimentAgentResult]
    reasoning: Optional[ReasoningResult]
    generated_at: datetime
    symbol: str
    agents_completed: list[str]    # Which agents ran successfully
    agents_failed: list[str]       # Which agents failed (with reason logged)
```

**Error handling**: If any individual agent raises an exception, mark it in `agents_failed`, set its result field to `None`, and continue with the remaining agents. The Reasoning Agent should degrade gracefully if one of its inputs is `None`.

---

## Task 3: Integration into Existing Codebase

### 3.1 `models.py`

Add to `CompanyData`:
```python
from finrobot.finrobot_orchestrator import FinRobotReport

class CompanyData(BaseModel):
    # ... all existing fields ...
    finrobot_report: Optional[FinRobotReport] = None
```

---

### 3.2 `agent1.py`

Add a new pydantic-ai tool:

```python
@agent.tool
async def run_finrobot_deep_analysis(ctx: RunContext[AgentDeps], symbol: str) -> ToolResponse:
    """
    Runs the full FinRobot three-agent pipeline on the currently analyzed stock.
    Call this when the user asks for deep analysis, investment reasoning, or a full report.
    Returns a chain-of-thought investment recommendation.
    """
```

Inside the tool:
1. Retrieve the `CompanyData` from context (already in session state / DB)
2. Run `FinBERTSentimentAnalyzer` on available news texts
3. Call `finrobot_orchestrator.run_finrobot_analysis(...)`
4. Store result in `CompanyData.finrobot_report`
5. Return formatted `ToolResponse` with the reasoning summary and recommendation

**Follow the existing `ToolResponse` wrapper pattern**:
```python
return create_tool_response(result_text, "run_finrobot_deep_analysis")
```

---

### 3.3 `app_advanced.py` (Streamlit UI)

**In the Sentiment Tab**:
- Replace or augment the current sentiment score display
- Show FinBERT score with label (Positive/Negative/Neutral) prominently
- Add a sub-section below: "Sentiment Agent Analysis" showing `theme_summary`, `sentiment_momentum`, and `key_drivers` as a bullet list

**In the Fundamental Analysis / Chat Tab**:
- After the main analysis card renders, add a collapsible `st.expander("🤖 FinRobot Deep Analysis")` section
- Inside the expander: show the Reasoning Agent's `chain_of_thought`, `recommendation` (as a badge/colored chip), `confidence`, and `summary`

**Session state caching**:
```python
# Cache key pattern — follow existing convention
st.session_state[f"finrobot_report_{symbol}"] = finrobot_report
```
Check this key before re-running the pipeline on tab switch.

---

## Recommended Implementation Order

Execute in this sequence to minimise integration risk:

| Step | Task | Files |
|------|------|-------|
| 1 | Create and test FinBERT wrapper standalone | `utils/finbert_sentiment.py` |
| 2 | Integrate FinBERT into Reddit sentiment | `utils/reddit_sentiment.py` |
| 3 | Integrate FinBERT into main sentiment analyzer | `utils/sentiment_analyzer_adanos.py` |
| 4 | Create FinRobot agent files | `finrobot/fundamental_agent.py`, `finrobot/sentiment_agent.py`, `finrobot/reasoning_agent.py` |
| 5 | Create FinRobot orchestrator | `finrobot/finrobot_orchestrator.py` |
| 6 | Add `FinRobotReport` field to models | `models.py` |
| 7 | Add new tool to agent | `agent1.py` |
| 8 | Update Streamlit UI | `app_advanced.py` |
| 9 | Update dependencies and docs | `requirements.txt`, `README.md` |

---

## Key Constraints & Rules

1. **FinBERT is a singleton** — load the model exactly once per process. Never reload per request. Use a class-level `_instance` or module-level variable.

2. **FinBERT max input is 512 tokens** — always truncate texts before passing to the pipeline.

3. **FinRobot = prompting patterns, not a library** — do not `pip install` any FinRobot package. The agents are LLM prompt strategies implemented using the existing OpenRouter pipeline in `utils/model_config.py`.

4. **All LLM calls via `utils/model_config.py`** — never hardcode model names, API keys, or create new OpenAI/Anthropic clients directly.

5. **Keep Adanos API as fallback** — do not delete the existing Adanos path in `sentiment_analyzer_adanos.py`. Only deprioritise it behind the `USE_FINBERT` flag.

6. **All new agent tools in `agent1.py` must return `ToolResponse`** using the `create_tool_response()` helper — this is the existing project convention.

7. **FinRobot agents receive data, they do not fetch it** — no new API calls or data fetching inside `finrobot/`. All data is passed in from the existing pipeline.

8. **Model file size**: FinBERT is ~440MB and requires ~2GB RAM when loaded. Document this in `README.md` under the Troubleshooting or Deployment section.

---

## Files to Create (New)

```
utils/finbert_sentiment.py
finrobot/__init__.py
finrobot/fundamental_agent.py
finrobot/sentiment_agent.py
finrobot/reasoning_agent.py
finrobot/finrobot_orchestrator.py
```

## Files to Modify (Existing)

```
utils/sentiment_analyzer_adanos.py   — Replace VADER scoring with FinBERT
utils/reddit_sentiment.py            — Replace VADER with FinBERT
models.py                            — Add finrobot_report field to CompanyData
agent1.py                            — Add run_finrobot_deep_analysis tool
app_advanced.py                      — Display FinBERT scores + FinRobot results in UI
requirements.txt                     — Add transformers, torch
README.md                            — Update tech stack table and add RAM note
```
