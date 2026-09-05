# main.py — MATIS v3: CoinDCX INR Simulation + ML Logging + WebSocket + Async Pipeline
import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, BackgroundTasks, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn
import time
from datetime import datetime, timezone, timedelta

from graph import matis_app
from database import (
    init_db, get_portfolio, get_asset_balance, execute_trade,
    get_trade_history, reset_portfolio, get_asset_cost_basis,
    INITIAL_INR_BALANCE, get_connection, SUPPORTED_ASSETS,
    get_executed_trades_count
)
from indicators import calculate_indicators, build_semantic_payload
from ml_database import (
    init_ml_db, log_trade, log_portfolio_snapshot,
    get_ml_trade_logs, get_equity_history,
    validate_coindcx_trade, calculate_coindcx_fee,
    reset_ml_logs
)
from price_feed import price_feed, ws_price_handler, live_prices, get_inr_price, get_usd_to_inr_rate

SERVER_START_TIME = time.time()


import httpx
import xml.etree.ElementTree as ET
from typing import Optional

# ============================================================
#  CRYPTO NEWS & TELEGRAM NOTIFIER
# ============================================================
def fetch_latest_crypto_news(asset: str = "BTC") -> str:
    """Fetch live crypto headlines from Decrypt RSS."""
    try:
        resp = httpx.get("https://decrypt.co/feed", timeout=8)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")
            titles = [item.find("title").text for item in items[:5] if item.find("title") is not None]
            if titles:
                return "\n".join(titles)
    except Exception as e:
        print(f"[NEWS] ⚠️ Failed to fetch RSS: {e}")
    return f"Live market monitoring for {asset}. General crypto market conditions active."


def send_telegram_alert(trade: dict):
    """Send formatted boardroom alert to Telegram if credentials are set in .env. Strictly for BUY or SELL."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    action = str(trade.get("action", "HOLD")).strip().upper()
    status = str(trade.get("status", "HOLD")).strip().upper()

    # STRICT: Only send notification on BUY or SELL
    if action not in ["BUY", "SELL"] or status == "HOLD":
        return

    asset = trade.get("asset", "N/A")
    price = trade.get("execution_price_inr", 0.0)
    value = trade.get("trade_value_inr", 0.0)
    confidence = trade.get("confidence", 0)
    sentiment = trade.get("news_sentiment", 0.5)
    reasoning = trade.get("reasoning", "")

    emoji = "🟢" if action == "BUY" else "🔴"
    status_tag = "✅ EXECUTED" if status == "EXECUTED" else f"⚠️ {status}"

    text = (
        f"🚨 MATIS Boardroom Report 🚨\n\n"
        f"🧠 STRATEGIST (Proposal):\n{reasoning}\n\n"
        f"📰 SENTINEL (News Sentiment): {sentiment:.2f}\n\n"
        f"⚖️ RISK MANAGER:\n"
        f"{emoji} Action: {action} {asset}\n"
        f"Status: {status_tag}\n"
        f"Fill Price: ₹{price:,.2f}\n"
        f"Trade Value: ₹{value:,.2f}\n"
        f"Confidence: {confidence}%"
    )

    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=8
        )
        print(f"[TELEGRAM] 📱 Alert sent to chat {chat_id}")
    except Exception as e:
        print(f"[TELEGRAM] ⚠️ Failed to send alert: {e}")


# ============================================================
#  AUTONOMOUS SCHEDULER (Concurrent Full Basket via Semaphore)
# ============================================================
_scheduler_running = False
_scheduler_task = None

async def evaluate_asset_with_semaphore(asset: str, sem: asyncio.Semaphore):
    """Evaluates an individual asset with concurrency controlled by semaphore."""
    async with sem:
        try:
            print(f"[SCHEDULER] ⚡ Deliberating on {asset} (Acquired semaphore slot)...")
            news = await run_in_threadpool(fetch_latest_crypto_news, asset)
            await run_in_threadpool(run_matis_pipeline, asset, news)
            print(f"[SCHEDULER] ✅ Deliberation completed for {asset}.")
        except Exception as e:
            print(f"[SCHEDULER] ⚠️ Error evaluating {asset}: {e}")


async def autonomous_scheduler_loop():
    """Every 5 minutes, evaluates ALL supported assets concurrently, controlled by a semaphore."""
    global _scheduler_running
    interval = int(os.getenv("AUTO_EVALUATE_INTERVAL_SECONDS", "300"))
    max_concurrency = int(os.getenv("MAX_CONCURRENT_EVALUATIONS", "2"))
    sem = asyncio.Semaphore(max_concurrency)

    print(f"[SCHEDULER] 🤖 Autonomous AI Trading active: Evaluating ALL {len(SUPPORTED_ASSETS)} assets every {interval}s (Concurrency Semaphore: {max_concurrency})")
    # Wait 8s after startup so price feed is populated
    await asyncio.sleep(8)

    while _scheduler_running:
        print(f"\n{'#'*65}")
        print(f" [SCHEDULER] 🚀 Starting Full Basket Deliberation Cycle ({', '.join(SUPPORTED_ASSETS)})")
        print(f"{'#'*65}")

        # Evaluate all assets concurrently via semaphore
        tasks = [evaluate_asset_with_semaphore(asset, sem) for asset in SUPPORTED_ASSETS]
        await asyncio.gather(*tasks, return_exceptions=True)

        print(f"\n[SCHEDULER] 🏁 All {len(SUPPORTED_ASSETS)} assets evaluated. Next full cycle in {interval}s ({interval//60} mins).\n")

        # Sleep in small slices to allow clean and responsive server shutdown
        for _ in range(interval):
            if not _scheduler_running:
                break
            await asyncio.sleep(1)


# ============================================================
#  LIFESPAN — replaces deprecated @app.on_event
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DBs + start CoinDCX price feed + start scheduler. Shutdown: stop."""
    global _scheduler_running, _scheduler_task
    init_db()
    init_ml_db()
    await price_feed.start()

    # Start autonomous trading loop if enabled (default true)
    if os.getenv("AUTO_TRADING", "true").lower() == "true":
        _scheduler_running = True
        _scheduler_task = asyncio.create_task(autonomous_scheduler_loop())

    yield

    _scheduler_running = False
    if _scheduler_task:
        _scheduler_task.cancel()
    await price_feed.stop()


