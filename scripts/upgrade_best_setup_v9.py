from pathlib import Path

DASH = Path("app/trading-dashboard.tsx")
CSS = Path("app/globals.css")
text = DASH.read_text()

if "const bestSetups = useMemo(() =>" not in text:
    marker = "  const serverOnline = lastEvent ? Date.now() - new Date(lastEvent.created_at).getTime() < 900_000 : false;\n"
    if marker not in text:
        raise SystemExit("best-setup insertion marker missing")
    block = r'''

  const bestSetups = useMemo(() => {
    const field = (name: string): string | null => {
      const match = lastEvent?.message.match(new RegExp(`(?:^|;)${name}=([^;]+)`));
      return match?.[1] ?? null;
    };
    const mapScores = (name: string) => {
      const map = new Map<string, number>();
      const raw = field(name);
      if (!raw || raw === "none") return map;
      for (const item of raw.split(",")) {
        const [symbol, rawScore] = item.split(":");
        const score = Number(rawScore);
        if (symbol && Number.isFinite(score)) map.set(symbol, score);
      }
      return map;
    };
    const markets = (field("markets") ?? "").split(",").filter(Boolean);
    const longRaw = field("signals") ?? "none";
    const shortRaw = field("shorts") ?? "none";
    const longSymbols = new Set(longRaw === "none" ? [] : longRaw.split(",").map((item) => item.split(":")[0]));
    const shortSymbols = new Set(shortRaw === "none" ? [] : shortRaw.split(","));
    const swing = mapScores("scores");
    const scalp = mapScores("scalp_scores");
    const short = mapScores("short_scores");
    const threshold = Math.max(1, Number(field("threshold") ?? 4));

    return markets.map((symbol) => {
      const longScore = Math.max(swing.get(symbol) ?? 0, scalp.get(symbol) ?? 0);
      const shortScore = short.get(symbol) ?? 0;
      const hasLong = longSymbols.has(symbol);
      const hasShort = shortSymbols.has(symbol);
      const direction: "LONG" | "SHORT" | "VENT" = hasLong ? "LONG" : hasShort ? "SHORT" : "VENT";
      const rawScore = direction === "SHORT" ? shortScore : longScore;
      const signalBonus = direction === "VENT" ? 0 : 3;
      const rank = rawScore + signalBonus + (direction === "LONG" && (longRaw.includes(`${symbol}:bullrun`) || longRaw.includes(`${symbol}:scalp`)) ? 1 : 0);
      const ratio = rawScore / threshold;
      const grade = direction === "VENT" ? "C" : ratio >= 1.45 ? "A" : ratio >= 1.05 ? "B" : "C";
      const sizeFactor = grade === "A" ? 1 : grade === "B" ? 0.7 : 0.4;
      const suggested = Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc), availableCapital) * sizeFactor;
      const mode = direction === "LONG" ? "SPOT" : direction === "SHORT" ? (settings.futures_enabled && settings.risk_profile === "extreme" ? `FUTURES ${settings.leverage}x` : settings.short_enabled ? "MARGIN" : "SHORT AV") : "INGEN HANDEL";
      return { symbol, direction, mode, rawScore, longScore, shortScore, rank, grade, suggested };
    }).sort((a, b) => b.rank - a.rank || b.rawScore - a.rawScore).slice(0, 3);
  }, [lastEvent, settings.order_size_usdc, settings.trade_cap_usdc, settings.futures_enabled, settings.short_enabled, settings.risk_profile, settings.leverage, availableCapital]);
'''
    text = text.replace(marker, marker + block, 1)

if "BESTE OPPSETT AKKURAT NÅ" not in text:
    marker = '    <section className="panel"><div className="panel-head"><div><p className="eyebrow">PORTEFØLJE</p><h3>Investert per valuta</h3></div>'
    if marker not in text:
        raise SystemExit("portfolio marker missing")
    panel = r'''    <section className="panel best-setup-panel">
      <div className="panel-head"><div><p className="eyebrow">BESTE OPPSETT AKKURAT NÅ</p><h3>Botens høyest rangerte muligheter</h3></div><button type="button" className="secondary compact" onClick={() => void load()}>Oppdater nå</button></div>
      <p className="muted best-setup-intro">Rangert fra siste faktiske markedsscan. A = sterkest oppsett, B = godt oppsett, C = svakere/vent. Beløpet er et forslag innenfor dine nåværende grenser – ingen ordre sendes fra denne boksen.</p>
      {bestSetups.length === 0 ? <p className="empty">Venter på ferske markedsdata.</p> : <div className="best-setup-grid">{bestSetups.map((setup, index) => <article className={`best-setup-card ${setup.direction.toLowerCase()}`} key={setup.symbol}>
        <div className="best-setup-rank">#{index + 1}</div>
        <div><span className={`setup-grade grade-${setup.grade.toLowerCase()}`}>{setup.grade}</span><strong>{setup.symbol}</strong></div>
        <div className={`setup-direction ${setup.direction.toLowerCase()}`}>{setup.direction}</div>
        <small>Modus: <b>{setup.mode}</b></small>
        <small>Aktuell score: <b>{setup.rawScore}</b> · Long {setup.longScore} / Short {setup.shortScore}</small>
        <small>Foreslått størrelse: <b>{money(setup.suggested)} {settings.quote_asset}</b></small>
      </article>)}</div>}
      <p className="muted best-setup-note">Denne rangeringen er beslutningsstøtte. Boten bruker fortsatt stop-loss, maks dagstap, kapitaltak, cooldown og posisjonsgrenser før en faktisk handel kan gjennomføres.</p>
    </section>
'''
    text = text.replace(marker, panel + marker, 1)

DASH.write_text(text)

css = CSS.read_text()
css_marker = "/* Best setup v9 */"
if css_marker not in css:
    css += r'''

/* Best setup v9 */
.best-setup-panel{border-color:rgba(59,130,246,.45);background:linear-gradient(135deg,rgba(16,28,45,.96),rgba(16,37,65,.88))}.best-setup-intro{max-width:950px;line-height:1.5}.best-setup-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.best-setup-card{position:relative;display:grid;gap:8px;padding:16px;border:1px solid var(--line);border-radius:14px;background:rgba(8,20,33,.62)}.best-setup-card.long{border-color:rgba(74,222,128,.5);box-shadow:inset 4px 0 0 rgba(74,222,128,.8)}.best-setup-card.short{border-color:rgba(249,115,22,.58);box-shadow:inset 4px 0 0 rgba(249,115,22,.9)}.best-setup-card.vent{opacity:.78}.best-setup-card strong{font-size:18px}.best-setup-rank{position:absolute;top:12px;right:12px;color:var(--muted);font-weight:800}.setup-grade{display:inline-grid;place-items:center;width:25px;height:25px;margin-right:8px;border-radius:8px;font-size:11px;font-weight:900}.grade-a{background:#14532d;color:#86efac}.grade-b{background:#713f12;color:#fde68a}.grade-c{background:#334155;color:#cbd5e1}.setup-direction{width:max-content;padding:5px 8px;border-radius:999px;font-size:10px;font-weight:900;letter-spacing:.08em}.setup-direction.long{background:rgba(74,222,128,.15);color:#86efac}.setup-direction.short{background:rgba(249,115,22,.18);color:#fdba74}.setup-direction.vent{background:#26384d;color:#cbd5e1}.best-setup-note{font-size:11px;margin:14px 0 0}@media(max-width:820px){.best-setup-grid{grid-template-columns:1fr}}
'''
    CSS.write_text(css)

print("UPGRADE_BEST_SETUP_V9_OK")
