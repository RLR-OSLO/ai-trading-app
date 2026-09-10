from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit(f"marker missing in {path}: {old[:120]!r}")
    p.write_text(s.replace(old, new, 1))
    print(f"patched {path}")


# Dashboard trade metadata: include leverage so futures positions can be labelled accurately.
replace_once(
    "app/trading-dashboard.tsx",
    'type Trade = { id: string; symbol: string; mode: string; side: "BUY" | "SELL"; quantity: number; entry_price: number | null; exit_price: number | null; pnl: number | null; created_at: string };',
    'type Trade = { id: string; symbol: string; mode: string; side: "BUY" | "SELL"; quantity: number; entry_price: number | null; exit_price: number | null; pnl: number | null; leverage: number | null; created_at: string };'
)

replace_once(
    "app/trading-dashboard.tsx",
    'supabase.from("trades").select("id,symbol,mode,side,quantity,entry_price,exit_price,pnl,created_at").order("created_at", { ascending: false }).limit(500),',
    'supabase.from("trades").select("id,symbol,mode,side,quantity,entry_price,exit_price,pnl,leverage,created_at").order("created_at", { ascending: false }).limit(500),'
)

# Build open derivative state independently of spot holdings. A SELL opens/increases a short;
# a BUY closes/reduces it. This keeps margin/futures positions visually separate from spot.
replace_once(
    "app/trading-dashboard.tsx",
    '    const assetTrades = trades.filter((trade) => trade.symbol === symbol && trade.mode === "live");\n    const orderedTrades = [...assetTrades].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());',
    '    const assetTrades = trades.filter((trade) => trade.symbol === symbol && trade.mode === "live");\n    const derivativeTrades = trades.filter((trade) => trade.symbol === symbol && (trade.mode === "margin" || trade.mode === "futures")).sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());\n    let derivativeQuantity = 0;\n    let derivativeMode: "margin" | "futures" | null = null;\n    let derivativeLeverage: number | null = null;\n    for (const trade of derivativeTrades) {\n      const qty = Math.max(0, Number(trade.quantity));\n      if (trade.side === "SELL") {\n        derivativeQuantity += qty;\n        derivativeMode = trade.mode as "margin" | "futures";\n        derivativeLeverage = trade.mode === "futures" ? Number(trade.leverage ?? 1) : 1;\n      } else {\n        derivativeQuantity = Math.max(0, derivativeQuantity - qty);\n        if (derivativeQuantity < 0.000000001) { derivativeQuantity = 0; derivativeMode = null; derivativeLeverage = null; }\n      }\n    }\n    const derivativeOpen = derivativeQuantity > 0.000000001 && derivativeMode !== null;\n    const orderedTrades = [...assetTrades].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());'
)

replace_once(
    "app/trading-dashboard.tsx",
    '    return { asset, invested: adjustedInvested, quantity: authoritativeQuantity, pnl, currentPrice, currentValue, unrealized, owned };\n  }).sort((a, b) => Number(b.owned) - Number(a.owned) || Number(b.currentValue ?? 0) - Number(a.currentValue ?? 0) || MARKET_UNIVERSE.indexOf(a.asset as typeof MARKET_UNIVERSE[number]) - MARKET_UNIVERSE.indexOf(b.asset as typeof MARKET_UNIVERSE[number])),',
    '    return { asset, invested: adjustedInvested, quantity: authoritativeQuantity, pnl, currentPrice, currentValue, unrealized, owned, derivativeOpen, derivativeMode, derivativeQuantity, derivativeLeverage };\n  }).sort((a, b) => Number(b.derivativeOpen) - Number(a.derivativeOpen) || Number(b.owned) - Number(a.owned) || Number(b.currentValue ?? 0) - Number(a.currentValue ?? 0) || MARKET_UNIVERSE.indexOf(a.asset as typeof MARKET_UNIVERSE[number]) - MARKET_UNIVERSE.indexOf(b.asset as typeof MARKET_UNIVERSE[number])),')

old_portfolio = '''    <section className="panel"><div className="panel-head"><div><p className="eyebrow">PORTEFØLJE</p><h3>Investert per valuta</h3></div><span className="muted">Alle godkjente markeder · investerte posisjoner vises først</span></div><div className="assets">{allocations.map(({ asset, invested, quantity, pnl, currentPrice, currentValue, unrealized, owned }) => <div className={`asset${owned ? " invested" : ""}`} key={asset}><span className="coin">{asset[0]}</span><div><b>{asset}/{settings.quote_asset}</b>{owned && <span className="owned-badge">INVESTERT</span>}<small>Investert: {money(invested)} {settings.quote_asset} · Eier: {crypto(quantity)} {asset}</small><small>Nåpris: {currentPrice === null ? "–" : `${money(currentPrice)} ${settings.quote_asset}`} · Verdi nå: {currentValue === null ? "–" : `${money(currentValue)} ${settings.quote_asset}`}</small></div><span className={(unrealized ?? pnl) < 0 ? "loss" : "gain"}>{unrealized === null ? `${money(pnl)} ${settings.quote_asset}` : `${unrealized >= 0 ? "+" : ""}${money(unrealized)} ${settings.quote_asset}`}</span></div>)}</div></section>'''
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

