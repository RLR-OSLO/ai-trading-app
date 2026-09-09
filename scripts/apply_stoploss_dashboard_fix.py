from pathlib import Path

portfolio = Path('trader/portfolio_live.py')
text = portfolio.read_text()
old_trailing = '''            if current <= trailing_stop and position.protective_order_list_id is None:\n                return _market_sell(client, state, state_path, position, limits, report_trade, now, "trailing_stop")\n'''
new_trailing = '''            if current <= trailing_stop:\n                if position.protective_order_list_id is not None:\n                    if not _cancel_protection(client, state, state_path, position):\n                        notes.append(f"trailing_stop_cancel_failed:{position.symbol}")\n                        continue\n                return _market_sell(client, state, state_path, position, limits, report_trade, now, "trailing_stop")\n'''
old_hard = '''        if current <= hard_stop and position.protective_order_list_id is None:\n            return _market_sell(client, state, state_path, position, limits, report_trade, now, "hard_stop")\n'''
new_hard = '''        if current <= hard_stop:\n            if position.protective_order_list_id is not None:\n                if not _cancel_protection(client, state, state_path, position):\n                    notes.append(f"hard_stop_cancel_failed:{position.symbol}")\n                    continue\n            return _market_sell(client, state, state_path, position, limits, report_trade, now, "hard_stop")\n'''
if old_trailing not in text or old_hard not in text:
    raise SystemExit('Expected stop-loss blocks not found')
text = text.replace(old_trailing, new_trailing).replace(old_hard, new_hard)
portfolio.write_text(text)

dash = Path('app/trading-dashboard.tsx')
text = dash.read_text()
old_alloc = '''    const assetTrades = trades.filter((trade) => trade.symbol === symbol);\n    const invested = assetTrades.reduce((sum, trade) => {\n      const cost = Number(trade.quantity) * Number(trade.entry_price ?? 0);\n      return Math.max(0, sum + (trade.side === "BUY" ? cost : -cost));\n    }, 0);\n    const quantity = Math.max(0, assetTrades.reduce((sum, trade) => sum + (trade.side === "BUY" ? Number(trade.quantity) : -Number(trade.quantity)), 0));\n'''
new_alloc = '''    const assetTrades = trades.filter((trade) => trade.symbol === symbol);\n    const orderedTrades = [...assetTrades].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());\n    let quantity = 0;\n    let invested = 0;\n    for (const trade of orderedTrades) {\n      const tradeQuantity = Math.max(0, Number(trade.quantity));\n      if (trade.side === "BUY") {\n        quantity += tradeQuantity;\n        invested += tradeQuantity * Number(trade.entry_price ?? 0);\n      } else if (quantity > 0) {\n        const soldQuantity = Math.min(quantity, tradeQuantity);\n        const averageCost = invested / quantity;\n        quantity = Math.max(0, quantity - soldQuantity);\n        invested = Math.max(0, invested - soldQuantity * averageCost);\n        if (quantity < 0.000000001) { quantity = 0; invested = 0; }\n      }\n    }\n'''
if old_alloc not in text:
    raise SystemExit('Expected dashboard allocation block not found')
text = text.replace(old_alloc, new_alloc)
dash.write_text(text)

# Remove this temporary machinery so the branch diff only contains the real fixes.
Path('scripts/apply_stoploss_dashboard_fix.py').unlink(missing_ok=True)
Path('.github/workflows/apply-stoploss-fix.yml').unlink(missing_ok=True)
