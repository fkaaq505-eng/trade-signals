# Phone notifications when you're away (no laptop needed)

Goal: get a push on your phone for SPY/QQQ signals — even with your laptop shut.
The check runs on GitHub's free servers (GitHub Actions cron), not your machine.

Stack: **ntfy.sh** (free push, no account) + **GitHub Actions** (free cron) +
Yahoo data (free). **Total cost: $0.** It only notifies — never places a trade.

### Two pushes a day, set for Saudi time (AST = UTC+3)

| push | when (AST) | what |
|------|-----------|------|
| **Close alert** | ~23:00 (summer) / 00:00 (winter) | only if a signal = BUY or SELL/EXIT — fires at the US close |
| **Morning brief** | **08:00** | always — a status recap so you can act at the next US open (~16:30/17:30 AST), a civil hour |

Connors RSI(2) decides at the US *close*. If 23:00/midnight is too late, just act
on the **morning brief** at the next US open — same signal, daytime.

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

The workflow [`.github/workflows/signal.yml`](.github/workflows/signal.yml) now
runs on its own: a **close alert** (when a signal fires) and an **08:00 AST
morning brief** (always). Test it now from the repo's **Actions** tab →
*trade-signal-notify* → *Run workflow* — that sends a brief to your phone
immediately.

> **Keeping it free:** GitHub Actions is free for public repos (unlimited) and
> ~2000 min/month on private — this uses ~60. **Note:** GitHub auto-pauses
> scheduled workflows after **60 days of no commits** to the repo; push any small
> change (or hit *Run workflow*) occasionally to keep it alive.

## Notes / honesty

- **GitHub cron can be delayed** 5–15 min under load. The notifier accepts a
  ~40-min window around the close, so that's usually fine.
- Daily strategies read the day's *provisional* close ~15 min early. Good enough
  for a near-close decision; a purist acts on the actual close.
- The push tells you what the **rules** say. You still open your broker/paper
  account and decide. This never trades for you.
- Prefer Telegram or Pushover instead of ntfy? Swap the `push()` function in
  [`notify.py`](notify.py) — it's ~6 lines.