app = FastAPI(title="MATIS Brain API", lifespan=lifespan)


# --- N8n Payload Model ---
class N8nPayload(BaseModel):
    asset: Optional[str] = "BTC"
    news: Optional[str] = "No news available"


# ============================================================
#  BACKGROUND TASK — Runs LangGraph pipeline off the event loop
# ============================================================
def run_matis_pipeline(asset: str, news: str):
    """
    Synchronous function executed in a BackgroundTask.
    Runs the full LangGraph pipeline, executes paper trades,
    validates CoinDCX constraints, and logs to ML database.
    """
    print(f"\n{'='*60}")
    print(f"  MATIS v3 — Analyzing {asset} (Background)")
    print(f"{'='*60}")

    # 1. Fetch live indicators from Binance (for technical analysis)
    market_data = calculate_indicators(asset)
    print(f"[INDICATORS] {asset} @ ${market_data.get('price', 0):,.2f} | RSI: {market_data.get('rsi')} | RVOL: {market_data.get('rvol')}x | BTC 24h: {market_data.get('btc_24h_change')}%")

    # 2. Fetch current portfolio balances
    portfolio = get_portfolio()
    asset_bal = get_asset_balance(asset)
    portfolio_snapshot = {
        "inr_balance": portfolio["inr_balance"],
        "asset_balance": asset_bal,
    }
    print(f"[DEBUG PORTFOLIO] INR: ₹{portfolio['inr_balance']:,.2f} | {asset}: {asset_bal:.8f}")

    # 3. Build the initial state for LangGraph
    initial_state = {
        "asset": asset,
        "market_data": market_data,
        "news_headlines": [news],
        "feedback_iterations": 0,
        "portfolio": portfolio_snapshot,
        "semantic_payload": {},
    }

    # 4. Run the graph (synchronous — runs in thread pool via BackgroundTask)
    final_state = matis_app.invoke(initial_state)
    decision = final_state.get("final_decision", {})
    sentiment_score = final_state.get("sentiment_score", 0.5)
    critic_feedback = final_state.get("critic_feedback", "N/A")

    # Extract semantic trend for ML logging
    semantic = final_state.get("semantic_payload", {})
    tech_state = semantic.get("technical_state", {})
    market_trend = tech_state.get("trend", "Unknown")

    # 5. Get INR price from CoinDCX live feed
    inr_price = get_inr_price(asset)
    if inr_price <= 0:
        # Fallback: approximate INR from USD
        conversion_rate = get_usd_to_inr_rate()
        inr_price = market_data.get("price", 0) * conversion_rate
        print(f"[PRICE] CoinDCX INR price not available for {asset}, using USDT conversion rate (₹{conversion_rate:.2f}): ₹{inr_price:,.2f}")
    else:
        print(f"[PRICE] CoinDCX INR price for {asset}: ₹{inr_price:,.2f}")

    # 6. Paper Trading Integration + CoinDCX Validation
    trade_result = None
    final_execution_details = {
        "asset": asset,
        "action": decision.get("action", "HOLD"),
        "status": "HOLD",
        "trade_value_inr": 0.0,
        "fee_inr": 0.0,
        "units_transacted": 0.0,
        "execution_price_inr": inr_price,
        "allocation_pct": decision.get("allocation_pct", 0.0),
        "confidence": decision.get("confidence", 0),
        "news_sentiment": sentiment_score,
        "reasoning": decision.get("reasoning", "")
    }

    if decision.get("status") == "EXECUTE_TRADE":
        action = decision.get("action", "HOLD")
        allocation_fraction = decision.get("allocation_fraction", 0.0)
        allocation_pct = decision.get("allocation_pct", 0.0)
        confidence = decision.get("confidence", 0)
        reasoning = decision.get("reasoning", "")

        current_portfolio = get_portfolio()
        current_asset_bal = get_asset_balance(asset)

        if action == "BUY":
            trade_inr = current_portfolio["inr_balance"] * allocation_fraction
            units_to_buy = trade_inr / inr_price if inr_price > 0 else 0
            
            final_execution_details["trade_value_inr"] = trade_inr
            final_execution_details["units_transacted"] = units_to_buy

            # CoinDCX validation
            validation = validate_coindcx_trade(action, trade_inr, current_portfolio["inr_balance"])
            if not validation["valid"]:
                final_execution_details["status"] = "BLOCKED_COINDCX"
                print(f"[COINDCX] ❌ {validation['message']}")
                log_trade(
                    asset=asset, action=action, confidence=confidence,
                    allocation_pct=allocation_pct, trade_value_inr=trade_inr,
                    entry_price=inr_price, sentiment_score=sentiment_score,
                    market_trend=market_trend, llm_reasoning=reasoning,
                    critic_feedback=critic_feedback, simulated_fee_inr=0.0,
                    net_pnl_inr=0.0, outcome_status="BLOCKED_COINDCX"
                )
            else:
                fee_inr = validation["fee_inr"]
                final_execution_details["status"] = "EXECUTED"
                final_execution_details["fee_inr"] = fee_inr
                print(f"[EXEC] BUY {asset} — ₹{trade_inr:,.2f} = {units_to_buy:.6f} {asset} @ ₹{inr_price:,.2f} | Fee: ₹{fee_inr:.2f}")
                trade_result = execute_trade(asset, "BUY", units_to_buy, inr_price, confidence, reasoning, fee_inr)

                # Log to ML database
                log_trade(
                    asset=asset, action=action, confidence=confidence,
                    allocation_pct=allocation_pct, trade_value_inr=trade_inr,
                    entry_price=inr_price, sentiment_score=sentiment_score,
                    market_trend=market_trend, llm_reasoning=reasoning,
                    critic_feedback=critic_feedback, simulated_fee_inr=fee_inr,
                    net_pnl_inr=0.0, outcome_status="EXECUTED"
                )

        elif action == "SELL":
            units_to_sell = current_asset_bal * allocation_fraction
            sell_inr = units_to_sell * inr_price
            
            final_execution_details["trade_value_inr"] = sell_inr
            final_execution_details["units_transacted"] = units_to_sell

            validation = validate_coindcx_trade(action, sell_inr, current_portfolio["inr_balance"])
            if not validation["valid"]:
                final_execution_details["status"] = "BLOCKED_COINDCX"
                print(f"[COINDCX] ❌ {validation['message']}")
                log_trade(
                    asset=asset, action=action, confidence=confidence,
                    allocation_pct=allocation_pct, trade_value_inr=sell_inr,
                    entry_price=inr_price, sentiment_score=sentiment_score,
                    market_trend=market_trend, llm_reasoning=reasoning,
                    critic_feedback=critic_feedback, simulated_fee_inr=0.0,
                    net_pnl_inr=0.0, outcome_status="BLOCKED_COINDCX"
                )
            else:
                fee_inr = validation["fee_inr"]
                final_execution_details["status"] = "EXECUTED"
                final_execution_details["fee_inr"] = fee_inr
                print(f"[EXEC] SELL {asset} — {units_to_sell:.6f} {asset} = ₹{sell_inr:,.2f} @ ₹{inr_price:,.2f} | Fee: ₹{fee_inr:.2f}")
                trade_result = execute_trade(asset, "SELL", units_to_sell, inr_price, confidence, reasoning, fee_inr)

                realized_pnl_inr = trade_result.get("realized_profit", 0.0) if trade_result else 0.0
                log_trade(
                    asset=asset, action=action, confidence=confidence,
                    allocation_pct=allocation_pct, trade_value_inr=sell_inr,
                    entry_price=inr_price, sentiment_score=sentiment_score,
                    market_trend=market_trend, llm_reasoning=reasoning,
                    critic_feedback=critic_feedback, simulated_fee_inr=fee_inr,
                    net_pnl_inr=realized_pnl_inr, outcome_status="EXECUTED"
                )
    else:
        # HOLD
        confidence = decision.get("confidence", 0)
        reasoning = decision.get("reasoning", "No reasoning provided.")
        now = datetime.now(timezone.utc).isoformat()

        conn = get_connection()
        conn.execute(
            """INSERT INTO trade_history
               (timestamp, asset, action, amount, execution_price, total_value_inr, fee_inr, confidence, reasoning, realized_profit)
               VALUES (?, ?, 'HOLD', 0, ?, 0, 0.0, ?, ?, 0.0)""",
            (now, asset, inr_price, confidence, reasoning)
        )
        conn.commit()
        conn.close()
        print(f"[HOLD] Logged HOLD for {asset} @ ₹{inr_price:,.2f} | Confidence: {confidence}%")

        # Log HOLD to ML database too
        log_trade(
            asset=asset, action="HOLD", confidence=confidence,
            allocation_pct=0.0, trade_value_inr=0.0,
            entry_price=inr_price, sentiment_score=sentiment_score,
            market_trend=market_trend, llm_reasoning=reasoning,
            critic_feedback=critic_feedback, simulated_fee_inr=0.0,
            net_pnl_inr=0.0, outcome_status="HOLD"
        )

    # 7. Log portfolio snapshot for equity curve
    updated_portfolio = get_portfolio()
    inr_total = updated_portfolio["inr_balance"]
    holdings = updated_portfolio.get("holdings", {})

    # Calculate exact total INR value
    total_inr = inr_total
    for a, bal in holdings.items():
        if bal > 0:
            a_inr = get_inr_price(a)
            if a_inr <= 0:
                try:
                    ind = calculate_indicators(a)
                    a_inr = ind.get("price", 0) * get_usd_to_inr_rate()
                except Exception:
                    a_inr = 0.0
            total_inr += bal * a_inr

    log_portfolio_snapshot(total_inr, inr_total)
    print(f"[ML DB] Portfolio snapshot logged: ₹{total_inr:,.2f} total | ₹{inr_total:,.2f} cash")

    d_action = decision.get("action", "HOLD")
    d_alloc = decision.get("allocation_pct", 0)
    print(f"[COMPLETE] {d_action} {asset} ({d_alloc}% allocation) @ ₹{inr_price:,.2f}")
    
    # Update final details with portfolio state
    final_execution_details["post_trade_inr_balance"] = round(inr_total, 2)
    final_execution_details["post_trade_asset_balance"] = round(holdings.get(asset, 0.0), 8)
    final_execution_details["total_portfolio_value_inr"] = round(total_inr, 2)
    
    # Send push notification to Telegram if enabled
    send_telegram_alert(final_execution_details)

    return final_execution_details


