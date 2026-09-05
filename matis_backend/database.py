# database.py — Multi-Asset Paper Trading Database
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

DB_PATH = os.path.join(os.path.dirname(__file__), "matis_paper_trading.db")

INITIAL_INR_BALANCE = 10_000.0

# Supported assets for the basket
SUPPORTED_ASSETS = ["BTC", "ETH", "SOL", "XRP", "BNB", "LINK"]


def get_connection():
    """Get a SQLite connection with row_factory for dict-like access."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrency for FastAPI
    return conn


def init_db():
    """Create tables and seed the portfolio if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    # Drop old tables if they are still on USD schema
    try:
        cursor.execute("SELECT usd_balance FROM portfolio")
        cursor.execute("DROP TABLE portfolio")
        cursor.execute("DROP TABLE trade_history")
    except sqlite3.OperationalError:
        pass

    # --- Core INR balance (single row) ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            inr_balance REAL NOT NULL DEFAULT 10000.0,
            updated_at TEXT NOT NULL
        )
    """)

    # --- Normalized asset holdings ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            asset TEXT PRIMARY KEY,
            balance REAL NOT NULL DEFAULT 0.0,
            avg_entry_price REAL NOT NULL DEFAULT 0.0,
            updated_at TEXT NOT NULL
        )
    """)

    # --- Trade history ---
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            asset TEXT NOT NULL,
            action TEXT NOT NULL,
            amount REAL NOT NULL,
            execution_price REAL NOT NULL,
            total_value_inr REAL NOT NULL,
            fee_inr REAL NOT NULL DEFAULT 0.0,
            confidence INTEGER NOT NULL DEFAULT 0,
            reasoning TEXT NOT NULL DEFAULT '',
            realized_profit REAL NOT NULL DEFAULT 0.0
        )
    """)

    # Seed the portfolio with 1,000,000 INR if the row doesn't exist
    now = datetime.now(timezone.utc).isoformat()
    existing = cursor.execute("SELECT id FROM portfolio WHERE id = 1").fetchone()
    if not existing:
        cursor.execute(
            "INSERT INTO portfolio (id, inr_balance, updated_at) VALUES (1, ?, ?)",
            (INITIAL_INR_BALANCE, now)
        )

    # Seed zero holdings for each supported asset
    for asset in SUPPORTED_ASSETS:
        exists = cursor.execute("SELECT asset FROM holdings WHERE asset = ?", (asset,)).fetchone()
        if not exists:
            cursor.execute(
                "INSERT INTO holdings (asset, balance, updated_at) VALUES (?, 0.0, ?)",
                (asset, now)
            )

    conn.commit()
    conn.close()
    print(f"[DB] Database initialized at {DB_PATH}")


# --- Portfolio Operations ---

def get_portfolio() -> dict:
    """Return current INR balance and all asset holdings."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM portfolio WHERE id = 1").fetchone()
    inr = dict(row)["inr_balance"] if row else INITIAL_INR_BALANCE

    holdings = {}
    rows = conn.execute("SELECT asset, balance FROM holdings").fetchall()
    for r in rows:
        holdings[r["asset"]] = r["balance"]

    conn.close()
    return {"inr_balance": inr, "holdings": holdings}


def get_asset_balance(asset: str) -> float:
    """Return the balance of a specific asset."""
    conn = get_connection()
    row = conn.execute("SELECT balance FROM holdings WHERE asset = ?", (asset,)).fetchone()
    conn.close()
    return row["balance"] if row else 0.0


