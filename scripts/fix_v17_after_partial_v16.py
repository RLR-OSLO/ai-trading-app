from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    s = p.read_text(encoding='utf-8')
    if new in s:
        print(f'already: {label}')
        return
    if old not in s:
        raise SystemExit(f'missing marker: {label}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')
    print(f'patched: {label}')

# --- worker wallet summary ---
replace_once(
    'trader/worker.py',
    'from .derivatives_live import run_short_cycle\n',
    'from .derivatives_live import run_short_cycle\nfrom .derivatives import BinanceFuturesClient\n',
    'worker futures import',
)

helper = '''def futures_wallet_summary(credentials: BinanceCredentials | None, quote_asset: str) -> tuple[Decimal, Decimal]:\n    if credentials is None:\n        return Decimal("0"), Decimal("0")\n    try:\n        account = BinanceFuturesClient(credentials).account()\n        assets = account.get("assets", [])\n        quote = next((row for row in assets if str(row.get("asset")) == quote_asset), None)\n        if quote is not None:\n            total = Decimal(str(quote.get("walletBalance", "0") or "0"))\n            available = Decimal(str(quote.get("availableBalance", account.get("availableBalance", "0")) or "0"))\n            return total, available\n        total = Decimal(str(account.get("totalWalletBalance", "0") or "0"))\n        available = Decimal(str(account.get("availableBalance", "0") or "0"))\n        return total, available\n    except Exception:\n        LOG.exception("could not read futures wallet summary")\n        return Decimal("0"), Decimal("0")\n\n\n'''
p = Path('trader/worker.py')
s = p.read_text(encoding='utf-8')
if 'def futures_wallet_summary(' not in s:
    marker = 'def bullrun_candidate('
    if marker not in s:
        raise SystemExit('missing marker: worker futures helper insertion')
    s = s.replace(marker, helper + marker, 1)
    p.write_text(s, encoding='utf-8')
    print('patched: worker futures wallet helper')
else:
    print('already: worker futures wallet helper')

replace_once(
    'trader/worker.py',
    '                balances_text, account_total, invested_value, wallet_value_text = binance_account_summary(client, quote_asset)\n',
    '                balances_text, spot_account_total, invested_value, wallet_value_text = binance_account_summary(client, quote_asset)\n                futures_total, futures_available = futures_wallet_summary(client.credentials, quote_asset)\n                account_total = spot_account_total + futures_total\n',
    'worker total wallet calculation',
)
replace_once(
    'trader/worker.py',
    '                    f"prices={price_text};balances={balances_text};wallet_values={wallet_value_text};account_total={account_total};invested_value={invested_value};markets={\',\'.join(pairs)};"\n',
    '                    f"prices={price_text};balances={balances_text};wallet_values={wallet_value_text};account_total={account_total};spot_total={spot_account_total};spot_available={available_balance};futures_total={futures_total};futures_available={futures_available};invested_value={invested_value};markets={\',\'.join(pairs)};"\n',
    'worker heartbeat wallet fields',
)

# --- futures cross fallback ---
replace_once(
    'trader/derivatives.py',
    '''        except BinanceError as exc:\n            if "-4046" in str(exc):\n                return None\n            raise\n''',
    '''        except BinanceError as exc:\n            text = str(exc)\n            if "-4046" in text:\n                return None\n            if "-4175" in text:\n                # Binance Futures Credits/Cross-only account: keep CROSS and continue.\n                return None\n            raise\n''',
    'futures cross fallback',
)

# --- dashboard manual amounts and wallet cards ---
p = Path('app/trading-dashboard.tsx')
s = p.read_text(encoding='utf-8')
if 'const [setupAmounts, setSetupAmounts]' not in s:
    s = s.replace(
        '  const [marketHistory, setMarketHistory] = useState<HistoryMap>({});\n',
        '  const [marketHistory, setMarketHistory] = useState<HistoryMap>({});\n  const [setupAmounts, setSetupAmounts] = useState<Record<string, string>>({});\n',
        1,
    )
    print('patched: setup amount state')
else:
    print('already: setup amount state')

