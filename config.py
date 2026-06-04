# ============================================================
#  DEGEN-BOT — Configuration
#  Parametri ottimizzati via grid search su 180 giorni reali
# ============================================================

# Trading pair & timeframe
SYMBOL   = "BTCUSDT"
INTERVAL = "5m"

# Paper trading starting balance (USDT)
INITIAL_BALANCE = 150.0

# ── Strategia (ottimizzata) ─────────────────────────────────
RSI_PERIOD      = 14
RSI_OVERSOLD    = 30     # BUY  when RSI < this
RSI_OVERBOUGHT  = 65     # SELL when RSI > this
SMA_FAST        = 7
SMA_SLOW        = 18

# ── Risk management ─────────────────────────────────────────
STOP_LOSS_PCT   = 0.020  # 2.0%
TAKE_PROFIT_PCT = 0.025  # 2.5%
TRADE_SIZE_PCT  = 0.95   # 95% del balance per trade

# ── Filtro volume ────────────────────────────────────────────
VOLUME_FILTER   = True
VOLUME_PERIOD   = 20
VOLUME_MIN_RATIO = 0.70  # volume corrente >= 70% della media

# ── Multi-timeframe (1H trend) ───────────────────────────────
MTF_ENABLED     = True
MTF_INTERVAL    = "1h"
MTF_FAST        = 20     # SMA veloce su 1H
MTF_SLOW        = 50     # SMA lenta  su 1H
MTF_REFRESH_MIN = 5      # aggiorna il trend ogni 5 tick (2.5 min)

# ── Trailing stop ────────────────────────────────────────────
TRAILING_ENABLED      = True
TRAILING_ACTIVATE_PCT = 0.010  # attiva dopo +1% di profitto
TRAILING_OFFSET_PCT   = 0.008  # trailing 0.8% sotto il peak

# ── Protezione rischio ───────────────────────────────────────
MAX_DAILY_LOSS_PCT   = 0.05    # ferma se -5% nel giorno
MAX_CONSEC_LOSSES    = 3       # pausa dopo 3 perdite consecutive
RECOVERY_SIZE_PCT    = 0.50    # usa 50% della size in recovery mode

# ── Binance ──────────────────────────────────────────────────
BINANCE_BASE_URL = "https://api.binance.com"

# ── Loop ─────────────────────────────────────────────────────
UPDATE_INTERVAL = 30   # secondi tra ogni tick

# ── Report giornaliero ───────────────────────────────────────
DAILY_REPORT_HOUR_UTC = 8   # invia report alle 08:00 UTC

# ── MACD ─────────────────────────────────────────────────────
MACD_FAST   = 12
MACD_SLOW   = 26
MACD_SIGNAL = 9

# ── ATR dinamico ─────────────────────────────────────────────
ATR_PERIOD   = 14
ATR_SL_MULT  = 1.5    # SL = ATR * 1.5
ATR_TP_MULT  = 2.5    # TP = ATR * 2.5
ATR_MIN_PCT  = 0.0015 # ATR/price min (mercato troppo piatto)
ATR_MAX_PCT  = 0.012  # ATR/price max (mercato troppo volatile)

# ── Filtro orario (UTC) ───────────────────────────────────────
TIME_FILTER = True
# (ora_inizio_h, ora_inizio_m, ora_fine_h, ora_fine_m) UTC
AVOID_WINDOWS_UTC = [
    (12, 20, 12, 45),  # 12:30 UTC = 8:30 ET macro USA
    (13, 20, 13, 50),  # 13:30 UTC = 9:30 ET apertura NYSE
    (18, 20, 18, 50),  # 18:30 UTC = 14:30 ET macro pomeriggio
]

# ── Funding rate (Binance Futures) ────────────────────────────
FUNDING_BULLISH_THRESHOLD = -0.0003  # < -0.03% → troppi short → BUY bias
FUNDING_BEARISH_THRESHOLD =  0.0003  # >  0.03% → troppi long  → SELL bias
FUNDING_REFRESH_TICKS     = 60       # aggiorna ogni 60 tick (~30 min)

# ── Fear & Greed Index ────────────────────────────────────────
FNG_FEAR_MAX   = 30   # <= 30 = Extreme Fear → BUY bias
FNG_GREED_MIN  = 70   # >= 70 = Extreme Greed → SELL bias
FNG_REFRESH_TICKS = 120  # aggiorna ogni 120 tick (~1 ora)

# ── Scoring ───────────────────────────────────────────────────
# Filtri HARD (tutti devono passare): volume, ATR, time, MACD
# Conferme SOFT (serve min 1 su 3): trend_1h, funding, fear&greed
MIN_SOFT_CONFIRMATIONS = 1
