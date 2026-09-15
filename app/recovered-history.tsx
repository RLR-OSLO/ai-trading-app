"use client";

import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";

type Fill = { symbol: string; exchange_trade_id: number; side: string; quantity: number; price: number; commission: number; commission_asset: string; executed_at: string };
export default function RecoveredHistory() {
  const [rows, setRows] = useState<Fill[]>([]);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const all: Fill[] = [];
      for (let offset = 0; ; offset += 1000) {
        const { data, error: readError } = await supabase.from("exchange_fills").select("symbol,exchange_trade_id,side,quantity,price,commission,commission_asset,executed_at").order("executed_at", { ascending: false }).order("symbol").order("exchange_trade_id").range(offset, offset + 999);
        if (cancelled) return;
        if (readError) { setError(readError.message); setLoading(false); return; }
        all.push(...(data ?? []) as Fill[]);
        if (!data || data.length < 1000) break;
      }
      if (!cancelled) { setRows(all); setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, []);
  return <section className="panel">
    <div className="panel-head"><div><p className="eyebrow">GJENOPPRETTET FRA BINANCE</p><h3>Handelshistorikk fra kontoen</h3></div><button className="secondary" onClick={() => setExpanded(!expanded)}>{expanded ? "Skjul" : "Vis historikk"}</button></div>
    <p className="muted">{loading ? "Henter historikk …" : `${rows.length} handelslinjer hentet fra Binance.`} Dette inkluderer eldre handler og er ikke et komplett resultatregnskap for boten. Resultatkortene over viser bare nye bot-handler etter databasebyttet.</p>
    {error && <p role="alert">{error}</p>}
    {expanded && <div className="portfolio-table-wrap"><table className="portfolio-table"><thead><tr><th>Tid</th><th>Marked</th><th>Side</th><th>Antall</th><th>Pris</th><th>Gebyr</th></tr></thead><tbody>{rows.map((row) => <tr key={`${row.symbol}:${row.exchange_trade_id}`}><td>{new Date(row.executed_at).toLocaleString("nb-NO")}</td><td>{row.symbol}</td><td>{row.side}</td><td>{Number(row.quantity).toLocaleString("nb-NO", { maximumFractionDigits: 8 })}</td><td>{Number(row.price).toLocaleString("nb-NO", { maximumFractionDigits: 8 })}</td><td>{row.commission} {row.commission_asset}</td></tr>)}</tbody></table></div>}
  </section>;
}
