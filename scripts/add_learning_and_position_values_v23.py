from pathlib import Path


def patch(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    if new in s:
        print(f"already: {label}")
        return
    if old not in s:
        raise SystemExit(f"missing marker: {label}")
    p.write_text(s.replace(old, new, 1), encoding="utf-8")
    print(f"patched: {label}")

patch(
    "trader/reporting.py",
    '"select": "symbol,side,quantity,entry_price,created_at",',
    '"select": "symbol,mode,side,quantity,entry_price,exit_price,pnl,leverage,created_at",',
    "learning trade history fields",
)

patch(
    "trader/worker.py",
    'from .portfolio_live import PortfolioLimits, recover_positions_from_trade_history, run_portfolio_cycle, load_state, save_state\n',
    'from .portfolio_live import PortfolioLimits, recover_positions_from_trade_history, run_portfolio_cycle, load_state, save_state\nfrom .learning import learning_factors, factor_for\n',
    "learning import",
)

patch(
    "trader/worker.py",
    '''            if authenticated and reporter:\n                recovered = recover_positions_from_trade_history(\n                    client, state_path, reporter.get_recent_trades(), quote_asset\n                )\n''',
    '''            recent_trades = reporter.get_recent_trades() if authenticated and reporter else []\n            learned = learning_factors(recent_trades)\n            if authenticated and reporter:\n                recovered = recover_positions_from_trade_history(\n                    client, state_path, recent_trades, quote_asset\n                )\n''',
    "single history read and learning factors",
)

patch(
    "trader/worker.py",
    '''                size_multipliers[pair] = max(Decimal("0.30"), min(Decimal("1"), Decimal("0.20") + confidence * Decimal("0.80")))\n''',
    '''                base_size = max(Decimal("0.30"), min(Decimal("1"), Decimal("0.20") + confidence * Decimal("0.80")))\n                learned_factor = factor_for(learned, pair, "live")\n                size_multipliers[pair] = max(Decimal("0.20"), min(Decimal("1"), base_size * learned_factor))\n''',
    "spot adaptive sizing",
)

patch(
    "trader/worker.py",
    '''                short_confidences = {pair: bearish_analyses[pair].confidence for pair in pairs}\n''',
    '''                derivative_mode = "futures" if bool(settings.get("futures_enabled")) and risk_profile == "extreme" else "margin"\n                short_confidences = {\n                    pair: max(Decimal("0"), min(Decimal("1"), bearish_analyses[pair].confidence * factor_for(learned, pair, derivative_mode)))\n                    for pair in pairs\n                }\n''',
    "short adaptive confidence",
)

patch(
    "trader/worker.py",
    'f"signals={signal_text};scores={score_text};scalp_scores={scalp_score_text};"',
    'f"signals={signal_text};scores={score_text};scalp_scores={scalp_score_text};short_scores={short_score_text};"',
    "heartbeat short scores",
)

patch(
    "app/trading-dashboard.tsx",
    '''    let derivativeQuantity = 0;\n    let derivativeMode: "margin" | "futures" | null = null;\n    let derivativeLeverage: number | null = null;\n''',
    '''    let derivativeQuantity = 0;\n    let derivativeEntryValue = 0;\n    let derivativeMode: "margin" | "futures" | null = null;\n    let derivativeLeverage: number | null = null;\n''',
    "derivative entry value state",
)

patch(
    "app/trading-dashboard.tsx",
    '''      if (trade.side === "SELL") {\n        derivativeQuantity += qty;\n        derivativeMode = trade.mode as "margin" | "futures";\n        derivativeLeverage = trade.mode === "futures" ? Number(trade.leverage ?? 1) : 1;\n      } else {\n        derivativeQuantity = Math.max(0, derivativeQuantity - qty);\n        if (derivativeQuantity < 0.000000001) { derivativeQuantity = 0; derivativeMode = null; derivativeLeverage = null; }\n      }\n''',
    '''      if (trade.side === "SELL") {\n        derivativeQuantity += qty;\n        derivativeEntryValue += qty * Number(trade.entry_price ?? 0);\n        derivativeMode = trade.mode as "margin" | "futures";\n        derivativeLeverage = trade.mode === "futures" ? Number(trade.leverage ?? 1) : 1;\n      } else {\n        if (derivativeQuantity > 0) {\n          const closed = Math.min(derivativeQuantity, qty);\n          derivativeEntryValue = Math.max(0, derivativeEntryValue - (derivativeEntryValue / derivativeQuantity) * closed);\n        }\n        derivativeQuantity = Math.max(0, derivativeQuantity - qty);\n        if (derivativeQuantity < 0.000000001) { derivativeQuantity = 0; derivativeEntryValue = 0; derivativeMode = null; derivativeLeverage = null; }\n      }\n''',
    "derivative running cost",
)

patch(
    "app/trading-dashboard.tsx",
    '''    const derivativeOpen = derivativeQuantity > 0.000000001 && derivativeMode !== null;\n''',
    '''    const derivativeOpen = derivativeQuantity > 0.000000001 && derivativeMode !== null;\n    const derivativeMarkPrice = marketPrices.get(symbol) ?? null;\n    const derivativeCurrentValue = derivativeOpen && derivativeMarkPrice !== null ? derivativeQuantity * derivativeMarkPrice : 0;\n    const derivativeUnrealized = derivativeOpen && derivativeMarkPrice !== null ? derivativeEntryValue - derivativeCurrentValue : null;\n''',
    "derivative current value and pnl",
)

patch(
    "app/trading-dashboard.tsx",
    '''    return { asset, invested: adjustedInvested, quantity: authoritativeQuantity, pnl, currentPrice, currentValue, unrealized, owned, derivativeOpen, derivativeMode, derivativeQuantity, derivativeLeverage };\n''',
    '''    return { asset, invested: adjustedInvested, quantity: authoritativeQuantity, pnl, currentPrice, currentValue, unrealized, owned, derivativeOpen, derivativeMode, derivativeQuantity, derivativeLeverage, derivativeEntryValue, derivativeCurrentValue, derivativeUnrealized };\n''',
    "allocation derivative values",
)

patch(
    "app/trading-dashboard.tsx",
    '''      <div className="assets">{allocations.map(({ asset, invested, quantity, pnl, currentPrice, currentValue, unrealized, owned, derivativeOpen, derivativeMode, derivativeQuantity, derivativeLeverage }) => {\n''',
    '''      <div className="assets">{allocations.map(({ asset, invested, quantity, pnl, currentPrice, currentValue, unrealized, owned, derivativeOpen, derivativeMode, derivativeQuantity, derivativeLeverage, derivativeEntryValue, derivativeCurrentValue, derivativeUnrealized }) => {\n''',
    "allocation destructuring",
)

patch(
    "app/trading-dashboard.tsx",
    '''<small>Spot investert: {money(invested)} {settings.quote_asset} · Eier: {crypto(quantity)} {asset}</small>{derivativeOpen && <small style={{ fontWeight: 700 }}>Åpen derivatposisjon: short {crypto(derivativeQuantity)} {asset}{derivativeMode === "futures" ? ` · gearing ${derivativeLeverage ?? 1}x` : " · margin/lån"}</small>}<small>Nåpris: {currentPrice === null ? "–" : `${money(currentPrice)} ${settings.quote_asset}`} · Spotverdi nå: {currentValue === null ? "–" : `${money(currentValue)} ${settings.quote_asset}`}</small>''',
    '''<small>Kjøpt for (Spot): {money(invested)} {settings.quote_asset} · Verdi nå: {currentValue === null ? "–" : `${money(currentValue)} ${settings.quote_asset}`} · Eier: {crypto(quantity)} {asset}</small>{derivativeOpen && <small style={{ fontWeight: 700 }}>Short åpnet for: {money(derivativeEntryValue)} {settings.quote_asset} · Verdi nå: {money(derivativeCurrentValue)} {settings.quote_asset} · {derivativeMode === "futures" ? `Futures ${derivativeLeverage ?? 1}x` : "Margin/lån"} · Urealisert: {derivativeUnrealized === null ? "–" : `${derivativeUnrealized >= 0 ? "+" : ""}${money(derivativeUnrealized)} ${settings.quote_asset}`}</small>}<small>Nåpris: {currentPrice === null ? "–" : `${money(currentPrice)} ${settings.quote_asset}`}</small>''',
    "box bought-for and current-value display",
)

print("FIX_V23_OK")
