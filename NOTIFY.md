# Phone notifications when you're away (no laptop needed)

Goal: get a push on your phone near the US close when the strategy flags
**BUY** or **SELL/EXIT** — even with your laptop shut. The check runs on
GitHub's free servers (GitHub Actions cron), not your machine.

Stack: **ntfy.sh** (free push, no account) + **GitHub Actions** (free cron).
It only notifies. It never places a trade.

## 1. Set up the phone push (2 min)

1. Install the **ntfy** app — [iOS](https://apps.apple.com/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy).
2. Pick a **private, hard-to-guess topic name** (anyone who knows it can read your
   pushes), e.g. `nema-trades-9x7k2f`.
3. In the app: **+** → subscribe to that topic.

## 2. Test it locally first

```bash
cd ~/trade-signals
NTFY_TOPIC=nema-trades-9x7k2f .venv/bin/python notify.py --force
```

`--force` skips the time gate so you can test any time. Your phone should buzz.
Without `NTFY_TOPIC` it runs in dry-run and just prints what it *would* send.

## 3. Put the code on GitHub

```bash
cd ~/trade-signals
git init && git add . && git commit -m "trade signal tool + notifier"
# create an EMPTY repo on github.com first, then:
git remote add origin https://github.com/<you>/trade-signals.git
git branch -M main && git push -u origin main
```

> `.venv/` is ignored via `.gitignore` — only source goes up, no secrets.

## 4. Add your topic as a secret

GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**
- Name: `NTFY_TOPIC`
- Value: `nema-trades-9x7k2f`

## 5. Done

The workflow [`.github/workflows/signal.yml`](.github/workflows/signal.yml) runs
weekdays near the US close. When SPY or QQQ flags BUY or SELL/EXIT, your phone
buzzes. Run it manually any time from the repo's **Actions** tab → *Run workflow*.

## Notes / honesty

- **GitHub cron can be delayed** 5–15 min under load. The notifier accepts a
  ~40-min window around the close, so that's usually fine.
- Daily strategies read the day's *provisional* close ~15 min early. Good enough
  for a near-close decision; a purist acts on the actual close.
- The push tells you what the **rules** say. You still open your broker/paper
  account and decide. This never trades for you.
- Prefer Telegram or Pushover instead of ntfy? Swap the `push()` function in
  [`notify.py`](notify.py) — it's ~6 lines.
