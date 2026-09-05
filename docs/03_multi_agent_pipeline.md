# Multi-Agent Deliberation Pipeline

## 1. Overview of the Cognitive Architecture

The core trading engine in MATIS v3 is built on **LangGraph**, orchestrating state transitions among specialized cognitive agents. Rather than asking a single large model to read raw indicators, compute risk ratios, write code, and size orders simultaneously, MATIS distributes cognition across dedicated nodes:

```text
[Market Feeds] ──► Sentinel (News) ──► Semantic Builder ──► Strategist (Thesis)
                                                                 │
                                ┌────────────────────────────────┴────────────────────────────────┐
                                ▼                                                                 ▼
                         [>= ₹100 & BUY/SELL]                                              [HOLD or < ₹100]
                                │                                                                 │
                                ▼                                                                 │
                           Critic Node ◄───────┐                                                  │
                                │              │                                                  │
                            APPROVED        REJECTED                                              │
                                │         (replan < 3)                                            │
                                └──────────────┬──────────────────────────────────────────────────┘
                                               │
                                               ▼
                                      Risk Manager Node
                                               │
                                               ▼
                                     [SQLite + Execution]
```

---

## 2. State Definition (`state.py`)

All nodes in the LangGraph graph pass and mutate a shared state object adhering to the `AgentState` TypedDict:

```python
from typing import TypedDict, List, Dict, Any

class AgentState(TypedDict):
    asset: str                         # e.g., "BTC", "ETH", "SOL"
    market_data: Dict[str, Any]        # Raw indicator values (price, rsi, bb, atr, rvol)
    news_headlines: List[str]          # Ingested news headlines
    sentiment_score: float             # Normalized score: 0.0 (bearish) to 1.0 (bullish)
    semantic_payload: Dict[str, Any]   # Translated human-readable domain text
    trade_proposal: Dict[str, Any]     # Strategist's proposed action, alloc, confidence
    critic_feedback: str               # Critic's rejection notes or approval stamp
    feedback_iterations: int           # Re-planning loop counter (capped at 2)
    portfolio: Dict[str, Any]          # Liquid INR cash and coin balance
    final_decision: Dict[str, Any]     # Validated trade ready for execution
```

---

## 3. Node-by-Node Pipeline Breakdown

### Node 1: Sentinel (News Sentiment)
- **Primary Model**: `nvidia/nemotron-3-super-120b-a12b` (Temperature: `0.2`).
- **Input**: Raw news headlines for the target asset.
- **Responsibility**: Parses macro narratives, regulatory announcements, and token-specific updates.
- **Structured Output**: Enforces strict JSON via Pydantic:
  ```python
  class SentimentResponse(BaseModel):
      sentiment_score: float = Field(description="A score between 0.0 and 1.0.")
      summary: str = Field(description="1-2 sentence summary of news.")
  ```
- **Error Recovery**: If the headlines are empty or the LLM rate limit is hit, Sentinel falls back gracefully to neutral `0.50` with a neutral summary.

---

### Node 2: Semantic Builder (Deterministic Translation Layer)
LLMs struggle to reliably interpret raw continuous numbers (e.g., `rsi: 74.2`, `bb_upper: 82150.3`). The Semantic Builder is a deterministic Python module (`indicators.py`) that translates mathematical values into rich domain-specific intelligence:

| Quantitative Input | Translated Semantic Representation |
|---|---|
| `rsi: 78.5` | `"RSI is 78.5 (Overbought)"` |
| `price > ema_9 > ema_21` | `"Price ($103.90) is trading ABOVE the 9 EMA and 21 EMA (Uptrend)"` |
| `rvol: 2.3` | `"Relative Volume is 2.3x vs. average (Strong participation)"` |
| `btc_24h: +3.2%` | `"Broad Market Trend (BTC): +3.2% (Bullish Market Gravity)"` |
| `atr: 1.45` | Recommends dynamic stop-loss buffer calculated as $2 \times \text{ATR}$. |

---

