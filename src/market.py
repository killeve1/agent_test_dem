"""
Fetches the current price for the configured futures symbol via yfinance.
No API key required.
"""

import yfinance as yf

from config import FUTURES_SYMBOL, ATR_LOOKBACK_DAYS


def get_current_price(symbol: str = FUTURES_SYMBOL) -> dict:
    """
    Returns {"symbol": str, "price": float, "currency": str, "as_of": str}
    Falls back to the last available close if a live quote isn't ready.
    """
    ticker = yf.Ticker(symbol)

    # fast_info is cheap and usually has a live-ish price during market hours
    try:
        price = float(ticker.fast_info["last_price"])
        currency = ticker.fast_info.get("currency", "USD")
    except Exception:
        # Fallback: last daily close
        hist = ticker.history(period="5d")
        if hist.empty:
            raise RuntimeError(f"Could not fetch price for {symbol}")
        price = float(hist["Close"].iloc[-1])
        currency = "USD"

    return {
        "symbol": symbol,
        "price": round(price, 2),
        "currency": currency,
    }


def get_volatility(symbol: str = FUTURES_SYMBOL, lookback_days: int = ATR_LOOKBACK_DAYS) -> dict:
    """
    Computes Average True Range (ATR) over the given lookback window —
    a standard volatility measure used to size positions and set stop
    distances. Returns {"symbol", "atr", "lookback_days"}.

    True Range for a day = max(
        high - low,
        abs(high - previous_close),
        abs(low - previous_close)
    )
    ATR = simple moving average of True Range over the lookback window.
    """
    ticker = yf.Ticker(symbol)
    # Pull a bit more than the lookback so the rolling average has enough data
    hist = ticker.history(period=f"{lookback_days + 10}d")
    if hist.empty or len(hist) < 2:
        raise RuntimeError(f"Not enough price history for {symbol} to compute ATR")

    high = hist["High"]
    low = hist["Low"]
    prev_close = hist["Close"].shift(1)

    true_range = (high - low).combine((high - prev_close).abs(), max).combine(
        (low - prev_close).abs(), max
    )
    atr = float(true_range.dropna().tail(lookback_days).mean())

    return {
        "symbol": symbol,
        "atr": round(atr, 4),
        "lookback_days": lookback_days,
    }


PRICE_HISTORY_PERIODS = ("1d", "5d", "1mo", "3mo")
PRICE_HISTORY_INTERVALS = ("5m", "15m", "30m", "1h", "1d")


def get_price_history(symbol: str = FUTURES_SYMBOL, period: str = "1d", interval: str = "15m",
                      max_candles: int = 16) -> dict:
    """
    Fetches historical candles and trend metrics for the crude futures contract.
    Gives the agent technical context: recent trend, period high/low, and recent
    candles — e.g. whether a headline was already priced in hours ago.
    """
    if period not in PRICE_HISTORY_PERIODS:
        return {"symbol": symbol, "error": f"Unsupported period '{period}'. Use one of {PRICE_HISTORY_PERIODS}."}
    if interval not in PRICE_HISTORY_INTERVALS:
        return {"symbol": symbol, "error": f"Unsupported interval '{interval}'. Use one of {PRICE_HISTORY_INTERVALS}."}

    ticker = yf.Ticker(symbol)
    try:
        hist = ticker.history(period=period, interval=interval)
    except Exception as e:
        return {"symbol": symbol, "error": f"Failed to fetch price history: {e}"}

    if hist.empty:
        return {"symbol": symbol, "error": f"No historical price data returned for {symbol}"}

    first_close = float(hist["Close"].iloc[0])
    last_close = float(hist["Close"].iloc[-1])
    change_pct = ((last_close - first_close) / first_close) * 100.0

    candles = []
    for idx, row in hist.tail(max_candles).iterrows():
        time_str = idx.strftime("%Y-%m-%d %H:%M") if hasattr(idx, "strftime") else str(idx)
        candles.append({
            "time": time_str,
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
            "volume": int(row["Volume"]),
        })

    return {
        "symbol": symbol,
        "period": period,
        "interval": interval,
        "current_price": round(last_close, 2),
        "period_high": round(float(hist["High"].max()), 2),
        "period_low": round(float(hist["Low"].min()), 2),
        "change_pct": f"{change_pct:+.2f}%",
        "recent_candles": candles,
    }


if __name__ == "__main__":
    print(get_current_price())
    print(get_volatility())
    print(get_price_history())

