from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"Patch target not found: {label}")
    return text.replace(old, new, 1)


# 1) Reduce churn, widen scalp noise tolerance, and tighten profit lock.
p = Path("trader/portfolio_live.py")
t = p.read_text(encoding="utf-8")
t = replace_once(
    t,
    'PROFILE_LIMITS = {"low": (6, 1800, 1), "normal": (24, 180, 4), "high": (100, 15, 8)}\nSCALP_STOP_FRACTION = Decimal("0.0045")\nSCALP_TARGET_FRACTION = Decimal("0.0075")\nSCALP_MAX_HOLD_SECONDS = 900\nTRAILING_OCO_CEILING_FRACTION = Decimal("0.50")\nTRAILING_REFRESH_FRACTION = Decimal("0.001")',
    'PROFILE_LIMITS = {"low": (6, 1800, 1), "normal": (12, 300, 3), "high": (36, 90, 4)}\nSCALP_STOP_FRACTION = Decimal("0.0075")\nSCALP_TARGET_FRACTION = Decimal("0.0060")\nSCALP_MAX_HOLD_SECONDS = 1800\nTRAILING_OCO_CEILING_FRACTION = Decimal("0.50")\nTRAILING_REFRESH_FRACTION = Decimal("0.001")\nTRAILING_GAP_RATIO = Decimal("0.45")\nTRAILING_MIN_GAP_FRACTION = Decimal("0.0025")\nSCALP_TIMEOUT_PROFIT_FRACTION = Decimal("0.0025")',
    "portfolio constants",
)

# Remove the unconditional scalp liquidation. A scalp that is merely noisy
# should remain protected by its hard stop instead of being dumped at an arbitrary loss.
t = replace_once(
    t,
    '''        expired_scalp = position.strategy == "scalp" and position.max_hold_seconds is not None and now - position.opened_at >= position.max_hold_seconds\n        if expired_scalp:\n            if not _cancel_protection(client, state, state_path, position):\n                notes.append(f"scalp_expiry_cancel_failed:{position.symbol}")\n                continue\n            return _market_sell(client, state, state_path, position, limits, report_trade, now, "timeout")\n\n''',
    '',
    "unconditional scalp timeout",
)

t = replace_once(
    t,
    '''        stop_fraction, activation_fraction = _position_limits(position, limits)\n        hard_stop = entry * (Decimal("1") - stop_fraction)\n        activation = entry * (Decimal("1") + activation_fraction)\n        peak = Decimal(position.peak_price) if position.peak_price is not None else entry\n''',
    '''        stop_fraction, activation_fraction = _position_limits(position, limits)\n        hard_stop = entry * (Decimal("1") - stop_fraction)\n        activation = entry * (Decimal("1") + activation_fraction)\n        trailing_gap = max(TRAILING_MIN_GAP_FRACTION, stop_fraction * TRAILING_GAP_RATIO)\n        peak = Decimal(position.peak_price) if position.peak_price is not None else entry\n\n        if position.strategy == "scalp" and position.max_hold_seconds is not None:\n            age = now - position.opened_at\n            if age >= position.max_hold_seconds and current >= entry * (Decimal("1") + SCALP_TIMEOUT_PROFIT_FRACTION):\n                if position.protective_order_list_id is not None and not _cancel_protection(client, state, state_path, position):\n                    notes.append(f"scalp_profit_timeout_cancel_failed:{position.symbol}")\n                    continue\n                return _market_sell(client, state, state_path, position, limits, report_trade, now, "timeout_profit")\n            if age >= position.max_hold_seconds * 2:\n                if position.protective_order_list_id is not None and not _cancel_protection(client, state, state_path, position):\n                    notes.append(f"scalp_hard_timeout_cancel_failed:{position.symbol}")\n                    continue\n                return _market_sell(client, state, state_path, position, limits, report_trade, now, "hard_timeout")\n''',
    "adaptive scalp timeout",
)

t = t.replace('peak * (Decimal("1") - stop_fraction)', 'peak * (Decimal("1") - trailing_gap)')
t = t.replace('new_peak * (Decimal("1") - stop_fraction)', 'new_peak * (Decimal("1") - trailing_gap)')
p.write_text(t, encoding="utf-8")


# 2) Require stronger multi-timeframe confirmation for scalps.
p = Path("trader/scalping.py")
t = p.read_text(encoding="utf-8")
t = replace_once(
    t,
    '''    threshold = 4 if aggressive else 5\n    confidence = min(Decimal("1"), Decimal(score) / Decimal("8"))\n    return ScalpAnalysis(not veto and score >= threshold, score, confidence, rsi, volume_ratio, momentum, tuple(reasons))''',
    '''    threshold = 5 if aggressive else 6\n    trend_confirmed = "5m_trend" in reasons\n    momentum_confirmed = any(reason in reasons for reason in ("1m_volume_burst", "3m_momentum", "10m_breakout"))\n    confidence = min(Decimal("1"), Decimal(score) / Decimal("8"))\n    return ScalpAnalysis(\n        not veto and trend_confirmed and momentum_confirmed and score >= threshold,\n        score, confidence, rsi, volume_ratio, momentum, tuple(reasons)\n    )''',
    "scalp signal threshold",
)
p.write_text(t, encoding="utf-8")