old_activity = '''    <section className="panel"><div className="panel-head"><div><p className="eyebrow">AKTIVITET</p><h3>Siste handler</h3></div><span className="muted">Oppdateres hvert 30. sekund</span></div>{trades.length === 0 ? <p className="empty">Ingen live-handler registrert ennå.</p> : <div className="trade-list">{trades.slice(0, 20).map((trade) => <div className="trade-row" key={trade.id}><b>{trade.mode.toUpperCase()} · {trade.side} {trade.symbol}</b><span>{Number(trade.quantity).toPrecision(6)}</span><span className={Number(trade.pnl ?? 0) < 0 ? "loss" : "gain"}>{money(Number(trade.pnl ?? 0))} {settings.quote_asset}</span><time>{new Date(trade.created_at).toLocaleString("nb-NO")}</time></div>)}</div>}</section>'''
new_activity = '''    <section className="panel"><div className="panel-head"><div><p className="eyebrow">AKTIVITET</p><h3>Siste handler</h3></div><span className="muted">Oppdateres hvert 30. sekund</span></div>{trades.length === 0 ? <p className="empty">Ingen live-handler registrert ennå.</p> : <div className="trade-list">{trades.slice(0, 20).map((trade) => <div className="trade-row" style={trade.mode === "futures" ? { background: "rgba(245,158,11,.06)" } : trade.mode === "margin" ? { background: "rgba(168,85,247,.06)" } : undefined} key={trade.id}><b>{trade.mode.toUpperCase()} · {trade.side} {trade.symbol}{trade.mode === "futures" && trade.leverage ? ` · ${trade.leverage}x` : ""}</b><span>{Number(trade.quantity).toPrecision(6)}</span><span className={Number(trade.pnl ?? 0) < 0 ? "loss" : "gain"}>{money(Number(trade.pnl ?? 0))} {settings.quote_asset}</span><time>{new Date(trade.created_at).toLocaleString("nb-NO")}</time></div>)}</div>}</section>'''
replace_once("app/trading-dashboard.tsx", old_activity, new_activity)

# Record leverage in derivative trade history so the dashboard reflects the actual opening configuration.
replace_once(
    "trader/derivatives_live.py",
    '_record(report_trade, {"mode": "margin", "symbol": position.symbol, "side": "BUY", "quantity": str(executed), "entry_price": position.entry_price, "exit_price": str(spent / executed), "pnl": str(pnl)})',
    '_record(report_trade, {"mode": "margin", "symbol": position.symbol, "side": "BUY", "quantity": str(executed), "entry_price": position.entry_price, "exit_price": str(spent / executed), "pnl": str(pnl), "leverage": 1})'
)
replace_once(
    "trader/derivatives_live.py",
    '_record(report_trade, {"mode": "margin", "symbol": symbol, "side": "SELL", "quantity": str(executed), "entry_price": str(entry), "exit_price": None, "pnl": None})',
    '_record(report_trade, {"mode": "margin", "symbol": symbol, "side": "SELL", "quantity": str(executed), "entry_price": str(entry), "exit_price": None, "pnl": None, "leverage": 1})'
)
replace_once(
    "trader/derivatives_live.py",
    '_record(report_trade, {"mode": "futures", "symbol": position.symbol, "side": "BUY", "quantity": str(qty), "entry_price": position.entry_price, "exit_price": str(exit_price), "pnl": str(pnl)})',
    '_record(report_trade, {"mode": "futures", "symbol": position.symbol, "side": "BUY", "quantity": str(qty), "entry_price": position.entry_price, "exit_price": str(exit_price), "pnl": str(pnl), "leverage": position.leverage})'
)
replace_once(
    "trader/derivatives_live.py",
    '_record(report_trade, {"mode": "futures", "symbol": symbol, "side": "SELL", "quantity": str(quantity), "entry_price": str(entry), "exit_price": None, "pnl": None})',
    '_record(report_trade, {"mode": "futures", "symbol": symbol, "side": "SELL", "quantity": str(quantity), "entry_price": str(entry), "exit_price": None, "pnl": None, "leverage": leverage})'
)

print("UPGRADE_DASHBOARD_DERIVATIVES_V6_OK")