def execute_trade(asset: str, action: str, amount: float, price: float, confidence: int, reasoning: str, fee_inr: float = 0.0) -> dict:
    """
    Execute a paper trade for any asset in INR. Updates portfolio and logs the trade.
    - BUY: Deducts total value + fee from INR balance.
    - SELL: Adds total value to INR balance, deducts fee.
    """
    conn = get_connection()
    cursor = conn.cursor()

    portfolio_row = conn.execute("SELECT inr_balance FROM portfolio WHERE id = 1").fetchone()
    inr = portfolio_row["inr_balance"]

    holding_row = conn.execute("SELECT balance, avg_entry_price FROM holdings WHERE asset = ?", (asset,)).fetchone()
    asset_balance = holding_row["balance"] if holding_row else 0.0
    current_avg_price = holding_row["avg_entry_price"] if holding_row else 0.0

    total_value_inr = amount * price
    now = datetime.now(timezone.utc).isoformat()
    realized_profit = 0.0

    if action == "BUY":
        total_cost = total_value_inr + fee_inr
        if total_cost > inr:
            conn.close()
            return {"success": False, "message": f"Insufficient INR. Need ₹{total_cost:.2f}, have ₹{inr:.2f}"}
        new_inr = inr - total_cost
        new_asset_balance = asset_balance + amount

        # Rolling average cost basis
        if asset_balance <= 0:
            new_avg_price = price
        else:
            new_avg_price = ((asset_balance * current_avg_price) + (amount * price)) / new_asset_balance

    elif action == "SELL":
        if amount > asset_balance:
            conn.close()
            return {"success": False, "message": f"Insufficient {asset}. Need {amount:.6f}, have {asset_balance:.6f}"}
        
        # Add value, subtract fee
        net_proceeds = total_value_inr - fee_inr
        new_inr = inr + net_proceeds
        new_asset_balance = asset_balance - amount

        # Realized P&L: (sell_price - avg_entry_price) * amount_sold - fee
        realized_profit = ((price - current_avg_price) * amount) - fee_inr

        # Do NOT alter avg_entry_price on SELL — unless balance hits zero
        new_avg_price = current_avg_price
        if new_asset_balance < 1e-12:  # floating-point zero check
            new_asset_balance = 0.0
            new_avg_price = 0.0

    else:
        conn.close()
        return {"success": False, "message": f"Unknown action: {action}"}

    # Update INR balance
    cursor.execute(
        "UPDATE portfolio SET inr_balance = ?, updated_at = ? WHERE id = 1",
        (new_inr, now)
    )

    # Update asset holding with avg_entry_price
    cursor.execute(
        "UPDATE holdings SET balance = ?, avg_entry_price = ?, updated_at = ? WHERE asset = ?",
        (new_asset_balance, new_avg_price, now, asset)
    )

    # Insert trade record with realized_profit
    cursor.execute(
        """INSERT INTO trade_history
           (timestamp, asset, action, amount, execution_price, total_value_inr, fee_inr, confidence, reasoning, realized_profit)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (now, asset, action, amount, price, total_value_inr, fee_inr, confidence, reasoning, realized_profit)
    )

    conn.commit()
    conn.close()

    print(f"[TRADE] {action} {amount:.6f} {asset} @ ₹{price:,.2f} = ₹{total_value_inr:,.2f} | Fee: ₹{fee_inr:.2f} | Realized P&L: ₹{realized_profit:,.2f}")
    return {
        "success": True,
        "message": f"{action} {amount:.6f} {asset} @ ₹{price:,.2f}",
        "new_inr_balance": new_inr,
        "new_asset_balance": new_asset_balance,
        "realized_profit": round(realized_profit, 2)
    }


def get_asset_cost_basis(asset: str) -> dict:
    """
    Calculate the cost basis for a specific asset from trade history.
    """
    conn = get_connection()

    # Total INR spent buying this asset (including fees)
    buy_row = conn.execute(
        "SELECT COALESCE(SUM(total_value_inr + fee_inr), 0) as total FROM trade_history WHERE asset = ? AND action = 'BUY'",
        (asset,)
    ).fetchone()
    total_bought_inr = buy_row["total"]

    # Total INR received selling this asset (after fees)
    sell_row = conn.execute(
        "SELECT COALESCE(SUM(total_value_inr - fee_inr), 0) as total FROM trade_history WHERE asset = ? AND action = 'SELL'",
        (asset,)
    ).fetchone()
    total_sold_inr = sell_row["total"]

    # Current avg_entry_price from holdings
    holding_row = conn.execute(
        "SELECT avg_entry_price FROM holdings WHERE asset = ?", (asset,)
    ).fetchone()
    avg_entry_price = holding_row["avg_entry_price"] if holding_row else 0.0

    # Total realized profit across all SELL trades for this asset
    rp_row = conn.execute(
        "SELECT COALESCE(SUM(realized_profit), 0) as total FROM trade_history WHERE asset = ? AND action = 'SELL'",
        (asset,)
    ).fetchone()
    total_realized_profit = rp_row["total"]

    conn.close()

    net_cost_basis = total_bought_inr - total_sold_inr
    return {
        "total_bought_inr": round(total_bought_inr, 2),
        "total_sold_inr": round(total_sold_inr, 2),
        "net_cost_basis": round(net_cost_basis, 2),
        "avg_entry_price": round(avg_entry_price, 2),
        "total_realized_profit": round(total_realized_profit, 2)
    }


def get_trade_history(limit: int = 50) -> list:
    """Return the latest trades, newest first."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM trade_history ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_executed_trades_count(asset: str = None) -> int:
    """Return the count of executed BUY and SELL trades (excluding HOLD)."""
    conn = get_connection()
    if asset:
        row = conn.execute(
            "SELECT COUNT(*) as count FROM trade_history WHERE action IN ('BUY', 'SELL') AND asset = ?",
            (asset,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) as count FROM trade_history WHERE action IN ('BUY', 'SELL')"
        ).fetchone()
    conn.close()
    return row["count"] if row else 0


def reset_portfolio():
    """Reset everything back to initial balance with zero holdings."""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cursor.execute(
        "UPDATE portfolio SET inr_balance = ?, updated_at = ? WHERE id = 1",
        (INITIAL_INR_BALANCE, now)
    )
    for asset in SUPPORTED_ASSETS:
        cursor.execute(
            "UPDATE holdings SET balance = 0.0, avg_entry_price = 0.0, updated_at = ? WHERE asset = ?",
            (now, asset)
        )
    cursor.execute("DELETE FROM trade_history")
    conn.commit()
    conn.close()
    print(f"[DB] Portfolio reset to ₹{INITIAL_INR_BALANCE:,.2f} with zero holdings")
