import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone
import database
import main


@pytest.fixture
def client(monkeypatch):
    """Create FastAPI TestClient with autonomous trading disabled."""
    monkeypatch.setenv("AUTO_TRADING", "false")
    with TestClient(main.app) as c:
        yield c


def test_root_serves_html_with_asset_column(client):
    """Verify GET / serves dashboard HTML with the dedicated Asset column and styles."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "badge-asset" in html
    assert ">Asset</th>" in html
    assert 'colspan="9"' in html


def test_portfolio_summary_endpoint(client):
    """Verify /api/portfolio_summary returns valid schema with total_trades=0 initially."""
    response = client.get("/api/portfolio_summary")
    assert response.status_code == 200
    data = response.json()
    assert data["inr_balance"] == 10_000.0
    assert data["total_portfolio_value"] == 10_000.0
    assert data["total_trades"] == 0


def test_trades_endpoint_executed_count_filter(client):
    """
    CRITICAL REQUIREMENT:
    Verify /api/trades accurately returns total count AND executed_count,
    where executed_count does not increment on HOLD.
    """
    # Initially 0
    res = client.get("/api/trades")
    assert res.status_code == 200
    assert res.json()["count"] == 0
    assert res.json()["executed_count"] == 0

    # 1. Add BUY trade
    database.execute_trade("BTC", "BUY", 0.001, 8_000_000.0, 85, "Buy BTC", 47.20)
    res_after_buy = client.get("/api/trades")
    assert res_after_buy.json()["count"] == 1
    assert res_after_buy.json()["executed_count"] == 1

    # 2. Add HOLD trade directly to trade_history
    conn = database.get_connection()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO trade_history
           (timestamp, asset, action, amount, execution_price, total_value_inr, fee_inr, confidence, reasoning, realized_profit)
           VALUES (?, 'ETH', 'HOLD', 0, 250000.0, 0, 0.0, 50, 'Market neutral', 0.0)""",
        (now,)
    )
    conn.commit()
    conn.close()

    # 3. Verify count is 2, but executed_count is STILL 1
    res_after_hold = client.get("/api/trades")
    assert res_after_hold.json()["count"] == 2
    assert res_after_hold.json()["executed_count"] == 1

    # Also verify /api/portfolio_summary reflects total_trades = 1
    res_summary = client.get("/api/portfolio_summary")
    assert res_summary.json()["total_trades"] == 1


def test_system_endpoint(client):
    """Verify /api/system reports active status and price feed info."""
    response = client.get("/api/system")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "Operational"
    assert "uptime" in data
    assert "price_feed" in data
    assert "tracked_assets" in data



def test_reset_endpoint(client):
    """Verify POST /api/reset resets portfolio and ledger."""
    # Execute a trade
    database.execute_trade("SOL", "BUY", 0.1, 10_000.0, 80, "Buy SOL", 5.90)
    assert database.get_executed_trades_count() == 1

    # Reset via API
    res = client.post("/api/reset")
    assert res.status_code == 200
    assert res.json()["status"] == "reset"

    # Verify cleared
    summary = client.get("/api/portfolio_summary").json()
    assert summary["inr_balance"] == 10_000.0
    assert summary["total_trades"] == 0

