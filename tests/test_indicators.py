import pytest
import pandas as pd
import numpy as np
import indicators


@pytest.fixture
def synthetic_price_data():
    """Generate 100 periods of synthetic price and volume data."""
    np.random.seed(42)
    periods = 100
    base_price = 100.0
    returns = np.random.normal(0.001, 0.02, periods)
    prices = base_price * np.cumprod(1 + returns)

    highs = prices * (1 + np.random.uniform(0.001, 0.01, periods))
    lows = prices * (1 - np.random.uniform(0.001, 0.01, periods))
    volumes = np.random.uniform(500, 2000, periods)

    df = pd.DataFrame({
        "open": prices,
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": volumes
    })
    return df


def test_rsi_calculation(synthetic_price_data):
    """Verify RSI calculation produces a valid float between 0 and 100."""
    close = synthetic_price_data["close"]
    rsi = indicators._rsi(close, length=14)
    assert isinstance(rsi, float)
    assert 0.0 <= rsi <= 100.0


def test_bollinger_bands(synthetic_price_data):
    """Verify Bollinger Bands lower <= mid <= upper."""
    close = synthetic_price_data["close"]
    lower, mid, upper = indicators._bollinger_bands(close, length=20, std_dev=2.0)
    assert lower < mid < upper


def test_atr(synthetic_price_data):
    """Verify ATR is positive."""
    high = synthetic_price_data["high"]
    low = synthetic_price_data["low"]
    close = synthetic_price_data["close"]
    atr = indicators._atr(high, low, close, length=14)
    assert atr > 0.0


def test_ema(synthetic_price_data):
    """Verify EMA is within min and max price range."""
    close = synthetic_price_data["close"]
    ema9 = indicators._ema(close, length=9)
    ema21 = indicators._ema(close, length=21)
    assert close.min() <= ema9 <= close.max()
    assert close.min() <= ema21 <= close.max()


def test_rvol(synthetic_price_data):
    """Verify RVOL calculation is non-negative."""
    vol = synthetic_price_data["volume"]
    rvol = indicators._rvol(vol, current_window=12, avg_window=90)
    assert rvol > 0.0


def test_semantic_trend_translation():
    """Verify semantic translator produces accurate textual descriptions for trend."""
    # Strong Uptrend: Price > 9 EMA > 21 EMA
    trend = indicators.translate_trend(price=110, ema_9=105, ema_21=100)
    assert "Uptrend" in trend

    # Strong Downtrend: Price < 9 EMA < 21 EMA
    trend_down = indicators.translate_trend(price=90, ema_9=95, ema_21=100)
    assert "Downtrend" in trend_down


def test_semantic_momentum_translation():
    """Verify RSI translation categorizes regimes properly."""
    assert "Extremely Overbought" in indicators.translate_momentum(85.0)
    assert "Overbought" in indicators.translate_momentum(75.0)
    assert "Extremely Oversold" in indicators.translate_momentum(15.0)
    assert "Neutral" in indicators.translate_momentum(50.0)


def test_semantic_macro_context():
    """Verify BTC macro gravity translation."""
    assert "Bullish Market Gravity" in indicators.translate_macro_context("ETH", 2.5)
    assert "Bearish Market Gravity" in indicators.translate_macro_context("SOL", -3.0)
    assert "Overall Market Benchmark" in indicators.translate_macro_context("BTC", 1.2)


def test_build_semantic_payload():
    """Verify full semantic payload dictionary structure."""
    raw_indicators = {
        "price": 100.0,
        "rsi": 55.0,
        "bb_upper": 110.0,
        "bb_mid": 100.0,
        "bb_lower": 90.0,
        "ema_9": 102.0,
        "ema_21": 98.0,
        "atr": 2.5,
        "rvol": 1.2,
        "btc_24h_change": 1.5,
    }
    payload = indicators.build_semantic_payload("SOL", raw_indicators, sentiment_score=0.65)
    assert "SOL" in payload["asset"]
    assert "macro_context" in payload
    assert "technical_state" in payload
    assert "news_sentiment" in payload

