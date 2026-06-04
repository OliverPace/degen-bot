# ============================================================
#  DEGEN-BOT — Paper Trading Engine
#  Trailing stop | Daily loss limit | Recovery mode
# ============================================================
import json
import os
from datetime import datetime, timezone
from config import (
    INITIAL_BALANCE, STOP_LOSS_PCT, TAKE_PROFIT_PCT, TRADE_SIZE_PCT,
    TRAILING_ENABLED, TRAILING_ACTIVATE_PCT, TRAILING_OFFSET_PCT,
    MAX_DAILY_LOSS_PCT, MAX_CONSEC_LOSSES, RECOVERY_SIZE_PCT,
)

STATE_FILE = "degen_state.json"


class PaperTrader:

    def __init__(self):
        self.balance        = INITIAL_BALANCE
        self.position       = None
        self.trades         = []
        self.total_pnl      = 0.0
        self.wins           = 0
        self.losses         = 0
        # Risk management state
        self.consec_losses  = 0      # perdite consecutive correnti
        self.paused         = False  # True = bot in pausa manuale (/stop)
        self.daily_start_eq = INITIAL_BALANCE   # equity all'inizio del giorno
        self.daily_date     = self._today()
        self.daily_stopped  = False  # True = daily loss limit raggiunto
        self._load()

    # ── Persistence ───────────────────────────────────────────

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load(self):
        if not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE) as f:
                s = json.load(f)
            self.balance        = s.get("balance",        INITIAL_BALANCE)
            self.position       = s.get("position",       None)
            self.trades         = s.get("trades",         [])
            self.total_pnl      = s.get("total_pnl",      0.0)
            self.wins           = s.get("wins",           0)
            self.losses         = s.get("losses",         0)
            self.consec_losses  = s.get("consec_losses",  0)
            self.paused         = s.get("paused",         False)
            self.daily_start_eq = s.get("daily_start_eq", INITIAL_BALANCE)
            self.daily_date     = s.get("daily_date",     self._today())
            self.daily_stopped  = s.get("daily_stopped",  False)
        except Exception:
            pass

    def _save(self):
        state = {
            "balance":        self.balance,
            "position":       self.position,
            "trades":         self.trades[-100:],
            "total_pnl":      self.total_pnl,
            "wins":           self.wins,
            "losses":         self.losses,
            "consec_losses":  self.consec_losses,
            "paused":         self.paused,
            "daily_start_eq": self.daily_start_eq,
            "daily_date":     self.daily_date,
            "daily_stopped":  self.daily_stopped,
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)

    # ── Daily reset ───────────────────────────────────────────

    def tick_day(self, current_equity: float):
        """
        Chiamato ad ogni tick. Resetta i contatori giornalieri
        se è cambiata la data UTC.
        """
        today = self._today()
        if today != self.daily_date:
            self.daily_date     = today
            self.daily_start_eq = current_equity
            self.daily_stopped  = False
            self._save()

    # ── Risk checks ───────────────────────────────────────────

    def check_daily_loss(self, current_equity: float) -> bool:
        """True se il limite di perdita giornaliera è stato superato."""
        if self.daily_start_eq <= 0:
            return False
        loss_pct = (current_equity - self.daily_start_eq) / self.daily_start_eq
        return loss_pct < -MAX_DAILY_LOSS_PCT

    def is_in_recovery(self) -> bool:
        return self.consec_losses >= MAX_CONSEC_LOSSES

    def _effective_trade_size(self) -> float:
        """Size ridotta in recovery mode."""
        if self.is_in_recovery():
            return TRADE_SIZE_PCT * RECOVERY_SIZE_PCT
        return TRADE_SIZE_PCT

    def can_trade(self) -> tuple[bool, str]:
        """
        Restituisce (True, '') se il bot può aprire nuovi trade,
        oppure (False, motivo) se è bloccato.
        """
        if self.paused:
            return False, "PAUSED"
        if self.daily_stopped:
            return False, "DAILY_LOSS_LIMIT"
        return True, ""

    # ── Trailing stop update ──────────────────────────────────

    def update_trailing(self, price: float):
        """Aggiorna il trailing stop se la posizione è in profitto sufficiente."""
        if not TRAILING_ENABLED or self.position is None:
            return

        p     = self.position
        entry = p["entry_price"]
        d     = p["direction"]

        if d == "BUY":
            profit_pct = (price - entry) / entry
            if profit_pct >= TRAILING_ACTIVATE_PCT:
                new_sl = price * (1 - TRAILING_OFFSET_PCT)
                if new_sl > p["stop_loss"]:   # il trailing sale, mai scende
                    p["stop_loss"] = new_sl
                    p["trailing_active"] = True
                    self._save()
        else:  # SELL
            profit_pct = (entry - price) / entry
            if profit_pct >= TRAILING_ACTIVATE_PCT:
                new_sl = price * (1 + TRAILING_OFFSET_PCT)
                if new_sl < p["stop_loss"]:   # il trailing scende, mai sale
                    p["stop_loss"] = new_sl
                    p["trailing_active"] = True
                    self._save()

    # ── Trade management ──────────────────────────────────────

    def open_position(self, price: float, direction: str) -> bool:
        if self.position is not None:
            return False
        ok, _ = self.can_trade()
        if not ok:
            return False

        size_pct  = self._effective_trade_size()
        trade_val = self.balance * size_pct
        if trade_val < 1:
            return False

        size = trade_val / price

        if direction == "BUY":
            sl = price * (1 - STOP_LOSS_PCT)
            tp = price * (1 + TAKE_PROFIT_PCT)
        else:
            sl = price * (1 + STOP_LOSS_PCT)
            tp = price * (1 - TAKE_PROFIT_PCT)

        self.position = {
            "direction":       direction,
            "entry_price":     price,
            "size":            size,
            "stop_loss":       sl,
            "take_profit":     tp,
            "trailing_active": False,
            "opened_at":       datetime.now(timezone.utc).isoformat(),
            "recovery_mode":   self.is_in_recovery(),
        }
        self.balance -= trade_val
        self._save()
        return True

    def check_exit(self, price: float) -> dict | None:
        if self.position is None:
            return None

        p  = self.position
        d  = p["direction"]
        sl = p["stop_loss"]
        tp = p["take_profit"]

        if d == "BUY":
            if price <= sl:  hit = "STOP_LOSS"
            elif price >= tp: hit = "TAKE_PROFIT"
            else:             return None
        else:
            if price >= sl:  hit = "STOP_LOSS"
            elif price <= tp: hit = "TAKE_PROFIT"
            else:             return None

        return self._close(price, hit)

    def _close(self, price: float, reason: str) -> dict:
        p = self.position

        if p["direction"] == "BUY":
            pnl = (price - p["entry_price"]) * p["size"]
        else:
            pnl = (p["entry_price"] - price) * p["size"]

        pnl_pct        = pnl / (p["entry_price"] * p["size"]) * 100
        self.balance  += p["entry_price"] * p["size"] + pnl
        self.total_pnl += pnl

        if pnl >= 0:
            self.wins         += 1
            self.consec_losses = 0
        else:
            self.losses        += 1
            self.consec_losses += 1

        trade = {
            "direction":       p["direction"],
            "entry_price":     round(p["entry_price"], 2),
            "exit_price":      round(price, 2),
            "pnl":             round(pnl, 4),
            "pnl_pct":         round(pnl_pct, 2),
            "reason":          reason,
            "trailing_active": p.get("trailing_active", False),
            "recovery_mode":   p.get("recovery_mode", False),
            "opened_at":       p["opened_at"],
            "closed_at":       datetime.now(timezone.utc).isoformat(),
        }
        self.trades.append(trade)
        self.position = None
        self._save()
        return trade

    # ── Helpers ───────────────────────────────────────────────

    @property
    def win_rate(self) -> float:
        t = self.wins + self.losses
        return (self.wins / t * 100) if t else 0.0

    def unrealized_pnl(self, price: float) -> float:
        if self.position is None:
            return 0.0
        p = self.position
        if p["direction"] == "BUY":
            return (price - p["entry_price"]) * p["size"]
        return (p["entry_price"] - price) * p["size"]

    def total_equity(self, price: float) -> float:
        pos_val = (self.position["entry_price"] * self.position["size"]
                   if self.position else 0.0)
        return self.balance + pos_val + self.unrealized_pnl(price)
