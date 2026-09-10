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

# Add sparkline helper after crypto formatter.
replace_once(
    'app/trading-dashboard.tsx',
    'const crypto = (value: number) => new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 8 }).format(value);\n',
    '''const crypto = (value: number) => new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 8 }).format(value);\n\ntype HistoryPoint = { t: number; c: number };\ntype HistoryMap = Record<string, HistoryPoint[]>;\n\nfunction Sparkline({ points, hours }: { points: HistoryPoint[]; hours: 3 | 6 | 12 }) {\n  const cutoff = Date.now() - hours * 3_600_000;\n  const visible = points.filter((point) => point.t >= cutoff);\n  if (visible.length < 2) return <div className="sparkline-empty">Ingen grafdata</div>;\n  const values = visible.map((point) => point.c);\n  const min = Math.min(...values);\n  const max = Math.max(...values);\n  const span = Math.max(max - min, Math.max(Math.abs(max), 1) * 0.000001);\n  const width = 150;\n  const height = 42;\n  const path = visible.map((point, index) => {\n    const x = (index / Math.max(1, visible.length - 1)) * width;\n    const y = height - ((point.c - min) / span) * height;\n    return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;\n  }).join(" ");\n  const first = visible[0].c;\n  const last = visible[visible.length - 1].c;\n  const change = first ? ((last / first) - 1) * 100 : 0;\n  const trend = change >= 0 ? "up" : "down";\n  return <div className={`sparkline-wrap ${trend}`} title={`${change >= 0 ? "+" : ""}${change.toFixed(2)} % siste ${hours}t`}>\n    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true"><path d={path} /></svg>\n    <span>{change >= 0 ? "+" : ""}{change.toFixed(2)} %</span>\n  </div>;\n}\n'''
)

# Add state.
replace_once(
    'app/trading-dashboard.tsx',
    '  const [priorityBusy, setPriorityBusy] = useState<number | null>(null);\n',
    '  const [priorityBusy, setPriorityBusy] = useState<number | null>(null);\n  const [historyHours, setHistoryHours] = useState<3 | 6 | 12>(6);\n  const [marketHistory, setMarketHistory] = useState<HistoryMap>({});\n'
)

# Add history loader after priority directives effect.
replace_once(
    'app/trading-dashboard.tsx',
    '  }, []);\n\n  const stats = useMemo(() => {\n',
    '''  }, []);\n\n  useEffect(() => {\n    const symbols = Array.from(new Set([\n      ...assets.map((asset) => `${asset}${settings.quote_asset}`),\n      ...bestSetups.map((setup) => setup.symbol),\n    ])).slice(0, 30);\n    if (!symbols.length) return;\n    let cancelled = false;\n    const loadHistory = async () => {\n      try {\n        const response = await fetch(`/api/market-history?symbols=${encodeURIComponent(symbols.join(","))}`, { cache: "no-store" });\n        if (!response.ok) return;\n        const payload = await response.json() as { series?: HistoryMap };\n        if (!cancelled && payload.series) setMarketHistory(payload.series);\n      } catch {\n        // Mini-grafer er pynt/beslutningsstøtte og skal aldri påvirke tradingmotoren.\n      }\n    };\n    void loadHistory();\n    const timer = window.setInterval(() => void loadHistory(), 60_000);\n    return () => { cancelled = true; window.clearInterval(timer); };\n  }, [assets, bestSetups, settings.quote_asset]);\n\n  const stats = useMemo(() => {\n'''
)

# Add global period control to best setup header.
replace_once(
    'app/trading-dashboard.tsx',
    '<div className="panel-head"><div><p className="eyebrow">BESTE OPPSETT AKKURAT NÅ</p><h3>Botens høyest rangerte muligheter</h3></div><button type="button" className="secondary compact" onClick={() => void load()}>Oppdater nå</button></div>',
    '<div className="panel-head"><div><p className="eyebrow">BESTE OPPSETT AKKURAT NÅ</p><h3>Botens høyest rangerte muligheter</h3></div><div className="chart-actions"><div className="chart-range" aria-label="Grafperiode">{([3,6,12] as const).map((hours) => <button type="button" key={hours} className={historyHours === hours ? "active" : ""} onClick={() => setHistoryHours(hours)}>{hours}t</button>)}</div><button type="button" className="secondary compact" onClick={() => void load()}>Oppdater nå</button></div></div>'
)

# Add sparkline to best setup card after score.
replace_once(
    'app/trading-dashboard.tsx',
    '        <small>Aktuell score: <b>{setup.rawScore}</b> · Long {setup.longScore} / Short {setup.shortScore}</small>\n        <small>Foreslått størrelse: <b>{money(setup.suggested)} {settings.quote_asset}</b></small>',
    '        <small>Aktuell score: <b>{setup.rawScore}</b> · Long {setup.longScore} / Short {setup.shortScore}</small>\n        <Sparkline points={marketHistory[setup.symbol] ?? []} hours={historyHours} />\n        <small>Foreslått størrelse: <b>{money(setup.suggested)} {settings.quote_asset}</b></small>'
)

# Add sparkline in portfolio cards before pnl span.
replace_once(
    'app/trading-dashboard.tsx',
    '</small></div><span className={(unrealized ?? pnl)',
    '</small><Sparkline points={marketHistory[`${asset}${settings.quote_asset}`] ?? []} hours={historyHours} /></div><span className={(unrealized ?? pnl)'
)

# CSS.
p = Path('app/globals.css')
s = p.read_text(encoding='utf-8')
css = '''\n\n/* Mini market charts v14 */\n.chart-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.chart-range{display:inline-flex;padding:3px;border:1px solid var(--line);border-radius:10px;background:rgba(8,20,33,.55)}.chart-range button{border:0;background:transparent;color:var(--muted);padding:5px 9px;border-radius:7px;font-size:10px;font-weight:800;cursor:pointer}.chart-range button.active{background:rgba(59,130,246,.22);color:#dbeafe}.sparkline-wrap{display:flex;align-items:center;gap:8px;min-width:0;margin-top:3px}.sparkline-wrap svg{display:block;width:150px;height:42px;overflow:visible}.sparkline-wrap path{fill:none;stroke:currentColor;stroke-width:2.2;vector-effect:non-scaling-stroke}.sparkline-wrap.up{color:#4ade80}.sparkline-wrap.down{color:#fb7185}.sparkline-wrap span{font-size:10px;font-weight:800;white-space:nowrap}.sparkline-empty{height:42px;display:flex;align-items:center;color:var(--muted);font-size:10px}.best-setup-card .sparkline-wrap{justify-content:flex-start}.asset .sparkline-wrap{margin-top:7px}.asset .sparkline-wrap svg{width:105px;height:30px}@media(max-width:620px){.chart-actions{width:100%;justify-content:space-between}.sparkline-wrap svg{width:120px}.asset .sparkline-wrap svg{width:95px}}\n'''
if '/* Mini market charts v14 */' not in s:
    p.write_text(s + css, encoding='utf-8')
    print('patched app/globals.css')
else:
    print('already patched app/globals.css')

print('UPGRADE_SPARKLINES_V14_OK')
