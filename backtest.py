#!/usr/bin/env python3
# ============================================================
#  DEGEN-BOT — Backtesting Engine
#  Testa la strategia su dati storici reali (Binance)
#
#  Uso:
#    python backtest.py              → backtest 180 giorni, parametri default
#    python backtest.py --days 90    → ultimi 90 giorni
#    python backtest.py --optimize   → cerca i parametri migliori
# ============================================================
import argparse
import json
import math
import time as _time
from datetime import datetime

import pandas as pd
import requests
from rich.console import Console
from rich.table   import Table
from rich.panel   import Panel
from rich.columns import Columns
from rich.text    import Text
from rich         import box

from config import BINANCE_BASE_URL, SYMBOL, INTERVAL

console = Console()

# ============================================================
#  1. SCARICA DATI STORICI
# ============================================================

def fetch_historical(days: int = 180) -> pd.DataFrame:
    """
    Scarica tutte le candele OHLCV da Binance per gli ultimi N giorni.
    Gestisce la paginazione (limite 1000 candele per richiesta).
    """
    end_ms   = int(_time.time() * 1000)
    start_ms = end_ms - days * 24 * 60 * 60 * 1000
    all_rows = []
    current  = start_ms

    with console.status(f"[cyan]Scaricando {days} giorni di dati BTC/USDT 5m...[/cyan]"):
        while current < end_ms:
            resp = requests.get(
                f"{BINANCE_BASE_URL}/api/v3/klines",
                params={"symbol": SYMBOL, "interval": INTERVAL,
                        "startTime": current, "endTime": end_ms, "limit": 1000},
                timeout=30
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            all_rows.extend(batch)
            current = batch[-1][0] + 1   # prossima candela
            if len(batch) < 1000:
                break
            _time.sleep(0.08)            # rispetta i rate limit Binance

    cols = ["open_time","open","high","low","close","volume",
            "close_time","quote_volume","trades",
            "taker_buy_base","taker_buy_quote","ignore"]
    df = pd.DataFrame(all_rows, columns=cols)
    for c in ("open","high","low","close","volume"):
        df[c] = df[c].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    df = df.drop_duplicates("open_time").reset_index(drop=True)
    return df


# ============================================================
#  2. INDICATORI
# ============================================================

def _rsi(s: pd.Series, p: int) -> pd.Series:
    d    = s.diff()
    gain = d.clip(lower=0).rolling(p).mean()
    loss = (-d.clip(upper=0)).rolling(p).mean()
    rs   = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))

def _sma(s: pd.Series, p: int) -> pd.Series:
    return s.rolling(p).mean()


# ============================================================
#  3. MOTORE DI SIMULAZIONE
# ============================================================