# ============================================================
#  CORE ENDPOINT — Returns immediately, processes in background
# ============================================================
@app.post("/api/evaluate/{asset}")
async def trigger_evaluation(
    asset: str, 
    background_tasks: BackgroundTasks, 
    payload: Optional[N8nPayload] = None,
    mode: str = Query("async", description="Use 'sync' for n8n/Telegram, 'async' for UI")
):
    """
    Dual-execution endpoint. 
    - mode=async offloads to BackgroundTasks (returns instantly).
    - mode=sync runs in a threadpool and waits for the result (for n8n).
    """
    asset_upper = asset.upper()
    news_text = payload.news if (payload and payload.news and payload.news != "No news available") else None
    if not news_text:
        news_text = await run_in_threadpool(fetch_latest_crypto_news, asset_upper)
    
    if mode == "sync":
        # For n8n: Run the heavy synchronous LLM pipeline in a worker thread.
        # This keeps the request open until finished, returning the actual trade data,
        # WITHOUT blocking the main asyncio event loop (keeping WebSockets alive).
        result = await run_in_threadpool(run_matis_pipeline, asset_upper, news_text)
        return result
        
    else:
        # For UI: Fire and forget to prevent UI lockup.
        background_tasks.add_task(run_matis_pipeline, asset_upper, news_text)
        return {
            "status": "processing", 
            "message": f"Evaluation pipeline for {asset_upper} started in background."
        }


