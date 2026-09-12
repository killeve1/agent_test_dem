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


if __name__ == "__main__":
    print(get_current_price())
    print(get_volatility())
