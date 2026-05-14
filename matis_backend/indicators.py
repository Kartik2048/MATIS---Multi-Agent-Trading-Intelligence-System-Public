# indicators.py — Local Technical Indicators via Binance + Pure Pandas/NumPy
# No pandas-ta or numba required — all indicators implemented directly.
import requests
import pandas as pd
import numpy as np


# Map our internal asset names to Binance trading pairs
BINANCE_PAIRS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "XRP": "XRPUSDT",
    "BNB": "BNBUSDT",
    "LINK": "LINKUSDT",
}

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER_24H_URL = "https://api.binance.com/api/v3/ticker/24hr"


def fetch_klines(asset: str, interval: str = "5m", limit: int = 100) -> pd.DataFrame:
    """
    Fetch candlestick data from the Binance public API.
    Returns a DataFrame with columns: open, high, low, close, volume.
    """
    symbol = BINANCE_PAIRS.get(asset, f"{asset}USDT")

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    resp = requests.get(BINANCE_KLINES_URL, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore"
    ])

    # Convert to numeric
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df.set_index("open_time", inplace=True)

    return df[["open", "high", "low", "close", "volume"]]


# ===================================================================
#  Pure Pandas/NumPy Indicator Implementations
# ===================================================================

def _rsi(series: pd.Series, length: int = 14) -> float:
    """Wilder's RSI."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/length, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1/length, min_periods=length).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def _bollinger_bands(series: pd.Series, length: int = 20, std_dev: float = 2.0) -> tuple:
    """Returns (lower, mid, upper)."""
    mid = series.rolling(window=length).mean()
    std = series.rolling(window=length).std()
    upper = mid + (std * std_dev)
    lower = mid - (std * std_dev)
    return float(lower.iloc[-1]), float(mid.iloc[-1]), float(upper.iloc[-1])


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> float:
    """Average True Range."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/length, min_periods=length).mean()
    return float(atr.iloc[-1])


def _ema(series: pd.Series, length: int) -> float:
    """Exponential Moving Average."""
    return float(series.ewm(span=length, adjust=False).mean().iloc[-1])


def _rvol(volume_series: pd.Series, current_window: int = 12, avg_window: int = 288) -> float:
    """
    Relative Volume (RVOL).
    With 5-min candles: current_window=12 → last 1 hour of volume,
    avg_window=288 → 24-hour moving average volume.
    Formula: sum of last 1h volume / rolling 24h average hourly volume.
    """
    if len(volume_series) < avg_window:
        # Not enough data for full 24h average; fallback to available data
        avg_window = len(volume_series)

    current_vol = volume_series.iloc[-current_window:].sum()

    # Rolling 24h total volume, then divide by number of hourly windows
    total_24h_vol = volume_series.iloc[-avg_window:].sum()
    num_hourly_windows = avg_window / current_window
    avg_hourly_vol = total_24h_vol / num_hourly_windows if num_hourly_windows > 0 else 1.0

    if avg_hourly_vol <= 0:
        return 1.0

    return current_vol / avg_hourly_vol


def fetch_btc_24h_change() -> float:
    """
    Fetch Bitcoin's 24-hour percentage price change from Binance.
    Returns the change as a float (e.g. 2.1 for +2.1%).
    """
    try:
        resp = requests.get(BINANCE_TICKER_24H_URL, params={"symbol": "BTCUSDT"}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("priceChangePercent", 0.0))
    except Exception as e:
        print(f"⚠️ Failed to fetch BTC 24h change: {e}")
        return 0.0


# ===================================================================
#  Main Entry Point — Raw Indicator Calculation
# ===================================================================

def calculate_indicators(asset: str) -> dict:
    """
    Fetch klines and compute all technical indicators.
    Returns a flat dictionary ready for injection into AgentState.market_data.
    MACD has been removed (pruned) — we keep RSI, BBands, ATR, EMA 9/21, and RVOL.
    """
    try:
        # Fetch 300 candles (5-min) to have enough for 24h RVOL calculation
        df = fetch_klines(asset, interval="5m", limit=300)
    except Exception as e:
        print(f"⚠️ Binance kline fetch failed for {asset}: {e}")
        return {"error": str(e), "price": 0.0}

    close = df["close"]
    current_price = float(close.iloc[-1])

    # --- RSI ---
    rsi = _rsi(close, 14)

    # --- Bollinger Bands ---
    bb_lower, bb_mid, bb_upper = _bollinger_bands(close, 20, 2.0)

    # --- ATR ---
    atr = _atr(df["high"], df["low"], close, 14)

    # --- EMAs ---
    ema_9 = _ema(close, 9)
    ema_21 = _ema(close, 21)

    # --- Relative Volume (RVOL) ---
    rvol = _rvol(df["volume"], current_window=12, avg_window=288)

    # --- BTC 24h change (for macro gravity) ---
    btc_24h_change = fetch_btc_24h_change()

    return {
        "price": current_price,
        "rsi": round(rsi, 2),
        "bb_upper": round(bb_upper, 2),
        "bb_mid": round(bb_mid, 2),
        "bb_lower": round(bb_lower, 2),
        "atr": round(atr, 4),
        "ema_9": round(ema_9, 2),
        "ema_21": round(ema_21, 2),
        "rvol": round(rvol, 2),
        "btc_24h_change": round(btc_24h_change, 2),
    }


# ===================================================================
#  Semantic Translation Layer
# ===================================================================

