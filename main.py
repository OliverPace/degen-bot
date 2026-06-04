#!/usr/bin/env python3
# ============================================================
#  DEGEN-BOT — Main loop
#  Paper Trading BTC/USDT 5m
#
#  Features:
#   - Strategia RSI + SMA con filtro volume e trend 1H
#   - Trailing stop automatico
#   - Daily loss limit + recovery mode
#   - Comandi Telegram: /status /balance /stop /resume /report
#   - Report giornaliero automatico alle 08:00 UTC
# ============================================================
import time
from datetime import datetime, timezone

from rich.console import Console
from rich.table   import Table
from rich.panel   import Panel
from rich.live    import Live
from rich.console import Group
from rich         import box

from config        import (UPDATE_INTERVAL, INITIAL_BALANCE,
                            MTF_REFRESH_MIN, DAILY_REPORT_HOUR_UTC)
from data_feed     import get_klines, get_klines_1h, get_current_price
from strategy      import get_signal
from paper_trader  import PaperTrader
import telegram_notifier as tg

console = Console()


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
    lines += [
        "",
        f"[bold]━━ INDICATORI ━━━━━━━━━━━━━━━━━━━━━━━[/bold]",
        f"  RSI(14)      {sig['rsi']:>6.1f}",
        f"  SMA {str(7):>2}/{str(18):>2}    {sig['sma_fast']:>8.0f} / {sig['sma_slow']:>8.0f}",
        f"  Volume       {volume_tag}",
        f"  Trend 1H     {trend_sym.get(sig['trend_1h'],'➡️')} {sig['trend_1h']}",
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
    console.print(Panel(
        "[bold green]⚡ DEGEN-BOT avviato[/bold green]\n"
        "[dim]Paper Trading  •  BTC/USDT 5m  •  Ctrl+C per fermare\n"
        "Comandi Telegram: /status  /balance  /stop  /resume  /report[/dim]",
        border_style="green"
    ))

    trader      = PaperTrader()
    df_1h       = None
    mtf_counter = 0
    last_report_date  = ""
    last_report_hour  = -1

    # Notifica avvio su Telegram
    tg.notify_start(trader.balance)

    # Carica il trend 1H immediatamente
    try:
        df_1h = get_klines_1h()
    except Exception:
        pass

    with Live(console=console, refresh_per_second=1, screen=False) as live:
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

                # ── 3. Reset giornaliero ────────────────────
                equity = trader.total_equity(price)
                trader.tick_day(equity)

                # ── 4. Trailing stop update ─────────────────
                trader.update_trailing(price)

                # ── 5. Controllo daily loss limit ───────────
                if not trader.daily_stopped and trader.check_daily_loss(equity):
                    trader.daily_stopped = True
                    trader._save()
                    tg.notify_risk_event(
                        "DAILY_LOSS_LIMIT",
                        f"Perdita giornaliera >5% raggiunta.\nBot fermo fino a domani.\n"
                        f"Equity: ${equity:.2f}"
                    )
                    console.log("[bold red]🚨 DAILY LOSS LIMIT — trading sospeso[/bold red]")

                # ── 6. Recovery mode alert ──────────────────
                if trader.consec_losses == 3:
                    tg.notify_risk_event(
                        "RECOVERY_MODE",
                        f"3 perdite consecutive.\nSize ridotta al 50% fino al prossimo win."
                    )

                # ── 7. Controlla uscite (SL/TP) ─────────────
                closed = trader.check_exit(price)
                if closed:
                    pc = "green" if closed["pnl"] >= 0 else "red"
                    console.log(
                        f"[bold]TRADE CHIUSO[/bold]  {closed['direction']} "
                        f"→ [{pc}]{closed['reason']}[/{pc}]  "
                        f"[bold {pc}]{'+' if closed['pnl']>=0 else ''}{closed['pnl']:.2f} USDT[/bold {pc}]"
                        + (" 🎯" if closed.get("trailing_active") else "")
                    )
                    tg.notify_trade_close(
                        closed["direction"], closed["entry_price"],
                        closed["exit_price"], closed["pnl"],
                        closed["reason"], trader.balance,
                        closed.get("trailing_active", False)
                    )

                # ── 8. Valuta segnale ────────────────────────
                sig = get_signal(df, df_1h)

                # ── 9. Apri posizione ────────────────────────
                if sig["signal"] in ("BUY", "SELL") and trader.position is None:
                    if trader.open_position(price, sig["signal"]):
                        pos = trader.position
                        sc  = "green" if sig["signal"] == "BUY" else "red"
                        console.log(
                            f"[bold]TRADE APERTO[/bold]  "
                            f"[{sc}]{sig['signal']}[/{sc}] @ ${price:,.2f}"
                            + (" ⚠ recovery" if pos.get("recovery_mode") else "")
                        )
                        tg.notify_trade_open(
                            sig["signal"], price,
                            pos["stop_loss"], pos["take_profit"],
                            False, pos.get("recovery_mode", False)
                        )

                # ── 10. Comandi Telegram ─────────────────────
                for cmd, chat_id in tg.poll_commands():
                    if cmd == "status":
                        tg.send_status(price, sig, trader, chat_id)
                    elif cmd == "balance":
                        tg.send_balance(price, trader, chat_id)
                    elif cmd == "stop":
                        trader.paused = True
                        trader._save()
                        tg.notify_risk_event("PAUSED", "Trading in pausa. Usa /resume per riprendere.")
                        console.log("[yellow]⏸ Bot in pausa (comando Telegram)[/yellow]")
                    elif cmd == "resume":
                        trader.paused = False
                        trader.daily_stopped = False
                        trader._save()
                        tg.notify_risk_event("RESUMED", "Trading ripreso.")
                        console.log("[green]▶ Bot ripreso (comando Telegram)[/green]")
                    elif cmd == "report":
                        tg.send_daily_report(price, trader)

                # ── 11. Report automatico 08:00 UTC ─────────
                now_utc = datetime.now(timezone.utc)
                if (now_utc.hour == DAILY_REPORT_HOUR_UTC
                        and now_utc.strftime("%Y-%m-%d") != last_report_date):
                    tg.send_daily_report(price, trader)
                    last_report_date = now_utc.strftime("%Y-%m-%d")

                # ── 12. Aggiorna dashboard ───────────────────
                live.update(build_ui(trader, price, sig))

            except KeyboardInterrupt:
                console.print("\n[yellow]Bot fermato. Stato salvato. A presto![/yellow]")
                break
            except Exception as e:
                console.log(f"[red]Errore: {e}[/red]")
                tg.notify_error(str(e))

            time.sleep(UPDATE_INTERVAL)


if __name__ == "__main__":
    main()