def run_backtest(df: pd.DataFrame, params: dict,
                 initial_balance: float = 150.0) -> dict:
    """
    Simula tutti i trade sulla serie storica.

    Precisione chirurgica:
    - SL/TP controllati sui massimi/minimi della candela (high/low),
      non solo sul prezzo di chiusura.
    - Se SL e TP sono entrambi violati nella stessa candela,
      si assume SL colpito per primo (scenario pessimistico = realistico).
    - Commissione Binance 0.1% applicata su apertura e chiusura.
    - Una sola posizione aperta alla volta.
    """
    rp   = params["rsi_period"]
    ros  = params["rsi_oversold"]
    rob  = params["rsi_overbought"]
    sf   = params["sma_fast"]
    ss   = params["sma_slow"]
    sl_p = params["stop_loss_pct"]
    tp_p = params["take_profit_pct"]

    closes = df["close"]
    rsi    = _rsi(closes, rp)
    smaf   = _sma(closes, sf)
    smas   = _sma(closes, ss)

    balance   = initial_balance
    position  = None
    trades    = []
    equity    = []          # equity curve tick-by-tick
    drawdowns = []

    start = max(rp + 1, ss + 1)

    for i in range(start, len(df)):
        row = df.iloc[i]
        price  = row["close"]
        high   = row["high"]
        low    = row["low"]
        ts     = row["open_time"]

        cur_rsi  = rsi.iloc[i]
        cur_smaf = smaf.iloc[i]
        cur_smas = smas.iloc[i]

        if pd.isna(cur_rsi) or pd.isna(cur_smaf) or pd.isna(cur_smas):
            equity.append(balance)
            continue

        # ── Gestione uscita posizione aperta ─────────────────────
        if position:
            exit_price  = None
            exit_reason = None
            d = position["direction"]

            if d == "BUY":
                sl_hit = low  <= position["sl"]
                tp_hit = high >= position["tp"]
            else:
                sl_hit = high >= position["sl"]
                tp_hit = low  <= position["tp"]

            if sl_hit:                           # SL ha precedenza
                exit_price  = position["sl"]
                exit_reason = "STOP_LOSS"
            elif tp_hit:
                exit_price  = position["tp"]
                exit_reason = "TAKE_PROFIT"

            if exit_price:
                entry_val  = position["entry"] * position["size"]
                comm       = entry_val * 0.002   # 0.1% apertura + 0.1% chiusura

                if d == "BUY":
                    gross = (exit_price - position["entry"]) * position["size"]
                else:
                    gross = (position["entry"] - exit_price) * position["size"]

                pnl      = gross - comm
                pnl_pct  = gross / entry_val * 100
                balance += entry_val + pnl

                trades.append({
                    "direction":   d,
                    "entry":       round(position["entry"], 2),
                    "exit":        round(exit_price, 2),
                    "entry_time":  str(position["entry_time"]),
                    "exit_time":   str(ts),
                    "pnl":         round(pnl, 4),
                    "pnl_pct":     round(pnl_pct, 2),
                    "reason":      exit_reason,
                    "balance":     round(balance, 4),
                })
                position = None

        # Equity corrente (con unrealized se in posizione)
        if position:
            d = position["direction"]
            unreal = ((price - position["entry"]) if d == "BUY"
                      else (position["entry"] - price)) * position["size"]
            eq = balance + position["entry"] * position["size"] + unreal
        else:
            eq = balance
        equity.append(eq)

        # ── Segnale di entrata (solo se flat) ────────────────────
        if position is None:
            if cur_rsi < ros and cur_smaf > cur_smas:
                sig = "BUY"
            elif cur_rsi > rob and cur_smaf < cur_smas:
                sig = "SELL"
            else:
                sig = None

            if sig:
                trade_val = balance * 0.95
                if trade_val < 1:
                    continue
                size = trade_val / price

                if sig == "BUY":
                    sl_price = price * (1 - sl_p)
                    tp_price = price * (1 + tp_p)
                else:
                    sl_price = price * (1 + sl_p)
                    tp_price = price * (1 - tp_p)

                balance -= trade_val
                position = {
                    "direction":  sig,
                    "entry":      price,
                    "size":       size,
                    "sl":         sl_price,
                    "tp":         tp_price,
                    "entry_time": ts,
                }

    # Chiude posizione aperta a fine dati
    if position:
        lp = df.iloc[-1]["close"]
        d  = position["direction"]
        entry_val = position["entry"] * position["size"]
        comm = entry_val * 0.002
        gross = ((lp - position["entry"]) if d == "BUY"
                 else (position["entry"] - lp)) * position["size"]
        pnl = gross - comm
        balance += entry_val + pnl
        trades.append({
            "direction":  d,
            "entry":      round(position["entry"], 2),
            "exit":       round(lp, 2),
            "entry_time": str(position["entry_time"]),
            "exit_time":  str(df.iloc[-1]["open_time"]),
            "pnl":        round(pnl, 4),
            "pnl_pct":    round(gross / entry_val * 100, 2),
            "reason":     "END_OF_DATA",
            "balance":    round(balance, 4),
        })

    return {
        "trades":          trades,
        "final_balance":   balance,
        "initial_balance": initial_balance,
        "equity_curve":    equity,
    }


# ============================================================
#  4. METRICHE
# ============================================================

