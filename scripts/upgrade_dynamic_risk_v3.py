from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit(f"marker missing in {path}: {old[:80]!r}")
    p.write_text(s.replace(old, new, 1))
    print(f"patched {path}")


# Dashboard: keep a user-defined total bot capital cap instead of silently
# replacing it with the full available Binance balance.
replace_once(
    "app/trading-dashboard.tsx",
    '    const effectiveCapital = Math.max(5, availableCapital);\n    const safe = {\n      ...settings,\n      trade_cap_usdc: effectiveCapital,\n      order_size_usdc: Math.max(5, Number(settings.order_size_usdc)),\n      max_daily_loss_usdc: Math.min(effectiveCapital, Math.max(0.5, Number(settings.max_daily_loss_usdc))),',
    '    const configuredCap = Math.max(5, Number(settings.trade_cap_usdc));\n    const safe = {\n      ...settings,\n      trade_cap_usdc: configuredCap,\n      order_size_usdc: Math.min(configuredCap, Math.max(5, Number(settings.order_size_usdc))),\n      max_daily_loss_usdc: Math.min(configuredCap, Math.max(0.5, Number(settings.max_daily_loss_usdc))),'
)

replace_once(
    "app/trading-dashboard.tsx",
    '    const next = { ...settings, trade_cap_usdc: Math.max(5, availableCapital), bot_enabled: enabled, live_trading_enabled: enabled };',
    '    const next = { ...settings, bot_enabled: enabled, live_trading_enabled: enabled };'
)

replace_once(
    "app/trading-dashboard.tsx",
    '      trade_cap_usdc: capital,\n      order_size_usdc: Math.min(capital, Math.max(5, roundedOrder)),',
    '      order_size_usdc: Math.min(Math.max(5, Number(current.trade_cap_usdc)), Math.max(5, roundedOrder)),'
)

replace_once(
    "app/trading-dashboard.tsx",
    '        <label className="number-field"><span>Tilgjengelig kapital ({settings.quote_asset})</span><input type="number" value={availableCapital} readOnly /></label>\n        <Field label={`Maks per investering (${settings.quote_asset})`} value={settings.order_size_usdc} min={5} step={5} onChange={(value) => update("order_size_usdc", value)} />',
    '        <label className="number-field"><span>Tilgjengelig kapital ({settings.quote_asset})</span><input type="number" value={availableCapital} readOnly /></label>\n        <Field label={`Maks botkapital (${settings.quote_asset})`} value={settings.trade_cap_usdc} min={5} step={5} onChange={(value) => update("trade_cap_usdc", value)} />\n        <Field label={`Maks per posisjon (${settings.quote_asset})`} value={settings.order_size_usdc} min={5} max={Math.max(5, settings.trade_cap_usdc)} step={5} onChange={(value) => update("order_size_usdc", value)} />'
)

replace_once(
    "app/trading-dashboard.tsx",
    'function Field({ label, value, min, max, step, onChange }: Readonly<{ label: string; value: number; min: number; max?: number; step: number; onChange: (value: number) => void }>) { return <label className="number-field"><span>{label}</span><input type="number" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} /></label>; }',
    '''function Field({ label, value, min, max, step, onChange }: Readonly<{ label: string; value: number; min: number; max?: number; step: number; onChange: (value: number) => void }>) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => { setDraft(String(value)); }, [value]);
  const commit = () => {
    const parsed = Number(draft);
    if (!Number.isFinite(parsed)) { setDraft(String(value)); return; }
    const bounded = Math.min(max ?? Number.POSITIVE_INFINITY, Math.max(min, parsed));
    onChange(bounded);
    setDraft(String(bounded));
  };
  return <label className="number-field"><span>{label}</span><input type="number" value={draft} min={min} max={max} step={step} onFocus={(event) => event.currentTarget.select()} onChange={(event) => setDraft(event.target.value)} onBlur={commit} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} /></label>;
}'''
)

# Portfolio engine: order_size is a hard per-position ceiling. Dynamic signal
# sizing may choose anything below it, while capital_cap limits aggregate open
# bot exposure. This prevents a multiplier from ever exceeding the user's cap.
replace_once(
    "trader/portfolio_live.py",
    '    multiplier = max(Decimal("0.5"), min(Decimal("1.5"), Decimal(str((entry_size_multipliers or {}).get(symbol, Decimal("1"))))))\n    # order_size is the user\'s maximum amount per investment. Risk presets provide\n    # a sensible default, but a manual override is honored up to the actual free balance.\n    spend = min(limits.order_size * multiplier, free_quote)\n    if spend < Decimal("5"):\n        return f"insufficient_{quote.lower()}_for_sized_entry"',
    '    multiplier = max(Decimal("0.25"), min(Decimal("1"), Decimal(str((entry_size_multipliers or {}).get(symbol, Decimal("0.5"))))))\n    open_notional = sum((Decimal(p.quote_spent) for p in state.positions or []), Decimal("0"))\n    remaining_cap = max(Decimal("0"), limits.capital_cap - open_notional)\n    # order_size is a hard maximum per position. Signal quality chooses a smaller\n    # amount when conviction is weaker, but can use the full maximum on the best setups.\n    spend = min(limits.order_size * multiplier, free_quote, remaining_cap)\n    if remaining_cap < Decimal("5"):\n        return "capital_cap_reached"\n    if spend < Decimal("5"):\n        return f"insufficient_{quote.lower()}_for_sized_entry"'
)

# Worker: preserve the configured capital cap and derive per-market size from
# actual signal confidence. Bullruns may use the full per-position ceiling;
# weaker setups use materially less.
replace_once(
    "trader/worker.py",
    '            runtime_settings = dict(settings or {})\n            runtime_settings["trade_cap_usdc"] = str(max(available_balance, Decimal("5")))\n            stop_overrides: dict[str, Decimal] = {}',
    '            runtime_settings = dict(settings or {})\n            if settings is None:\n                runtime_settings["trade_cap_usdc"] = str(max(available_balance, Decimal("5")))\n            stop_overrides: dict[str, Decimal] = {}'
)

replace_once(
    "trader/worker.py",
    '            for pair, strategy in strategies.items():\n                if strategy == "bullrun":',
    '            for pair, strategy in strategies.items():\n                swing_conf = analyses[pair].confidence\n                scalp_conf = scalp_analyses[pair].confidence if strategy == "scalp" else Decimal("0")\n                confidence = max(swing_conf, scalp_conf)\n                size_multipliers[pair] = max(Decimal("0.30"), min(Decimal("1"), Decimal("0.20") + confidence * Decimal("0.80")))\n                if strategy == "bullrun":')

replace_once(
    "trader/worker.py",
    '                    size_multipliers[pair] = size_multiplier\n                    max_hold_overrides[pair] = BULLRUN_MAX_HOLD_SECONDS\n                elif strategy == "scalp":\n                    size_multipliers[pair] = Decimal("0.65") if risk_profile in {"high", "extreme"} else Decimal("0.75")',
    '                    size_multipliers[pair] = min(Decimal("1"), max(size_multipliers[pair], size_multiplier / Decimal("1.5")))\n                    max_hold_overrides[pair] = BULLRUN_MAX_HOLD_SECONDS\n                elif strategy == "scalp":\n                    scalp_ceiling = Decimal("0.75") if risk_profile in {"high", "extreme"} else Decimal("0.65")\n                    size_multipliers[pair] = min(size_multipliers[pair], scalp_ceiling)'
)

print("UPGRADE_DYNAMIC_RISK_V3_OK")
