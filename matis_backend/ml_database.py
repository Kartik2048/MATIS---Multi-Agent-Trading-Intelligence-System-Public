# ml_database.py — CoinDCX INR Simulation & ML Training Data Logger
import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import sqlite3
from datetime import datetime, timezone

ML_DB_PATH = os.path.join(os.path.dirname(__file__), "matis_ml_training.db")

# CoinDCX INR constraints
COINDCX_MIN_TRADE_INR = 100.0
COINDCX_FEE_RATE = 0.005       # 0.50% per side
COINDCX_GST_MULTIPLIER = 1.18  # 18% GST on the fee

# CoinDCX market symbol mapping
COINDCX_MARKETS = {
    "BTC": "BTCINR",
    "ETH": "ETHINR",
    "SOL": "SOLINR",
    "XRP": "XRPINR",
    "BNB": "BNBINR",
    "LINK": "LINKINR",
}


def get_ml_connection():
    """Get a SQLite connection for the ML training database."""
    conn = sqlite3.connect(ML_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_ml_db():
    """Create ML training tables if they don't exist."""
    conn = get_ml_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            asset TEXT NOT NULL,
            action TEXT NOT NULL,
            confidence INTEGER NOT NULL DEFAULT 0,
            allocation_pct REAL NOT NULL DEFAULT 0.0,
            trade_value_inr REAL NOT NULL DEFAULT 0.0,
            entry_price REAL NOT NULL DEFAULT 0.0,
            sentiment_score REAL NOT NULL DEFAULT 0.5,
            market_trend TEXT NOT NULL DEFAULT '',
            llm_reasoning TEXT NOT NULL DEFAULT '',
            critic_feedback TEXT NOT NULL DEFAULT '',
            simulated_fee_inr REAL NOT NULL DEFAULT 0.0,
            net_pnl_inr REAL NOT NULL DEFAULT 0.0,
            outcome_status TEXT NOT NULL DEFAULT 'PENDING'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            total_value_inr REAL NOT NULL DEFAULT 0.0,
            cash_balance_inr REAL NOT NULL DEFAULT 0.0
        )
    """)

    conn.commit()
    conn.close()
    print(f"[ML DB] ML training database initialized at {ML_DB_PATH}")


def calculate_coindcx_fee(trade_value_inr: float) -> float:
    """
    Calculate CoinDCX simulated fee.
    Fee = trade_value * 0.50% * 1.18 (GST)
    Effective ~0.59% per side.
    """
    return trade_value_inr * COINDCX_FEE_RATE * COINDCX_GST_MULTIPLIER


def validate_coindcx_trade(action: str, trade_value_inr: float, cash_balance_inr: float) -> dict:
    """
    Validate a trade against CoinDCX INR constraints.
    Returns dict with 'valid' bool, 'fee_inr', and 'message'.
    """
    if trade_value_inr < COINDCX_MIN_TRADE_INR:
        return {
            "valid": False,
            "fee_inr": 0.0,
            "message": f"Trade value ₹{trade_value_inr:.2f} is below CoinDCX minimum of ₹{COINDCX_MIN_TRADE_INR:.2f}"
        }

    fee_inr = calculate_coindcx_fee(trade_value_inr)

    if action == "BUY":
        total_cost = trade_value_inr + fee_inr
        if total_cost > cash_balance_inr:
            return {
                "valid": False,
                "fee_inr": fee_inr,
                "message": f"Insufficient INR. Need ₹{total_cost:.2f} (trade + fee), have ₹{cash_balance_inr:.2f}"
            }

    return {
        "valid": True,
        "fee_inr": round(fee_inr, 2),
        "message": f"Trade validated. Fee: ₹{fee_inr:.2f} (~{(COINDCX_FEE_RATE * COINDCX_GST_MULTIPLIER * 100):.2f}%)"
    }


def log_trade(
    asset: str,
    action: str,
    confidence: int,
    allocation_pct: float,
    trade_value_inr: float,
    entry_price: float,
    sentiment_score: float,
    market_trend: str,
    llm_reasoning: str,
    critic_feedback: str,
    simulated_fee_inr: float,
    net_pnl_inr: float = 0.0,
    outcome_status: str = "EXECUTED"
):
    """Log a complete trade record to the ML training database."""
    conn = get_ml_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO trade_logs
           (timestamp, asset, action, confidence, allocation_pct, trade_value_inr,
            entry_price, sentiment_score, market_trend, llm_reasoning, critic_feedback,
            simulated_fee_inr, net_pnl_inr, outcome_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (now, asset, action, confidence, allocation_pct, trade_value_inr,
         entry_price, sentiment_score, market_trend, llm_reasoning, critic_feedback,
         simulated_fee_inr, net_pnl_inr, outcome_status)
    )
    conn.commit()
    conn.close()
    print(f"[ML DB] Logged {action} {asset} — ₹{trade_value_inr:,.2f} | Fee: ₹{simulated_fee_inr:.2f} | Status: {outcome_status}")


def log_portfolio_snapshot(total_value_inr: float, cash_balance_inr: float):
    """Log a portfolio snapshot for equity curve charting."""
    conn = get_ml_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO portfolio_snapshots (timestamp, total_value_inr, cash_balance_inr) VALUES (?, ?, ?)",
        (now, total_value_inr, cash_balance_inr)
    )
    conn.commit()
    conn.close()


def get_ml_trade_logs(limit: int = 100, action_filter: str = "ALL", asset_filter: str = "ALL") -> list:
    """Retrieve ML trade logs with optional filters."""
    conn = get_ml_connection()
    query = "SELECT * FROM trade_logs WHERE 1=1"
    params = []

    if action_filter != "ALL":
        query += " AND action = ?"
        params.append(action_filter)
    if asset_filter != "ALL":
        query += " AND asset = ?"
        params.append(asset_filter)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_equity_history(limit: int = 200) -> list:
    """Retrieve portfolio equity snapshots for the equity curve chart."""
    conn = get_ml_connection()
    rows = conn.execute(
        "SELECT * FROM portfolio_snapshots ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    # Return in chronological order (oldest first) for charting
    return [dict(r) for r in reversed(rows)]


def reset_ml_logs():
    """Clear all trade logs and portfolio snapshots from the ML training database."""
    conn = get_ml_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM trade_logs")
    cursor.execute("DELETE FROM portfolio_snapshots")
    conn.commit()
    conn.close()
    print("[ML DB] Trade logs and portfolio snapshots cleared.")
