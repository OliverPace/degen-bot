#!/usr/bin/env python3
# ============================================================
#  DEGEN-BOT — Main loop
#  Paper Trading BTC/USDT 5m
#
#  Modalità automatica:
#   - TTY  (Mac locale) → dashboard Rich interattiva
#   - Cloud (Railway)   → logging semplice su stdout
# ============================================================
import sys
import time
from datetime import datetime, timezone

from rich.console import Console
from rich.table   import Table
from rich.panel   import Panel
from rich.live    import Live
from rich.console import Group
from rich         import box

IS_TTY = sys.stdout.isatty()   # True = terminale locale, False = cloud

from config        import (UPDATE_INTERVAL, INITIAL_BALANCE,
                            MTF_REFRESH_MIN, DAILY_REPORT_HOUR_UTC,
                            FUNDING_REFRESH_TICKS, FNG_REFRESH_TICKS)
from data_feed     import get_klines, get_klines_1h, get_current_price, get_funding_rate, get_fear_greed
from strategy      import get_signal
from paper_trader  import PaperTrader
import telegram_notifier as tg

console = Console()


def clog(msg: str):
    """Log unificato: Rich in locale, stdout semplice in cloud."""
    if IS_TTY:
        console.log(msg)
    else:
        # Rimuove markup Rich per output pulito nei log cloud
        import re
        clean = re.sub(r'\[.*?\]', '', msg)
        print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {clean}", flush=True)


# ── Dashboard ─────────────────────────────────────────────────

def build_ui(trader: PaperTrader, price: float, sig: dict) -> Group:
    equity  = trader.total_equity(price)
    pnl     = equity - INITIAL_BALANCE
    unreal  = trader.unrealized_pnl(price)

    _sign  = lambda v: "+" if v >= 0 else ""
    _color = lambda v: "green" if v >= 0 else "red"

    sig_col   = {"BUY": "bold green", "SELL": "bold red", "HOLD": "yellow"}
    trend_sym = {"UP": "📈", "DOWN": "📉", "NEUTRAL": "➡️"}

    # ── Status string ──
    status_str = ""
    if trader.paused:
        status_str = "  [bold yellow]⏸ PAUSA[/bold yellow]"
    elif trader.daily_stopped:
        status_str = "  [bold red]🚨 DAILY STOP[/bold red]"
    elif trader.is_in_recovery():
        status_str = "  [bold yellow]⚠ RECOVERY[/bold yellow]"

    lines = [
        f"[bold cyan]DEGEN-BOT[/bold cyan]  •  [yellow]PAPER TRADING[/yellow]  •  BTC/USDT 5M  •  "
        f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC{status_str}",
        "",
        f"[bold]BTC:[/bold]           ${price:>12,.2f}",
        f"[bold]Balance:[/bold]       ${trader.balance:>12,.2f}",
        f"[bold]Equity:[/bold]        ${equity:>12,.2f}",
        f"[bold {_color(pnl)}]P&L netto:     "
        f"{_sign(pnl)}${abs(pnl):>10,.2f}  ({_sign(pnl)}{pnl/INITIAL_BALANCE*100:.1f}%)"
        f"[/bold {_color(pnl)}]",
    ]

    # Posizione aperta
    if trader.position:
        p = trader.position
        trail_tag = "  [dim]🎯trailing[/dim]" if p.get("trailing_active") else ""
        lines += [
            "",
            f"[magenta]━━ POSIZIONE APERTA ━━━━━━━━━━━━━━━━━[/magenta]",
            f"  {p['direction']}  @  ${p['entry_price']:,.2f}{trail_tag}",
            f"  SL  ${p['stop_loss']:,.2f}   TP  ${p['take_profit']:,.2f}",
            f"  [bold {_color(unreal)}]Unrealized  {_sign(unreal)}${abs(unreal):.2f}"
            f"[/bold {_color(unreal)}]",
        ]
    else:
        lines += ["", "[dim]Nessuna posizione aperta[/dim]"]

    # Indicatori
    blocked = f"  [dim]({sig['blocked_by']})[/dim]" if sig.get("blocked_by") else ""
    volume_tag = "[green]✓[/green]" if sig["volume_ok"] else "[red]✗[/red]"
    _atr_disp     = sig.get("atr", 0.0) or 0.0
    _macd_disp    = sig.get("macd_hist", 0.0) or 0.0
    _soft_disp    = sig.get("soft_score", 0)
    _fr_disp      = sig.get("funding_rate", 0.0) or 0.0
    _fng_val_disp = sig.get("fng_value", 50)
    _fng_lbl_disp = sig.get("fng_label", "N/A")
    lines += [
        "",
        f"[bold]━━ INDICATORI ━━━━━━━━━━━━━━━━━━━━━━━[/bold]",
        f"  RSI(14)      {sig['rsi']:>6.1f}",
        f"  SMA {str(7):>2}/{str(18):>2}    {sig['sma_fast']:>8.0f} / {sig['sma_slow']:>8.0f}",
        f"  Volume       {volume_tag}",
        f"  Trend 1H     {trend_sym.get(sig['trend_1h'],'➡️')} {sig['trend_1h']}",
        f"  Funding: {_fr_disp*100:.4f}%  F&G: {_fng_val_disp} ({_fng_lbl_disp})",
        f"  Soft score: {_soft_disp}/3  ATR: {_atr_disp:.0f}",
        f"  Segnale      [{sig_col[sig['signal']]}]{sig['signal']}[/{sig_col[sig['signal']]}]"
        + blocked,
        "",
        f"[bold]━━ STATS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold]",
        f"  Trade: {trader.wins + trader.losses}   Win rate: {trader.win_rate:.1f}%"
        f"   Consec.loss: {trader.consec_losses}",
        f"  P&L realizzato: "
        f"[bold {_color(trader.total_pnl)}]{_sign(trader.total_pnl)}${abs(trader.total_pnl):.2f}[/bold {_color(trader.total_pnl)}]",
    ]

    panel = Panel("\n".join(lines),
                  title="[bold green]⚡ DEGEN-BOT[/bold green]",
                  border_style="green")

    # Tabella trade
    table = Table(title="Ultimi Trade", box=box.SIMPLE_HEAD,
                  title_style="bold", header_style="bold dim")
    table.add_column("Dir",    width=6,  justify="center")
    table.add_column("Entry",  width=11, justify="right")
    table.add_column("Exit",   width=11, justify="right")
    table.add_column("P&L",    width=12, justify="right")
    table.add_column("Motivo", width=13)
    table.add_column("Ora",    width=8)

    _s = lambda v: "+" if v >= 0 else ""
    for t in reversed(trader.trades[-10:]):
        dc  = "green" if t["direction"] == "BUY" else "red"
        pc  = "green" if t["pnl"] >= 0 else "red"
        trail = " 🎯" if t.get("trailing_active") else ""
        rec   = " ⚠" if t.get("recovery_mode") else ""
        ts    = t.get("closed_at", "")[:10+6].replace("T"," ")[11:19]
        table.add_row(
            f"[{dc}]{t['direction']}[/{dc}]",
            f"${t['entry_price']:,.0f}",
            f"${t['exit_price']:,.0f}",
            f"[{pc}]{_s(t['pnl'])}${abs(t['pnl']):.2f}[/{pc}]",
            t["reason"] + trail + rec,
            ts,
        )

    return Group(panel, table)


