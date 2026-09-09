from pathlib import Path

# 1) Do not recover dust/non-sellable positions from trade history.
p = Path('trader/portfolio_live.py')
text = p.read_text()
old = '''        quantity = min(lot["qty"], wallet_qty)\n        if quantity <= Decimal("0.00000001"):\n            continue\n        avg_price = lot["cost"] / lot["qty"] if lot["qty"] > 0 else Decimal("0")\n'''
new = '''        quantity = min(lot["qty"], wallet_qty)\n        if quantity <= Decimal("0.00000001"):\n            continue\n        # Binance wallet is authoritative. Ignore residual dust that cannot be\n        # sold as a real position, otherwise stale trade history resurrects it\n        # every worker cycle.\n        try:\n            sellable = _sellable_quantity(client, symbol, quantity)\n            current_price = client.ticker_price(symbol)\n        except BinanceError:\n            continue\n        if sellable <= 0 or sellable * current_price < Decimal("5"):\n            continue\n        quantity = sellable\n        avg_price = lot["cost"] / lot["qty"] if lot["qty"] > 0 else Decimal("0")\n'''
if old not in text: raise SystemExit('recovery block not found')
text = text.replace(old, new, 1)
p.write_text(text)

# 2) Put actual Binance balances in heartbeat.
p = Path('trader/worker.py')
text = p.read_text()
old = '''                price_text = ",".join(f"{pair}:{client.ticker_price(pair)}" for pair in pairs)\n                reporter.record_event(\n                    "heartbeat",\n                    f"live={allow_new_entries};available={available_balance};quote={quote_asset};{context};"\n                    f"signals={signal_text};scores={score_text};scalp_scores={scalp_score_text};"\n                    f"prices={price_text};markets={','.join(pairs)};"\n'''
new = '''                price_text = ",".join(f"{pair}:{client.ticker_price(pair)}" for pair in pairs)\n                account_snapshot = client.account()\n                balances_text = ",".join(\n                    f"{row.get('asset')}:{Decimal(str(row.get('free','0'))) + Decimal(str(row.get('locked','0')))}"\n                    for row in account_snapshot.get("balances", [])\n                    if Decimal(str(row.get("free", "0"))) + Decimal(str(row.get("locked", "0"))) > 0\n                )\n                reporter.record_event(\n                    "heartbeat",\n                    f"live={allow_new_entries};available={available_balance};quote={quote_asset};{context};"\n                    f"signals={signal_text};scores={score_text};scalp_scores={scalp_score_text};"\n                    f"prices={price_text};balances={balances_text};markets={','.join(pairs)};"\n'''
if old not in text: raise SystemExit('worker heartbeat block not found')
text = text.replace(old, new, 1)
p.write_text(text)

# 3) Dashboard ownership/value comes from Binance balances when present.
p = Path('app/trading-dashboard.tsx')
text = p.read_text()
anchor = '''  const marketPrices = useMemo(() => {\n    const prices = new Map<string, number>();\n    const match = lastEvent?.message.match(/(?:^|;)prices=([^;]+)/);\n    if (!match) return prices;\n    for (const item of match[1].split(",")) {\n      const [symbol, rawPrice] = item.split(":");\n      const value = Number(rawPrice);\n      if (symbol && Number.isFinite(value)) prices.set(symbol, value);\n    }\n    return prices;\n  }, [lastEvent]);\n'''
addition = anchor + '''\n  const binanceBalances = useMemo(() => {\n    const balances = new Map<string, number>();\n    const match = lastEvent?.message.match(/(?:^|;)balances=([^;]+)/);\n    if (!match) return balances;\n    for (const item of match[1].split(",")) {\n      const [asset, rawQty] = item.split(":");\n      const qty = Number(rawQty);\n      if (asset && Number.isFinite(qty)) balances.set(asset, qty);\n    }\n    return balances;\n  }, [lastEvent]);\n'''
if anchor not in text: raise SystemExit('marketPrices anchor not found')
text = text.replace(anchor, addition, 1)
old = '''    const pnl = assetTrades.reduce((sum, trade) => sum + Number(trade.pnl ?? 0), 0);\n    const currentPrice = marketPrices.get(symbol) ?? null;\n    const currentValue = currentPrice === null ? null : quantity * currentPrice;\n    const unrealized = currentValue === null ? null : currentValue - invested;\n    return { asset, invested, quantity, pnl, currentPrice, currentValue, unrealized, owned: quantity > 0.000000001 };\n  }).sort((a, b) => Number(b.owned) - Number(a.owned) || MARKET_UNIVERSE.indexOf(a.asset as typeof MARKET_UNIVERSE[number]) - MARKET_UNIVERSE.indexOf(b.asset as typeof MARKET_UNIVERSE[number])), [assets, settings.quote_asset, trades, marketPrices]);\n'''
new = '''    const pnl = assetTrades.reduce((sum, trade) => sum + Number(trade.pnl ?? 0), 0);\n    const walletQuantity = binanceBalances.has(asset) ? Number(binanceBalances.get(asset)) : quantity;\n    const authoritativeQuantity = walletQuantity * (marketPrices.get(symbol) ?? 0) >= 5 ? walletQuantity : 0;\n    const currentPrice = marketPrices.get(symbol) ?? null;\n    const currentValue = currentPrice === null ? null : authoritativeQuantity * currentPrice;\n    const adjustedInvested = quantity > 0 && authoritativeQuantity > 0 ? invested * Math.min(1, authoritativeQuantity / quantity) : 0;\n    const unrealized = currentValue === null ? null : currentValue - adjustedInvested;\n    return { asset, invested: adjustedInvested, quantity: authoritativeQuantity, pnl, currentPrice, currentValue, unrealized, owned: authoritativeQuantity > 0.000000001 };\n  }).sort((a, b) => Number(b.owned) - Number(a.owned) || MARKET_UNIVERSE.indexOf(a.asset as typeof MARKET_UNIVERSE[number]) - MARKET_UNIVERSE.indexOf(b.asset as typeof MARKET_UNIVERSE[number])), [assets, settings.quote_asset, trades, marketPrices, binanceBalances]);\n'''
if old not in text: raise SystemExit('allocation block not found')
text = text.replace(old, new, 1)
p.write_text(text)

# cleanup temporary files after applying
Path('scripts/apply_binance_authoritative_balances.py').unlink(missing_ok=True)
Path('.github/workflows/apply-binance-authority.yml').unlink(missing_ok=True)
