# MATIS v3 — Project Overview

## 1. Introduction

**MATIS (Multi-Agent Trading Intelligence System) v3** is an autonomous cryptocurrency paper-trading platform powered by cooperative AI agents organized in a **LangGraph** multi-agent state graph.

Operating on **NVIDIA NIM** foundation models (specifically `nvidia/nemotron-3-super-120b-a12b` and `meta/llama-3.3-70b-instruct`), MATIS translates raw market feeds into actionable quantitative intelligence, deliberates through specialized cognitive roles (sentiment analysis, strategy formulation, adversarial critique, and risk management), and executes simulated trades under realistic exchange rules.

---

## 2. Core Problem & Motivation

Traditional algorithmic crypto trading systems rely almost exclusively on fixed-parameter rule sets (e.g., SMA crossovers, static RSI overbought/oversold boundaries) or opaque "black-box" machine learning regressors. These systems face distinct failure modes:

1. **Blindness to Macro and Narrative Sentiment**: Hardcoded indicators cannot parse regulatory developments, geopolitical events, or sudden sentiment shifts that invalidate technical patterns.
2. **Lack of Critical Reflection**: Traditional quantitative algorithms generate orders without sanity checks against opposing market forces (e.g., buying an overbought altcoin during a steep Bitcoin macro selloff).
3. **Unrealistic Paper Trading**: Most paper-trading simulators operate in frictionless USD vacuums without accounting for regional currency conversions, exchange minimum order sizes, maker/taker slippage, or localized transaction taxes (like India's 18% GST on trading fees).
4. **Data Waste**: Deliberations, discarded theses, and intermediate market states are typically discarded rather than harvested to train future predictive models.

MATIS addresses these shortcomings through a cognitive multi-agent architecture designed specifically for the **Indian Rupee (INR)** trading ecosystem on **CoinDCX**.

---

## 3. Key Pillars & Capabilities

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                            MATIS ARCHITECTURAL PILLARS                        │
├──────────────────────┬───────────────────────┬───────────────────────────────┤
│ Cognitive Roles      │ Execution Integrity   │ Telemetry & Learning          │
├──────────────────────┼───────────────────────┼───────────────────────────────┤
│ • Sentinel (News)    │ • CoinDCX INR Rules   │ • Dual SQLite Architecture    │
│ • Semantic Builder   │ • ₹100 Min Trade Size │ • ML Training Dataset Logger  │
│ • Strategist (Thesis)│ • ~0.59% GST Fees     │ • WebSocket Live Streaming    │
│ • Critic (Adversary) │ • Weighted Cost Basis │ • Filtered Telegram Alerts    │
│ • Risk Manager (Math)│ • Semaphore Throttling│ • Dark-Mode Glassmorphic UI   │
└──────────────────────┴───────────────────────┴───────────────────────────────┘
```

### A. Cooperative Multi-Agent Deliberation
Instead of relying on a single prompt or monolith model, MATIS segments trading cognition into discrete agent nodes:
- **Sentinel**: Reads live news headlines and assigns a normalized sentiment score ($0.0 \dots 1.0$).
- **Semantic Builder**: Deterministically translates complex numeric indicators (RSI, Bollinger Bands, ATR, 9/21 EMAs, RVOL) into domain-specific structured natural language.
- **Strategist**: Formulates high-conviction trade proposals (Action, Allocation %, Confidence, and Reasoning).
- **Cost-Optimized Graph Router**: Instantly routes non-trade (`HOLD`) or sub-minimum orders directly to the Risk Manager, bypassing LLM critique to preserve API quotas and cut execution latency.
- **Critic**: Adversarially evaluates proposals against strict market principles and enforces a replanning loop if the thesis is flawed.
- **Risk Manager**: Mathematically checks solvency, calculates exact coin units and CoinDCX fees, and executes the paper trade.

### B. Autonomous Multi-Asset Scheduler
A native background task periodically evaluates all 6 supported cryptocurrency assets (`BTC`, `ETH`, `SOL`, `XRP`, `BNB`, `LINK`) every 5 minutes (300 seconds), regulated by an `asyncio.Semaphore(2)` to eliminate burst rate limits on NVIDIA NIM endpoints.

### C. Native CoinDCX Exchange Simulation
All portfolios, orders, and ledger balances are tracked natively in **INR (₹)**:
- **₹100 Minimum Threshold**: Orders below ₹100 are rejected by the exchange validator.
- **Taker Fee + GST**: Implements the CoinDCX spot fee formula ($0.50\% \text{ fee} \times 1.18 \text{ GST} \approx 0.59\%$).
- **Dynamic USDT Conversion**: Provides fallback synthetic pricing via CoinDCX `USDTINR` quotes if a native INR ticker experiences network latency.

### D. Filtered High-Signal Telegram Notifications
Push notifications are dispatched to Telegram channels **strictly upon executed BUY or SELL orders**. Deliberations that resolve to `HOLD` are logged for auditability but suppressed from chat channels to eliminate notification fatigue.

### E. Dual Database & ML Data Harvesting
- `matis_paper_trading.db`: Maintains account balance, active holdings, weighted entry prices, and executed transaction logs.
- `matis_ml_training.db`: Captures the full state of the market, complete raw LLM reasoning chains, adversarial critic feedback, simulated fees, and resulting P&L to construct supervised fine-tuning (SFT) and reinforcement learning (RL) datasets.

---

## 4. Supported Assets

| Symbol | Binance Klines Pair | CoinDCX Spot Pair | Primary Role in Portfolio |
|---|---|---|---|
| **BTC** | `BTCUSDT` | `BTCINR` | Market Gravity Benchmark & Anchor Asset |
| **ETH** | `ETHUSDT` | `ETHINR` | Smart Contract & Layer-1 Core |
| **SOL** | `SOLUSDT` | `SOLINR` | High-Beta High-Throughput Layer-1 |
| **XRP** | `XRPUSDT` | `XRPINR` | Global Settlement & High-Liquidity Large-Cap |
| **BNB** | `BNBUSDT` | `BNBINR` | Centralized Exchange Ecosystem Asset |
| **LINK** | `LINKUSDT` | `LINKINR` | Decentralized Oracle Infrastructure |

---

## 5. Live Instance

A live deployment running the single news sentiment score agent and Python conditional statements version is accessible at:
- **Web Dashboard**: [https://matis.duckdns.org/](https://matis.duckdns.org/)
- **Local Development**: `http://localhost:8000`
