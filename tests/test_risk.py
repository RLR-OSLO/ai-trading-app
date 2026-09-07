import unittest
from decimal import Decimal

from trader.bullrun import MarketRegime, exit_plan_for_regime, validate_exit_plan
from trader.config import DEFAULT_CONFIG
from trader.risk import (
    build_risk_budget,
    position_notional_for_stop,
    profit_to_lock,
    should_pause_for_drawdown,
)


class RiskTests(unittest.TestCase):
    def test_normal_profile_for_6000_nok(self) -> None:
        budget = build_risk_budget(Decimal("6000"), DEFAULT_CONFIG)
        self.assertEqual(budget.protected_reserve, Decimal("1200.00"))
        self.assertEqual(budget.active_capital, Decimal("4800.00"))
        self.assertEqual(budget.max_loss_per_trade, Decimal("30.00"))
        self.assertEqual(budget.max_daily_loss, Decimal("120.00"))
        self.assertEqual(budget.hard_drawdown_amount, Decimal("480.00"))

    def test_position_size_is_capped(self) -> None:
        notional = position_notional_for_stop(
            equity=Decimal("6000"),
            entry_price=Decimal("100"),
            stop_price=Decimal("98"),
            config=DEFAULT_CONFIG,
        )
        self.assertEqual(notional, Decimal("1500.00"))

    def test_hard_drawdown_pause(self) -> None:
        self.assertTrue(
            should_pause_for_drawdown(
                Decimal("5520"), Decimal("6000"), DEFAULT_CONFIG
            )
        )

    def test_weekly_profit_lock(self) -> None:
        self.assertEqual(
            profit_to_lock(Decimal("400"), DEFAULT_CONFIG), Decimal("100.00")
        )

    def test_bullrun_plans_allocate_whole_position(self) -> None:
        for regime in MarketRegime:
            validate_exit_plan(exit_plan_for_regime(regime))

    def test_strong_bull_keeps_larger_runner(self) -> None:
        plan = exit_plan_for_regime(MarketRegime.STRONG_BULL)
        self.assertEqual(plan.runner_fraction, Decimal("0.65"))
        self.assertEqual(plan.trailing_atr_multiple, Decimal("3.5"))


if __name__ == "__main__":
    unittest.main()