# ============================================================
#  WEBSOCKET — Live CoinDCX Prices
# ============================================================
@app.websocket("/ws/prices")
async def websocket_prices(websocket: WebSocket):
    """Stream live CoinDCX INR prices to connected frontend clients."""
    await ws_price_handler(websocket)


# ============================================================
#  DASHBOARD API ENDPOINTS
# ============================================================

@app.get("/api/portfolio")
async def api_portfolio(current_price: float = 0.0, asset: str = "BTC"):
    """
    Returns portfolio data with asset-specific view.
    Global P&L is handled by /api/portfolio_summary.
    """
    portfolio = get_portfolio()
    inr = portfolio.get("inr_balance", INITIAL_INR_BALANCE)
    holdings = portfolio.get("holdings", {})
    asset_bal = holdings.get(asset, 0.0)
    cost_basis = get_asset_cost_basis(asset)

    asset_market_value = asset_bal * current_price
    asset_pnl = asset_market_value - cost_basis["net_cost_basis"]

    return {
        "inr_balance": round(inr, 2),
        "holdings": {k: round(v, 8) for k, v in holdings.items()},
        "current_asset": asset,
        "current_asset_balance": round(asset_bal, 8),
        "current_price": current_price,
        "cost_basis": cost_basis,
        "avg_entry_price": cost_basis.get("avg_entry_price", 0.0),
        "total_realized_profit": cost_basis.get("total_realized_profit", 0.0),
        "asset_market_value": round(asset_market_value, 2),
        "asset_pnl": round(asset_pnl, 2),
        "initial_balance": INITIAL_INR_BALANCE,
        "total_trades": get_executed_trades_count(),
        "supported_assets": SUPPORTED_ASSETS
    }


