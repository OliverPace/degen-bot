#!/usr/bin/env python3
# ============================================================
#  DEGEN-BOT — Main loop  (Paper Trading BTC/USDT 5m)
#  Avvia con:  python main.py
# ============================================================
import time
from datetime import datetime

from rich.console import Console
from rich.table   import Table
from rich.panel   import Panel
from rich.live    import Live
from rich.text    import Text
from rich.console import Group
from rich         import box

from config           import UPDATE_INTERVAL, INITIAL_BALANCE
from data_feed        import get_klines, get_current_price
from strategy         import get_signal
from paper_trader     import PaperTrader
import telegram_notifier as tg

console = Console()


# ----------------------------------------------------------
#  Dashboard builder
# ----------------------------------------------------------
def build_ui(trader: PaperTrader, price: float,
             signal: str, rsi: float, sma_fast: float, sma_slow: float):

    equity  = trader.total_equity(price)
    pnl     = equity - INITIAL_BALANCE
    unreal  = trader.unrealized_pnl(price)

    sign    = lambda v: "+" if v >= 0 else ""
    color   = lambda v: "green" if v >= 0 else "red"

    sig_col = {"BUY": "bold green", "SELL": "bold red", "HOLD": "yellow"}

    # ---- Status panel ----
    lines = [
        f"[bold cyan]DEGEN-BOT[/bold cyan]  •  [yellow]PAPER TRADING[/yellow]  •  BTC/USDT 5M  •  {datetime.now().strftime('%H:%M:%S')}",
        "",
        f"[bold]BTC:[/bold]          ${price:>12,.2f}",
        f"[bold]Balance:[/bold]      ${trader.balance:>12,.2f}",
        f"[bold]Equity totale:[/bold] ${equity:>11,.2f}",
        f"[bold {color(pnl)}]P&L netto:    {sign(pnl)}${abs(pnl):>10,.2f}  ({sign(pnl)}{pnl/INITIAL_BALANCE*100:.1f}%)[/bold {color(pnl)}]",
    ]

    if trader.position:
        p = trader.position
        lines += [
            "",
            f"[magenta]━━ POSIZIONE APERTA ━━━━━━━━━━━━━━[/magenta]",
            f"  {p['direction']}  @  ${p['entry_price']:,.2f}",
            f"  SL  ${p['stop_loss']:,.2f}   TP  ${p['take_profit']:,.2f}",
            f"  [bold {color(unreal)}]Unrealized  {sign(unreal)}${abs(unreal):.2f}[/bold {color(unreal)}]",
        ]
    else:
        lines += ["", "[dim]Nessuna posizione aperta[/dim]"]

    lines += [
        "",
        f"[bold]━━ INDICATORI ━━━━━━━━━━━━━━━━━━━━[/bold]",
        f"  RSI(14)   {rsi:>6.1f}",
        f"  SMA {str(9):>2} / {str(21):>2}  {sma_fast:>8.0f} / {sma_slow:>8.0f}",
        f"  Segnale   [{sig_col[signal]}]{signal}[/{sig_col[signal]}]",
        "",
        f"[bold]━━ STATS ━━━━━━━━━━━━━━━━━━━━━━━━━[/bold]",
        f"  Trade:    {trader.wins + trader.losses}   Win rate: {trader.win_rate:.1f}%",
        f"  P&L real: [bold {color(trader.total_pnl)}]{sign(trader.total_pnl)}${abs(trader.total_pnl):.2f}[/bold {color(trader.total_pnl)}]",
    ]

    panel = Panel("\n".join(lines), title="[bold green]⚡ DEGEN-BOT[/bold green]",
                  border_style="green")

    # ---- Trade history table ----
    table = Table(title="Ultimi Trade", box=box.SIMPLE_HEAD, show_header=True,
                  title_style="bold", header_style="bold dim")
    table.add_column("Dir",   width=6,  justify="center")
    table.add_column("Entry", width=11, justify="right")
    table.add_column("Exit",  width=11, justify="right")
    table.add_column("P&L",   width=12, justify="right")
    table.add_column("Motivo",width=12)
    table.add_column("Ora",   width=8)

    for t in reversed(trader.trades[-10:]):
        dc  = "green"  if t["direction"] == "BUY" else "red"
        pc  = "green"  if t["pnl"] >= 0 else "red"
        ts  = t["closed_at"][11:19] if "closed_at" in t else ""
        table.add_row(
            f"[{dc}]{t['direction']}[/{dc}]",
            f"${t['entry_price']:,.0f}",
            f"${t['exit_price']:,.0f}",
            f"[{pc}]{sign(t['pnl'])}${abs(t['pnl']):.2f}[/{pc}]",
            t["reason"],
            ts,
        )

    return Group(panel, table)


# ----------------------------------------------------------
#  Main loop
# ----------------------------------------------------------
def main():
    console.print(Panel(
        "[bold green]⚡ DEGEN-BOT avviato[/bold green]\n"
        "[dim]Modalità: PAPER TRADING (nessun soldo reale)\n"
        f"Balance iniziale: $150.00 USDT  •  BTC/USDT 5m\n"
        "Premi Ctrl+C per fermare[/dim]",
        border_style="green"
    ))

    trader = PaperTrader()
    tg.notify_start(trader.balance)

    with Live(console=console, refresh_per_second=1, screen=False) as live:
        while True:
            try:
                df    = get_klines(limit=100)
                price = get_current_price()

                # 1. Controlla uscite (SL / TP)
                closed = trader.check_exit(price)
                if closed:
                    pc = "green" if closed["pnl"] >= 0 else "red"
                    console.log(
                        f"[bold]TRADE CHIUSO[/bold] {closed['direction']} "
                        f"→ [{pc}]{closed['reason']}[/{pc}]  "
                        f"[bold {pc}]{'+' if closed['pnl']>=0 else ''}{closed['pnl']:.2f} USDT[/bold {pc}]"
                    )
                    tg.notify_trade_close(
                        closed["direction"], closed["entry_price"],
                        closed["exit_price"], closed["pnl"],
                        closed["reason"], trader.balance
                    )

                # 2. Valuta nuovo segnale
                signal, rsi, sma_fast, sma_slow = get_signal(df)

                # 3. Apri posizione se segnale e piatti
                if signal in ("BUY", "SELL") and trader.position is None:
                    if trader.open_position(price, signal):
                        sc = "green" if signal == "BUY" else "red"
                        console.log(
                            f"[bold]TRADE APERTO[/bold]  "
                            f"[{sc}]{signal}[/{sc}] @ ${price:,.2f}"
                        )
                        pos = trader.position
                        tg.notify_trade_open(
                            signal, price,
                            pos["stop_loss"], pos["take_profit"]
                        )

                # 4. Aggiorna dashboard
                live.update(build_ui(trader, price, signal, rsi, sma_fast, sma_slow))

            except KeyboardInterrupt:
                console.print("\n[yellow]Bot fermato. Stato salvato. A presto![/yellow]")
                break
            except Exception as e:
                console.log(f"[red]Errore: {e}[/red]")
                tg.notify_error(str(e))

            time.sleep(UPDATE_INTERVAL)


if __name__ == "__main__":
    main()
