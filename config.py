# ============================================================
#  DEGEN-BOT — Configuration
# ============================================================

# Trading pair & timeframe
SYMBOL   = "BTCUSDT"
INTERVAL = "5m"          # 5-minute candles

# Paper trading starting balance (USDT)
INITIAL_BALANCE = 150.0

# --- Strategy parameters ---
RSI_PERIOD      = 14
RSI_OVERSOLD    = 35     # BUY when RSI < this
RSI_OVERBOUGHT  = 65     # SELL when RSI > this
SMA_FAST        = 9
SMA_SLOW        = 21

# --- Risk management ---
STOP_LOSS_PCT   = 0.015  # 1.5%  stop loss
TAKE_PROFIT_PCT = 0.025  # 2.5%  take profit
TRADE_SIZE_PCT  = 0.95   # use 95% of free balance per trade

# --- Binance public REST (no API key needed for paper trading) ---
BINANCE_BASE_URL = "https://api.binance.com"

# Seconds between each bot loop tick
UPDATE_INTERVAL = 30
