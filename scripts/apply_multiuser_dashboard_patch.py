from pathlib import Path

path = Path('app/trading-dashboard.tsx')
text = path.read_text(encoding='utf-8')

if 'import LogoutButton from "./logout-button";' not in text:
    text = text.replace('import HowItWorks from "./how-it-works";\n', 'import HowItWorks from "./how-it-works";\nimport LogoutButton from "./logout-button";\n', 1)

old = '    const walletQuantity = binanceBalances.has(asset) ? Number(binanceBalances.get(asset)) : quantity;\n'
new = '    const hasBinanceBalances = /(?:^|;)balances=/.test(lastEvent?.message ?? "");\n    const walletQuantity = hasBinanceBalances ? Number(binanceBalances.get(asset) ?? 0) : quantity;\n'
if old in text:
    text = text.replace(old, new, 1)

old_dep = ']), [assets, settings.quote_asset, trades, marketPrices, binanceBalances, binanceWalletValues]);'
new_dep = ']), [assets, settings.quote_asset, trades, marketPrices, binanceBalances, binanceWalletValues, lastEvent]);'
if old_dep in text:
    text = text.replace(old_dep, new_dep, 1)

old_header = '    <header className="topbar"><div><span className="eyebrow">AI TRADING APP</span><h1>Kontrollpanel</h1></div><span className="pill"><i /> {serverOnline ? "Server online" : "Ingen fersk serverstatus"}</span></header>\n'
new_header = '    <header className="topbar"><div><span className="eyebrow">AI TRADING APP</span><h1>Kontrollpanel</h1></div><div style={{ display: "flex", gap: 10, alignItems: "center" }}><span className="pill"><i /> {serverOnline ? "Server online" : "Ingen fersk serverstatus"}</span><LogoutButton /></div></header>\n'
if old_header not in text:
    raise SystemExit('topbar marker not found')
text = text.replace(old_header, new_header, 1)

path.write_text(text, encoding='utf-8')
