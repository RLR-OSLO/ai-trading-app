from pathlib import Path


def rep(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    s = p.read_text(encoding='utf-8')
    if new in s:
        print(f'already: {label}')
        return
    if old not in s:
        raise SystemExit(f'missing marker: {label}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')
    print(f'patched: {label}')

# --- Futures wallet data in worker heartbeat ---
rep('trader/worker.py',
    'from .derivatives_live import run_short_cycle\n',
    'from .derivatives_live import run_short_cycle\nfrom .derivatives import BinanceFuturesClient\n',
    'worker futures import')

rep('trader/worker.py',
    'def bullrun_candidate(analysis: MarketAnalysis, scalp: ScalpAnalysis, risk_profile: str) -> bool:\n',
    '''def futures_wallet_summary(credentials: BinanceCredentials | None) -> tuple[Decimal, Decimal]:\n    if credentials is None:\n        return Decimal("0"), Decimal("0")\n    try:\n        account = BinanceFuturesClient(credentials).account()\n        return (\n            Decimal(str(account.get("totalWalletBalance", "0") or "0")),\n            Decimal(str(account.get("availableBalance", "0") or "0")),\n        )\n    except Exception:\n        LOG.exception("could not read futures wallet summary")\n        return Decimal("0"), Decimal("0")\n\n\ndef bullrun_candidate(analysis: MarketAnalysis, scalp: ScalpAnalysis, risk_profile: str) -> bool:\n''',
    'worker futures wallet helper')

rep('trader/worker.py',
    '                balances_text, account_total, invested_value, wallet_value_text = binance_account_summary(client, quote_asset)\n                reporter.record_event(\n',
    '                balances_text, spot_total, invested_value, wallet_value_text = binance_account_summary(client, quote_asset)\n                futures_total, futures_available = futures_wallet_summary(client.credentials)\n                account_total = spot_total + futures_total\n                reporter.record_event(\n',
    'worker wallet calculation')

rep('trader/worker.py',
    '                    f"prices={price_text};balances={balances_text};wallet_values={wallet_value_text};account_total={account_total};invested_value={invested_value};markets={\',\'.join(pairs)};"\n',
    '                    f"prices={price_text};balances={balances_text};wallet_values={wallet_value_text};account_total={account_total};spot_total={spot_total};spot_available={available_balance};futures_total={futures_total};futures_available={futures_available};invested_value={invested_value};markets={\',\'.join(pairs)};"\n',
    'worker heartbeat wallet fields')

# --- Futures Cross fallback for Binance credit mode (-4175) ---
rep('trader/derivatives.py',
    '            if "-4046" in str(exc):\n                return None\n            raise\n',
    '            if "-4046" in str(exc) or "-4175" in str(exc):\n                return None\n            raise\n',
    'futures cross fallback')

# --- Priority stays visible until executed/rejected/cancelled ---
rep('trader/reporting.py',
    '        self.expire_stale_directives()\n        query = urllib.parse.urlencode({\n            "user_id": f"eq.{self.user_id}",\n            "status": "eq.pending",\n            "expires_at": "gt.now()",\n',
    '        query = urllib.parse.urlencode({\n            "user_id": f"eq.{self.user_id}",\n            "status": "eq.pending",\n',
    'worker persistent priority')

rep('app/trading-dashboard.tsx',
    '      .eq("status", "pending")\n      .gt("expires_at", new Date().toISOString())\n      .order("created_at", { ascending: false });\n',
    '      .eq("status", "pending")\n      .order("created_at", { ascending: false });\n',
    'dashboard persistent priority')

# --- Manual amount state ---
rep('app/trading-dashboard.tsx',
    '  const [marketHistory, setMarketHistory] = useState<HistoryMap>({});\n',
    '  const [marketHistory, setMarketHistory] = useState<HistoryMap>({});\n  const [setupAmounts, setSetupAmounts] = useState<Record<string, string>>({});\n',
    'manual amount state')

# --- Reliable graph history from own Supabase heartbeats instead of public Binance fetch ---
start = '''  useEffect(() => {\n    const symbols = Array.from(new Set([\n      ...assets.map((asset) => `${asset}${settings.quote_asset}`),\n      ...bestSetups.map((setup) => setup.symbol),\n    ])).slice(0, 30);\n    if (!symbols.length) return;\n    let cancelled = false;\n    const loadHistory = async () => {\n      try {\n        const response = await fetch(`/api/market-history?symbols=${encodeURIComponent(symbols.join(","))}`, { cache: "no-store" });\n        if (!response.ok) return;\n        const payload = await response.json() as { series?: HistoryMap };\n        if (!cancelled && payload.series) setMarketHistory(payload.series);\n      } catch {\n        // Mini-grafer er kun visning og skal aldri påvirke tradingmotoren.\n      }\n    };\n    void loadHistory();\n    const timer = window.setInterval(() => void loadHistory(), 60_000);\n    return () => { cancelled = true; window.clearInterval(timer); };\n  }, [assets, bestSetups, settings.quote_asset]);\n'''
newhist = '''  useEffect(() => {\n    let cancelled = false;\n    const loadHistory = async () => {\n      const since = new Date(Date.now() - 12 * 3_600_000).toISOString();\n      const pages = await Promise.all([\n        supabase.from("bot_events").select("message,created_at").eq("event_type", "heartbeat").gte("created_at", since).order("created_at", { ascending: false }).range(0, 999),\n        supabase.from("bot_events").select("message,created_at").eq("event_type", "heartbeat").gte("created_at", since).order("created_at", { ascending: false }).range(1000, 1999),\n      ]);\n      const rows = pages.flatMap((page) => page.data ?? []);\n      const series: HistoryMap = {};\n      for (const row of rows.reverse()) {\n        const match = String(row.message ?? "").match(/(?:^|;)prices=([^;]+)/);\n        if (!match) continue;\n        const t = new Date(row.created_at).getTime();\n        for (const item of match[1].split(",")) {\n          const [symbol, raw] = item.split(":");\n          const c = Number(raw);\n          if (!symbol || !Number.isFinite(c)) continue;\n          (series[symbol] ??= []).push({ t, c });\n        }\n      }\n      if (!cancelled) setMarketHistory(series);\n    };\n    void loadHistory();\n    const timer = window.setInterval(() => void loadHistory(), 60_000);\n    return () => { cancelled = true; window.clearInterval(timer); };\n  }, []);\n'''
rep('app/trading-dashboard.tsx', start, newhist, 'heartbeat chart history')

# --- Wallet numbers and total ---
rep('app/trading-dashboard.tsx',
    '  const totalAssets = useMemo(() => {\n',
    '''  const heartbeatNumber = (name: string, fallback = 0) => {\n    const match = lastEvent?.message.match(new RegExp(`(?:^|;)${name}=([0-9.]+)`));\n    const value = match ? Number(match[1]) : Number.NaN;\n    return Number.isFinite(value) ? value : fallback;\n  };\n  const spotAvailable = heartbeatNumber("spot_available", availableCapital);\n  const spotTotal = heartbeatNumber("spot_total", availableCapital + portfolioValue);\n  const futuresAvailable = heartbeatNumber("futures_available", 0);\n  const futuresTotal = heartbeatNumber("futures_total", 0);\n\n  const totalAssets = useMemo(() => {\n''',
    'dashboard wallet numbers')

rep('app/trading-dashboard.tsx',
    '    return Number.isFinite(value) ? value : availableCapital + portfolioValue;\n  }, [availableCapital, lastEvent, portfolioValue]);\n',
    '    return Number.isFinite(value) ? value : spotTotal + futuresTotal;\n  }, [lastEvent, spotTotal, futuresTotal]);\n',
    'dashboard total wallet fallback')

# --- Suggested amount uses relevant wallet ---
rep('app/trading-dashboard.tsx',
    '      const suggested = Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc), availableCapital) * sizeFactor;\n      const mode = direction === "LONG" ? "SPOT" : direction === "SHORT" ? (settings.futures_enabled && settings.risk_profile === "extreme" ? `FUTURES ${settings.leverage}x` : settings.short_enabled ? "MARGIN" : "SHORT AV") : "INGEN HANDEL";\n',
    '      const mode = direction === "LONG" ? "SPOT" : direction === "SHORT" ? (settings.futures_enabled && settings.risk_profile === "extreme" ? `FUTURES ${settings.leverage}x` : settings.short_enabled ? "MARGIN" : "SHORT AV") : "INGEN HANDEL";\n      const walletAvailable = mode.startsWith("FUTURES") ? futuresAvailable : spotAvailable;\n      const suggested = Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc), walletAvailable) * sizeFactor;\n',
    'wallet-aware suggested amount')

rep('app/trading-dashboard.tsx',
    'settings.leverage, availableCapital]);\n',
    'settings.leverage, availableCapital, spotAvailable, futuresAvailable]);\n',
    'best setup wallet dependencies')

# --- Manual amount on submit ---
rep('app/trading-dashboard.tsx',
    '  async function prioritizeSetup(setup: { symbol: string; direction: "LONG" | "SHORT" | "VENT"; mode: string; suggested: number }) {\n    if (setup.direction === "VENT") return;\n    const confirmed = window.confirm(`Be boten prioritere og gjennomføre ${setup.direction} ${setup.symbol} via ${setup.mode} for ca. ${money(setup.suggested)} ${settings.quote_asset}? Alle vanlige risikogrenser gjelder fortsatt.`);\n',
    '''  async function prioritizeSetup(setup: { symbol: string; direction: "LONG" | "SHORT" | "VENT"; mode: string; suggested: number }) {\n    if (setup.direction === "VENT") return;\n    const requestedAmount = Number(setupAmounts[setup.symbol] ?? setup.suggested.toFixed(2));\n    if (!Number.isFinite(requestedAmount) || requestedAmount < 5) { setMessage("Beløpet må være minst 5 USDC."); return; }\n    const hardMax = Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc));\n    if (requestedAmount > hardMax) { setMessage(`Beløpet kan ikke være høyere enn ${money(hardMax)} ${settings.quote_asset}.`); return; }\n    const confirmed = window.confirm(`Be boten prioritere og gjennomføre ${setup.direction} ${setup.symbol} via ${setup.mode} for ${money(requestedAmount)} ${settings.quote_asset}? Alle vanlige risikogrenser gjelder fortsatt.`);\n''',
    'manual amount validation')

rep('app/trading-dashboard.tsx',
    '      requested_notional: Math.max(5, setup.suggested),\n',
    '      requested_notional: requestedAmount,\n',
    'manual amount directive')

# --- Editable amount field on cards ---
rep('app/trading-dashboard.tsx',
    '        <small>Foreslått størrelse: <b>{money(setup.suggested)} {settings.quote_asset}</b></small>\n',
    '        <div className="setup-amount"><small>Beløp ({settings.quote_asset}) · forslag {money(setup.suggested)}</small><input type="number" min={5} max={Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc))} step="1" value={setupAmounts[setup.symbol] ?? setup.suggested.toFixed(2)} onFocus={(event) => event.currentTarget.select()} onChange={(event) => setSetupAmounts((current) => ({ ...current, [setup.symbol]: event.target.value }))} /></div>\n',
    'editable setup amount')

# --- Explicit top wallet overview ---
oldtop = '''      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 18, alignItems: "end" }}>\n        <div><span className="label">TOTAL BINANCE-VERDI</span><strong style={{ display: "block", fontSize: "clamp(2.2rem, 5vw, 4.4rem)", lineHeight: 1.05, marginTop: 8 }}>{money(totalAssets)} {settings.quote_asset}</strong><small>Kun faktisk beholdning på Binance, verdsatt til markedspris</small></div>\n        <div><span className="label">Investert på Binance</span><strong style={{ display: "block", fontSize: "1.6rem", marginTop: 8 }}>{money(portfolioValue)} {settings.quote_asset}</strong><small>Faktisk krypto-beholdning nå</small></div>\n        <div><span className="label">Ledig på Binance</span><strong style={{ display: "block", fontSize: "1.6rem", marginTop: 8 }}>{money(availableCapital)} {settings.quote_asset}</strong><small>Faktisk fri {settings.quote_asset}-saldo</small></div>\n      </div>'''
newtop = '''      <div className="wallet-overview">\n        <div className="wallet-total"><span className="label">TOTAL BINANCE-VERDI</span><strong>{money(totalAssets)} {settings.quote_asset}</strong><small>Spot + Futures</small></div>\n        <div><span className="label">SPOT TOTALT</span><strong>{money(spotTotal)} {settings.quote_asset}</strong><small>Ledig Spot: {money(spotAvailable)} · Investert Spot: {money(portfolioValue)}</small></div>\n        <div><span className="label">FUTURES TOTALT</span><strong>{money(futuresTotal)} {settings.quote_asset}</strong><small>Ledig Futures: {money(futuresAvailable)} {settings.quote_asset}</small></div>\n      </div>'''
rep('app/trading-dashboard.tsx', oldtop, newtop, 'top wallet overview')

# CSS
p = Path('app/globals.css')
s = p.read_text(encoding='utf-8')
css = '''\n\n/* v18 wallet overview and manual trade amount */\n.wallet-overview{display:grid;grid-template-columns:2fr 1fr 1fr;gap:18px;align-items:end}.wallet-overview strong{display:block;font-size:1.55rem;margin-top:8px}.wallet-overview .wallet-total strong{font-size:clamp(2.2rem,5vw,4.4rem);line-height:1.05}.setup-amount{display:grid;gap:5px;margin-top:4px}.setup-amount input{width:100%;background:rgba(5,15,25,.72);border:1px solid var(--line);border-radius:9px;color:var(--text);padding:8px 10px;font-weight:800}.setup-amount input:focus{outline:2px solid rgba(59,130,246,.35);border-color:rgba(59,130,246,.65)}@media(max-width:800px){.wallet-overview{grid-template-columns:1fr}.wallet-overview .wallet-total strong{font-size:2.6rem}}\n'''
if '/* v18 wallet overview and manual trade amount */' not in s:
    p.write_text(s + css, encoding='utf-8')
    print('patched: v18 css')
else:
    print('already: v18 css')

print('FIX_V18_OK')
