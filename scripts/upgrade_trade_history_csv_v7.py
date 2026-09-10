from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"marker missing in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1))
    print(f"patched {path}")


replace_once(
    "app/trading-dashboard.tsx",
    'type Trade = { id: string; symbol: string; mode: string; side: "BUY" | "SELL"; quantity: number; entry_price: number | null; exit_price: number | null; pnl: number | null; created_at: string };',
    'type Trade = { id: string; symbol: string; mode: string; side: "BUY" | "SELL"; quantity: number; entry_price: number | null; exit_price: number | null; pnl: number | null; leverage?: number | null; created_at: string };'
)

replace_once(
    "app/trading-dashboard.tsx",
    'supabase.from("trades").select("id,symbol,mode,side,quantity,entry_price,exit_price,pnl,created_at").order("created_at", { ascending: false }).limit(500),',
    'supabase.from("trades").select("id,symbol,mode,side,quantity,entry_price,exit_price,pnl,leverage,created_at").order("created_at", { ascending: false }).limit(500),'
)

marker = '  async function sendChat() {'
insert = r'''  async function downloadTradesCsv() {
    setMessage("");
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) { setMessage("Du må være innlogget for å laste ned handler."); return; }

    const rows: Trade[] = [];
    const pageSize = 1000;
    for (let start = 0; ; start += pageSize) {
      const { data, error } = await supabase
        .from("trades")
        .select("id,symbol,mode,side,quantity,entry_price,exit_price,pnl,leverage,created_at")
        .order("created_at", { ascending: true })
        .range(start, start + pageSize - 1);
      if (error) { setMessage(`CSV-feil: ${error.message}`); return; }
      const page = (data ?? []) as Trade[];
      rows.push(...page);
      if (page.length < pageSize) break;
    }

    const q = (value: unknown) => `"${String(value ?? "").replaceAll('"', '""')}"`;
    const header = ["Dato/tid", "Type", "Side", "Symbol", "Antall", "Kjøps-/inngangspris", "Salgs-/utgangspris", "Resultat", "Gearing"];
    const lines = [header.map(q).join(";")];
    for (const trade of rows) {
      const type = trade.mode === "futures" ? "FUTURES SHORT" : trade.mode === "margin" ? "MARGIN SHORT" : "SPOT";
      lines.push([
        new Date(trade.created_at).toLocaleString("nb-NO"),
        type,
        trade.side,
        trade.symbol,
        trade.quantity,
        trade.entry_price ?? "",
        trade.exit_price ?? "",
        trade.pnl ?? "",
        trade.mode === "futures" ? `${Number(trade.leverage ?? 1)}x` : "",
      ].map(q).join(";"));
    }
    const blob = new Blob(["\ufeff" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `ai-trading-handler-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setMessage(`${rows.length} handler eksportert til CSV.`);
  }

'''
replace_once("app/trading-dashboard.tsx", marker, insert + marker)

