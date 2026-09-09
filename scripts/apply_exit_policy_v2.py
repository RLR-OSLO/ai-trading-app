from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


portfolio_path = Path("trader/portfolio_live.py")
portfolio = portfolio_path.read_text(encoding="utf-8")

portfolio = replace_once(
    portfolio,
    'SCALP_STOP_FRACTION = Decimal("0.0075")\nSCALP_TARGET_FRACTION = Decimal("0.0060")\nSCALP_MAX_HOLD_SECONDS = 1800\n',
    'SCALP_STOP_FRACTION = Decimal("0.0060")\nSCALP_TARGET_FRACTION = Decimal("0.0080")\nSCALP_MAX_HOLD_SECONDS = 2700\n',
    "scalp risk/reward constants",
)
portfolio = replace_once(
    portfolio,
    'SCALP_TIMEOUT_PROFIT_FRACTION = Decimal("0.0025")\n',
    'SCALP_TIMEOUT_PROFIT_FRACTION = Decimal("0.0040")\nSCALP_TIMEOUT_MAX_LOSS_FRACTION = Decimal("0.0030")\nSCALP_BREAKEVEN_LOCK_FRACTION = Decimal("0.0035")\n',
    "scalp timeout constants",
)

old_timeout = '''            if age >= position.max_hold_seconds * 2:\n                if position.protective_order_list_id is not None and not _cancel_protection(client, state, state_path, position):\n                    notes.append(f"scalp_hard_timeout_cancel_failed:{position.symbol}")\n                    continue\n                return _market_sell(client, state, state_path, position, limits, report_trade, now, "hard_timeout")\n'''
new_timeout = '''            # Do not force-sell a scalp at a material loss just because a timer expired.\n            # Time exit is allowed only after the entry signal has disappeared and the\n            # position is close to flat. A genuinely bad trade is still bounded by the\n            # hard stop below. This prevents repeated small timer-driven losses.\n            if (\n                age >= position.max_hold_seconds * 2\n                and not signals.get(position.symbol, False)\n                and current >= entry * (Decimal("1") - SCALP_TIMEOUT_MAX_LOSS_FRACTION)\n            ):\n                if position.protective_order_list_id is not None and not _cancel_protection(client, state, state_path, position):\n                    notes.append(f"scalp_signal_timeout_cancel_failed:{position.symbol}")\n                    continue\n                return _market_sell(client, state, state_path, position, limits, report_trade, now, "signal_timeout")\n'''
portfolio = replace_once(portfolio, old_timeout, new_timeout, "scalp timeout logic")

portfolio = replace_once(
    portfolio,
    '            trailing_stop = peak * (Decimal("1") - trailing_gap)\n            position.trailing_stop_price = str(trailing_stop)\n',
    '            trailing_stop = peak * (Decimal("1") - trailing_gap)\n            if position.strategy == "scalp":\n                trailing_stop = max(trailing_stop, entry * (Decimal("1") + SCALP_BREAKEVEN_LOCK_FRACTION))\n            position.trailing_stop_price = str(trailing_stop)\n',
    "initial trailing profit floor",
)
portfolio = replace_once(
    portfolio,
    '                new_stop = new_peak * (Decimal("1") - trailing_gap)\n                position.peak_price = str(new_peak)\n',
    '                new_stop = new_peak * (Decimal("1") - trailing_gap)\n                if position.strategy == "scalp":\n                    new_stop = max(new_stop, entry * (Decimal("1") + SCALP_BREAKEVEN_LOCK_FRACTION))\n                position.peak_price = str(new_peak)\n',
    "raised trailing profit floor",
)
portfolio_path.write_text(portfolio, encoding="utf-8")

scalp_path = Path("trader/scalping.py")
scalp = scalp_path.read_text(encoding="utf-8")
scalp = replace_once(
    scalp,
    '    if volume_ratio >= (Decimal("1.05") if aggressive else Decimal("1.15")):\n',
    '    if volume_ratio >= (Decimal("1.10") if aggressive else Decimal("1.15")):\n',
    "aggressive volume filter",
)
scalp = replace_once(
    scalp,
    '    if momentum >= (Decimal("0.08") if aggressive else Decimal("0.15")):\n',
    '    if momentum >= (Decimal("0.12") if aggressive else Decimal("0.15")):\n',
    "aggressive momentum filter",
)
scalp = replace_once(
    scalp,
    '    threshold = 5 if aggressive else 6\n',
    '    threshold = 6\n',
    "aggressive score threshold",
)
scalp_path.write_text(scalp, encoding="utf-8")

test_path = Path("tests/test_portfolio_live.py")
tests = test_path.read_text(encoding="utf-8")
tests = replace_once(tests, '        self.assertEqual(position.stop_fraction, "0.0075")\n        self.assertEqual(position.target_fraction, "0.0060")\n        self.assertEqual(position.max_hold_seconds, 1800)\n', '        self.assertEqual(position.stop_fraction, "0.0060")\n        self.assertEqual(position.target_fraction, "0.0080")\n        self.assertEqual(position.max_hold_seconds, 2700)\n', "scalp limits test")

anchor = '''    def test_high_profile_is_aggressive_but_bounded(self):\n'''
extra = '''    def test_expired_scalp_does_not_force_sell_material_loss(self):\n        client = FakeClient()\n        with tempfile.TemporaryDirectory() as directory:\n            path = Path(directory) / "state.json"\n            run_portfolio_cycle(\n                client,\n                {"BTCUSDC": True},\n                path,\n                self.limits(),\n                entry_strategies={"BTCUSDC": "scalp"},\n            )\n            state = load_state(path)\n            state.positions[0].opened_at = int(__import__("time").time()) - 5600\n            state.cooldown_until = 0\n            save_state(path, state)\n            client.price = Decimal("99.50")\n            result = run_portfolio_cycle(client, {"BTCUSDC": False}, path, self.limits())\n            final = load_state(path)\n        self.assertEqual(client.live_sells, 0)\n        self.assertEqual(len(final.positions), 1)\n        self.assertIn("holding:BTCUSDC", result)\n\n    def test_expired_scalp_can_exit_small_loss_after_signal_disappears(self):\n        client = FakeClient()\n        with tempfile.TemporaryDirectory() as directory:\n            path = Path(directory) / "state.json"\n            run_portfolio_cycle(\n                client,\n                {"BTCUSDC": True},\n                path,\n                self.limits(),\n                entry_strategies={"BTCUSDC": "scalp"},\n            )\n            state = load_state(path)\n            state.positions[0].opened_at = int(__import__("time").time()) - 5600\n            state.cooldown_until = 0\n            save_state(path, state)\n            client.price = Decimal("99.80")\n            result = run_portfolio_cycle(client, {"BTCUSDC": False}, path, self.limits())\n        self.assertIn("reason=signal_timeout", result)\n        self.assertEqual(client.live_sells, 1)\n\n'''
tests = replace_once(tests, anchor, extra + anchor, "new timeout tests")
test_path.write_text(tests, encoding="utf-8")

print("Applied exit policy v2")