def translate_macro_context(asset: str, btc_24h_change: float) -> str:
    """
    Build a dynamic macro context string.
    - For altcoins: BTC acts as "Macro Gravity"
    - For BTC itself: it's the overarching market baseline
    """
    direction = "Bullish" if btc_24h_change >= 0 else "Bearish"
    sign = "+" if btc_24h_change >= 0 else ""

    if asset == "BTC":
        return f"Overall Market Benchmark: {sign}{btc_24h_change}% ({direction} Crypto Environment)"
    else:
        return f"Broad Market Trend (BTC): {sign}{btc_24h_change}% ({direction} Market Gravity)"


def translate_trend(price: float, ema_9: float, ema_21: float) -> str:
    """Describe price position relative to EMA 9 and EMA 21."""
    above_9 = price > ema_9
    above_21 = price > ema_21

    if above_9 and above_21:
        return f"Price (${price:,.2f}) is trading ABOVE the 9 EMA (${ema_9:,.2f}) and 21 EMA (${ema_21:,.2f}) (Uptrend)"
    elif not above_9 and not above_21:
        return f"Price (${price:,.2f}) is trading BELOW the 9 EMA (${ema_9:,.2f}) and 21 EMA (${ema_21:,.2f}) (Downtrend)"
    elif above_21 and not above_9:
        return f"Price (${price:,.2f}) is ABOVE the 21 EMA (${ema_21:,.2f}) but BELOW the 9 EMA (${ema_9:,.2f}) (Weakening / Pullback)"
    else:
        return f"Price (${price:,.2f}) is ABOVE the 9 EMA (${ema_9:,.2f}) but BELOW the 21 EMA (${ema_21:,.2f}) (Potential Reversal)"


def translate_momentum(rsi: float) -> str:
    """Describe RSI with semantic context."""
    if rsi >= 80:
        label = "Extremely Overbought"
    elif rsi >= 70:
        label = "Overbought"
    elif rsi >= 60:
        label = "Mildly Bullish"
    elif rsi >= 40:
        label = "Neutral"
    elif rsi >= 30:
        label = "Mildly Bearish"
    elif rsi >= 20:
        label = "Oversold"
    else:
        label = "Extremely Oversold"

    return f"RSI is {rsi} ({label})"


def translate_volatility(price: float, bb_upper: float, bb_mid: float, bb_lower: float, atr: float) -> str:
    """Describe price vs. Bollinger Bands + ATR stop-loss recommendation."""
    # Determine band position
    bb_range = bb_upper - bb_lower
    if bb_range <= 0:
        band_pos = "within"
    else:
        pct_in_band = (price - bb_lower) / bb_range

        if pct_in_band >= 0.95:
            band_pos = "testing the Upper Bollinger Band"
        elif pct_in_band >= 0.75:
            band_pos = "in the upper zone of the Bollinger Bands"
        elif pct_in_band <= 0.05:
            band_pos = "testing the Lower Bollinger Band"
        elif pct_in_band <= 0.25:
            band_pos = "in the lower zone of the Bollinger Bands"
        else:
            band_pos = "near the middle of the Bollinger Bands"

    return (
        f"Price is {band_pos} "
        f"(Upper: ${bb_upper:,.2f}, Mid: ${bb_mid:,.2f}, Lower: ${bb_lower:,.2f}). "
        f"Current ATR is ${atr:,.2f}; recommend setting stop-loss at least this wide."
    )


def translate_volume(rvol: float) -> str:
    """Describe relative volume."""
    if rvol >= 3.0:
        label = "Extremely high participation"
    elif rvol >= 2.0:
        label = "Strong participation"
    elif rvol >= 1.5:
        label = "Above-average participation"
    elif rvol >= 0.8:
        label = "Average participation"
    elif rvol >= 0.5:
        label = "Below-average participation"
    else:
        label = "Very low participation"

    return f"Relative Volume is {rvol}x vs. average ({label})"


def build_semantic_payload(asset: str, market_data: dict, sentiment_score: float) -> dict:
    """
    Master function: takes raw market_data dict and produces the semantic
    payload structure for the LLM Decision/Critic agents.

    Output format:
    {
        "asset": "BTC",
        "macro_context": "...",
        "news_sentiment": "...",
        "technical_state": {
            "trend": "...",
            "momentum": "...",
            "volatility": "...",
            "volume": "..."
        }
    }
    """
    price = market_data.get("price", 0.0)
    rsi = market_data.get("rsi", 50.0)
    bb_upper = market_data.get("bb_upper", 0.0)
    bb_mid = market_data.get("bb_mid", 0.0)
    bb_lower = market_data.get("bb_lower", 0.0)
    atr = market_data.get("atr", 0.0)
    ema_9 = market_data.get("ema_9", 0.0)
    ema_21 = market_data.get("ema_21", 0.0)
    rvol = market_data.get("rvol", 1.0)
    btc_24h_change = market_data.get("btc_24h_change", 0.0)

    # Sentiment label
    if sentiment_score >= 0.7:
        sent_label = "Bullish"
    elif sentiment_score >= 0.55:
        sent_label = "Mildly Bullish"
    elif sentiment_score >= 0.45:
        sent_label = "Neutral"
    elif sentiment_score >= 0.3:
        sent_label = "Mildly Bearish"
    else:
        sent_label = "Bearish"

    return {
        "asset": asset,
        "macro_context": translate_macro_context(asset, btc_24h_change),
        "news_sentiment": f"Sentiment Score: {sentiment_score:.2f} ({sent_label})",
        "technical_state": {
            "trend": translate_trend(price, ema_9, ema_21),
            "momentum": translate_momentum(rsi),
            "volatility": translate_volatility(price, bb_upper, bb_mid, bb_lower, atr),
            "volume": translate_volume(rvol),
        }
    }
