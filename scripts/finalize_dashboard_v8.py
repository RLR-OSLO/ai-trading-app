from pathlib import Path


def replace_once(path: str, old: str, new: str) -> bool:
    p = Path(path)
    text = p.read_text()
    if new in text:
        return False
    if old not in text:
        raise SystemExit(f"marker missing in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1))
    print(f"patched {path}")
    return True


dash = Path("app/trading-dashboard.tsx")
text = dash.read_text()

# v7 may already be applied locally. Only add the open derivative portfolio model if absent.
if "const derivativeTrades = trades.filter" not in text:
    old = '    const assetTrades = trades.filter((trade) => trade.symbol === symbol && trade.mode === "live");\n    const orderedTrades = [...assetTrades].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());'
    new = '    const assetTrades = trades.filter((trade) => trade.symbol === symbol && trade.mode === "live");\n    const derivativeTrades = trades.filter((trade) => trade.symbol === symbol && (trade.mode === "margin" || trade.mode === "futures")).sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());\n    let derivativeQuantity = 0;\n    let derivativeMode: "margin" | "futures" | null = null;\n    let derivativeLeverage: number | null = null;\n    for (const trade of derivativeTrades) {\n      const qty = Math.max(0, Number(trade.quantity));\n      if (trade.side === "SELL") {\n        derivativeQuantity += qty;\n        derivativeMode = trade.mode as "margin" | "futures";\n        derivativeLeverage = trade.mode === "futures" ? Number(trade.leverage ?? 1) : 1;\n      } else {\n        derivativeQuantity = Math.max(0, derivativeQuantity - qty);\n        if (derivativeQuantity < 0.000000001) { derivativeQuantity = 0; derivativeMode = null; derivativeLeverage = null; }\n      }\n    }\n    const derivativeOpen = derivativeQuantity > 0.000000001 && derivativeMode !== null;\n    const orderedTrades = [...assetTrades].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());'
    replace_once("app/trading-dashboard.tsx", old, new)
    text = dash.read_text()

if "derivativeOpen, derivativeMode, derivativeQuantity, derivativeLeverage" not in text:
    old = '    return { asset, invested: adjustedInvested, quantity: authoritativeQuantity, pnl, currentPrice, currentValue, unrealized, owned };\n  }).sort((a, b) => Number(b.owned) - Number(a.owned) || Number(b.currentValue ?? 0) - Number(a.currentValue ?? 0) || MARKET_UNIVERSE.indexOf(a.asset as typeof MARKET_UNIVERSE[number]) - MARKET_UNIVERSE.indexOf(b.asset as typeof MARKET_UNIVERSE[number])), '
    if old not in text:
        old = '    return { asset, invested: adjustedInvested, quantity: authoritativeQuantity, pnl, currentPrice, currentValue, unrealized, owned };\n  }).sort((a, b) => Number(b.owned) - Number(a.owned) || Number(b.currentValue ?? 0) - Number(a.currentValue ?? 0) || MARKET_UNIVERSE.indexOf(a.asset as typeof MARKET_UNIVERSE[number]) - MARKET_UNIVERSE.indexOf(b.asset as typeof MARKET_UNIVERSE[number])), '
    # Exact source variant without trailing space.
    old2 = '    return { asset, invested: adjustedInvested, quantity: authoritativeQuantity, pnl, currentPrice, currentValue, unrealized, owned };\n  }).sort((a, b) => Number(b.owned) - Number(a.owned) || Number(b.currentValue ?? 0) - Number(a.currentValue ?? 0) || MARKET_UNIVERSE.indexOf(a.asset as typeof MARKET_UNIVERSE[number]) - MARKET_UNIVERSE.indexOf(b.asset as typeof MARKET_UNIVERSE[number])), '
    target = old if old in text else old2
    if target not in text:
        target = '    return { asset, invested: adjustedInvested, quantity: authoritativeQuantity, pnl, currentPrice, currentValue, unrealized, owned };\n  }).sort((a, b) => Number(b.owned) - Number(a.owned) || Number(b.currentValue ?? 0) - Number(a.currentValue ?? 0) || MARKET_UNIVERSE.indexOf(a.asset as typeof MARKET_UNIVERSE[number]) - MARKET_UNIVERSE.indexOf(b.asset as typeof MARKET_UNIVERSE[number])),'
    new = '    return { asset, invested: adjustedInvested, quantity: authoritativeQuantity, pnl, currentPrice, currentValue, unrealized, owned, derivativeOpen, derivativeMode, derivativeQuantity, derivativeLeverage };\n  }).sort((a, b) => Number(b.derivativeOpen) - Number(a.derivativeOpen) || Number(b.owned) - Number(a.owned) || Number(b.currentValue ?? 0) - Number(a.currentValue ?? 0) || MARKET_UNIVERSE.indexOf(a.asset as typeof MARKET_UNIVERSE[number]) - MARKET_UNIVERSE.indexOf(b.asset as typeof MARKET_UNIVERSE[number])),'
    replace_once("app/trading-dashboard.tsx", target, new)
    text = dash.read_text()

if "FUTURES SHORT · kan ha gearing" not in text:
    old_portfolio = '    <section className="panel"><div className="panel-head"><div><p className="eyebrow">PORTEFØLJE</p><h3>Investert per valuta</h3></div><span className="muted">Alle godkjente markeder · investerte posisjoner vises først</span></div><div className="assets">{allocations.map(({ asset, invested, quantity, pnl, currentPrice, currentValue, unrealized, owned }) => <div className={`asset${owned ? " invested" : ""}`} key={asset}><span className="coin">{asset[0]}</span><div><b>{asset}/{settings.quote_asset}</b>{owned && <span className="owned-badge">INVESTERT</span>}<small>Investert: {money(invested)} {settings.quote_asset} · Eier: {crypto(quantity)} {asset}</small><small>Nåpris: {currentPrice === null ? "–" : `${money(currentPrice)} ${settings.quote_asset}`} · Verdi nå: {currentValue === null ? "–" : `${money(currentValue)} ${settings.quote_asset}`}</small></div><span className={(unrealized ?? pnl) < 0 ? "loss" : "gain"}>{unrealized === null ? `${money(pnl)} ${settings.quote_asset}` : `${unrealized >= 0 ? "+" : ""}${money(unrealized)} ${settings.quote_asset}`}</span></div>)}</div></section>'
    new_portfolio = '''    <section className="panel"><div className="panel-head"><div><p className="eyebrow">PORTEFØLJE</p><h3>Investert per valuta</h3></div><span className="muted">Spot, Margin-short og Futures vises tydelig hver for seg</span></div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
        <span style={{ padding: "6px 10px", borderRadius: 999, background: "rgba(34,197,94,.12)", border: "1px solid rgba(34,197,94,.32)", fontSize: 12 }}>SPOT · vanlig beholdning</span>
        <span style={{ padding: "6px 10px", borderRadius: 999, background: "rgba(168,85,247,.12)", border: "1px solid rgba(168,85,247,.35)", fontSize: 12 }}>MARGIN SHORT · lånt og solgt</span>
        <span style={{ padding: "6px 10px", borderRadius: 999, background: "rgba(245,158,11,.13)", border: "1px solid rgba(245,158,11,.38)", fontSize: 12 }}>FUTURES SHORT · kan ha gearing</span>
      </div>
      <div className="assets">{allocations.map(({ asset, invested, quantity, pnl, currentPrice, currentValue, unrealized, owned, derivativeOpen, derivativeMode, derivativeQuantity, derivativeLeverage }) => {
        const derivativeStyle = derivativeOpen ? (derivativeMode === "futures"
          ? { borderColor: "rgba(245,158,11,.65)", background: "rgba(245,158,11,.08)" }
          : { borderColor: "rgba(168,85,247,.60)", background: "rgba(168,85,247,.08)" }) : undefined;
        return <div className={`asset${owned ? " invested" : ""}`} style={derivativeStyle} key={asset}><span className="coin">{asset[0]}</span><div><b>{asset}/{settings.quote_asset}</b>{owned && <span className="owned-badge">SPOT</span>}{derivativeOpen && <span className="owned-badge" style={{ marginLeft: 6 }}>{derivativeMode === "futures" ? `SHORT · FUTURES · ${derivativeLeverage ?? 1}x` : "SHORT · MARGIN"}</span>}<small>Spot investert: {money(invested)} {settings.quote_asset} · Eier: {crypto(quantity)} {asset}</small>{derivativeOpen && <small style={{ fontWeight: 700 }}>Åpen derivatposisjon: short {crypto(derivativeQuantity)} {asset}{derivativeMode === "futures" ? ` · gearing ${derivativeLeverage ?? 1}x` : " · margin/lån"}</small>}<small>Nåpris: {currentPrice === null ? "–" : `${money(currentPrice)} ${settings.quote_asset}`} · Spotverdi nå: {currentValue === null ? "–" : `${money(currentValue)} ${settings.quote_asset}`}</small></div><span className={(unrealized ?? pnl) < 0 ? "loss" : "gain"}>{unrealized === null ? `${money(pnl)} ${settings.quote_asset}` : `${unrealized >= 0 ? "+" : ""}${money(unrealized)} ${settings.quote_asset}`}</span></div>;
      })}</div>
      <p className="muted" style={{ marginTop: 12, marginBottom: 0 }}>Farget markering betyr at denne valutaen har en åpen short-/derivatposisjon i tillegg til eventuell spotbeholdning. Lilla = Margin-short. Oransje = Futures-short; badge viser gearingen som ble brukt ved åpning.</p>
    </section>'''
    replace_once("app/trading-dashboard.tsx", old_portfolio, new_portfolio)

# Record actual leverage on derivative history rows. Safe to run repeatedly.
deriv = Path("trader/derivatives_live.py")
d = deriv.read_text()
replacements = [
    ('"pnl": str(pnl)})\n    return f"margin_short_closed', '"pnl": str(pnl), "leverage": 1})\n    return f"margin_short_closed'),
    ('"pnl": None})\n    return f"margin_short_opened', '"pnl": None, "leverage": 1})\n    return f"margin_short_opened'),
    ('"pnl": str(pnl)})\n    return f"futures_short_closed', '"pnl": str(pnl), "leverage": position.leverage})\n    return f"futures_short_closed'),
    ('"pnl": None})\n    return f"futures_short_opened', '"pnl": None, "leverage": leverage})\n    return f"futures_short_opened'),
]
changed = False
for old, new in replacements:
    if new in d:
        continue
    if old not in d:
        raise SystemExit(f"marker missing in trader/derivatives_live.py: {old[:80]!r}")
    d = d.replace(old, new, 1)
    changed = True
if changed:
    deriv.write_text(d)
    print("patched trader/derivatives_live.py")

print("FINALIZE_DASHBOARD_V8_OK")