def calc_metrics(result: dict) -> dict:
    trades  = result["trades"]
    initial = result["initial_balance"]
    final   = result["final_balance"]
    equity  = result["equity_curve"]

    if not trades:
        return {}

    pnls   = [t["pnl"] for t in trades]
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # Drawdown massimo
    peak   = initial
    max_dd = 0.0
    for eq in equity:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Profit factor
    gross_win  = sum(wins)   if wins   else 0
    gross_loss = abs(sum(losses)) if losses else 1e-9
    pf = gross_win / gross_loss

    # Streak massima
    max_win_streak = max_loss_streak = cur_w = cur_l = 0
    for p in pnls:
        if p > 0:
            cur_w += 1; cur_l = 0
        else:
            cur_l += 1; cur_w = 0
        max_win_streak  = max(max_win_streak,  cur_w)
        max_loss_streak = max(max_loss_streak, cur_l)

    # Sharpe semplificato (daily returns su equity curve)
    eq_series = pd.Series(equity)
    daily_ret = eq_series.pct_change().dropna()
    sharpe = (daily_ret.mean() / daily_ret.std() * math.sqrt(365 * 288)
              if daily_ret.std() > 0 else 0)

    total_return_pct = (final - initial) / initial * 100
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    avg_win  = sum(wins)   / len(wins)   if wins   else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    rr_ratio = abs(avg_win / avg_loss)   if avg_loss else 0

    return {
        "total_trades":     len(trades),
        "wins":             len(wins),
        "losses":           len(losses),
        "win_rate":         round(win_rate, 2),
        "total_return":     round(total_return_pct, 2),
        "final_balance":    round(final, 2),
        "profit_factor":    round(pf, 3),
        "max_drawdown":     round(max_dd, 2),
        "avg_win":          round(avg_win, 4),
        "avg_loss":         round(avg_loss, 4),
        "rr_ratio":         round(rr_ratio, 2),
        "best_trade":       round(max(pnls), 4),
        "worst_trade":      round(min(pnls), 4),
        "max_win_streak":   max_win_streak,
        "max_loss_streak":  max_loss_streak,
        "sharpe":           round(sharpe, 3),
    }


# ============================================================
#  5. REPORT TERMINALE
# ============================================================

