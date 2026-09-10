from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    s = p.read_text(encoding='utf-8')
    if new in s:
        print(f'already patched {path}')
        return
    if old not in s:
        raise SystemExit(f'marker missing in {path}: {old[:120]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')
    print(f'patched {path}')

# Worker: read futures wallet and publish it in heartbeat.
replace_once(
    'trader/worker.py',
    'from .derivatives_live import run_short_cycle\n',
    'from .derivatives_live import run_short_cycle\nfrom .derivatives import BinanceFuturesClient\n'
)

replace_once(
    'trader/worker.py',
    'def bullrun_candidate(analysis: MarketAnalysis, scalp: ScalpAnalysis, risk_profile: str) -> bool:\n',
    '''def futures_wallet_summary(credentials: BinanceCredentials | None, quote_asset: str) -> tuple[Decimal, Decimal]:\n    if credentials is None:\n        return Decimal("0"), Decimal("0")\n    try:\n        account = BinanceFuturesClient(credentials).account()\n        total = Decimal(str(account.get("totalWalletBalance", "0") or "0"))\n        available = Decimal(str(account.get("availableBalance", "0") or "0"))\n        return total, available\n    except Exception:\n        LOG.exception("could not read futures wallet summary")\n        return Decimal("0"), Decimal("0")\n\n\ndef bullrun_candidate(analysis: MarketAnalysis, scalp: ScalpAnalysis, risk_profile: str) -> bool:\n'''
)

replace_once(
    'trader/worker.py',
    '                balances_text, account_total, invested_value, wallet_value_text = binance_account_summary(client, quote_asset)\n',
    '                balances_text, spot_account_total, invested_value, wallet_value_text = binance_account_summary(client, quote_asset)\n                futures_total, futures_available = futures_wallet_summary(client.credentials, quote_asset)\n                account_total = spot_account_total + futures_total\n'
)

replace_once(
    'trader/worker.py',
    '                    f"prices={price_text};balances={balances_text};wallet_values={wallet_value_text};account_total={account_total};invested_value={invested_value};markets={\',\'.join(pairs)};"\n',
    '                    f"prices={price_text};balances={balances_text};wallet_values={wallet_value_text};account_total={account_total};spot_total={spot_account_total};spot_available={available_balance};futures_total={futures_total};futures_available={futures_available};invested_value={invested_value};markets={\',\'.join(pairs)};"\n'
)

# Dashboard state for per-card manual amount.
replace_once(
    'app/trading-dashboard.tsx',
    '  const [marketHistory, setMarketHistory] = useState<HistoryMap>({});\n',
    '  const [marketHistory, setMarketHistory] = useState<HistoryMap>({});\n  const [setupAmounts, setSetupAmounts] = useState<Record<string, string>>({});\n'
)

# Add wallet field helpers before totalAssets.
replace_once(
    'app/trading-dashboard.tsx',
    '  const totalAssets = useMemo(() => {\n',
    '''  const heartbeatNumber = (name: string, fallback = 0) => {\n    const match = lastEvent?.message.match(new RegExp(`(?:^|;)${name}=([0-9.]+)`));\n    const value = match ? Number(match[1]) : Number.NaN;\n    return Number.isFinite(value) ? value : fallback;\n  };\n  const spotAvailable = heartbeatNumber("spot_available", availableCapital);\n  const spotTotal = heartbeatNumber("spot_total", Math.max(0, totalAssetsFallback()));\n  const futuresAvailable = heartbeatNumber("futures_available", 0);\n  const futuresTotal = heartbeatNumber("futures_total", 0);\n  function totalAssetsFallback() { return availableCapital + portfolioValue; }\n\n  const totalAssets = useMemo(() => {\n'''
)

# Fix fallback reference inside totalAssets to include futures if heartbeat total unavailable.
replace_once(
    'app/trading-dashboard.tsx',
    '    return Number.isFinite(value) ? value : availableCapital + portfolioValue;\n',
    '    return Number.isFinite(value) ? value : availableCapital + portfolioValue + futuresTotal;\n'
)

# Expand top summary from 3 to 4 columns and make wallet breakdown explicit.
replace_once(
    'app/trading-dashboard.tsx',
    '<div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 18, alignItems: "end" }}>\n        <div><span className="label">TOTAL BINANCE-VERDI</span><strong style={{ display: "block", fontSize: "clamp(2.2rem, 5vw, 4.4rem)", lineHeight: 1.05, marginTop: 8 }}>{money(totalAssets)} {settings.quote_asset}</strong><small>Kun faktisk beholdning på Binance, verdsatt til markedspris</small></div>\n        <div><span className="label">Investert på Binance</span><strong style={{ display: "block", fontSize: "1.6rem", marginTop: 8 }}>{money(portfolioValue)} {settings.quote_asset}</strong><small>Faktisk krypto-beholdning nå</small></div>\n        <div><span className="label">Ledig på Binance</span><strong style={{ display: "block", fontSize: "1.6rem", marginTop: 8 }}>{money(availableCapital)} {settings.quote_asset}</strong><small>Faktisk fri {settings.quote_asset}-saldo</small></div>\n      </div>',
    '<div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr", gap: 18, alignItems: "end" }}>\n        <div><span className="label">TOTAL BINANCE-VERDI</span><strong style={{ display: "block", fontSize: "clamp(2.2rem, 5vw, 4.4rem)", lineHeight: 1.05, marginTop: 8 }}>{money(totalAssets)} {settings.quote_asset}</strong><small>Spot + Futures, verdsatt fra faktisk Binance-konto</small></div>\n        <div><span className="label">Investert i Spot</span><strong style={{ display: "block", fontSize: "1.6rem", marginTop: 8 }}>{money(portfolioValue)} {settings.quote_asset}</strong><small>Krypto-beholdning i Spot</small></div>\n        <div><span className="label">Ledig Spot</span><strong style={{ display: "block", fontSize: "1.6rem", marginTop: 8 }}>{money(spotAvailable)} {settings.quote_asset}</strong><small>Fri saldo for Spot/Margin-flyt</small></div>\n        <div><span className="label">Ledig Futures</span><strong style={{ display: "block", fontSize: "1.6rem", marginTop: 8 }}>{money(futuresAvailable)} {settings.quote_asset}</strong><small>Futures-wallet totalt: {money(futuresTotal)} {settings.quote_asset}</small></div>\n      </div>'
)