@app.get("/api/portfolio_summary")
async def api_portfolio_summary():
    """
    GLOBAL portfolio valuation — fetches live CoinDCX prices for ALL held assets.
    Returns the TRUE total portfolio value and net P&L across the entire basket.
    """
    portfolio = get_portfolio()
    inr = portfolio.get("inr_balance", INITIAL_INR_BALANCE)
    holdings = portfolio.get("holdings", {})

    total_holdings_value = 0.0
    asset_valuations = {}

    for asset_name, balance in holdings.items():
        if balance > 0:
            price = get_inr_price(asset_name)
            if price <= 0:
                try:
                    indicators = calculate_indicators(asset_name)
                    price = indicators.get("price", 0.0) * get_usd_to_inr_rate()
                except Exception:
                    price = 0.0
            
            value = balance * price
            total_holdings_value += value
            asset_valuations[asset_name] = {
                "balance": round(balance, 8),
                "price": round(price, 2),
                "value_inr": round(value, 2)
            }

    total_portfolio_value = inr + total_holdings_value
    pnl = total_portfolio_value - INITIAL_INR_BALANCE
    pnl_pct = (pnl / INITIAL_INR_BALANCE) * 100 if INITIAL_INR_BALANCE > 0 else 0

    conn = get_connection()
    rp_row = conn.execute(
        "SELECT COALESCE(SUM(realized_profit), 0) as total FROM trade_history WHERE action = 'SELL'"
    ).fetchone()
    global_realized = rp_row["total"]
    conn.close()

    global_unrealized = pnl - global_realized

    return {
        "inr_balance": round(inr, 2),
        "total_holdings_value": round(total_holdings_value, 2),
        "total_portfolio_value": round(total_portfolio_value, 2),
        "net_pnl": round(pnl, 2),
        "net_pnl_pct": round(pnl_pct, 4),
        "global_realized_pnl": round(global_realized, 2),
        "global_unrealized_pnl": round(global_unrealized, 2),
        "initial_balance": INITIAL_INR_BALANCE,
        "asset_valuations": asset_valuations,
        "total_trades": get_executed_trades_count()
    }


