# API Reference

## 1. REST Endpoints Overview

| Method | Path | Purpose | Query / Body Parameters |
|---|---|---|---|
| `POST` | `/api/evaluate/{asset}` | Trigger multi-agent deliberation | `mode=async|sync`, Optional JSON body |
| `GET` | `/api/portfolio_summary` | Global mark-to-market portfolio overview | None |
| `GET` | `/api/portfolio` | Asset-specific cost basis and P&L | `asset=BTC&current_price=...` |
| `GET` | `/api/trades` | Transaction history ledger | `limit=50` |
| `GET` | `/api/ml/trades` | Complete ML decision traces | `limit=100&action=...&asset=...` |
| `GET` | `/api/portfolio/equity` | Historical equity curve snapshots | `limit=200` |
| `GET` | `/api/prices` | Latest cached CoinDCX spot prices | None |
| `POST` | `/api/reset` | Wipe environment back to ₹10,000 | None |
| `GET` | `/api/system` | Server health and uptime | None |

---

## 2. Detailed REST Endpoints

### A. Trigger Multi-Agent Evaluation
```http
POST /api/evaluate/{asset}?mode={async|sync}
```
Initiates a full LangGraph deliberation cycle for the specified cryptocurrency (`BTC`, `ETH`, `SOL`, `XRP`, `BNB`, `LINK`).

#### Query Parameters:
- `mode=async` *(Default)*: Enqueues deliberation as a background task and returns immediately (`{"status": "processing"}`).
- `mode=sync`: Awaits deliberation completion and returns the final execution dictionary. Used by n8n workflows and automated test scripts.

#### Request Body *(Optional)*:
```json
{
  "asset": "BTC",
  "news": "Bitcoin ETF inflows accelerate as institutional volume surges."
}
```

#### Synchronous Response (`200 OK`):
```json
{
  "asset": "BTC",
  "action": "BUY",
  "status": "EXECUTED",
  "trade_value_inr": 1500.00,
  "fee_inr": 8.85,
  "units_transacted": 0.00018888,
  "execution_price_inr": 7941266.20,
  "allocation_pct": 15.0,
  "confidence": 85,
  "news_sentiment": 0.72,
  "reasoning": "Price confirmed breakout above 9 and 21 EMAs with strong volume.",
  "post_trade_inr_balance": 8491.15,
  "post_trade_asset_balance": 0.00018888,
  "total_portfolio_value_inr": 9991.15
}
```

---

### B. Global Portfolio Summary
```http
GET /api/portfolio_summary
```
Returns mark-to-market valuations across all active holdings. Note that `total_trades` strictly reflects executed `BUY` and `SELL` orders (ignoring `HOLD`).

#### Response (`200 OK`):
```json
{
  "inr_balance": 8491.15,
  "total_holdings_value": 1500.00,
  "total_portfolio_value": 9991.15,
  "net_pnl": -8.85,
  "net_pnl_pct": -0.0885,
  "global_realized_pnl": 0.00,
  "global_unrealized_pnl": -8.85,
  "initial_balance": 10000.0,
  "total_trades": 1
}
```

---

### C. Trade History Ledger
```http
GET /api/trades?limit=50
```
Returns latest deliberation audit records from `matis_paper_trading.db`.

#### Response (`200 OK`):
```json
{
  "trades": [
    {
      "id": 1,
      "timestamp": "2026-09-06T00:58:00+00:00",
      "asset": "BTC",
      "action": "HOLD",
      "amount": 0.0,
      "execution_price": 7941266.20,
      "total_value_inr": 0.0,
      "fee_inr": 0.0,
      "confidence": 58,
      "reasoning": "Confidence 58% < Dynamic Target 74% — forcing HOLD",
      "realized_profit": 0.0
    }
  ],
  "count": 1,
  "executed_count": 0
}
```
- `count`: Total deliberation records (including `HOLD`).
- `executed_count`: Count of filled `BUY` and `SELL` transactions only.

---

### D. Machine Learning Decision Traces
```http
GET /api/ml/trades?limit=100&action=ALL&asset=ALL
```
Returns deep cognitive audit records containing full LLM reasoning chains and critic evaluations.

#### Response (`200 OK`):
```json
{
  "trades": [
    {
      "id": 1,
      "timestamp": "2026-09-06T00:58:00+00:00",
      "asset": "SOL",
      "action": "BUY",
      "confidence": 85,
      "allocation_pct": 10.0,
      "trade_value_inr": 1000.0,
      "entry_price": 10300.0,
      "sentiment_score": 0.65,
      "market_trend": "Strong Uptrend",
      "llm_reasoning": "Price testing upper Bollinger band with 2.1x RVOL.",
      "critic_feedback": "APPROVED (Iteration 1, Attempt 1)",
      "simulated_fee_inr": 5.90,
      "net_pnl_inr": 0.0,
      "outcome_status": "EXECUTED"
    }
  ],
  "count": 1
}
```

---

### E. System Health
```http
GET /api/system
```

#### Response (`200 OK`):
```json
{
  "uptime": "01:14:32",
  "status": "Operational",
  "price_feed": "Active",
  "tracked_assets": 6
}
```

---

## 3. WebSocket Price Stream

```
ws://localhost:8000/ws/prices
```
Real-time JSON broadcasts streaming directly from the CoinDCX background fetcher every 5 seconds:

```json
{
  "type": "price_update",
  "prices": {
    "BTC": { "price_inr": 7941266.2, "change_24h": 0.21 },
    "ETH": { "price_inr": 246479.7, "change_24h": -0.45 },
    "SOL": { "price_inr": 10300.0, "change_24h": 1.12 },
    "XRP": { "price_inr": 140.39, "change_24h": 0.85 },
    "BNB": { "price_inr": 77176.5, "change_24h": -0.15 },
    "LINK": { "price_inr": 1200.78, "change_24h": 0.60 }
  }
}
```