def print_report(metrics: dict, params: dict, days: int):
    if not metrics:
        console.print("[red]Nessun trade generato.[/red]")
        return

    tr = metrics["total_return"]
    tr_col = "green" if tr >= 0 else "red"
    sign = "+" if tr >= 0 else ""

    # Pannello principale
    lines = [
        f"[bold]Periodo:[/bold]   {days} giorni  •  BTC/USDT 5m",
        f"[bold]Balance:[/bold]   $150.00  →  [bold]${metrics['final_balance']:.2f}[/bold]",
        f"[bold {tr_col}]Rendimento:  {sign}{tr:.2f}%[/bold {tr_col}]",
        "",
        f"[bold]Trade totali:[/bold]  {metrics['total_trades']}",
        f"[bold]Win rate:[/bold]      [{'green' if metrics['win_rate']>=50 else 'red'}]{metrics['win_rate']:.1f}%[/]"
        f"  ({metrics['wins']}W / {metrics['losses']}L)",
        f"[bold]Profit factor:[/bold] [{'green' if metrics['profit_factor']>=1 else 'red'}]{metrics['profit_factor']:.3f}[/]"
        f"  [dim](>1 = strategia profittevole)[/dim]",
        f"[bold]Max drawdown:[/bold]  [{'red' if metrics['max_drawdown']>10 else 'yellow'}]-{metrics['max_drawdown']:.2f}%[/]",
        f"[bold]Sharpe ratio:[/bold]  {metrics['sharpe']:.3f}  [dim](>1 buono, >2 ottimo)[/dim]",
        "",
        f"[bold]Avg win:[/bold]   +${metrics['avg_win']:.4f}",
        f"[bold]Avg loss:[/bold]  -${abs(metrics['avg_loss']):.4f}",
        f"[bold]R/R ratio:[/bold]  {metrics['rr_ratio']:.2f}  [dim](>1.5 ideale)[/dim]",
        f"[bold]Best trade:[/bold]  +${metrics['best_trade']:.4f}",
        f"[bold]Worst trade:[/bold] -${abs(metrics['worst_trade']):.4f}",
        "",
        f"[bold]Max streak WIN:[/bold]   {metrics['max_win_streak']}",
        f"[bold]Max streak LOSS:[/bold]  {metrics['max_loss_streak']}",
    ]

    # Valutazione globale
    score = 0
    if metrics["win_rate"]     >= 50:  score += 1
    if metrics["profit_factor"] >= 1:  score += 2
    if metrics["max_drawdown"] <= 15:  score += 1
    if metrics["sharpe"]        >= 1:  score += 1
    if metrics["rr_ratio"]      >= 1.5: score += 1

    verdicts = {
        6: ("[bold green]★★★ OTTIMA — Deploy consigliato[/bold green]",     "green"),
        5: ("[bold green]★★☆ BUONA — Testa ancora un mese[/bold green]",    "green"),
        4: ("[bold yellow]★☆☆ DISCRETA — Ottimizza i parametri[/bold yellow]", "yellow"),
        3: ("[bold red]☆☆☆ DEBOLE — Non deployare ora[/bold red]",          "red"),
    }
    verdict_text, vcolor = verdicts.get(score, ("[bold red]☆☆☆ DEBOLE[/bold red]", "red"))
    lines += ["", f"[bold]Giudizio:[/bold]  {verdict_text}"]

    console.print(Panel("\n".join(lines),
                        title=f"[bold green]⚡ BACKTEST RESULTS[/bold green]",
                        border_style=vcolor))

    # Tabella parametri usati
    pt = Table(title="Parametri testati", box=box.SIMPLE, show_header=True,
               title_style="bold dim")
    pt.add_column("Parametro", style="dim")
    pt.add_column("Valore",    style="bold")
    for k, v in params.items():
        pt.add_row(k, str(v))
    console.print(pt)


# ============================================================
#  6. OTTIMIZZAZIONE PARAMETRI (grid search)
# ============================================================

