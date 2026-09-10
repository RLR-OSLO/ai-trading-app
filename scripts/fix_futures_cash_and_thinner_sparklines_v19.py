from pathlib import Path

worker = Path('trader/worker.py')
s = worker.read_text(encoding='utf-8')
old = '''def futures_wallet_summary(credentials: BinanceCredentials | None) -> tuple[Decimal, Decimal]:
    if credentials is None:
        return Decimal("0"), Decimal("0")
    try:
        account = BinanceFuturesClient(credentials).account()
        return (
            Decimal(str(account.get("totalWalletBalance", "0") or "0")),
            Decimal(str(account.get("availableBalance", "0") or "0")),
        )
    except Exception:
        LOG.exception("could not read futures wallet summary")
        return Decimal("0"), Decimal("0")
'''
new = '''def futures_wallet_summary(credentials: BinanceCredentials | None, quote_asset: str) -> tuple[Decimal, Decimal]:
    if credentials is None:
        return Decimal("0"), Decimal("0")
    try:
        account = BinanceFuturesClient(credentials).account()
        # In Futures Credits / multi-asset modes Binance can expose the real cash
        # balance on the per-asset row even when top-level totals are not useful.
        assets = account.get("assets", []) or []
        quote_row = next((row for row in assets if str(row.get("asset", "")).upper() == quote_asset.upper()), None)
        if quote_row is not None:
            wallet = Decimal(str(quote_row.get("walletBalance", quote_row.get("marginBalance", "0")) or "0"))
            available = Decimal(str(quote_row.get("availableBalance", quote_row.get("maxWithdrawAmount", "0")) or "0"))
            if wallet != 0 or available != 0:
                return wallet, available
        return (
            Decimal(str(account.get("totalWalletBalance", "0") or "0")),
            Decimal(str(account.get("availableBalance", "0") or "0")),
        )
    except Exception:
        LOG.exception("could not read futures wallet summary")
        return Decimal("0"), Decimal("0")
'''
if new not in s:
    if old not in s:
        raise SystemExit('missing futures_wallet_summary marker')
    s = s.replace(old, new, 1)

old_call = 'futures_total, futures_available = futures_wallet_summary(client.credentials)'
new_call = 'futures_total, futures_available = futures_wallet_summary(client.credentials, quote_asset)'
if new_call not in s:
    if old_call not in s:
        raise SystemExit('missing futures_wallet_summary call marker')
    s = s.replace(old_call, new_call, 1)
worker.write_text(s, encoding='utf-8')
print('patched futures wallet cash read')

css = Path('app/globals.css')
c = css.read_text(encoding='utf-8')
old_css = 'stroke-width:2.2;vector-effect:non-scaling-stroke'
new_css = 'stroke-width:1.15;vector-effect:non-scaling-stroke'
if new_css not in c:
    if old_css not in c:
        raise SystemExit('missing sparkline stroke marker')
    c = c.replace(old_css, new_css, 1)
css.write_text(c, encoding='utf-8')
print('patched thinner sparklines')
print('FIX_V19_OK')
