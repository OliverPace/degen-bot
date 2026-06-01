# ============================================================
#  DEGEN-BOT — Data Feed  (Binance public API, no auth)
# ============================================================
import requests
import pandas as pd
from config import BINANCE_BASE_URL, SYMBOL, INTERVAL


def get_klines(limit: int = 100) -> pd.DataFrame:
    """Fetch recent OHLCV candles from Binance."""
    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    resp = requests.get(url, params={"symbol": SYMBOL, "interval": INTERVAL, "limit": limit}, timeout=10)
    resp.raise_for_status()

    cols = ["open_time","open","high","low","close","volume",
            "close_time","quote_volume","trades",
            "taker_buy_base","taker_buy_quote","ignore"]
    df = pd.DataFrame(resp.json(), columns=cols)

    for col in ("open","high","low","close","volume"):
        df[col] = df[col].astype(float)

    return df


def get_current_price() -> float:
    """Return the latest BTC/USDT spot price."""
    url = f"{BINANCE_BASE_URL}/api/v3/ticker/price"
    resp = requests.get(url, params={"symbol": SYMBOL}, timeout=10)
    resp.raise_for_status()
    return float(resp.json()["price"])
