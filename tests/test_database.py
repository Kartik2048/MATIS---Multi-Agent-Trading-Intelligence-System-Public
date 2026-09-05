import pytest
import sqlite3
from datetime import datetime, timezone
import database


def test_initial_portfolio_state():
    """Verify fresh database initializes with 10,000 INR and 0 holdings."""
    portfolio = database.get_portfolio()
    assert portfolio["inr_balance"] == 10_000.0
    for asset in database.SUPPORTED_ASSETS:
        assert portfolio["holdings"][asset] == 0.0
        assert database.get_asset_balance(asset) == 0.0


def test_buy_trade_execution():
    """Verify BUY trade reduces cash, increases coin balance, and computes cost basis."""
    res = database.execute_trade(
        asset="BTC",
        action="BUY",
        amount=0.001,
        price=5_000_000.0,  # 5,000 INR total value
        confidence=85,
        reasoning="Bullish momentum",
        fee_inr=29.50,
    )
    assert res["success"] is True
    assert res["new_inr_balance"] == pytest.approx(10_000.0 - 5_000.0 - 29.50, rel=1e-3)
    assert res["new_asset_balance"] == pytest.approx(0.001, rel=1e-6)

    # Cost basis check
    basis = database.get_asset_cost_basis("BTC")
    assert basis["avg_entry_price"] == pytest.approx(5_000_000.0, rel=1e-3)


def test_buy_insufficient_funds():
    """Verify BUY fails if cost exceeds available INR balance."""
    res = database.execute_trade(
        asset="BTC",
        action="BUY",
        amount=1.0,
        price=20_000_000.0,  # Far exceeds 10,000 INR
        confidence=90,
        reasoning="Way too big",
        fee_inr=118.0,
    )
    assert res["success"] is False
    assert "Insufficient INR" in res["message"]


def test_sell_trade_execution_and_realized_profit():
    """Verify SELL trade calculates realized profit and updates cash correctly."""
    # First buy 0.001 BTC at 5,000,000
    database.execute_trade("BTC", "BUY", 0.001, 5_000_000.0, 80, "Buy dip", 29.50)

    # Sell half (0.0005 BTC) at 6,000,000 (Gain: (6M - 5M) * 0.0005 - 17.70 fee = 500 - 17.70 = 482.30)
    res = database.execute_trade(
        asset="BTC",
        action="SELL",
        amount=0.0005,
        price=6_000_000.0,
        confidence=75,
        reasoning="Take profit",
        fee_inr=17.70,
    )
    assert res["success"] is True
    expected_profit = ((6_000_000.0 - 5_000_000.0) * 0.0005) - 17.70
    assert res["realized_profit"] == pytest.approx(expected_profit, rel=1e-2)
    assert res["new_asset_balance"] == pytest.approx(0.0005, rel=1e-6)


def test_sell_insufficient_asset():
    """Verify SELL fails if trying to sell more than held."""
    res = database.execute_trade(
        asset="ETH",
        action="SELL",
        amount=0.5,
        price=250_000.0,
        confidence=60,
        reasoning="Sell empty bag",
        fee_inr=10.0,
    )
    assert res["success"] is False
    assert "Insufficient ETH" in res["message"]


def test_trade_count_filters_out_hold():
    """
    CRITICAL REQUIREMENT:
    Verify get_executed_trades_count strictly counts BUY and SELL,
    and does NOT increment on HOLD.
    """
    assert database.get_executed_trades_count() == 0

    # 1. Execute BUY -> count = 1
    database.execute_trade("SOL", "BUY", 0.1, 10_000.0, 80, "Buy SOL", 5.90)
    assert database.get_executed_trades_count() == 1
    assert database.get_executed_trades_count("SOL") == 1
    assert database.get_executed_trades_count("ETH") == 0

    # 2. Insert HOLD record directly into trade_history
    conn = database.get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO trade_history
           (timestamp, asset, action, amount, execution_price, total_value_inr, fee_inr, confidence, reasoning, realized_profit)
           VALUES (?, 'SOL', 'HOLD', 0, 10000.0, 0, 0.0, 50, 'Neutral sentiment', 0.0)""",
        (now,)
    )
    conn.commit()
    conn.close()

    # Verify: executed trade count is STILL 1
    assert database.get_executed_trades_count() == 1
    assert database.get_executed_trades_count("SOL") == 1

    # But full trade history contains both 2 records
    history = database.get_trade_history()
    assert len(history) == 2

    # 3. Execute SELL -> count = 2
    database.execute_trade("SOL", "SELL", 0.05, 12_000.0, 70, "Sell partial", 3.54)
    assert database.get_executed_trades_count() == 2
    assert database.get_executed_trades_count("SOL") == 2


def test_reset_portfolio():
    """Verify reset_portfolio wipes all trades and resets balances."""
    database.execute_trade("ETH", "BUY", 0.01, 250_000.0, 80, "Buy ETH", 14.75)
    assert database.get_executed_trades_count() == 1

    database.reset_portfolio()

    portfolio = database.get_portfolio()
    assert portfolio["inr_balance"] == 10_000.0
    assert portfolio["holdings"]["ETH"] == 0.0
    assert database.get_executed_trades_count() == 0
    assert len(database.get_trade_history()) == 0
