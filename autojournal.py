"""
Auto-journal: the system logs its OWN signals' outcomes. For each completed
trading day it replays the ORB plan it would have pushed, checks the real bars to
see whether price hit the TARGET, the STOP, or neither (EOD-flat), and appends the
realized trade to journal.csv — no manual entry. Run it on a daily cron and the
journal becomes a true forward paper-test of the (no-backtested-edge) ORB push.

Idempotent: a day already in the journal is skipped, so re-running is safe. The
current (possibly unfinished) day is skipped until it closes.

    python autojournal.py                       # SPY 15m from Yahoo (recent ~60d)
    python autojournal.py --src spy_5m.csv       # backfill from a deep CSV
    python autojournal.py --journal /tmp/x.csv   # write to a different journal file

READ-ONLY on market data. Never places an order. Paper only.
"""

from __future__ import annotations

import argparse
import csv
import os
from datetime import date, datetime, timezone

import journal as J
from data import fetch
from data_csv import load_csv
from orb import ACCOUNT, RISK_PCT, RR, backtest_orb_records
from sessions import in_session_mask


def _outcome(r: float) -> str:
    if abs(r - RR) < 1e-9:
        return "TP"
    if abs(r + 1.0) < 1e-9:
        return "SL"
    return "EOD-flat"


def _row_for(trade, today: str) -> dict:
    # Reconstruct the realized exit price from the gross R and 1R-in-points (rng).
    exit_px = (trade.entry + trade.r * trade.rng if trade.side == "long"
               else trade.entry - trade.r * trade.rng)
    size = (ACCOUNT * RISK_PCT / 100.0) / trade.rng if trade.rng > 0 else 0.0
    return {
        "logged_at": today, "strat": "orb", "symbol": "SPY", "side": trade.side,
        "entry": round(trade.entry, 2), "exit": round(exit_px, 2),
        "size": round(size, 2), "fee_bps": 1.0,
        "date_in": trade.date, "date_out": trade.date, "note": f"auto:{_outcome(trade.r)}",
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Auto-log ORB signal outcomes to the journal.")
    p.add_argument("--src", default=None, help="CSV path; default = Yahoo SPY 15m")
    p.add_argument("--journal", default="journal_orb.csv",
                   help="auto-journal file (default journal_orb.csv; tracked in repo)")
    args = p.parse_args()

    df = load_csv(args.src) if args.src else fetch("SPY", "60d", "15m")
    df = df[in_session_mask(df.index, "us")]          # RTH only -> real 9:30 open range
    trades, _ = backtest_orb_records(df)

    seen = {(r["strat"], r["symbol"], r["date_in"]) for r in J._read(args.journal)}
    today = date.today().isoformat()
    # Log past days always; log TODAY only once the US session has closed
    # (>=21:00 UTC ~= 16:00-17:00 ET both DST), so we never log a half-finished day.
    post_close = datetime.now(timezone.utc).hour >= 21

    def loggable(d: str) -> bool:
        return (d < today or (d == today and post_close)) and ("orb", "SPY", d) not in seen

    rows = [_row_for(t, today) for t in trades if loggable(t.date)]

    if rows:
        new_file = not os.path.exists(args.journal)
        with open(args.journal, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=J.FIELDS)
            if new_file:
                w.writeheader()
            w.writerows(rows)

    print(f"auto-logged {len(rows)} new ORB trade(s) -> {args.journal}")
    for row in rows[-6:]:
        net, pct = J._pnl(row)
        print(f"  {row['date_in']} {row['side']:<5} {row['note']:<12} {net:+.2f}$ ({pct:+.2f}%)")
    if rows:
        print(f"\n  see the running record: python journal.py --file {args.journal} stats --strat orb")


if __name__ == "__main__":
    main()