old = '''  const totalAssets = useMemo(() => {\n    const match = lastEvent?.message.match(/(?:^|;)account_total=([0-9.]+)/);\n    const value = match ? Number(match[1]) : Number.NaN;\n    return Number.isFinite(value) ? value : availableCapital + portfolioValue;\n  }, [availableCapital, lastEvent, portfolioValue]);\n'''
new = '''  const heartbeatNumber = (name: string, fallback = 0) => {\n    const match = lastEvent?.message.match(new RegExp(`(?:^|;)${name}=([0-9.]+)`));\n    const value = match ? Number(match[1]) : Number.NaN;\n    return Number.isFinite(value) ? value : fallback;\n  };\n  const spotAvailable = heartbeatNumber("spot_available", availableCapital);\n  const spotTotal = heartbeatNumber("spot_total", availableCapital + portfolioValue);\n  const futuresAvailable = heartbeatNumber("futures_available", 0);\n  const futuresTotal = heartbeatNumber("futures_total", 0);\n\n  const totalAssets = useMemo(() => {\n    const match = lastEvent?.message.match(/(?:^|;)account_total=([0-9.]+)/);\n    const value = match ? Number(match[1]) : Number.NaN;\n    return Number.isFinite(value) ? value : spotTotal + futuresTotal;\n  }, [lastEvent, spotTotal, futuresTotal]);\n'''
if new not in s:
    if old not in s: raise SystemExit('missing marker: dashboard wallet numbers')
    s = s.replace(old, new, 1)
    print('patched: dashboard wallet numbers')
else:
    print('already: dashboard wallet numbers')

old = '''      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 18, alignItems: "end" }}>\n        <div><span className="label">TOTAL BINANCE-VERDI</span><strong style={{ display: "block", fontSize: "clamp(2.2rem, 5vw, 4.4rem)", lineHeight: 1.05, marginTop: 8 }}>{money(totalAssets)} {settings.quote_asset}</strong><small>Kun faktisk beholdning på Binance, verdsatt til markedspris</small></div>\n        <div><span className="label">Investert på Binance</span><strong style={{ display: "block", fontSize: "1.6rem", marginTop: 8 }}>{money(portfolioValue)} {settings.quote_asset}</strong><small>Faktisk krypto-beholdning nå</small></div>\n        <div><span className="label">Ledig på Binance</span><strong style={{ display: "block", fontSize: "1.6rem", marginTop: 8 }}>{money(availableCapital)} {settings.quote_asset}</strong><small>Faktisk fri {settings.quote_asset}-saldo</small></div>\n      </div>'''
new = '''      <div className="wallet-summary-grid">\n        <div className="wallet-total"><span className="label">TOTAL BINANCE-VERDI</span><strong>{money(totalAssets)} {settings.quote_asset}</strong><small>Spot + Futures</small></div>\n        <div><span className="label">SPOT TOTALT</span><strong>{money(spotTotal)} {settings.quote_asset}</strong><small>Ledig Spot: {money(spotAvailable)} · Investert Spot: {money(portfolioValue)}</small></div>\n        <div><span className="label">FUTURES TOTALT</span><strong>{money(futuresTotal)} {settings.quote_asset}</strong><small>Ledig Futures: {money(futuresAvailable)} {settings.quote_asset}</small></div>\n      </div>'''
if new not in s:
    if old not in s: raise SystemExit('missing marker: top wallet summary')
    s = s.replace(old, new, 1)
    print('patched: top wallet summary')
else:
    print('already: top wallet summary')

old = '      const suggested = Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc), availableCapital) * sizeFactor;\n      const mode = direction === "LONG" ? "SPOT" : direction === "SHORT" ? (settings.futures_enabled && settings.risk_profile === "extreme" ? `FUTURES ${settings.leverage}x` : settings.short_enabled ? "MARGIN" : "SHORT AV") : "INGEN HANDEL";\n'
new = '      const mode = direction === "LONG" ? "SPOT" : direction === "SHORT" ? (settings.futures_enabled && settings.risk_profile === "extreme" ? `FUTURES ${settings.leverage}x` : settings.short_enabled ? "MARGIN" : "SHORT AV") : "INGEN HANDEL";\n      const walletAvailable = mode.startsWith("FUTURES") ? futuresAvailable : availableCapital;\n      const suggested = Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc), walletAvailable) * sizeFactor;\n'
if new not in s:
    if old not in s: raise SystemExit('missing marker: futures-aware suggestion')
    s = s.replace(old, new, 1)
    print('patched: futures-aware suggestion')
else:
    print('already: futures-aware suggestion')