# Make suggested size use relevant wallet for futures.
replace_once(
    'app/trading-dashboard.tsx',
    '      const suggested = Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc), availableCapital) * sizeFactor;\n      const mode = direction === "LONG" ? "SPOT" : direction === "SHORT" ? (settings.futures_enabled && settings.risk_profile === "extreme" ? `FUTURES ${settings.leverage}x` : settings.short_enabled ? "MARGIN" : "SHORT AV") : "INGEN HANDEL";\n',
    '      const mode = direction === "LONG" ? "SPOT" : direction === "SHORT" ? (settings.futures_enabled && settings.risk_profile === "extreme" ? `FUTURES ${settings.leverage}x` : settings.short_enabled ? "MARGIN" : "SHORT AV") : "INGEN HANDEL";\n      const walletAvailable = mode.startsWith("FUTURES") ? futuresAvailable : availableCapital;\n      const suggested = Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc), walletAvailable) * sizeFactor;\n'
)

# Add dependencies for futures balance to bestSetups memo.
replace_once(
    'app/trading-dashboard.tsx',
    'settings.leverage, availableCapital]);\n',
    'settings.leverage, availableCapital, futuresAvailable]);\n'
)

# Prioritize function: accept manual amount.
replace_once(
    'app/trading-dashboard.tsx',
    '  async function prioritizeSetup(setup: { symbol: string; direction: "LONG" | "SHORT" | "VENT"; mode: string; suggested: number }) {\n    if (setup.direction === "VENT") return;\n    const confirmed = window.confirm(`Be boten prioritere og gjennomføre ${setup.direction} ${setup.symbol} via ${setup.mode} for ca. ${money(setup.suggested)} ${settings.quote_asset}? Alle vanlige risikogrenser gjelder fortsatt.`);\n',
    '  async function prioritizeSetup(setup: { symbol: string; direction: "LONG" | "SHORT" | "VENT"; mode: string; suggested: number }) {\n    if (setup.direction === "VENT") return;\n    const rawAmount = setupAmounts[setup.symbol] ?? String(setup.suggested.toFixed(2));\n    const requestedAmount = Number(rawAmount);\n    if (!Number.isFinite(requestedAmount) || requestedAmount < 5) { setMessage("Beløpet må være minst 5 USDC."); return; }\n    const hardMax = Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc));\n    if (requestedAmount > hardMax) { setMessage(`Beløpet kan ikke være høyere enn gjeldende maks per posisjon/botkapital (${money(hardMax)} ${settings.quote_asset}).`); return; }\n    const confirmed = window.confirm(`Be boten prioritere og gjennomføre ${setup.direction} ${setup.symbol} via ${setup.mode} for ${money(requestedAmount)} ${settings.quote_asset}? Alle vanlige risikogrenser gjelder fortsatt.`);\n'
)

replace_once(
    'app/trading-dashboard.tsx',
    '      requested_notional: setup.suggested,\n',
    '      requested_notional: requestedAmount,\n'
)

# Replace suggested-size line in cards with editable amount input.
replace_once(
    'app/trading-dashboard.tsx',
    '        <small>Foreslått størrelse: <b>{money(setup.suggested)} {settings.quote_asset}</b></small>\n',
    '        <div className="setup-amount"><small>Beløp ({settings.quote_asset}) · forslag {money(setup.suggested)}</small><input type="number" min={5} max={Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc))} step="1" value={setupAmounts[setup.symbol] ?? setup.suggested.toFixed(2)} onFocus={(event) => event.currentTarget.select()} onChange={(event) => setSetupAmounts((current) => ({ ...current, [setup.symbol]: event.target.value }))} /></div>\n'
)

# Responsive CSS for wallet summary and amount field.
p = Path('app/globals.css')
s = p.read_text(encoding='utf-8')
css = '''\n\n/* Wallet summary + manual setup amount v15 */\n.setup-amount{display:grid;gap:5px;margin-top:4px}.setup-amount input{width:100%;background:rgba(5,15,25,.72);border:1px solid var(--line);border-radius:9px;color:var(--text);padding:8px 10px;font-weight:800}.setup-amount input:focus{outline:2px solid rgba(59,130,246,.35);border-color:rgba(59,130,246,.65)}@media(max-width:900px){.panel>div[style*="gridTemplateColumns: \"2fr 1fr 1fr 1fr\""]{grid-template-columns:1fr 1fr!important}}@media(max-width:620px){.panel>div[style*="gridTemplateColumns: \"2fr 1fr 1fr 1fr\""]{grid-template-columns:1fr!important}}\n'''
if '/* Wallet summary + manual setup amount v15 */' not in s:
    p.write_text(s + css, encoding='utf-8')
    print('patched app/globals.css')
else:
    print('already patched app/globals.css')

print('UPGRADE_WALLETS_MANUAL_AMOUNT_V15_OK')