# ── Main loop ─────────────────────────────────────────────────

def main():
    mode = "LOCAL (dashboard)" if IS_TTY else "CLOUD (headless)"
    if IS_TTY:
        console.print(Panel(
            f"[bold green]⚡ DEGEN-BOT avviato — {mode}[/bold green]\n"
            "[dim]Paper Trading  •  BTC/USDT 5m  •  Ctrl+C per fermare\n"
            "Comandi Telegram: /status  /balance  /stop  /resume  /report[/dim]",
            border_style="green"
        ))
    else:
        print(f"[BOOT] DEGEN-BOT avviato — {mode}", flush=True)
        print(f"[BOOT] Paper Trading | BTC/USDT 5m | Balance: ${INITIAL_BALANCE}", flush=True)

    trader      = PaperTrader()
    df_1h       = None
    mtf_counter = 0
    last_report_date  = ""
    last_report_hour  = -1
    funding_rate      = 0.0
    fng               = {"value": 50, "label": "Neutral"}
    funding_counter   = 0
    fng_counter       = 0

    tg.notify_start(trader.balance)

    try:
        df_1h = get_klines_1h()
    except Exception:
        pass

    # Wrapper: usa Live solo in locale
    def _run_loop(live=None):
        nonlocal df_1h, mtf_counter, last_report_date, funding_rate, fng, funding_counter, fng_counter

        while True:
            try:
                # ── 1. Fetch dati ────────────────────────────
                df    = get_klines(limit=100)
                price = get_current_price()

                # ── 2. Aggiorna trend 1H ogni MTF_REFRESH_MIN tick ──
                mtf_counter += 1
                if mtf_counter >= MTF_REFRESH_MIN:
                    try:
                        df_1h = get_klines_1h()
                    except Exception:
                        pass
                    mtf_counter = 0

                # ── 2b. Aggiorna funding rate ────────────────
                funding_counter += 1
                if funding_counter >= FUNDING_REFRESH_TICKS:
                    try:
                        funding_rate = get_funding_rate()
                    except Exception:
                        pass
                    funding_counter = 0

                # ── 2c. Aggiorna Fear & Greed ────────────────
                fng_counter += 1
                if fng_counter >= FNG_REFRESH_TICKS:
                    try:
                        fng = get_fear_greed()
                    except Exception:
                        pass
                    fng_counter = 0

                # ── 3. Reset giornaliero ────────────────────
                equity = trader.total_equity(price)
                trader.tick_day(equity)

                # ── 4. Trailing stop update ─────────────────
                trader.update_trailing(price)

                # ── 5. Daily loss limit ─────────────────────
                if not trader.daily_stopped and trader.check_daily_loss(equity):
                    trader.daily_stopped = True
                    trader._save()
                    tg.notify_risk_event("DAILY_LOSS_LIMIT",
                        f"Perdita giornaliera >5%.\nBot fermo fino a domani.\nEquity: ${equity:.2f}")
                    clog("[bold red]DAILY LOSS LIMIT — trading sospeso[/bold red]")

                # ── 6. Recovery mode alert ──────────────────
                if trader.consec_losses == 3:
                    tg.notify_risk_event("RECOVERY_MODE",
                        "3 perdite consecutive. Size ridotta al 50%.")

                # ── 7. Uscite SL/TP ─────────────────────────
                closed = trader.check_exit(price)
                if closed:
                    sign = "+" if closed["pnl"] >= 0 else ""
                    clog(f"TRADE CHIUSO {closed['direction']} → {closed['reason']} "
                         f"{sign}{closed['pnl']:.2f} USDT"
                         + (" TRAILING" if closed.get("trailing_active") else ""))
                    tg.notify_trade_close(
                        closed["direction"], closed["entry_price"],
                        closed["exit_price"], closed["pnl"],
                        closed["reason"], trader.balance,
                        closed.get("trailing_active", False))

                # ── 8. Segnale ───────────────────────────────
                sig = get_signal(df, df_1h, funding_rate, fng)

                # ── 9. Apri posizione ────────────────────────
                if sig["signal"] in ("BUY", "SELL") and trader.position is None:
                    if trader.open_position(price, sig["signal"],
                                            sl_override=sig.get("sl") or None,
                                            tp_override=sig.get("tp") or None):
                        pos = trader.position
                        clog(f"TRADE APERTO {sig['signal']} @ ${price:,.2f}"
                             + (" RECOVERY" if pos.get("recovery_mode") else ""))
                        tg.notify_trade_open(
                            sig["signal"], price,
                            pos["stop_loss"], pos["take_profit"],
                            False, pos.get("recovery_mode", False))

                # ── 10. Comandi Telegram ─────────────────────
                for cmd, chat_id in tg.poll_commands():
                    if cmd == "status":
                        tg.send_status(price, sig, trader, chat_id)
                    elif cmd == "balance":
                        tg.send_balance(price, trader, chat_id)
                    elif cmd == "stop":
                        trader.paused = True; trader._save()
                        tg.notify_risk_event("PAUSED", "Trading in pausa. /resume per riprendere.")
                        clog("Bot in pausa (Telegram)")
                    elif cmd == "resume":
                        trader.paused = False; trader.daily_stopped = False; trader._save()
                        tg.notify_risk_event("RESUMED", "Trading ripreso.")
                        clog("Bot ripreso (Telegram)")
                    elif cmd == "report":
                        tg.send_daily_report(price, trader)

                # ── 11. Report 08:00 UTC ─────────────────────
                now_utc = datetime.now(timezone.utc)
                if (now_utc.hour == DAILY_REPORT_HOUR_UTC
                        and now_utc.strftime("%Y-%m-%d") != last_report_date):
                    tg.send_daily_report(price, trader)
                    last_report_date = now_utc.strftime("%Y-%m-%d")

                # ── 12. Dashboard o log ──────────────────────
                if live:
                    live.update(build_ui(trader, price, sig))
                else:
                    # Cloud: stampa riga di stato ogni tick
                    eq   = trader.total_equity(price)
                    pnl  = eq - INITIAL_BALANCE
                    sign = "+" if pnl >= 0 else ""
                    print(f"[{now_utc.strftime('%H:%M:%S')}] BTC ${price:,.0f} | "
                          f"RSI {sig['rsi']:.1f} | {sig['signal']}"
                          + (f" ({sig['blocked_by']})" if sig.get('blocked_by') else "")
                          + f" | Equity ${eq:.2f} ({sign}{pnl:.2f})",
                          flush=True)

            except KeyboardInterrupt:
                clog("Bot fermato. Stato salvato.")
                break
            except Exception as e:
                clog(f"Errore: {e}")
                tg.notify_error(str(e))

            time.sleep(UPDATE_INTERVAL)

    # ── Avvia nel modo corretto ──────────────────────────────────
    if IS_TTY:
        with Live(console=console, refresh_per_second=1, screen=False) as live:
            _run_loop(live)
    else:
        _run_loop(live=None)


if __name__ == "__main__":
    main()
