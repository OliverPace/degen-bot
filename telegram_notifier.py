# ============================================================
#  DEGEN-BOT — Telegram Notifier
# ============================================================
import requests
from datetime import datetime

import os

# Legge prima dalle variabili d'ambiente (server cloud), poi da secrets_tg.py (locale)
try:
    from secrets_tg import TELEGRAM_TOKEN as _TK, TELEGRAM_CHAT_ID as _CID
except ImportError:
    _TK, _CID = "", ""

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   _TK)
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", _CID)
ENABLED = bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)


def _send(text: str) -> None:
    """Manda un messaggio Telegram. Silenzioso se non configurato."""
    if not ENABLED:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text":    text,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception:
        pass  # notifica fallita → il bot non si ferma


# ----------------------------------------------------------
#  Messaggi pronti
# ----------------------------------------------------------
def notify_start(balance: float) -> None:
    _send(
        f"⚡ <b>DEGEN-BOT avviato</b>\n"
        f"💰 Balance: <b>${balance:.2f}</b>\n"
        f"📊 BTC/USDT • 5m • Paper Trading\n"
        f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )


def notify_trade_open(direction: str, price: float,
                      stop_loss: float, take_profit: float) -> None:
    emoji = "🟢" if direction == "BUY" else "🔴"
    _send(
        f"{emoji} <b>TRADE APERTO — {direction}</b>\n"
        f"📈 Entry:  <b>${price:,.2f}</b>\n"
        f"🛑 Stop:   ${stop_loss:,.2f}\n"
        f"🎯 Target: ${take_profit:,.2f}"
    )


def notify_trade_close(direction: str, entry: float, exit_price: float,
                       pnl: float, reason: str, balance: float) -> None:
    emoji   = "✅" if pnl >= 0 else "❌"
    sign    = "+" if pnl >= 0 else ""
    reason_map = {"TAKE_PROFIT": "🎯 Take Profit", "STOP_LOSS": "🛑 Stop Loss"}
    _send(
        f"{emoji} <b>TRADE CHIUSO — {direction}</b>\n"
        f"📌 Entry:  ${entry:,.2f}\n"
        f"📌 Exit:   ${exit_price:,.2f}\n"
        f"💵 P&L:    <b>{sign}${abs(pnl):.2f}</b>\n"
        f"📋 Motivo: {reason_map.get(reason, reason)}\n"
        f"💰 Balance: ${balance:.2f}"
    )


def notify_error(message: str) -> None:
    _send(f"⚠️ <b>ERRORE BOT</b>\n{message[:200]}")


def notify_status(price: float, rsi: float, signal: str,
                  balance: float, equity: float, pnl: float,
                  wins: int, losses: int) -> None:
    sign  = "+" if pnl >= 0 else ""
    total = wins + losses
    wr    = f"{wins/total*100:.0f}%" if total else "—"
    _send(
        f"📊 <b>DEGEN-BOT Status</b>\n"
        f"₿  BTC:    ${price:,.2f}\n"
        f"📉 RSI:    {rsi:.1f}\n"
        f"📡 Signal: {signal}\n"
        f"──────────────\n"
        f"💰 Balance: ${balance:.2f}\n"
        f"📈 Equity:  ${equity:.2f}\n"
        f"💵 P&L:     {sign}${abs(pnl):.2f}\n"
        f"🏆 Win rate: {wr} ({wins}W / {losses}L)\n"
        f"🕐 {datetime.now().strftime('%H:%M:%S')}"
    )