def optimize(df: pd.DataFrame, initial_balance: float = 150.0):
    """
    Testa tutte le combinazioni di parametri e trova la migliore
    in base al Profit Factor (metrica più robusta del win rate).
    """
    grid = {
        "rsi_period":      [14],
        "rsi_oversold":    [30, 35, 40],
        "rsi_overbought":  [60, 65, 70],
        "sma_fast":        [7, 9, 12],
        "sma_slow":        [18, 21, 26],
        "stop_loss_pct":   [0.010, 0.015, 0.020],
        "take_profit_pct": [0.020, 0.025, 0.030],
    }

    # Genera tutte le combinazioni
    import itertools
    keys   = list(grid.keys())
    combos = list(itertools.product(*grid.values()))
    total  = len(combos)

    console.print(f"[cyan]Ottimizzazione: {total} combinazioni...[/cyan]")
    results = []

    with console.status("") as status:
        for i, values in enumerate(combos, 1):
            params = dict(zip(keys, values))
            # Salta combinazioni con RSI_oversold >= RSI_overbought
            if params["rsi_oversold"] >= params["rsi_overbought"]:
                continue
            # Salta SMA fast >= slow
            if params["sma_fast"] >= params["sma_slow"]:
                continue

            r = run_backtest(df, params, initial_balance)
            m = calc_metrics(r)
            if not m or m["total_trades"] < 5:
                continue

            results.append({**params, **m})
            status.update(f"[cyan]{i}/{total} — best PF finora: "
                          f"{max(x['profit_factor'] for x in results):.3f}[/cyan]")

    if not results:
        console.print("[red]Nessun risultato valido.[/red]")
        return

    # Ordina per profit factor
    results.sort(key=lambda x: x["profit_factor"], reverse=True)
    top = results[:10]

    # Tabella top 10
    t = Table(title="Top 10 combinazioni", box=box.SIMPLE_HEAD,
              title_style="bold", header_style="bold dim")
    cols = ["rsi_oversold","rsi_overbought","sma_fast","sma_slow",
            "stop_loss_pct","take_profit_pct",
            "win_rate","profit_factor","max_drawdown","total_return","total_trades"]
    for c in cols:
        t.add_column(c, justify="right")

    for r in top:
        row = [
            str(r["rsi_oversold"]), str(r["rsi_overbought"]),
            str(r["sma_fast"]),     str(r["sma_slow"]),
            f"{r['stop_loss_pct']*100:.1f}%", f"{r['take_profit_pct']*100:.1f}%",
            f"{r['win_rate']:.1f}%",
            f"[green]{r['profit_factor']:.3f}[/green]",
            f"[red]-{r['max_drawdown']:.1f}%[/red]",
            f"{'+' if r['total_return']>=0 else ''}{r['total_return']:.1f}%",
            str(r["total_trades"]),
        ]
        t.add_row(*row)

    console.print(t)

    best = top[0]
    console.print(Panel(
        f"[bold]Migliori parametri trovati:[/bold]\n\n"
        f"  RSI oversold/overbought:  {best['rsi_oversold']} / {best['rsi_overbought']}\n"
        f"  SMA fast/slow:            {best['sma_fast']} / {best['sma_slow']}\n"
        f"  Stop loss:                {best['stop_loss_pct']*100:.1f}%\n"
        f"  Take profit:              {best['take_profit_pct']*100:.1f}%\n\n"
        f"[dim]Copia questi valori in config.py per usarli nel bot live.[/dim]",
        title="[bold green]Ottimizzazione completata[/bold green]",
        border_style="green"
    ))

    # Salva risultati
    with open("optimization_results.json", "w") as f:
        json.dump(top, f, indent=2)
    console.print("[dim]Risultati salvati in optimization_results.json[/dim]")


# ============================================================
#  7. ENTRY POINT
# ============================================================

DEFAULT_PARAMS = {
    "rsi_period":      14,
    "rsi_oversold":    35,
    "rsi_overbought":  65,
    "sma_fast":        9,
    "sma_slow":        21,
    "stop_loss_pct":   0.015,
    "take_profit_pct": 0.025,
}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DEGEN-BOT Backtester")
    parser.add_argument("--days",     type=int,  default=180,
                        help="Giorni di storia da testare (default 180)")
    parser.add_argument("--optimize", action="store_true",
                        help="Lancia grid search per trovare i parametri migliori")
    args = parser.parse_args()

    console.print(Panel(
        "[bold green]⚡ DEGEN-BOT — Backtesting Engine[/bold green]\n"
        f"[dim]Simbolo: {SYMBOL}  •  Intervallo: {INTERVAL}  •  Periodo: {args.days} giorni[/dim]",
        border_style="green"
    ))

    df = fetch_historical(days=args.days)
    console.print(f"[green]✓[/green] {len(df):,} candele scaricate  "
                  f"({df['open_time'].iloc[0].strftime('%d/%m/%Y')} → "
                  f"{df['open_time'].iloc[-1].strftime('%d/%m/%Y')})\n")

    if args.optimize:
        optimize(df)
    else:
        with console.status("[cyan]Simulazione in corso...[/cyan]"):
            result  = run_backtest(df, DEFAULT_PARAMS)
            metrics = calc_metrics(result)

        print_report(metrics, DEFAULT_PARAMS, args.days)

        # Salva risultati completi
        output = {
            "timestamp":  datetime.now().isoformat(),
            "days":       args.days,
            "params":     DEFAULT_PARAMS,
            "metrics":    metrics,
            "trades":     result["trades"],
        }
        with open("backtest_results.json", "w") as f:
            json.dump(output, f, indent=2)
        console.print(f"\n[dim]Risultati completi salvati in backtest_results.json[/dim]")
