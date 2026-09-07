import AuthGate from "./auth-gate";

const assets = [
  ["BTC", "Monitorerer", "#f59e0b"],
  ["ETH", "Monitorerer", "#8b5cf6"],
  ["SOL", "Monitorerer", "#22c55e"],
  ["BNB", "Monitorerer", "#eab308"],
  ["XRP", "Monitorerer", "#38bdf8"],
];

export default function Dashboard() {
  return (
    <AuthGate><main className="shell">
      <header className="topbar"><div><span className="eyebrow">AI TRADING APP</span><h1>Kontrollpanel</h1></div><span className="pill"><i /> Server aktiv</span></header>
      <section className="hero"><div><p className="eyebrow">PAPIRHANDEL</p><h2>Systemet overvåker markedet trygt.</h2><p className="muted">Ekte handel er deaktivert. Signaler og risikoregler testes uten ordre.</p></div><button disabled>Start live-handel</button></section>
      <section className="grid metrics"><article><span className="label">Kontotilkobling</span><strong>Godkjent</strong><small>Binance API · lesetilgang</small></article><article><span className="label">Daglig resultat</span><strong>—</strong><small>Ingen live-handler</small></article><article><span className="label">Risikonivå</span><strong>Normal</strong><small>0,5 % per handel</small></article><article><span className="label">Sikkerhetsreserve</span><strong>20 %</strong><small>Beskyttet kapital</small></article></section>
      <section className="panel"><div className="panel-head"><div><p className="eyebrow">MARKEDSOVERVÅKING</p><h3>Godkjent univers</h3></div><span className="muted">15-minutters signaler</span></div><div className="assets">{assets.map(([symbol, status, color]) => <div className="asset" key={symbol}><span className="coin" style={{ background: color }}>{symbol.slice(0, 1)}</span><div><b>{symbol}/USDC</b><small>{status}</small></div><span className="neutral">Ingen signal</span></div>)}</div></section>
      <section className="panel notice"><p className="eyebrow">NESTE STEG</p><h3>Innlogging og rapporter kobles til her</h3><p className="muted">Google-innlogging, Authenticator og brukerisolerte rapporter aktiveres før kontrollknapper åpnes.</p></section>
    </main></AuthGate>
  );
}
