# ============================================================
#  DEGEN-BOT — Telegram Notifier + Command Handler
#
#  Comandi disponibili:
#    /status   → stato corrente del bot
#    /balance  → saldo e posizione aperta
#    /stop     → mette in pausa il trading
#    /resume   → riprende il trading
#    /report   → report giornaliero on-demand
# ============================================================
import os
import requests
from datetime import datetime, timezone

try:
    from secrets_tg import TELEGRAM_TOKEN as _TK, TELEGRAM_CHAT_ID as _CID
except ImportError:
    _TK, _CID = "", ""

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   _TK)
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", _CID)
ENABLED          = bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)

_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


# ── Invio messaggi ────────────────────────────────────────────

def _send(text: str, chat_id: str = None) -> None:
    if not ENABLED:
        return
    try:
        requests.post(f"{_BASE}/sendMessage", json={
            "chat_id":    chat_id or TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception:
        pass


# ── Messaggi evento ───────────────────────────────────────────

def notify_start(balance: float) -> None:
    _send(
        f"⚡ <b>DEGEN-BOT avviato</b>\n"
        f"💰 Balance: <b>${balance:.2f}</b>\n"
        f"📊 BTC/USDT • 5m • Paper Trading\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M')} UTC\n\n"
        f"Comandi: /status /balance /stop /resume /report"
    )


def notify_trade_open(direction: str, price: float,
                      stop_loss: float, take_profit: float,
                      trailing: bool, recovery: bool) -> None:
    emoji   = "🟢" if direction == "BUY" else "🔴"
    extras  = []
    if trailing: extras.append("🎯 Trailing attivo")
    if recovery: extras.append("⚠️ Recovery mode")
    extra_str = "\n" + "\n".join(extras) if extras else ""
    _send(
        f"{emoji} <b>TRADE APERTO — {direction}</b>\n"
        f"📈 Entry:  <b>${price:,.2f}</b>\n"
        f"🛑 Stop:   ${stop_loss:,.2f}\n"
        f"🎯 Target: ${take_profit:,.2f}"
        + extra_str
    )


def notify_trade_close(direction: str, entry: float, exit_price: float,
                       pnl: float, reason: str, balance: float,
                       trailing_used: bool) -> None:
    emoji     = "✅" if pnl >= 0 else "❌"
    sign      = "+" if pnl >= 0 else ""
    reason_map = {
        "TAKE_PROFIT": "🎯 Take Profit",
        "STOP_LOSS":   "🛑 Stop Loss",
    }
    trail_tag = "  <i>(trailing)</i>" if trailing_used else ""
    _send(
        f"{emoji} <b>TRADE CHIUSO — {direction}</b>\n"
        f"📌 Entry:  ${entry:,.2f}\n"
        f"📌 Exit:   ${exit_price:,.2f}\n"
        f"💵 P&L:    <b>{sign}${abs(pnl):.2f}</b>{trail_tag}\n"
        f"📋 Motivo: {reason_map.get(reason, reason)}\n"
        f"💰 Balance: ${balance:.2f}"
    )


def notify_risk_event(event: str, detail: str) -> None:
    icons = {
        "DAILY_LOSS_LIMIT": "🚨",
        "RECOVERY_MODE":    "⚠️",
        "PAUSED":           "⏸️",
        "RESUMED":          "▶️",
    }
    _send(f"{icons.get(event,'⚠️')} <b>{event}</b>\n{detail}")


def notify_error(message: str) -> None:
    _send(f"⚠️ <b>ERRORE BOT</b>\n<code>{message[:300]}</code>")


# ── Report giornaliero ────────────────────────────────────────

def send_daily_report(price: float, trader) -> None:
    from config import INITIAL_BALANCE
    equity   = trader.total_equity(price)
    pnl      = equity - INITIAL_BALANCE
    sign     = "+" if pnl >= 0 else ""
    total    = trader.wins + trader.losses
    wr       = f"{trader.win_rate:.0f}%" if total else "—"
    status   = "⏸️ PAUSA" if trader.paused else ("🚨 DAILY STOP" if trader.daily_stopped else "🟢 ATTIVO")
    recovery = "⚠️ Recovery" if trader.is_in_recovery() else "✅ Normale"

    _send(
        f"📊 <b>Report Giornaliero — {datetime.now(timezone.utc).strftime('%d/%m/%Y')}</b>\n\n"
        f"₿  BTC:     ${price:,.2f}\n"
        f"💰 Balance: ${trader.balance:.2f}\n"
        f"📈 Equity:  ${equity:.2f}\n"
        f"💵 P&L tot: <b>{sign}${abs(pnl):.2f}</b>  ({sign}{pnl/INITIAL_BALANCE*100:.1f}%)\n\n"
        f"🏆 Trade:   {total}  •  Win: {wr}\n"
        f"📉 Consec.loss: {trader.consec_losses}\n\n"
        f"🤖 Bot:     {status}\n"
        f"⚙️  Modo:    {recovery}"
    )


# ── Status on-demand ─────────────────────────────────────────

def send_status(price: float, sig: dict, trader, chat_id: str = None) -> None:
    from config import INITIAL_BALANCE
    equity = trader.total_equity(price)
    pnl    = equity - INITIAL_BALANCE
    sign   = "+" if pnl >= 0 else ""
    sig_em = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}
    trend_em = {"UP": "📈", "DOWN": "📉", "NEUTRAL": "➡️"}

    pos_info = ""
    if trader.position:
        p = trader.position
        unreal = trader.unrealized_pnl(price)
        trail  = " 🎯trailing" if p.get("trailing_active") else ""
        pos_info = (
            f"\n\n<b>Posizione aperta:</b>\n"
            f"  {p['direction']} @ ${p['entry_price']:,.0f}{trail}\n"
            f"  SL ${p['stop_loss']:,.0f}  TP ${p['take_profit']:,.0f}\n"
            f"  Unrealized: {'+' if unreal>=0 else ''}{unreal:.2f}"
        )

    _send(
        f"📊 <b>DEGEN-BOT Status</b>  {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n\n"
        f"₿  BTC:    ${price:,.2f}\n"
        f"💰 Balance: ${trader.balance:.2f}\n"
        f"📈 Equity:  ${equity:.2f}\n"
        f"💵 P&L:     {sign}${abs(pnl):.2f}\n\n"
        f"RSI: {sig['rsi']:.1f}  •  "
        f"Trend 1H: {trend_em.get(sig['trend_1h'],'➡️')} {sig['trend_1h']}\n"
        f"Segnale: {sig_em.get(sig['signal'],'🟡')} {sig['signal']}"
        + (f"  <i>({sig['blocked_by']})</i>" if sig.get('blocked_by') else "")
        + pos_info,
        chat_id=chat_id
    )


def send_balance(price: float, trader, chat_id: str = None) -> None:
    equity = trader.total_equity(price)
    unreal = trader.unrealized_pnl(price)
    _send(
        f"💰 <b>Balance</b>\n\n"
        f"Liquido:   ${trader.balance:.2f}\n"
        f"Unrealized: {'+' if unreal>=0 else ''}{unreal:.2f}\n"
        f"Equity:    <b>${equity:.2f}</b>",
        chat_id=chat_id
    )


# ── Polling comandi ───────────────────────────────────────────

_last_update_id = None

def poll_commands() -> list:
    """
    Recupera nuovi aggiornamenti Telegram (long-poll 5s).
    Restituisce lista di (command, chat_id).
    """
    if not ENABLED:
        return []
    global _last_update_id
    try:
        params = {"timeout": 5, "allowed_updates": ["message"]}
        if _last_update_id:
            params["offset"] = _last_update_id + 1
        resp = requests.get(f"{_BASE}/getUpdates", params=params, timeout=10)
        updates = resp.json().get("result", [])
        commands = []
        for u in updates:
            _last_update_id = u["update_id"]
            msg = u.get("message", {})
            text = msg.get("text", "").strip().lower()
            chat_id = str(msg.get("chat", {}).get("id", ""))
            if text.startswith("/"):
                cmd = text.split()[0].lstrip("/").split("@")[0]
                commands.append((cmd, chat_id))
        return commands
    except Exception:
        return []