old_trade = '''    <section className="panel"><div className="panel-head"><div><p className="eyebrow">AKTIVITET</p><h3>Siste handler</h3></div><span className="muted">Oppdateres hvert 30. sekund</span></div>{trades.length === 0 ? <p className="empty">Ingen live-handler registrert ennå.</p> : <div className="trade-list">{trades.slice(0, 20).map((trade) => <div className="trade-row" key={trade.id}><b>{trade.mode.toUpperCase()} · {trade.side} {trade.symbol}</b><span>{Number(trade.quantity).toPrecision(6)}</span><span className={Number(trade.pnl ?? 0) < 0 ? "loss" : "gain"}>{money(Number(trade.pnl ?? 0))} {settings.quote_asset}</span><time>{new Date(trade.created_at).toLocaleString("nb-NO")}</time></div>)}</div>}</section>'''
new_trade = '''    <section className="panel trade-history-panel"><div className="panel-head"><div><p className="eyebrow">AKTIVITET</p><h3>Siste handler</h3></div><div className="trade-head-actions"><span className="muted">Oppdateres hvert 30. sekund</span><button type="button" className="secondary compact" onClick={() => void downloadTradesCsv()}>Last ned CSV</button></div></div>{trades.length === 0 ? <p className="empty">Ingen live-handler registrert ennå.</p> : <div className="trade-list"><div className="trade-row trade-header"><span>Handel</span><span>Antall</span><span>Inngang</span><span>Utgang</span><span>Resultat</span><span>Tid</span></div>{trades.slice(0, 20).map((trade) => { const derivative = trade.mode === "margin" || trade.mode === "futures"; const modeClass = trade.mode === "futures" ? "trade-futures" : trade.mode === "margin" ? "trade-margin" : "trade-spot"; const label = trade.mode === "futures" ? `SHORT · FUTURES · ${Number(trade.leverage ?? 1)}x` : trade.mode === "margin" ? "SHORT · MARGIN" : "SPOT"; return <div className={`trade-row ${modeClass}`} key={trade.id}><div><span className={`trade-mode-badge ${modeClass}`}>{label}</span><b>{trade.side} {trade.symbol}</b><small>{derivative ? (trade.side === "SELL" ? "Åpnet short-posisjon" : "Lukket short-posisjon") : (trade.side === "BUY" ? "Kjøpt spot" : "Solgt spot")}</small></div><span>{Number(trade.quantity).toPrecision(6)}</span><span>{trade.entry_price == null ? "–" : money(Number(trade.entry_price))}</span><span>{trade.exit_price == null ? "ÅPEN" : money(Number(trade.exit_price))}</span><span className={Number(trade.pnl ?? 0) < 0 ? "loss" : "gain"}>{trade.pnl == null ? "–" : `${Number(trade.pnl) >= 0 ? "+" : ""}${money(Number(trade.pnl))} ${settings.quote_asset}`}</span><time>{new Date(trade.created_at).toLocaleString("nb-NO")}</time></div>; })}</div>}</section>'''
replace_once("app/trading-dashboard.tsx", old_trade, new_trade)

css = Path("app/globals.css")
css.write_text(css.read_text() + r'''

/* Trade mode clarity */
.trade-head-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap;justify-content:flex-end}.trade-history-panel .trade-list{gap:7px}.trade-history-panel .trade-row{grid-template-columns:1.55fr .65fr .75fr .75fr .8fr 1fr;align-items:center;padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:rgba(8,20,33,.44)}.trade-history-panel .trade-row.trade-header{background:transparent;border:0;border-bottom:1px solid var(--line);border-radius:0;padding:7px 12px;color:var(--muted);font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase}.trade-history-panel .trade-row.trade-margin{background:linear-gradient(90deg,rgba(139,92,246,.18),rgba(30,20,55,.28));border-color:rgba(167,139,250,.55);box-shadow:inset 4px 0 0 #8b5cf6}.trade-history-panel .trade-row.trade-futures{background:linear-gradient(90deg,rgba(249,115,22,.20),rgba(60,30,12,.28));border-color:rgba(251,146,60,.62);box-shadow:inset 4px 0 0 #f97316}.trade-history-panel .trade-row.trade-spot{box-shadow:inset 4px 0 0 rgba(74,222,128,.52)}.trade-history-panel .trade-row>div:first-child{display:grid;gap:4px}.trade-history-panel .trade-row small{font-size:10px}.trade-mode-badge{display:inline-flex;width:max-content;padding:3px 7px;border-radius:999px;font-size:8px;font-weight:900;letter-spacing:.1em}.trade-mode-badge.trade-spot{background:rgba(74,222,128,.16);color:#86efac}.trade-mode-badge.trade-margin{background:rgba(139,92,246,.22);color:#c4b5fd}.trade-mode-badge.trade-futures{background:rgba(249,115,22,.24);color:#fdba74}.trade-history-panel .trade-row time{text-align:right}.trade-history-panel .trade-row span{overflow-wrap:anywhere}@media(max-width:900px){.trade-history-panel .trade-row{grid-template-columns:1.5fr .7fr .8fr .8fr}.trade-history-panel .trade-row>*:nth-child(5),.trade-history-panel .trade-row>*:nth-child(6){margin-top:4px}.trade-history-panel .trade-row time{text-align:left}.trade-history-panel .trade-row.trade-header{display:none}}@media(max-width:620px){.trade-head-actions{justify-content:flex-start}.trade-history-panel .trade-row{grid-template-columns:1fr 1fr}.trade-history-panel .trade-row>div:first-child{grid-column:1/-1}}
''')
print("patched app/globals.css")
print("UPGRADE_TRADE_HISTORY_CSV_V7_OK")