s = s.replace('settings.leverage, availableCapital]);', 'settings.leverage, availableCapital, futuresAvailable]);', 1) if 'settings.leverage, availableCapital, futuresAvailable]);' not in s else s

old = '''  async function prioritizeSetup(setup: { symbol: string; direction: "LONG" | "SHORT" | "VENT"; mode: string; suggested: number }) {\n    if (setup.direction === "VENT") return;\n    const confirmed = window.confirm(`Be boten prioritere og gjennomføre ${setup.direction} ${setup.symbol} via ${setup.mode} for ca. ${money(setup.suggested)} ${settings.quote_asset}? Alle vanlige risikogrenser gjelder fortsatt.`);\n'''
new = '''  async function prioritizeSetup(setup: { symbol: string; direction: "LONG" | "SHORT" | "VENT"; mode: string; suggested: number }) {\n    if (setup.direction === "VENT") return;\n    const rawAmount = setupAmounts[setup.symbol] ?? setup.suggested.toFixed(2);\n    const requestedAmount = Number(rawAmount);\n    if (!Number.isFinite(requestedAmount) || requestedAmount < 5) { setMessage("Beløpet må være minst 5 USDC."); return; }\n    const hardMax = Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc));\n    if (requestedAmount > hardMax) { setMessage(`Beløpet kan ikke være høyere enn ${money(hardMax)} ${settings.quote_asset}.`); return; }\n    const confirmed = window.confirm(`Be boten prioritere og gjennomføre ${setup.direction} ${setup.symbol} via ${setup.mode} for ${money(requestedAmount)} ${settings.quote_asset}? Alle vanlige risikogrenser gjelder fortsatt.`);\n'''
if new not in s:
    if old not in s: raise SystemExit('missing marker: prioritize manual amount')
    s = s.replace(old, new, 1)
    print('patched: prioritize manual amount')
else:
    print('already: prioritize manual amount')

if 'requested_notional: requestedAmount,' not in s:
    if 'requested_notional: setup.suggested,' not in s: raise SystemExit('missing marker: requested notional')
    s = s.replace('requested_notional: setup.suggested,', 'requested_notional: requestedAmount,', 1)
    print('patched: requested notional')
else:
    print('already: requested notional')

old = '        <small>Foreslått størrelse: <b>{money(setup.suggested)} {settings.quote_asset}</b></small>\n'
new = '        <div className="setup-amount"><small>Beløp ({settings.quote_asset}) · botforslag {money(setup.suggested)}</small><input type="number" min={5} max={Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc))} step="1" value={setupAmounts[setup.symbol] ?? setup.suggested.toFixed(2)} onFocus={(event) => event.currentTarget.select()} onChange={(event) => setSetupAmounts((current) => ({ ...current, [setup.symbol]: event.target.value }))} /></div>\n'
if new not in s:
    if old not in s: raise SystemExit('missing marker: setup amount input')
    s = s.replace(old, new, 1)
    print('patched: setup amount input')
else:
    print('already: setup amount input')

p.write_text(s, encoding='utf-8')

# CSS
p = Path('app/globals.css')
s = p.read_text(encoding='utf-8')
css = '''\n\n/* Wallet + manual amount v17 */\n.wallet-summary-grid{display:grid;grid-template-columns:2fr 1fr 1fr;gap:22px;align-items:end}.wallet-summary-grid strong{display:block;font-size:1.55rem;margin-top:8px}.wallet-summary-grid .wallet-total strong{font-size:clamp(2.2rem,5vw,4.4rem);line-height:1.05}.setup-amount{display:grid;gap:5px;margin-top:7px}.setup-amount input{width:100%;box-sizing:border-box;background:rgba(5,15,25,.82);border:1px solid rgba(96,165,250,.45);border-radius:9px;color:#fff;padding:9px 10px;font-weight:800;font-size:14px}.setup-amount input:focus{outline:2px solid rgba(59,130,246,.35);border-color:#60a5fa}@media(max-width:800px){.wallet-summary-grid{grid-template-columns:1fr 1fr}.wallet-summary-grid .wallet-total{grid-column:1/-1}}@media(max-width:520px){.wallet-summary-grid{grid-template-columns:1fr}}\n'''
if '/* Wallet + manual amount v17 */' not in s:
    p.write_text(s + css, encoding='utf-8')
    print('patched: dashboard css')
else:
    print('already: dashboard css')

print('FIX_V17_OK')
