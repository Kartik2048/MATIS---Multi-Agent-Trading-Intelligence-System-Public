import pytest
from unittest.mock import patch
import main


def test_telegram_suppresses_hold_action(monkeypatch):
    """Verify send_telegram_alert strictly does NOT send alerts when action is HOLD."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:FAKE_TOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999999")

    trade_hold = {
        "asset": "BTC",
        "action": "HOLD",
        "status": "HOLD",
        "execution_price_inr": 8_000_000.0,
        "confidence": 55,
        "reasoning": "Consolidation phase"
    }

    with patch("httpx.post") as mock_post:
        main.send_telegram_alert(trade_hold)
        mock_post.assert_not_called()


def test_telegram_suppresses_hold_status(monkeypatch):
    """Verify alert is suppressed even if action was BUY but status became HOLD (forced by risk manager)."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:FAKE_TOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999999")

    trade_forced_hold = {
        "asset": "ETH",
        "action": "BUY",
        "status": "HOLD",
        "execution_price_inr": 250_000.0,
        "confidence": 52,
        "reasoning": "Confidence < dynamic threshold"
    }

    with patch("httpx.post") as mock_post:
        main.send_telegram_alert(trade_forced_hold)
        mock_post.assert_not_called()


def test_telegram_sends_on_buy(monkeypatch):
    """Verify Telegram alert is dispatched when actionable BUY occurs."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:FAKE_TOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999999")

    trade_buy = {
        "asset": "BTC",
        "action": "BUY",
        "status": "EXECUTED",
        "execution_price_inr": 8_000_000.0,
        "trade_value_inr": 1500.0,
        "confidence": 85,
        "news_sentiment": 0.75,
        "reasoning": "Strong momentum breakdown above EMA"
    }

    with patch("httpx.post") as mock_post:
        main.send_telegram_alert(trade_buy)
        assert mock_post.called
        call_url = mock_post.call_args[0][0]
        call_json = mock_post.call_args[1]["json"]
        assert "123456:FAKE_TOKEN" in call_url
        assert call_json["chat_id"] == "999999"
        assert "BUY BTC" in call_json["text"]
        assert "✅ EXECUTED" in call_json["text"]


def test_telegram_sends_on_sell(monkeypatch):
    """Verify Telegram alert is dispatched when actionable SELL occurs."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:FAKE_TOKEN")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999999")

    trade_sell = {
        "asset": "SOL",
        "action": "SELL",
        "status": "EXECUTED",
        "execution_price_inr": 12_000.0,
        "trade_value_inr": 1200.0,
        "confidence": 80,
        "news_sentiment": 0.40,
        "reasoning": "RSI overbought, taking profits"
    }

    with patch("httpx.post") as mock_post:
        main.send_telegram_alert(trade_sell)
        assert mock_post.called
        call_json = mock_post.call_args[1]["json"]
        assert "SELL SOL" in call_json["text"]


def test_telegram_no_credentials(monkeypatch):
    """Verify safe early exit when Telegram env keys are absent."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with patch("httpx.post") as mock_post:
        main.send_telegram_alert({"action": "BUY", "status": "EXECUTED"})
        mock_post.assert_not_called()