@app.get("/api/trades")
async def api_trades(limit: int = 50):
    """Returns the latest trade history entries."""
    trades = get_trade_history(limit=limit)
    return {
        "trades": trades, 
        "count": len(trades),
        "executed_count": get_executed_trades_count()
    }


@app.get("/api/ml/trades")
async def api_ml_trades(limit: int = 100, action: str = "ALL", asset: str = "ALL"):
    """Returns ML trade logs with optional action/asset filters."""
    logs = get_ml_trade_logs(limit=limit, action_filter=action, asset_filter=asset)
    return {"trades": logs, "count": len(logs)}


@app.get("/api/portfolio/equity")
async def api_equity(limit: int = 200):
    """Returns portfolio equity snapshots for the equity curve chart."""
    history = get_equity_history(limit=limit)
    return {"snapshots": history, "count": len(history)}


@app.get("/api/prices")
async def api_prices():
    """Returns the current CoinDCX live prices from the in-memory store."""
    return {"prices": live_prices}


@app.post("/api/reset")
async def api_reset():
    """Reset portfolio to initial balance with zero holdings. For testing only."""
    reset_portfolio()
    reset_ml_logs()
    return {"status": "reset", "message": f"Portfolio reset to {INITIAL_INR_BALANCE:,.2f}"}


@app.get("/api/system")
async def api_system():
    """Returns server uptime and operational status."""
    elapsed = time.time() - SERVER_START_TIME
    td = timedelta(seconds=int(elapsed))
    days = td.days
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days > 0:
        uptime_str = f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    feed_status = "Active" if price_feed._running else "Stopped"
    ws_count = len(live_prices)

    return {
        "uptime": uptime_str,
        "status": "Operational",
        "price_feed": feed_status,
        "tracked_assets": ws_count,
    }


# --- Serve the Dashboard ---
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def serve_dashboard():
    """Serve the main dashboard HTML."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)