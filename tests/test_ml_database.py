import pytest
import ml_database


def test_coindcx_validation_min_trade_size():
    """Verify orders below 100 INR are rejected per CoinDCX rules."""
    # Under 100 INR
    res_under = ml_database.validate_coindcx_trade("BUY", 99.99, cash_balance_inr=1000.0)
    assert res_under["valid"] is False
    assert "below CoinDCX minimum" in res_under["message"]
    assert res_under["fee_inr"] == 0.0

    # Exactly 100 INR
    res_min = ml_database.validate_coindcx_trade("BUY", 100.0, cash_balance_inr=1000.0)
    assert res_min["valid"] is True
    expected_fee = 100.0 * 0.005 * 1.18  # 0.59 INR
    assert res_min["fee_inr"] == pytest.approx(expected_fee, rel=1e-2)


def test_coindcx_validation_insufficient_inr():
    """Verify BUY order is rejected if INR balance is insufficient for trade + fee."""
    trade_value = 500.0
    res = ml_database.validate_coindcx_trade("BUY", trade_value, cash_balance_inr=500.0)
    # Trade is 500, fee is ~2.95, total needed ~502.95 > 500 balance
    assert res["valid"] is False
    assert "Insufficient INR" in res["message"]


def test_ml_trade_logging_and_retrieval():
    """Verify ML dataset logs trade reasoning and filters accurately."""
    ml_database.log_trade(
        asset="BTC",
        action="BUY",
        confidence=88,
        allocation_pct=10.0,
        trade_value_inr=1000.0,
        entry_price=8_000_000.0,
        sentiment_score=0.75,
        market_trend="Strong Uptrend",
        llm_reasoning="EMA golden cross with 2.5x volume",
        critic_feedback="Approved",
        simulated_fee_inr=5.90,
        net_pnl_inr=0.0,
        outcome_status="EXECUTED",
    )

    ml_database.log_trade(
        asset="BTC",
        action="HOLD",
        confidence=50,
        allocation_pct=0.0,
        trade_value_inr=0.0,
        entry_price=8_000_000.0,
        sentiment_score=0.50,
        market_trend="Neutral",
        llm_reasoning="Low volume consolidation",
        critic_feedback="N/A",
        simulated_fee_inr=0.0,
        net_pnl_inr=0.0,
        outcome_status="HOLD",
    )

    logs = ml_database.get_ml_trade_logs(limit=10)
    assert len(logs) == 2

    # Test filtering by action
    buy_logs = ml_database.get_ml_trade_logs(action_filter="BUY")
    assert len(buy_logs) == 1
    assert buy_logs[0]["action"] == "BUY"
    assert buy_logs[0]["confidence"] == 88

    hold_logs = ml_database.get_ml_trade_logs(action_filter="HOLD")
    assert len(hold_logs) == 1
    assert hold_logs[0]["action"] == "HOLD"


def test_equity_curve_snapshots():
    """Verify portfolio snapshots are recorded and retrievable."""
    ml_database.log_portfolio_snapshot(total_value_inr=10_000.0, cash_balance_inr=10_000.0)
    ml_database.log_portfolio_snapshot(total_value_inr=10_500.0, cash_balance_inr=9_000.0)

    snapshots = ml_database.get_equity_history(limit=10)
    assert len(snapshots) == 2
    assert snapshots[-1]["total_value_inr"] == 10_500.0


