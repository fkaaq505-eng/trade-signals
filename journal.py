"""
Paper-trade journal — log YOUR actual paper trades and get the only numbers that
matter: real win rate, expectancy, net AFTER fees, profit factor, max drawdown.
Strategy-agnostic: tag each trade (meanrev / orb / ict / discretionary) and stats
can filter by tag. This is how you find out if ANY method — including a
discretionary TJR/ICT "feel" — actually has an edge for YOU. Numbers, not vibes.

Storage: a local CSV (default journal.csv, gitignored). Code is in the repo; your
trades stay on your machine. Append-only; stats recompute from the raw fields so
there is one source of truth and no drift.

    python journal.py add --strat meanrev --symbol SPY --side long \\
        --entry 756.5 --exit 761.2 --size 100 --in 2026-05-20 --out 2026-05-25
    python journal.py stats                 # all trades
    python journal.py stats --strat orb     # one strategy
    python journal.py list --last 10

NEVER places an order — it only records what you already did. Paper only.
"""

from __future__ import annotations

import argparse
import csv
import os
from datetime import date

FIELDS = ["logged_at", "strat", "symbol", "side", "entry", "exit",
          "size", "fee_bps", "date_in", "date_out", "note"]
SIDES = ("long", "short")


def _pnl(row: dict) -> tuple[float, float]:
    """(net_usd, net_pct) for one trade, fees on both legs. Recomputed from raw."""
    entry, exit_ = float(row["entry"]), float(row["exit"])
    size, fee_bps = float(row["size"]), float(row["fee_bps"])
    gross = (exit_ - entry) * size if row["side"] == "long" else (entry - exit_) * size
    fees = (entry + exit_) * size * (fee_bps / 10_000.0)
    net = gross - fees
    notional = entry * size
    return net, (100.0 * net / notional if notional else 0.0)


def _read(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def cmd_add(args) -> None:
    if args.side not in SIDES:
        raise SystemExit(f"--side must be long|short, got {args.side!r}")
    for name, val in (("entry", args.entry), ("exit", args.exit), ("size", args.size)):
        if val <= 0:
            raise SystemExit(f"--{name} must be > 0, got {val}")
    row = {
        "logged_at": date.today().isoformat(), "strat": args.strat.strip().lower(),
        "symbol": args.symbol.strip().upper(), "side": args.side,
        "entry": args.entry, "exit": args.exit, "size": args.size,
        "fee_bps": args.fee_bps, "date_in": args.date_in or date.today().isoformat(),
        "date_out": args.date_out or date.today().isoformat(), "note": args.note or "",
    }
    new = not os.path.exists(args.file)
    with open(args.file, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    net, pct = _pnl(row)
    print(f"logged: {row['strat']} {row['symbol']} {row['side']} "
          f"{args.entry}->{args.exit} x{args.size:g}  =>  {net:+.2f}$ ({pct:+.2f}%)")


def cmd_list(args) -> None:
    rows = _read(args.file)
    if args.strat:
        rows = [r for r in rows if r["strat"] == args.strat.lower()]
    rows = rows[-args.last:] if args.last else rows
    if not rows:
        print("no trades logged yet.")
        return
    print(f"{'in':>11}  {'strat':<10}{'sym':<5}{'side':<6}{'entry':>9}{'exit':>9}"
          f"{'size':>7}{'net$':>10}{'net%':>8}")
    for r in rows:
        net, pct = _pnl(r)
        print(f"{r['date_in']:>11}  {r['strat']:<10}{r['symbol']:<5}{r['side']:<6}"
              f"{float(r['entry']):>9.2f}{float(r['exit']):>9.2f}{float(r['size']):>7g}"
              f"{net:>10.2f}{pct:>8.2f}")


def cmd_stats(args) -> None:
    rows = _read(args.file)
    if args.strat:
        rows = [r for r in rows if r["strat"] == args.strat.lower()]
    if not rows:
        print("no trades to score. log one: python journal.py add --strat ... --entry ... --exit ...")
        return

    pnls = [_pnl(r) for r in rows]
    nets = [u for u, _ in pnls]
    pcts = [p for _, p in pnls]
    wins = [u for u in nets if u > 0]
    losses = [u for u in nets if u <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    equity = peak = dd = 0.0
    for u in nets:                     # drawdown in $ across the trade sequence
        equity += u
        peak = max(peak, equity)
        dd = min(dd, equity - peak)

    n = len(rows)
    tag = f" [{args.strat}]" if args.strat else ""
    print(f"\n=== JOURNAL STATS{tag} — {n} trades ===")
    print(f"  win_rate_%        {100.0 * len(wins) / n:.1f}")
    print(f"  expectancy_%/trd  {sum(pcts) / n:+.2f}   (avg net % per trade; >0 = edge)")
    print(f"  net_total_$       {sum(nets):+.2f}")
    print(f"  profit_factor     {gross_win / gross_loss:.2f}" if gross_loss else
          f"  profit_factor     inf (no losers yet)")
    print(f"  avg_win_$         {sum(wins) / len(wins):+.2f}" if wins else "  avg_win_$         n/a")
    print(f"  avg_loss_$        {sum(losses) / len(losses):+.2f}" if losses else "  avg_loss_$        n/a")
    print(f"  max_drawdown_$    {dd:.2f}")
    print("\n  Honest: expectancy > 0 AND a profit_factor > ~1.3 over 30+ trades is a "
          "real edge.\n  A high win rate with negative expectancy = the win-rate trap.")


def main() -> None:
    p = argparse.ArgumentParser(description="Paper-trade journal (record-only, never trades).")
    p.add_argument("--file", default="journal.csv", help="journal CSV path (default journal.csv)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="log a closed paper trade")
    a.add_argument("--strat", required=True)
    a.add_argument("--symbol", required=True)
    a.add_argument("--side", required=True, choices=SIDES)
    a.add_argument("--entry", type=float, required=True)
    a.add_argument("--exit", type=float, required=True)
    a.add_argument("--size", type=float, required=True, help="shares/contracts")
    a.add_argument("--fee-bps", type=float, default=1.0, dest="fee_bps")
    a.add_argument("--in", dest="date_in", default=None)
    a.add_argument("--out", dest="date_out", default=None)
    a.add_argument("--note", default=None)
    a.set_defaults(func=cmd_add)

    s = sub.add_parser("stats", help="real win/expectancy/net/PF/drawdown")
    s.add_argument("--strat", default=None)
    s.set_defaults(func=cmd_stats)

    li = sub.add_parser("list", help="show logged trades")
    li.add_argument("--strat", default=None)
    li.add_argument("--last", type=int, default=0)
    li.set_defaults(func=cmd_list)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