# 3) Smaller scalp sizing. Keep swing sizing intact and bull-run logic unchanged.
p = Path("trader/worker.py")
t = p.read_text(encoding="utf-8")
t = replace_once(
    t,
    '''                if strategy == "bullrun":\n                    stop, activation, size_multiplier = bullrun_profile(\n                        analyses[pair], (settings or {}).get("stop_loss_percent", "1"), risk_profile\n                    )\n                    stop_overrides[pair] = stop\n                    activation_overrides[pair] = activation\n                    size_multipliers[pair] = size_multiplier\n                    max_hold_overrides[pair] = BULLRUN_MAX_HOLD_SECONDS\n''',
    '''                if strategy == "bullrun":\n                    stop, activation, size_multiplier = bullrun_profile(\n                        analyses[pair], (settings or {}).get("stop_loss_percent", "1"), risk_profile\n                    )\n                    stop_overrides[pair] = stop\n                    activation_overrides[pair] = activation\n                    size_multipliers[pair] = size_multiplier\n                    max_hold_overrides[pair] = BULLRUN_MAX_HOLD_SECONDS\n                elif strategy == "scalp":\n                    size_multipliers[pair] = Decimal("0.65") if risk_profile == "high" else Decimal("0.75")\n''',
    "scalp size multiplier",
)
p.write_text(t, encoding="utf-8")


# 4) Update tests to assert the new behavior.
p = Path("tests/test_portfolio_live.py")
t = p.read_text(encoding="utf-8")
t = t.replace('self.assertEqual(position.stop_fraction, "0.0045")', 'self.assertEqual(position.stop_fraction, "0.0075")')
t = t.replace('self.assertEqual(position.target_fraction, "0.0075")', 'self.assertEqual(position.target_fraction, "0.0060")')
t = t.replace('self.assertEqual(position.max_hold_seconds, 900)', 'self.assertEqual(position.max_hold_seconds, 1800)')
t = t.replace('self.assertEqual(limits.max_open_positions, 8)', 'self.assertEqual(limits.max_open_positions, 4)')
t = t.replace('self.assertEqual(limits.cooldown_seconds, 15)', 'self.assertEqual(limits.cooldown_seconds, 90)')
t = t.replace('self.assertEqual(limits.max_trades_per_day, 100)', 'self.assertEqual(limits.max_trades_per_day, 36)')
# The tighter trailing lock uses 45% of the original 1% risk gap at a 110 peak:
# 110 * (1 - 0.0045) = 109.5050. Update both existing trailing assertions.
t = t.replace('self.assertEqual(Decimal(position.trailing_stop_price), Decimal("108.90"))', 'self.assertEqual(Decimal(position.trailing_stop_price), Decimal("109.5050"))')

old_timeout = '''    def test_expired_scalp_cancels_oco_before_market_exit(self):\n        client = FakeClient()\n        with tempfile.TemporaryDirectory() as directory:\n            path = Path(directory) / "state.json"\n            run_portfolio_cycle(\n                client,\n                {"BTCUSDC": True},\n                path,\n                self.limits(),\n                entry_strategies={"BTCUSDC": "scalp"},\n            )\n            state = load_state(path)\n            state.positions[0].opened_at = 1\n            state.cooldown_until = 0\n            save_state(path, state)\n            result = run_portfolio_cycle(client, {"BTCUSDC": False}, path, self.limits())\n        self.assertIn("reason=timeout", result)\n        self.assertEqual(client.cancelled_oco, 1)\n        self.assertEqual(client.live_sells, 1)\n'''
new_timeout = '''    def test_expired_scalp_only_time_exits_when_profitable(self):\n        client = FakeClient()\n        with tempfile.TemporaryDirectory() as directory:\n            path = Path(directory) / "state.json"\n            run_portfolio_cycle(\n                client,\n                {"BTCUSDC": True},\n                path,\n                self.limits(),\n                entry_strategies={"BTCUSDC": "scalp"},\n            )\n            state = load_state(path)\n            state.positions[0].opened_at = int(__import__("time").time()) - 1900\n            state.cooldown_until = 0\n            save_state(path, state)\n            client.price = Decimal("100.30")\n            result = run_portfolio_cycle(client, {"BTCUSDC": False}, path, self.limits())\n        self.assertIn("reason=timeout_profit", result)\n        self.assertEqual(client.cancelled_oco, 1)\n        self.assertEqual(client.live_sells, 1)\n'''
if old_timeout not in t:
    raise SystemExit("Patch target not found: timeout test")
t = t.replace(old_timeout, new_timeout, 1)
p.write_text(t, encoding="utf-8")

p = Path("tests/test_scalping.py")
t = p.read_text(encoding="utf-8")
t = t.replace('self.assertGreaterEqual(analysis.score, 4)', 'self.assertGreaterEqual(analysis.score, 5)')
p.write_text(t, encoding="utf-8")

print("Exit-policy optimization applied")
