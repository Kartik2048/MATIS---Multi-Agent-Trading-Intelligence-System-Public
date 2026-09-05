# Autonomous Scheduler & Concurrency Control

## 1. Background Execution Architecture

MATIS v3 incorporates an autonomous scheduling engine implemented as a native background daemon within FastAPI's modern **lifespan** context (`@asynccontextmanager`). 

Unlike external cron triggers or manual UI buttons, the autonomous scheduler continuously monitors and trades the entire basket without human intervention:

```text
FastAPI Lifespan Startup
       │
       ├──► Start CoinDCX WebSocket Price Poller
       │
       └──► Launch autonomous_scheduler_loop()
                  │
                  ▼
         ┌────────────────────────────────────────────────────────┐
         │ Every 300 Seconds (5 Minutes):                         │
         │                                                        │
         │  1. Ingest real-time news per asset                    │
         │  2. Dispatch all 6 assets concurrently via gather()    │
         │  3. Throttle concurrency via asyncio.Semaphore(2)      │
         │  4. Execute LangGraph multi-agent pipeline             │
         │  5. Filter Telegram alerts to BUY/SELL only            │
         └────────────────────────────────────────────────────────┘
```

---

## 2. Full Basket Deliberation

In every 5-minute cycle, the scheduler evaluates all 6 supported cryptocurrency assets:
- **Bitcoin** (`BTC`)
- **Ethereum** (`ETH`)
- **Solana** (`SOL`)
- **Ripple** (`XRP`)
- **BNB** (`BNB`)
- **Chainlink** (`LINK`)

### Dispatch Pattern (`asyncio.gather`):
```python
async def autonomous_scheduler_loop():
    interval = int(os.getenv("AUTO_EVALUATE_INTERVAL_SECONDS", "300"))
    max_concurrency = int(os.getenv("MAX_CONCURRENT_EVALUATIONS", "2"))
    sem = asyncio.Semaphore(max_concurrency)

    while _scheduler_running:
        tasks = [evaluate_asset_with_semaphore(asset, sem) for asset in SUPPORTED_ASSETS]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Sliced sleep for graceful shutdown
        for _ in range(interval):
            if not _scheduler_running:
                break
            await asyncio.sleep(1)
```

---

## 3. Concurrency Throttling with `asyncio.Semaphore`

### The Problem: Burst Overload on NVIDIA NIM
Evaluating 6 assets concurrently without throttling would cause 6 heavyweight LLM queries (Sentinel sentiment) to hit the NVIDIA NIM API within milliseconds, followed by 6 simultaneous Strategist prompts and 6 Critic prompts. 

This causes:
1. **HTTP 503 Service Temporarily Overloaded**: NIM API gateway throttling.
2. **HTTP 429 Too Many Requests**: Token-per-minute (TPM) and request-per-minute (RPM) quota breaches.
3. **CoinDCX Public Feed Rate-Limiting**: Simultaneous rapid-fire ticker lookups.

### The Solution: `asyncio.Semaphore(2)`
By wrapping each asset's evaluation in a semaphore:
```python
async def evaluate_asset_with_semaphore(asset: str, sem: asyncio.Semaphore):
    async with sem:
        news = await run_in_threadpool(fetch_latest_crypto_news, asset)
        await run_in_threadpool(run_matis_pipeline, asset, news)
```
- Exactly **2 assets** deliberate concurrently at any moment.
- As soon as one asset finishes (e.g., `BTC`), its semaphore slot is released and the next waiting asset (e.g., `SOL`) immediately acquires it.
- Full basket deliberation finishes smoothly in under 45 seconds without triggering API limits or dropped requests.

---

## 4. Real-Time News Aggregation

If an external news webhook (e.g., n8n) is not supplying news, the autonomous scheduler automatically aggregates real-time news per asset using `fetch_latest_crypto_news(asset)`:

1. **Google News RSS**: Queries `https://news.google.com/rss/search?q={asset}+crypto+when:1d&hl=en-IN`.
2. **Title Extraction**: Parses the latest 3 headlines for the asset.
3. **Fallback String**: If the network is unreachable or returns zero items, provides clean baseline context (*"Live market monitoring for {asset}. General crypto market conditions active."*).

---

## 5. Responsive Server Shutdown

Instead of performing a monolithic `await asyncio.sleep(300)` (which would hang and block process termination until the full 5 minutes expire), the sleep is sliced into 1-second ticks:

```python
for _ in range(interval):
    if not _scheduler_running:
        break
    await asyncio.sleep(1)
```
When `SIGINT` (Ctrl+C) or Uvicorn reload occurs, `lifespan` sets `_scheduler_running = False`, causing the sleep loop to break immediately and release system resources without dangling tasks.