### Node 3: Strategist (Trade Proposal Formulation)
- **Primary Model**: `nvidia/nemotron-3-super-120b-a12b` (Temperature: `0.1`).
- **Input**:
  - Semantic market state (trend, momentum, volume, volatility).
  - Bitcoin macro gravity.
  - Sentinel sentiment score.
  - Available liquid INR cash balance and existing coin holdings.
  - *Optional*: Rejection feedback from the Critic if in a replanning loop.
- **Output Schema**:
  ```python
  class TradeProposal(BaseModel):
      action: str       # Strictly "BUY", "SELL", or "HOLD"
      confidence: int   # Integer 0 to 100
      allocation_pct: float # 0.0% to 100.0%
      reasoning: str    # Exhaustive rationale
  ```

---

### Component 4: Cost-Optimized Graph Router
In production trading, the majority of evaluation intervals result in a `HOLD` (market consolidating, no edge present) or propose trivial order sizes below exchange minimums.

To prevent wasteful LLM token consumption and unnecessary latency:
```python
def should_critique(state: AgentState) -> str:
    proposal = state.get("trade_proposal", {})
    action = proposal.get("action", "HOLD")
    alloc = proposal.get("allocation_pct", 0)

    # Fast-path bypass: Skip Critic if action is HOLD
    if action == "HOLD" or alloc <= 0:
        return "risk_manager"

    # Fast-path bypass: Skip Critic if proposed trade is under ₹100 min
    inr_val = (alloc / 100.0) * state["portfolio"]["inr_balance"]
    if inr_val < 100.0:
        return "risk_manager"

    # Actionable trade >= ₹100: Submit to adversarial review
    return "critic"
```

---

### Node 5: Critic & Reflection Loop
- **Primary Model**: `nvidia/nemotron-3-super-120b-a12b`.
- **Role**: Serves as a ruthless risk officer and logic adversary.
- **Verification Rules**:
  - Rejects attempts to `BUY` into overbought resistance without above-average volume.
  - Rejects buying an altcoin when Bitcoin macro gravity is sharply negative.
  - Rejects `SELL` proposals when the asset is oversold and holding major support.
  - Validates stop-loss placement against ATR volatility widths.
- **Replanning Loop**:
  - If rejected and `feedback_iterations < 2`, returns targeted feedback to the Strategist to reformulate the trade.
  - If approved, or if the 2-iteration limit is reached, forwards the proposal to the Risk Manager.

---

### Node 6: Risk Manager (Sizing & Constraint Enforcement)
- **Role**: Pure mathematical execution engine operating without generative randomness.
- **Key Checks**:
  1. **Solvency Verification**: Ensures liquid INR cash $\ge \text{Trade Value} + \text{Fee}$ on `BUY`, and coin holdings $\ge \text{Units}$ on `SELL`.
  2. **Dynamic Confidence Threshold**:
     $$\text{Target Confidence} = 75\% - (\text{Sentiment} - 0.5) \times 20\%$$
     If Strategist's confidence is below target, the order is forced to `HOLD`.
  3. **CoinDCX Sizing & Fees**: Computes order units in coin quantity and calculates simulated exchange fees:
     $$\text{Fee (INR)} = \text{Order Value (INR)} \times 0.005 \times 1.18$$
  4. **Ledger Execution**: Writes approved trades to SQLite and updates the portfolio balance.

---

## 4. Foundation Models & NIM Integration

MATIS uses the **LangChain NVIDIA AI Endpoints** library (`langchain-nvidia-ai-endpoints`) configured via `.env`:

```env
NVIDIA_API_KEY=nvapi-your-key-here
NVIDIA_MODEL=nvidia/nemotron-3-super-120b-a12b
```

### Supported Models:
1. `nvidia/nemotron-3-super-120b-a12b` *(Default & Recommended)*:
   Exceptional mathematical coherence, structured JSON reliability, and adherence to negative constraints in adversarial prompting.
2. `meta/llama-3.3-70b-instruct`:
   Fast, lightweight alternative with high instruction-following fidelity.
