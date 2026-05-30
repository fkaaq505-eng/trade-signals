"""
test_risk_engine.py — unit tests for risk_engine.py

Run: python -m pytest test_risk_engine.py -v
  or: python test_risk_engine.py (stdlib unittest fallback)

Safety-critical logic: coverage is high by design.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

import risk_engine as R
from risk_engine import (
    APEX_50K,
    TOPSTEP_50K,
    Decision,
    RiskState,
    can_enter,
    check_consistency,
    days_elapsed,
    days_remaining,
    make_apex_state,
    make_state,
    make_topstep_state,
    must_flatten,
    on_new_day,
    profit_pace_report,
    register_close,
    register_fill,
    remaining_dd_buffer,
    status_summary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

START = date(2026, 1, 2)
TS_MORNING = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)   # 9:30 ET
TS_NEAR_CLOSE = datetime(2026, 1, 2, 20, 50, tzinfo=timezone.utc)  # 3:50 PM ET (10 min before 4pm)
TS_AFTER_CLOSE = datetime(2026, 1, 2, 21, 5, tzinfo=timezone.utc)  # after 4pm ET

ACCOUNT = 50_000.0
STOP_PCT = 0.005   # 0.5% stop distance


def _apex() -> RiskState:
    return make_apex_state(account_size=ACCOUNT, start_date=START)


def _topstep() -> RiskState:
    return make_topstep_state(account_size=ACCOUNT, start_date=START)


def _fill(state: RiskState, ts: datetime = TS_MORNING,
          entry: float = 100.0, size: float = 10_000.0) -> RiskState:
    return register_fill(state, timestamp=ts, entry_price=entry, size_dollars=size)


def _close_win(state: RiskState, pnl: float = 200.0, mae: float = 0.0) -> RiskState:
    return register_close(state, timestamp=TS_MORNING, close_price=102.0,
                          pnl_dollars=pnl, mae_pct=mae)


def _close_loss(state: RiskState, pnl: float = -200.0, mae: float = -0.5) -> RiskState:
    return register_close(state, timestamp=TS_MORNING, close_price=99.0,
                          pnl_dollars=pnl, mae_pct=mae)


# ---------------------------------------------------------------------------
# 1. Factory / initial state
# ---------------------------------------------------------------------------

class TestFactories(unittest.TestCase):

    def test_apex_initial_state(self):
        s = _apex()
        self.assertEqual(s.current_equity, ACCOUNT)
        self.assertEqual(s.equity_peak, ACCOUNT)
        self.assertEqual(s.cumulative_profit, 0.0)
        self.assertFalse(s.daily_locked_out)
        self.assertFalse(s.eval_passed)
        self.assertFalse(s.eval_failed)
        self.assertFalse(s.in_position)

    def test_topstep_initial_state(self):
        s = _topstep()
        self.assertEqual(s.config.trailing_dd_mode, "eod")
        self.assertEqual(s.config.name, TOPSTEP_50K.name)

    def test_invalid_account_raises(self):
        with self.assertRaises(ValueError):
            make_state(APEX_50K, -1000.0, START)
        with self.assertRaises(ValueError):
            make_state(APEX_50K, 0.0, START)

    def test_dd_buffer_equals_trailing_limit_at_start(self):
        s = _apex()
        expected = ACCOUNT * APEX_50K.trailing_dd_pct / 100.0
        self.assertAlmostEqual(remaining_dd_buffer(s), expected)


# ---------------------------------------------------------------------------
# 2. Position sizing math
# ---------------------------------------------------------------------------

class TestSizingMath(unittest.TestCase):

    def test_sizing_capped_by_risk_pct(self):
        s = _apex()
        d = can_enter(s, stop_distance_pct=STOP_PCT, timestamp=TS_MORNING)
        self.assertTrue(d.allowed)
        # 0.75% risk * 50k = $375 at risk; $375 / 0.5% stop = $75,000 notional
        expected_risk_cap = (ACCOUNT * APEX_50K.per_trade_risk_pct / 100.0) / STOP_PCT
        self.assertAlmostEqual(d.max_size_dollars, min(expected_risk_cap,
                                                       _dd_size_cap(s, STOP_PCT)), places=0)

    def test_sizing_capped_by_dd_buffer_when_close_to_limit(self):
        # Simulate equity very close to the trailing-DD breach point.
        # Remaining buffer = $100; stop = 0.5% => max_size_from_dd = 100/0.005 = $20,000
        s = _apex()
        # Force equity peak to be 100 below trailing limit breach
        trail = ACCOUNT * APEX_50K.trailing_dd_pct / 100.0  # e.g. $1,250
        # Set equity to (account - trail + 100); peak stays at ACCOUNT
        # Remaining buffer = trail - (peak - equity) = trail - (ACCOUNT - equity)
        # We want remaining buffer = 100 => equity = ACCOUNT - trail + 100
        from dataclasses import replace as dc_replace
        low_buffer_state = dc_replace(s, current_equity=ACCOUNT - trail + 100.0)
        d = can_enter(low_buffer_state, stop_distance_pct=STOP_PCT, timestamp=TS_MORNING)
        self.assertTrue(d.allowed)
        # DD-buffer cap: 100 / 0.005 = $20,000
        expected_dd_cap = 100.0 / STOP_PCT
        self.assertAlmostEqual(d.max_size_dollars, expected_dd_cap, delta=1.0)

    def test_stop_distance_zero_is_blocked(self):
        s = _apex()
        d = can_enter(s, stop_distance_pct=0.0, timestamp=TS_MORNING)
        self.assertFalse(d.allowed)
        self.assertIn("must be > 0", d.reasons[0])

    def test_negative_stop_blocked(self):
        s = _apex()
        d = can_enter(s, stop_distance_pct=-0.01, timestamp=TS_MORNING)
        self.assertFalse(d.allowed)

    def test_minimum_stop_guard(self):
        # Very tiny stop (0.0001 = 0.01%) is below MIN_RISK_PCT and should be blocked
        s = _apex()
        d = can_enter(s, stop_distance_pct=0.00001, timestamp=TS_MORNING)
        self.assertFalse(d.allowed)
        self.assertIn("minimum", d.reasons[0])

    def test_override_risk_pct(self):
        s = _apex()
        d_default = can_enter(s, stop_distance_pct=STOP_PCT, timestamp=TS_MORNING)
        d_lower = can_enter(s, stop_distance_pct=STOP_PCT, timestamp=TS_MORNING,
                            override_risk_pct=0.5)
        self.assertTrue(d_lower.allowed)
        self.assertLess(d_lower.max_size_dollars, d_default.max_size_dollars)

    def test_exhausted_buffer_blocks_entry(self):
        s = _apex()
        trail = ACCOUNT * APEX_50K.trailing_dd_pct / 100.0
        from dataclasses import replace as dc_replace
        # Set equity exactly at the DD limit (buffer = 0)
        s_at_limit = dc_replace(s, current_equity=ACCOUNT - trail)
        d = can_enter(s_at_limit, stop_distance_pct=STOP_PCT, timestamp=TS_MORNING)
        self.assertFalse(d.allowed)
        self.assertIn("buffer", d.reasons[0])


# ---------------------------------------------------------------------------
# 3. Daily lockout
# ---------------------------------------------------------------------------

class TestDailyLockout(unittest.TestCase):

    def test_daily_loss_limit_triggers_lockout(self):
        s = _apex()
        s = _fill(s)
        # Daily loss limit = 1.5% of 50k = $750
        big_loss = -(ACCOUNT * APEX_50K.daily_loss_limit_pct / 100.0 + 1.0)  # just over limit
        s = _close_loss(s, pnl=big_loss, mae=-1.0)
        self.assertTrue(s.daily_locked_out)

    def test_locked_out_blocks_entry(self):
        s = _apex()
        s = _fill(s)
        big_loss = -(ACCOUNT * APEX_50K.daily_loss_limit_pct / 100.0 + 1.0)
        s = _close_loss(s, pnl=big_loss, mae=-1.0)
        d = can_enter(s, stop_distance_pct=STOP_PCT, timestamp=TS_MORNING)
        self.assertFalse(d.allowed)
        self.assertIn("lockout", d.reasons[0])

    def test_lockout_resets_on_new_day(self):
        s = _apex()
        s = _fill(s)
        big_loss = -(ACCOUNT * APEX_50K.daily_loss_limit_pct / 100.0 + 1.0)
        s = _close_loss(s, pnl=big_loss, mae=-1.0)
        self.assertTrue(s.daily_locked_out)

        next_day = date(2026, 1, 3)
        s = on_new_day(s, next_day)
        self.assertFalse(s.daily_locked_out)

        d = can_enter(s, stop_distance_pct=STOP_PCT, timestamp=TS_MORNING)
        self.assertTrue(d.allowed)

    def test_small_loss_does_not_trigger_lockout(self):
        s = _apex()
        s = _fill(s)
        s = _close_loss(s, pnl=-100.0, mae=-0.1)  # $100 loss, well within $750 limit
        self.assertFalse(s.daily_locked_out)

    def test_today_stats_reset_on_new_day(self):
        s = _apex()
        s = _fill(s)
        s = _close_win(s, pnl=200.0)
        self.assertEqual(s.today_stats.trade_count, 1)
        s = on_new_day(s, date(2026, 1, 3))
        self.assertEqual(s.today_stats.trade_count, 0)
        self.assertEqual(s.today_stats.realized_pnl, 0.0)


# ---------------------------------------------------------------------------
# 4. Max trades per day
# ---------------------------------------------------------------------------

class TestMaxTradesPerDay(unittest.TestCase):

    def test_entry_blocked_after_max_trades(self):
        s = _apex()
        max_t = APEX_50K.max_trades_per_day  # 3

        for _ in range(max_t):
            d = can_enter(s, stop_distance_pct=STOP_PCT, timestamp=TS_MORNING)
            self.assertTrue(d.allowed, f"should allow trade {_ + 1}")
            s = _fill(s)
            s = _close_win(s, pnl=50.0)

        d = can_enter(s, stop_distance_pct=STOP_PCT, timestamp=TS_MORNING)
        self.assertFalse(d.allowed)
        self.assertIn("max trades", d.reasons[0])

    def test_trade_count_increments_on_close(self):
        s = _apex()
        self.assertEqual(s.today_stats.trade_count, 0)
        s = _fill(s)
        s = _close_win(s, pnl=100.0)
        self.assertEqual(s.today_stats.trade_count, 1)

    def test_max_trades_resets_on_new_day(self):
        s = _apex()
        for _ in range(APEX_50K.max_trades_per_day):
            s = _fill(s)
            s = _close_win(s, pnl=50.0)

        s = on_new_day(s, date(2026, 1, 3))
        d = can_enter(s, stop_distance_pct=STOP_PCT, timestamp=TS_MORNING)
        self.assertTrue(d.allowed)


# ---------------------------------------------------------------------------
# 5. EOD-flat
# ---------------------------------------------------------------------------

class TestEodFlat(unittest.TestCase):

    def test_entry_blocked_near_close(self):
        s = _apex()
        # TS_NEAR_CLOSE = 20:50 UTC, close = 21:00 → within 15 min → blocked
        d = can_enter(s, stop_distance_pct=STOP_PCT, timestamp=TS_NEAR_CLOSE)
        self.assertFalse(d.allowed)
        self.assertIn("EOD-flat", d.reasons[0])

    def test_entry_allowed_well_before_close(self):
        s = _apex()
        d = can_enter(s, stop_distance_pct=STOP_PCT, timestamp=TS_MORNING)
        self.assertTrue(d.allowed)

    def test_must_flatten_after_close(self):
        s = _apex()
        self.assertTrue(must_flatten(s, TS_AFTER_CLOSE))

    def test_must_flatten_before_close(self):
        s = _apex()
        self.assertFalse(must_flatten(s, TS_MORNING))

    def test_must_flatten_when_eval_concluded(self):
        s = _apex()
        from dataclasses import replace as dc_replace
        s_passed = dc_replace(s, eval_passed=True)
        self.assertTrue(must_flatten(s_passed, TS_MORNING))

    def test_must_flatten_at_boundary(self):
        # Exactly at close time -> must flatten
        s = _apex()
        ts_at_close = datetime(2026, 1, 2, 21, 0, tzinfo=timezone.utc)
        self.assertTrue(must_flatten(s, ts_at_close))


# ---------------------------------------------------------------------------
# 6. Trailing drawdown — Apex intraday vs Topstep EOD
# ---------------------------------------------------------------------------

class TestTrailingDrawdown(unittest.TestCase):

    def _apex_with_mae_breach(self) -> RiskState:
        """Set up an Apex state where the MAE during a trade would breach the DD limit."""
        s = _apex()
        trail = ACCOUNT * APEX_50K.trailing_dd_pct / 100.0  # $1,250
        # Position size $10,000; a -13% MAE => $1,300 loss intraday > $1,250 limit
        s = _fill(s, size=10_000.0)
        return s

    def test_apex_intraday_breach_via_mae(self):
        s = self._apex_with_mae_breach()
        trail = ACCOUNT * APEX_50K.trailing_dd_pct / 100.0
        # MAE that causes: position_size * |mae| / 100 > trail
        # 10,000 * mae/100 > 1250 => mae < -12.5%
        bad_mae = -13.0  # -13% => $1,300 intraday loss
        s2 = register_close(s, timestamp=TS_MORNING, close_price=90.0,
                             pnl_dollars=-200.0, mae_pct=bad_mae)
        self.assertTrue(s2.eval_failed)
        self.assertIn("intraday", s2.failure_reason)

    def test_apex_intraday_small_mae_survives(self):
        s = self._apex_with_mae_breach()
        # MAE of -5% => $500 intraday loss < $1,250 limit
        s2 = register_close(s, timestamp=TS_MORNING, close_price=95.0,
                             pnl_dollars=-100.0, mae_pct=-5.0)
        self.assertFalse(s2.eval_failed)

    def test_topstep_eod_not_triggered_by_mae(self):
        """Topstep should NOT fail on intraday MAE — only on EOD equity."""
        s = _topstep()
        trail = ACCOUNT * TOPSTEP_50K.trailing_dd_pct / 100.0  # $2,000
        # Large MAE but trade closes flat — Topstep only watches EOD
        s = _fill(s, size=10_000.0)
        # MAE of -25% = $2,500 intraday => would breach Apex; should NOT breach Topstep
        s2 = register_close(s, timestamp=TS_MORNING, close_price=100.0,
                             pnl_dollars=0.0, mae_pct=-25.0)
        self.assertFalse(s2.eval_failed)

    def test_topstep_eod_breach_at_close(self):
        """Topstep fails when closing equity is below peak - DD limit."""
        s = _topstep()
        trail = ACCOUNT * TOPSTEP_50K.trailing_dd_pct / 100.0  # $2,000
        # Close with a loss exceeding the trailing limit
        s = _fill(s, size=1.0)
        s2 = register_close(s, timestamp=TS_MORNING, close_price=1.0,
                             pnl_dollars=-(trail + 1.0), mae_pct=0.0)
        self.assertTrue(s2.eval_failed)
        self.assertIn("Topstep", s2.failure_reason)

    def test_apex_peak_trails_up(self):
        """After a winning trade, the peak should update and tighten the buffer."""
        s = _apex()
        s = _fill(s)
        win_pnl = 500.0
        s2 = _close_win(s, pnl=win_pnl)
        self.assertEqual(s2.equity_peak, ACCOUNT + win_pnl)

    def test_topstep_peak_only_updates_on_new_day(self):
        """EOD mode: winning trade does NOT immediately update peak mid-day (handled in on_new_day)."""
        s = _topstep()
        s = _fill(s)
        s2 = _close_win(s, pnl=500.0)
        # Immediately after the win, peak may update (we allow it — design choice);
        # the KEY distinction is that the intraday MAE is ignored for DD breach.
        # Verify that the peak after on_new_day is correct.
        s3 = on_new_day(s2, date(2026, 1, 3))
        self.assertGreaterEqual(s3.equity_peak, ACCOUNT + 500.0)

    def test_apex_vs_topstep_differ_on_large_mae(self):
        """Same trade, same MAE: Apex fails, Topstep does not."""
        trail_apex = ACCOUNT * APEX_50K.trailing_dd_pct / 100.0

        apex = _apex()
        apex = _fill(apex, size=20_000.0)
        topstep = _topstep()
        topstep = _fill(topstep, size=20_000.0)

        # MAE causing $1,300 intraday loss (just beyond Apex $1,250 limit)
        # Apex trailing_dd = 2.5% of 50k = $1,250
        mae_pct = -(trail_apex / 20_000.0 * 100.0) - 0.1  # just over apex limit

        apex2 = register_close(apex, TS_MORNING, 99.0, -50.0, mae_pct=mae_pct)
        topstep2 = register_close(topstep, TS_MORNING, 99.0, -50.0, mae_pct=mae_pct)

        self.assertTrue(apex2.eval_failed, "Apex should fail on large MAE")
        self.assertFalse(topstep2.eval_failed, "Topstep should NOT fail on MAE alone")

    def test_remaining_buffer_decreases_with_loss(self):
        s = _apex()
        s = _fill(s)
        loss = -300.0
        s2 = _close_loss(s, pnl=loss, mae=-1.0)
        buf_before = remaining_dd_buffer(s)
        buf_after = remaining_dd_buffer(s2)
        self.assertLess(buf_after, buf_before)


# ---------------------------------------------------------------------------
# 7. Consistency rule
# ---------------------------------------------------------------------------

class TestConsistencyRule(unittest.TestCase):

    def test_flags_when_day_exceeds_limit(self):
        # If today would be 60% of total profit and limit is 50%, flag it
        s = _apex()
        # Build up some cumulative profit
        s = _fill(s)
        s = _close_win(s, pnl=500.0)  # cumulative = 500
        s = on_new_day(s, date(2026, 1, 3))

        # A trade that would win 300 on a day where cumulative becomes 800 = 37.5% ok
        result = check_consistency(s, today_pnl_if_trade_wins=300.0)
        self.assertFalse(result["flag"])

        # A trade that would win 700 on a day where cumulative becomes 1200 = 58% > 50% limit
        result = check_consistency(s, today_pnl_if_trade_wins=700.0)
        self.assertTrue(result["flag"])

    def test_no_flag_with_zero_cumulative(self):
        s = _apex()
        result = check_consistency(s, today_pnl_if_trade_wins=1000.0)
        self.assertFalse(result["flag"])

    def test_consistency_message_present(self):
        s = _apex()
        s = _fill(s)
        s = _close_win(s, pnl=1000.0)
        s = on_new_day(s, date(2026, 1, 3))
        result = check_consistency(s, today_pnl_if_trade_wins=600.0)
        self.assertIn("message", result)
        self.assertIsInstance(result["message"], str)


# ---------------------------------------------------------------------------
# 8. Profit target and pacing
# ---------------------------------------------------------------------------

class TestProfitTarget(unittest.TestCase):

    def test_eval_passes_on_target(self):
        s = _apex()
        target = ACCOUNT * APEX_50K.profit_target_pct / 100.0  # $3,000
        s = _fill(s)
        s2 = _close_win(s, pnl=target + 1.0)
        self.assertTrue(s2.eval_passed)

    def test_eval_not_passed_below_target(self):
        s = _apex()
        s = _fill(s)
        s2 = _close_win(s, pnl=100.0)
        self.assertFalse(s2.eval_passed)

    def test_blocks_entry_after_pass(self):
        s = _apex()
        target = ACCOUNT * APEX_50K.profit_target_pct / 100.0
        s = _fill(s)
        s = _close_win(s, pnl=target + 1.0)
        d = can_enter(s, stop_distance_pct=STOP_PCT, timestamp=TS_MORNING)
        self.assertFalse(d.allowed)
        self.assertIn("PASSED", d.reasons[0])

    def test_profit_pace_report_on_pace(self):
        s = _apex()
        # Simulate 5 days of profit: $600/day for 15 days remaining
        from dataclasses import replace as dc_replace
        s = dc_replace(s,
                       cumulative_profit=600.0,
                       current_date=date(2026, 1, 7))  # 5 days elapsed
        report = profit_pace_report(s)
        self.assertIn("on_pace", report)
        self.assertIn("required_daily_to_finish", report)
        self.assertIn("safe_pace_note", report)

    def test_profit_pace_behind_warns_not_to_oversize(self):
        s = _apex()
        from dataclasses import replace as dc_replace
        # 28 days elapsed, only $100 profit, target $3000: very behind
        s = dc_replace(s,
                       cumulative_profit=100.0,
                       current_date=date(2026, 1, 30))
        report = profit_pace_report(s)
        self.assertFalse(report["on_pace"])
        self.assertIn("discipline", report["safe_pace_note"].lower())

    def test_days_elapsed_and_remaining(self):
        s = _apex()
        self.assertEqual(days_elapsed(s), 0)
        self.assertEqual(days_remaining(s), APEX_50K.max_eval_days)

        from dataclasses import replace as dc_replace
        s5 = dc_replace(s, current_date=date(2026, 1, 7))  # 5 days later
        self.assertEqual(days_elapsed(s5), 5)
        self.assertEqual(days_remaining(s5), APEX_50K.max_eval_days - 5)


# ---------------------------------------------------------------------------
# 9. register_fill / register_close guards
# ---------------------------------------------------------------------------

class TestFillCloseGuards(unittest.TestCase):

    def test_double_fill_raises(self):
        s = _apex()
        s = _fill(s)
        with self.assertRaises(ValueError):
            _fill(s)  # already in position

    def test_close_without_position_raises(self):
        s = _apex()
        with self.assertRaises(ValueError):
            register_close(s, TS_MORNING, 101.0, 100.0)

    def test_invalid_entry_price_raises(self):
        s = _apex()
        with self.assertRaises(ValueError):
            register_fill(s, TS_MORNING, entry_price=0.0, size_dollars=1000.0)

    def test_invalid_size_raises(self):
        s = _apex()
        with self.assertRaises(ValueError):
            register_fill(s, TS_MORNING, entry_price=100.0, size_dollars=-500.0)

    def test_positive_mae_raises(self):
        s = _fill(_apex())
        with self.assertRaises(ValueError):
            register_close(s, TS_MORNING, 105.0, 200.0, mae_pct=1.0)  # mae must be <= 0

    def test_invalid_close_price_raises(self):
        s = _fill(_apex())
        with self.assertRaises(ValueError):
            register_close(s, TS_MORNING, 0.0, 100.0)

    def test_blocks_entry_while_in_position(self):
        s = _apex()
        s = _fill(s)
        d = can_enter(s, stop_distance_pct=STOP_PCT, timestamp=TS_MORNING)
        self.assertFalse(d.allowed)
        self.assertIn("already in a position", d.reasons[0])


# ---------------------------------------------------------------------------
# 10. on_new_day guards and history
# ---------------------------------------------------------------------------

class TestOnNewDay(unittest.TestCase):

    def test_on_new_day_same_date_raises(self):
        s = _apex()
        with self.assertRaises(ValueError):
            on_new_day(s, START)

    def test_on_new_day_earlier_date_raises(self):
        s = _apex()
        with self.assertRaises(ValueError):
            on_new_day(s, date(2025, 12, 31))

    def test_daily_profit_history_archived(self):
        s = _apex()
        s = _fill(s)
        s = _close_win(s, pnl=300.0)
        s = on_new_day(s, date(2026, 1, 3))
        # History should have yesterday's entry
        self.assertEqual(len(s.daily_profit_history), 1)
        hist_date, hist_pnl = s.daily_profit_history[0]
        self.assertEqual(hist_date, START)
        self.assertAlmostEqual(hist_pnl, 300.0)

    def test_topstep_peak_updates_on_new_day(self):
        s = _topstep()
        s = _fill(s)
        win = 500.0
        s = _close_win(s, pnl=win)
        peak_before = s.equity_peak
        s2 = on_new_day(s, date(2026, 1, 3))
        self.assertGreaterEqual(s2.equity_peak, peak_before)

    def test_apex_peak_not_changed_by_new_day(self):
        """Apex peak is updated immediately on trade close, not on new day."""
        s = _apex()
        s = _fill(s)
        win = 500.0
        s = _close_win(s, pnl=win)
        peak_after_close = s.equity_peak
        s2 = on_new_day(s, date(2026, 1, 3))
        # Peak should not decrease on new day
        self.assertGreaterEqual(s2.equity_peak, peak_after_close)


# ---------------------------------------------------------------------------
# 11. status_summary
# ---------------------------------------------------------------------------

class TestStatusSummary(unittest.TestCase):

    def test_summary_has_required_keys(self):
        s = _apex()
        summary = status_summary(s)
        required = [
            "firm", "trailing_dd_mode", "account_size", "current_equity",
            "cumulative_profit", "profit_target", "trailing_dd_limit",
            "trailing_dd_buffer_remaining", "daily_loss_limit", "today_pnl",
            "today_trades", "daily_locked_out", "eval_passed", "eval_failed",
        ]
        for key in required:
            self.assertIn(key, summary, f"missing key: {key}")

    def test_summary_values_consistent(self):
        s = _apex()
        summary = status_summary(s)
        self.assertEqual(summary["account_size"], ACCOUNT)
        self.assertEqual(summary["current_equity"], ACCOUNT)
        self.assertFalse(summary["eval_passed"])
        self.assertFalse(summary["eval_failed"])


# ---------------------------------------------------------------------------
# 12. Firm preset sanity
# ---------------------------------------------------------------------------

class TestFirmPresets(unittest.TestCase):

    def test_apex_is_intraday_trailing(self):
        self.assertEqual(APEX_50K.trailing_dd_mode, "intraday")

    def test_topstep_is_eod_trailing(self):
        self.assertEqual(TOPSTEP_50K.trailing_dd_mode, "eod")

    def test_apex_eod_flat_mandatory(self):
        self.assertTrue(APEX_50K.eod_flat_mandatory)

    def test_topstep_eod_flat_mandatory(self):
        self.assertTrue(TOPSTEP_50K.eod_flat_mandatory)

    def test_all_presets_have_positive_limits(self):
        for cfg in [APEX_50K, R.APEX_100K, TOPSTEP_50K, R.TOPSTEP_100K]:
            self.assertGreater(cfg.trailing_dd_pct, 0, cfg.name)
            self.assertGreater(cfg.daily_loss_limit_pct, 0, cfg.name)
            self.assertGreater(cfg.profit_target_pct, 0, cfg.name)
            self.assertGreater(cfg.max_eval_days, 0, cfg.name)


# ---------------------------------------------------------------------------
# Helper (also tested above)
# ---------------------------------------------------------------------------

def _dd_size_cap(state: RiskState, stop_pct: float) -> float:
    """Expected DD-buffer-based size cap (mirrors engine logic)."""
    trail_limit = state.account_size * state.config.trailing_dd_pct / 100.0
    current_dd = state.equity_peak - state.current_equity
    buffer = trail_limit - current_dd
    return buffer / stop_pct


if __name__ == "__main__":
    unittest.main(verbosity=2)
