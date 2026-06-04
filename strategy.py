# ============================================================
#  DEGEN-BOT — Strategy
#
#  Segnale finale = RSI + SMA crossover
#                 + filtro volume   (hard)
#                 + filtro ATR      (hard: volatilità nel range corretto)
#                 + filtro orario   (hard: evita finestre macro)
#                 + MACD inversione (soft: istogramma in virata)
#                 + trend 1H        (soft)
#                 + funding rate    (soft)
#                 + F&G index       (soft)
#  Serve almeno MIN_SOFT_CONFIRMATIONS conferme soft per eseguire
# ============================================================
import pandas as pd
from datetime import datetime, timezone

from config import (
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT,
    SMA_FAST, SMA_SLOW,
    VOLUME_FILTER, VOLUME_PERIOD, VOLUME_MIN_RATIO,
    MTF_ENABLED, MTF_FAST, MTF_SLOW,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    ATR_PERIOD, ATR_SL_MULT, ATR_TP_MULT, ATR_MIN_PCT, ATR_MAX_PCT,
    TIME_FILTER, AVOID_WINDOWS_UTC,
    FUNDING_BULLISH_THRESHOLD, FUNDING_BEARISH_THRESHOLD,
    FNG_FEAR_MAX, FNG_GREED_MIN,
    MIN_SOFT_CONFIRMATIONS,
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


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    hi  = df["high"]
    lo  = df["low"]
    cp  = df["close"].shift(1)
    tr  = pd.concat([(hi - lo), (hi - cp).abs(), (lo - cp).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _macd(prices: pd.Series, fast: int, slow: int, sig: int):
    ema_f  = prices.ewm(span=fast,  adjust=False).mean()
    ema_s  = prices.ewm(span=slow,  adjust=False).mean()
    line   = ema_f - ema_s
    signal = line.ewm(span=sig, adjust=False).mean()
    hist   = line - signal
    return line, signal, hist


def _time_ok(signal_direction: str) -> bool:
    """Ritorna False se siamo dentro una finestra di news/macro da evitare."""
    if not TIME_FILTER:
        return True
    now     = datetime.now(timezone.utc)
    now_min = now.hour * 60 + now.minute
    for (sh, sm, eh, em) in AVOID_WINDOWS_UTC:
        start = sh * 60 + sm
        end   = eh * 60 + em
        if start <= now_min <= end:
            return False
    return True


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

def get_signal(df: pd.DataFrame,
               df_1h: pd.DataFrame = None,
               funding_rate: float = 0.0,
               fng: dict = None) -> dict:
    """
    Analizza le candele e restituisce un dizionario con:
      signal       : 'BUY' | 'SELL' | 'HOLD'
      rsi          : float
      sma_fast     : float
      sma_slow     : float
      volume_ok    : bool
      trend_1h     : 'UP' | 'DOWN' | 'NEUTRAL'
      blocked_by   : motivo per cui un segnale valido è stato filtrato (o '')
      sl           : float  (stop-loss ATR-based, 0.0 se HOLD)
      tp           : float  (take-profit ATR-based, 0.0 se HOLD)
      atr          : float  (ATR corrente)
      macd_hist    : float
      soft_score   : int    (0-3)
      funding_rate : float
      fng_value    : int
      fng_label    : str

    Logica:
      1. Calcola RSI, SMA, MACD, ATR  → segnale base
      2. Hard filters: volume, ATR, time, MACD
      3. Soft confirmations (>= MIN_SOFT_CONFIRMATIONS): trend_1h, funding, F&G
    """
    if fng is None:
        fng = {"value": 50, "label": "Neutral"}

    closes  = df["close"]
    volumes = df["volume"]
    price   = closes.iloc[-1]

    # ── Indicatori ──
    rsi_series        = _rsi(closes, RSI_PERIOD)
    smaf_series       = _sma(closes, SMA_FAST)
    smas_series       = _sma(closes, SMA_SLOW)
    atr_series        = _atr(df, ATR_PERIOD)
    _, _, hist_series = _macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)

    cur_rsi   = rsi_series.iloc[-1]
    cur_fast  = smaf_series.iloc[-1]
    cur_slow  = smas_series.iloc[-1]
    cur_atr   = atr_series.iloc[-1]
    cur_hist  = hist_series.iloc[-1]
    prev_hist = hist_series.iloc[-2] if len(hist_series) > 1 else cur_hist
    # MACD "in inversione": istogramma si sta muovendo nella direzione giusta
    # Per BUY (mean-reversion da oversold): hist sta salendo (meno negativo o più positivo)
    # Per SELL (mean-reversion da overbought): hist sta scendendo
    macd_turning_up   = (not pd.isna(cur_hist)) and (not pd.isna(prev_hist)) and (cur_hist > prev_hist)
    macd_turning_down = (not pd.isna(cur_hist)) and (not pd.isna(prev_hist)) and (cur_hist < prev_hist)

    # ── 1. Segnale base (RSI + SMA) ──
    if cur_rsi < RSI_OVERSOLD and cur_fast > cur_slow:
        base = "BUY"
    elif cur_rsi > RSI_OVERBOUGHT and cur_fast < cur_slow:
        base = "SELL"
    else:
        base = "HOLD"

    signal     = base
    blocked_by = ""

    # Helper defaults
    sl = 0.0
    tp = 0.0

    if base == "HOLD":
        return {
            "signal":       "HOLD",
            "rsi":          cur_rsi,
            "sma_fast":     cur_fast,
            "sma_slow":     cur_slow,
            "volume_ok":    True,
            "trend_1h":     get_trend_1h(df_1h),
            "blocked_by":   "",
            "sl":           sl,
            "tp":           tp,
            "atr":          cur_atr if not pd.isna(cur_atr) else 0.0,
            "macd_hist":    cur_hist if not pd.isna(cur_hist) else 0.0,
            "soft_score":   0,
            "funding_rate": funding_rate,
            "fng_value":    fng["value"],
            "fng_label":    fng["label"],
        }

    # ── 2. Hard filters ──

    # 2a. Volume
    volume_ok = True
    if VOLUME_FILTER:
        vol_avg   = volumes.rolling(VOLUME_PERIOD).mean().iloc[-1]
        vol_cur   = volumes.iloc[-1]
        volume_ok = (not pd.isna(vol_avg)) and (vol_cur >= vol_avg * VOLUME_MIN_RATIO)
        if not volume_ok:
            signal     = "HOLD"
            blocked_by = "LOW_VOLUME"

    # 2b. ATR range filter
    if signal != "HOLD" and not pd.isna(cur_atr) and price > 0:
        atr_pct = cur_atr / price
        if atr_pct < ATR_MIN_PCT:
            signal     = "HOLD"
            blocked_by = "ATR_TOO_LOW"
        elif atr_pct > ATR_MAX_PCT:
            signal     = "HOLD"
            blocked_by = "ATR_TOO_HIGH"

    # 2c. Time filter
    if signal != "HOLD" and not _time_ok(base):
        signal     = "HOLD"
        blocked_by = "TIME_FILTER"

    # 2d. (MACD non è più hard filter — vedi soft confirmations)

    # If blocked by any hard filter, return early
    if signal == "HOLD":
        trend_1h = get_trend_1h(df_1h)
        return {
            "signal":       "HOLD",
            "rsi":          cur_rsi,
            "sma_fast":     cur_fast,
            "sma_slow":     cur_slow,
            "volume_ok":    volume_ok,
            "trend_1h":     trend_1h,
            "blocked_by":   blocked_by,
            "sl":           sl,
            "tp":           tp,
            "atr":          cur_atr if not pd.isna(cur_atr) else 0.0,
            "macd_hist":    cur_hist if not pd.isna(cur_hist) else 0.0,
            "soft_score":   0,
            "funding_rate": funding_rate,
            "fng_value":    fng["value"],
            "fng_label":    fng["label"],
        }

    # ── 3. Soft confirmations ──
    trend_1h   = get_trend_1h(df_1h)
    soft_score = 0

    # 3a. MACD in inversione (compatibile con mean-reversion)
    if base == "BUY"  and macd_turning_up:
        soft_score += 1
    elif base == "SELL" and macd_turning_down:
        soft_score += 1

    # 3b. Trend 1H
    if MTF_ENABLED:
        if base == "BUY"  and trend_1h == "UP":
            soft_score += 1
        elif base == "SELL" and trend_1h == "DOWN":
            soft_score += 1

    # 3c. Funding rate
    if base == "BUY"  and funding_rate < FUNDING_BULLISH_THRESHOLD:
        soft_score += 1
    elif base == "SELL" and funding_rate > FUNDING_BEARISH_THRESHOLD:
        soft_score += 1

    # 3d. Fear & Greed
    fng_val = fng["value"]
    if base == "BUY"  and fng_val <= FNG_FEAR_MAX:
        soft_score += 1
    elif base == "SELL" and fng_val >= FNG_GREED_MIN:
        soft_score += 1

    if soft_score < MIN_SOFT_CONFIRMATIONS:
        signal     = "HOLD"
        blocked_by = "LOW_CONFIDENCE"
        return {
            "signal":       "HOLD",
            "rsi":          cur_rsi,
            "sma_fast":     cur_fast,
            "sma_slow":     cur_slow,
            "volume_ok":    volume_ok,
            "trend_1h":     trend_1h,
            "blocked_by":   blocked_by,
            "sl":           sl,
            "tp":           tp,
            "atr":          cur_atr if not pd.isna(cur_atr) else 0.0,
            "macd_hist":    cur_hist if not pd.isna(cur_hist) else 0.0,
            "soft_score":   soft_score,
            "funding_rate": funding_rate,
            "fng_value":    fng_val,
            "fng_label":    fng["label"],
        }

    # ── 4. Segnale valido: calcola SL/TP ATR-based ──
    atr_val = cur_atr if not pd.isna(cur_atr) else 0.0
    if base == "BUY":
        sl = price - atr_val * ATR_SL_MULT
        tp = price + atr_val * ATR_TP_MULT
    else:
        sl = price + atr_val * ATR_SL_MULT
        tp = price - atr_val * ATR_TP_MULT

    return {
        "signal":       signal,
        "rsi":          cur_rsi,
        "sma_fast":     cur_fast,
        "sma_slow":     cur_slow,
        "volume_ok":    volume_ok,
        "trend_1h":     trend_1h,
        "blocked_by":   "",
        "sl":           sl,
        "tp":           tp,
        "atr":          atr_val,
        "macd_hist":    cur_hist if not pd.isna(cur_hist) else 0.0,
        "soft_score":   soft_score,
        "funding_rate": funding_rate,
        "fng_value":    fng_val,
        "fng_label":    fng["label"],
    }
