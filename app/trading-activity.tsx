"use client";

import { useEffect, useState } from "react";
import { activityDescription, engineSummary, type ActivityEvent } from "../lib/trading-activity";

type LastTrade = { side: string; symbol: string; mode: string; created_at: string };
const time = (value: string) => new Date(value).toLocaleString("nb-NO");

export default function TradingActivity({ heartbeat, events, trade, error, refreshedAt, enabled, live, onRefresh }: {
  heartbeat: ActivityEvent | null; events: ActivityEvent[]; trade?: LastTrade; error: string;
  refreshedAt: string | null; enabled: boolean; live: boolean; onRefresh: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 15_000); return () => window.clearInterval(timer); }, []);
  const summary = engineSummary(heartbeat, events, now, enabled, live);
  return <section className={`panel trading-activity activity-${summary.tone}`} aria-label="Handelsaktivitet">
    <div className="panel-head"><div><p className="eyebrow">HANDELSAKTIVITET</p><h3>{summary.label}</h3></div><button type="button" className="secondary compact" onClick={onRefresh}>Oppdater nå</button></div>
    {error && <p className="activity-error" role="alert">Kunne ikke hente alle oppdateringer: {error}. Viste opplysninger kan være utdaterte.</p>}
    <p className="activity-explanation">{summary.detail}</p>
    <div className="activity-facts"><div><span className="label">SISTE BOT-HANDEL</span><strong>{trade ? `${trade.side === "BUY" ? "Kjøp" : "Salg"} ${trade.symbol} · ${trade.mode === "live" ? "Spot" : trade.mode}` : "Ingen nye bot-handler registrert"}</strong><small>{trade ? time(trade.created_at) : "Gjenopprettet Binance-historikk vises separat lenger ned."}</small><a href="#trade-history">Se handelshistorikk ↓</a></div><div><span className="label">SISTE MOTORRAPPORT</span><strong>{heartbeat ? time(heartbeat.created_at) : "Venter på rapport"}</strong><small>{refreshedAt ? `Panelet oppdatert ${time(refreshedAt)}` : "Henter opplysninger …"}</small><small>Oppdateres hvert 15. sekund.</small></div></div>
    <details className="activity-details"><summary>Siste hendelser{events.length ? ` (${events.length})` : ""}</summary>
      {events.length === 0 ? <p className="muted">Ingen hendelser hentet ennå.</p> : <ol className="activity-list">{events.map((event) => <li key={event.id} className={event.level === "error" ? "activity-error" : ""}><time>{time(event.created_at)}</time><span>{activityDescription(event)}</span><details><summary>Tekniske detaljer</summary><code>{event.message}</code></details></li>)}</ol>}
    </details>
  </section>;
}
