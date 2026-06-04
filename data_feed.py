# ============================================================
#  DEGEN-BOT — Data Feed  (Binance public API, no auth)
# ============================================================
import requests
import pandas as pd
from config import BINANCE_BASE_URL, SYMBOL, INTERVAL, MTF_INTERVAL


def _fetch(interval: str, limit: int) -> pd.DataFrame:
    resp = requests.get(
        f"{BINANCE_BASE_URL}/api/v3/klines",
        params={"symbol": SYMBOL, "interval": interval, "limit": limit},
        timeout=10
    )
    resp.raise_for_status()
    cols = ["open_time","open","high","low","close","volume",
            "close_time","quote_volume","trades",
            "taker_buy_base","taker_buy_quote","ignore"]
    df = pd.DataFrame(resp.json(), columns=cols)
    for c in ("open","high","low","close","volume"):
        df[c] = df[c].astype(float)
    return df


def get_klines(limit: int = 100) -> pd.DataFrame:
    """Candele 5m per la strategia principale."""
    return _fetch(INTERVAL, limit)


def get_klines_1h(limit: int = 60) -> pd.DataFrame:
    """Candele 1H per il filtro multi-timeframe (60 ore = 2.5 giorni)."""
    return _fetch(MTF_INTERVAL, limit)


def get_current_price() -> float:
    resp = requests.get(
        f"{BINANCE_BASE_URL}/api/v3/ticker/price",
        params={"symbol": SYMBOL},
        timeout=10
    )
    resp.raise_for_status()
    return float(resp.json()["price"])
