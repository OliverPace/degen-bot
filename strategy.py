# ============================================================
#  DEGEN-BOT — Strategy
#
#  Segnale finale = RSI + SMA crossover
#                 + filtro volume (evita segnali in mercato morto)
#                 + conferma trend 1H (non tradare contro trend)
# ============================================================
import pandas as pd
from config import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    SMA_FAST, SMA_SLOW,
    VOLUME_FILTER, VOLUME_PERIOD, VOLUME_MIN_RATIO,
    MTF_ENABLED, MTF_FAST, MTF_SLOW,
)


# ── Indicatori ───────────────────────────────────────────────

def _rsi(s: pd.Series, p: int) -> pd.Series:
    d    = s.diff()
    gain = d.clip(lower=0).rolling(p).mean()
    loss = (-d.clip(upper=0)).rolling(p).mean()
    rs   = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))

def _sma(s: pd.Series, p: int) -> pd.Series:
    return s.rolling(p).mean()


# ── Trend 1H ─────────────────────────────────────────────────

def get_trend_1h(df_1h: pd.DataFrame) -> str:
    """
    Restituisce 'UP', 'DOWN' o 'NEUTRAL'.
    UP   = SMA20 > SMA50 su timeframe orario
    DOWN = SMA20 < SMA50
    """
    if df_1h is None or len(df_1h) < MTF_SLOW:
        return "NEUTRAL"
    closes   = df_1h["close"]
    sma_fast = _sma(closes, MTF_FAST).iloc[-1]
    sma_slow = _sma(closes, MTF_SLOW).iloc[-1]
    if pd.isna(sma_fast) or pd.isna(sma_slow):
        return "NEUTRAL"
    return "UP" if sma_fast > sma_slow else "DOWN"


# ── Segnale principale ────────────────────────────────────────

def get_signal(df: pd.DataFrame, df_1h: pd.DataFrame = None) -> dict:
    """
    Analizza le candele e restituisce un dizionario con:
      signal      : 'BUY' | 'SELL' | 'HOLD'
      rsi         : float
      sma_fast    : float
      sma_slow    : float
      volume_ok   : bool
      trend_1h    : 'UP' | 'DOWN' | 'NEUTRAL'
      blocked_by  : motivo per cui un segnale valido è stato filtrato (o '')

    Logica:
      1. Calcola RSI e SMA → segnale base
      2. Filtro volume → annulla se volume < soglia
      3. Filtro MTF    → annulla se trade va contro trend 1H
    """
    closes  = df["close"]
    volumes = df["volume"]

    rsi      = _rsi(closes, RSI_PERIOD)
    smaf     = _sma(closes, SMA_FAST)
    smas     = _sma(closes, SMA_SLOW)

    cur_rsi  = rsi.iloc[-1]
    cur_fast = smaf.iloc[-1]
    cur_slow = smas.iloc[-1]

    # ── 1. Segnale base ──
    if cur_rsi < RSI_OVERSOLD and cur_fast > cur_slow:
        base = "BUY"
    elif cur_rsi > RSI_OVERBOUGHT and cur_fast < cur_slow:
        base = "SELL"
    else:
        base = "HOLD"

    signal     = base
    blocked_by = ""

    # ── 2. Filtro volume ──
    volume_ok = True
    if VOLUME_FILTER and base != "HOLD":
        vol_avg = volumes.rolling(VOLUME_PERIOD).mean().iloc[-1]
        vol_cur = volumes.iloc[-1]
        volume_ok = (not pd.isna(vol_avg)) and (vol_cur >= vol_avg * VOLUME_MIN_RATIO)
        if not volume_ok:
            signal     = "HOLD"
            blocked_by = "LOW_VOLUME"

    # ── 3. Filtro multi-timeframe ──
    trend_1h = get_trend_1h(df_1h)
    if MTF_ENABLED and signal != "HOLD":
        if signal == "BUY"  and trend_1h == "DOWN":
            signal     = "HOLD"
            blocked_by = "MTF_BEARISH"
        elif signal == "SELL" and trend_1h == "UP":
            signal     = "HOLD"
            blocked_by = "MTF_BULLISH"

    return {
        "signal":     signal,
        "rsi":        cur_rsi,
        "sma_fast":   cur_fast,
        "sma_slow":   cur_slow,
        "volume_ok":  volume_ok,
        "trend_1h":   trend_1h,
        "blocked_by": blocked_by,
    }
