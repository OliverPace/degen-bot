# ============================================================
#  DEGEN-BOT — Paper Trading Engine
# ============================================================
import json
import os
from datetime import datetime
from config import INITIAL_BALANCE, STOP_LOSS_PCT, TAKE_PROFIT_PCT, TRADE_SIZE_PCT

STATE_FILE = "degen_state.json"


class PaperTrader:
    def __init__(self):
        self.balance   = INITIAL_BALANCE
        self.position  = None   # dict when open, None when flat
        self.trades    = []
        self.total_pnl = 0.0
        self.wins      = 0
        self.losses    = 0
        self._load()

    # ----------------------------------------------------------
    #  Persistence
    # ----------------------------------------------------------
    def _load(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    s = json.load(f)
                self.balance   = s.get("balance",   INITIAL_BALANCE)
                self.position  = s.get("position",  None)
                self.trades    = s.get("trades",    [])
                self.total_pnl = s.get("total_pnl", 0.0)
                self.wins      = s.get("wins",      0)
                self.losses    = s.get("losses",    0)
            except Exception:
                pass  # file corrotto → riparte da zero

    def _save(self):
        state = {
            "balance":   self.balance,
            "position":  self.position,
            "trades":    self.trades[-100:],   # ultimi 100
            "total_pnl": self.total_pnl,
            "wins":      self.wins,
            "losses":    self.losses,
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    # ----------------------------------------------------------
    #  Trade management
    # ----------------------------------------------------------
    def open_position(self, price: float, direction: str) -> bool:
        """Apre una nuova posizione. Ritorna False se già aperta."""
        if self.position is not None:
            return False

        trade_value = self.balance * TRADE_SIZE_PCT
        if trade_value < 1:
            return False   # balance troppo basso

        size = trade_value / price  # quantità BTC

        if direction == "BUY":
            sl = price * (1 - STOP_LOSS_PCT)
            tp = price * (1 + TAKE_PROFIT_PCT)
        else:  # SELL (short simulato)
            sl = price * (1 + STOP_LOSS_PCT)
            tp = price * (1 - TAKE_PROFIT_PCT)

        self.position = {
            "direction":   direction,
            "entry_price": price,
            "size":        size,
            "stop_loss":   sl,
            "take_profit": tp,
            "opened_at":   datetime.now().isoformat(),
        }
        self.balance -= trade_value
        self._save()
        return True

    def check_exit(self, price: float) -> dict | None:
        """Controlla SL/TP e chiude la posizione se necessario."""
        if self.position is None:
            return None

        p   = self.position
        hit = None

        if p["direction"] == "BUY":
            if price <= p["stop_loss"]:
                hit = "STOP_LOSS"
            elif price >= p["take_profit"]:
                hit = "TAKE_PROFIT"
        else:
            if price >= p["stop_loss"]:
                hit = "STOP_LOSS"
            elif price <= p["take_profit"]:
                hit = "TAKE_PROFIT"

        if hit:
            return self._close(price, hit)
        return None

    def _close(self, price: float, reason: str) -> dict:
        p = self.position

        if p["direction"] == "BUY":
            pnl = (price - p["entry_price"]) * p["size"]
        else:
            pnl = (p["entry_price"] - price) * p["size"]

        pnl_pct = pnl / (p["entry_price"] * p["size"]) * 100
        self.balance   += p["entry_price"] * p["size"] + pnl
        self.total_pnl += pnl

        if pnl >= 0:
            self.wins += 1
        else:
            self.losses += 1

        trade = {
            "direction":   p["direction"],
            "entry_price": round(p["entry_price"], 2),
            "exit_price":  round(price, 2),
            "pnl":         round(pnl, 4),
            "pnl_pct":     round(pnl_pct, 2),
            "reason":      reason,
            "opened_at":   p["opened_at"],
            "closed_at":   datetime.now().isoformat(),
        }
        self.trades.append(trade)
        self.position = None
        self._save()
        return trade

    # ----------------------------------------------------------
    #  Helper properties
    # ----------------------------------------------------------
    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return (self.wins / total * 100) if total else 0.0

    def unrealized_pnl(self, price: float) -> float:
        if self.position is None:
            return 0.0
        p = self.position
        if p["direction"] == "BUY":
            return (price - p["entry_price"]) * p["size"]
        return (p["entry_price"] - price) * p["size"]

    def total_equity(self, price: float) -> float:
        pos_value = (self.position["entry_price"] * self.position["size"]
                     if self.position else 0.0)
        return self.balance + pos_value + self.unrealized_pnl(price)
