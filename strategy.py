# ============================================================
#  DEGEN-BOT — Strategy  (RSI + SMA crossover)
# ============================================================
import pandas as pd
from config import RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT, SMA_FAST, SMA_SLOW


def _rsi(prices: pd.Series, period: int) -> pd.Series:
    delta = prices.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def _sma(prices: pd.Series, period: int) -> pd.Series:
    return prices.rolling(period).mean()


def get_signal(df: pd.DataFrame) -> tuple:
    """
    Analizza le candele e restituisce (signal, rsi, sma_fast, sma_slow).
    signal: 'BUY' | 'SELL' | 'HOLD'

    Regole:
      BUY  → RSI < RSI_OVERSOLD  AND sma_fast > sma_slow  (momentum verso l'alto)
      SELL → RSI > RSI_OVERBOUGHT AND sma_fast < sma_slow  (momentum verso il basso)
      HOLD → tutto il resto
    """
    closes    = df["close"]
    rsi       = _rsi(closes, RSI_PERIOD)
    sma_fast  = _sma(closes, SMA_FAST)
    sma_slow  = _sma(closes, SMA_SLOW)

    cur_rsi  = rsi.iloc[-1]
    cur_fast = sma_fast.iloc[-1]
    cur_slow = sma_slow.iloc[-1]

    if cur_rsi < RSI_OVERSOLD and cur_fast > cur_slow:
        signal = "BUY"
    elif cur_rsi > RSI_OVERBOUGHT and cur_fast < cur_slow:
        signal = "SELL"
    else:
        signal = "HOLD"

    return signal, cur_rsi, cur_fast, cur_slow
