# Telemetry, Alerting & Automation

## 1. Telegram Alerting Architecture

MATIS v3 features integrated Telegram alerting dispatched directly from `send_telegram_alert()` in `main.py`. This provides real-time visibility into boardroom agent deliberations directly on mobile and desktop devices.

```text
Deliberation Settled
       │
       ▼
Action in ["BUY", "SELL"]? 
       │
       ├──► NO (HOLD) ────────► Suppress notification (0 Telegram requests)
       │
       └──► YES (BUY / SELL) ──► Dispatch rich Telegram boardroom report
```

---

## 2. Strict Filter Policy (BUY / SELL Only)

In algorithmic trading, sending an alert every time an automated system considers the market and decides to `HOLD` produces overwhelming chat spam (up to 72 notifications per hour across 6 coins).

### Implementation Guard:
```python
def send_telegram_alert(trade: dict):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    action = str(trade.get("action", "HOLD")).strip().upper()
    status = str(trade.get("status", "HOLD")).strip().upper()

    # STRICT: Only send notification on BUY or SELL
    if action not in ["BUY", "SELL"] or status == "HOLD":
        return
```

- **Zero Noise on HOLD**: Whenever the agents decide to hold, or when the Risk Manager forces an order to `HOLD` because confidence failed dynamic thresholds, Telegram push alerts are completely silenced.
- **High-Signal Alerts**: Telegram is reserved exclusively for actionable events when paper capital is committed or profits are taken.

---

## 3. Sample Boardroom Telegram Alert

When an actionable trade executes, a rich markdown report is transmitted:

```text
🚨 MATIS Boardroom Report 🚨

🧠 STRATEGIST (Proposal):
Price has broken above both 9 and 21 EMAs with RVOL at 2.1x. RSI sits at 54 (Mildly Bullish), supported by positive Bitcoin macro gravity (+3.2%). Proposing 15% allocation.

📰 SENTINEL (News Sentiment): 0.72

⚖️ RISK MANAGER:
🟢 Action: BUY BTC
Status: ✅ EXECUTED
Fill Price: ₹7,941,266.20
Trade Value: ₹1,500.00
Confidence: 85%
```

---

## 4. n8n Orchestration Workflow (`n8n workflow.json`)

For external scheduling or integration with secondary data pipelines, MATIS includes a turnkey **n8n workflow**:

```text
[Cron Trigger (7m)] ──► [RSS Headline Parser] ──► [Item Batcher]
                                                          │
                                                          ▼
                                            [HTTP POST /api/evaluate/{asset}]
                                                          │
                                                          ▼
                                            [Telegram Notification Node]
```

### Workflow Steps:
1. **Schedule Trigger**: Fires on a custom cron interval (default: every 7 minutes).
2. **Crypto News RSS**: Ingests the latest headlines from public feeds (e.g., Decrypt, CoinDesk).
3. **HTTP Request Node**: Dispatches a synchronous evaluation call:
   ```http
   POST http://127.0.0.1:8000/api/evaluate/{{$json["asset"]}}?mode=sync
   ```
4. **Telegram Dispatcher**: Formats the JSON execution response and relays it to chat subscribers.

---

## 5. Configuration Guide

Add your Telegram bot credentials to `matis_backend/.env`:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

### How to Get Credentials:
1. **Bot Token**: Message [@BotFather](https://t.me/botfather) on Telegram, create a new bot using `/newbot`, and copy the HTTP API token.
2. **Chat ID**: Message your new bot, then open:
   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
   ```
   Locate your `"id"` under the `"chat"` block.
