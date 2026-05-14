# backfill_avg_price.py — One-time migration to compute avg_entry_price
# and realized_profit from existing trade history.
#
# This replays every BUY/SELL in chronological order per asset,
# computing the rolling average cost basis and realized P&L exactly
# as the live system would, then writes the corrected values back.
#
# Safe to run multiple times — it recomputes from scratch each run.

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "matis_paper_trading.db")

def backfill():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all distinct assets that have trades
    assets = [r["asset"] for r in cursor.execute(
        "SELECT DISTINCT asset FROM trade_history"
    ).fetchall()]

    print(f"[BACKFILL] Found assets with trade history: {assets}")

    for asset in assets:
        # Fetch all trades for this asset in chronological order
        trades = cursor.execute(
            "SELECT id, action, amount, execution_price FROM trade_history WHERE asset = ? ORDER BY id ASC",
            (asset,)
        ).fetchall()

        balance = 0.0
        avg_price = 0.0
        total_realized = 0.0

        print(f"\n{'='*50}")
        print(f"  Replaying {len(trades)} trades for {asset}")
        print(f"{'='*50}")

        for t in trades:
            tid = t["id"]
            action = t["action"]
            amount = t["amount"]
            price = t["execution_price"]

            if action == "BUY" and amount > 0:
                # Rolling average cost basis
                new_balance = balance + amount
                if balance <= 0:
                    avg_price = price
                else:
                    avg_price = ((balance * avg_price) + (amount * price)) / new_balance
                balance = new_balance

                # BUY trades always have 0 realized profit
                cursor.execute(
                    "UPDATE trade_history SET realized_profit = 0.0 WHERE id = ?",
                    (tid,)
                )
                print(f"  BUY  #{tid}: +{amount:.6f} @ ${price:,.2f} -> bal={balance:.6f}, avg=${avg_price:,.2f}")

            elif action == "SELL" and amount > 0:
                # Realized P&L
                realized = (price - avg_price) * amount
                total_realized += realized
                balance -= amount

                # Reset avg if position fully closed
                if balance < 1e-12:
                    balance = 0.0
                    avg_price = 0.0

                cursor.execute(
                    "UPDATE trade_history SET realized_profit = ? WHERE id = ?",
                    (realized, tid)
                )
                print(f"  SELL #{tid}: -{amount:.6f} @ ${price:,.2f} -> realized=${realized:+,.2f}, bal={balance:.6f}, avg=${avg_price:,.2f}")

            else:
                # HOLD or zero-amount — no effect on cost basis
                cursor.execute(
                    "UPDATE trade_history SET realized_profit = 0.0 WHERE id = ?",
                    (tid,)
                )

        # Write the final avg_entry_price back to holdings
        cursor.execute(
            "UPDATE holdings SET avg_entry_price = ? WHERE asset = ?",
            (avg_price, asset)
        )

        print(f"\n  [OK] {asset} final: balance={balance:.6f}, avg_entry_price=${avg_price:,.2f}, total_realized=${total_realized:+,.2f}")

    conn.commit()
    conn.close()
    print(f"\n[BACKFILL] Done. All avg_entry_price and realized_profit values updated.")


if __name__ == "__main__":
    backfill()
