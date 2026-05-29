"""
News + event-risk awareness. All stdlib, no extra deps, no key required for the
core features (free).

Why this exists: research shows mean-reversion strategies misbehave around
high-impact macro events (FOMC, CPI, NFP) — those create sustained directional
moves that don't revert intraday. So we (a) surface fresh headlines and (b) flag
high-impact days so you can stand aside or expect whipsaw.
Refs: buildalpha.com/news-event-trading , proptradingvibes.com mean-reversion.

Data sources:
  - Headlines: Yahoo Finance RSS (keyless, free).
  - Events: built-in 2026 FOMC schedule (federalreserve.gov) + NFP rule
    (first Friday). Optionally Finnhub's economic calendar if FINNHUB_KEY is set
    (free key at finnhub.io); degrades silently if unavailable.
"""

from __future__ import annotations

import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

# 2026 FOMC announcement days (2nd meeting day, 14:00 ET). Source: federalreserve.gov.
# Update yearly when the Fed publishes the next calendar.
FOMC_DAYS = {
    date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29), date(2026, 6, 17),
    date(2026, 7, 29), date(2026, 9, 16), date(2026, 10, 28), date(2026, 12, 9),
}

_UA = {"User-Agent": "Mozilla/5.0 (trade-signals notifier)"}


def is_nfp_day(d: date) -> bool:
    """US Non-Farm Payrolls: first Friday of the month, 08:30 ET."""
    return d.weekday() == 4 and d.day <= 7


def fetch_headlines(symbols: list[str], limit: int = 3, timeout: int = 10) -> list[str]:
    """Top recent headlines for the symbols via Yahoo RSS. Empty list on failure."""
    q = ",".join(symbols)
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={q}&region=US&lang=en-US"
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            root = ET.fromstring(resp.read())
        titles = [it.findtext("title", "").strip() for it in root.findall(".//item")]
        return [t for t in titles if t][:limit]
    except Exception:
        return []


def _finnhub_events(day: date, key: str, timeout: int = 10) -> list[str]:
    """High-impact US events for `day` from Finnhub, if a key is set. [] otherwise."""
    if not key:
        return []
    url = f"https://finnhub.io/api/v1/calendar/economic?token={key}"
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        rows = data.get("economicCalendar") or data.get("data") or []
        out = []
        for e in rows:
            same_day = str(e.get("time", "")).startswith(str(day))
            high = str(e.get("impact", "")).lower() in ("high", "3")
            if e.get("country") == "US" and same_day and high:
                out.append(str(e.get("event", "")).strip())
        return [x for x in out if x]
    except Exception:
        return []


def high_impact_events(day: date, finnhub_key: str | None = None) -> list[str]:
    """Labels of high-impact macro events on `day` (empty = clear)."""
    labels: list[str] = []
    if day in FOMC_DAYS:
        labels.append("FOMC rate decision (14:00 ET)")
    if is_nfp_day(day):
        labels.append("NFP jobs report (08:30 ET)")
    labels += _finnhub_events(day, finnhub_key or os.environ.get("FINNHUB_KEY", ""))
    return labels


def news_block(symbols: list[str], day: date,
               finnhub_key: str | None = None) -> str:
    """A ready-to-append text block: event warning + headlines."""
    parts: list[str] = []
    events = high_impact_events(day, finnhub_key)
    if events:
        parts.append("HIGH-IMPACT TODAY: " + ", ".join(events) +
                     "\n  -> mean reversion unreliable here; expect whipsaw, consider standing aside.")
    heads = fetch_headlines(symbols)
    if heads:
        parts.append("News:\n" + "\n".join(f"  - {h}" for h in heads))
    return "\n".join(parts)
