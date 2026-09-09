from pathlib import Path

p = Path('app/trading-dashboard.tsx')
s = p.read_text(encoding='utf-8')
old = '    const walletQuantity = binanceBalances.has(asset) ? Number(binanceBalances.get(asset)) : quantity;\n'
new = '    const hasBinanceSnapshot = /(?:^|;)balances=/.test(lastEvent?.message ?? "");\n    const walletQuantity = hasBinanceSnapshot ? Number(binanceBalances.get(asset) ?? 0) : quantity;\n'
if old not in s:
    raise SystemExit('walletQuantity line not found')
s = s.replace(old, new, 1)
old_dep = '  }).sort((a, b) => Number(b.owned) - Number(a.owned) || Number(b.currentValue ?? 0) - Number(a.currentValue ?? 0) || MARKET_UNIVERSE.indexOf(a.asset as typeof MARKET_UNIVERSE[number]) - MARKET_UNIVERSE.indexOf(b.asset as typeof MARKET_UNIVERSE[number])), [assets, settings.quote_asset, trades, marketPrices, binanceBalances, binanceWalletValues]);\n'
new_dep = '  }).sort((a, b) => Number(b.owned) - Number(a.owned) || Number(b.currentValue ?? 0) - Number(a.currentValue ?? 0) || MARKET_UNIVERSE.indexOf(a.asset as typeof MARKET_UNIVERSE[number]) - MARKET_UNIVERSE.indexOf(b.asset as typeof MARKET_UNIVERSE[number])), [assets, settings.quote_asset, trades, marketPrices, binanceBalances, binanceWalletValues, lastEvent]);\n'
if old_dep not in s:
    raise SystemExit('allocations dependency line not found')
s = s.replace(old_dep, new_dep, 1)
p.write_text(s, encoding='utf-8')
Path('scripts/fix_wallet_authority_cards.py').unlink(missing_ok=True)
Path('.github/workflows/apply-wallet-authority-cards.yml').unlink(missing_ok=True)
