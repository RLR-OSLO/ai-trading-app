"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { supabase } from "../lib/supabase";

type Settings = {
  bot_enabled: boolean;
  live_trading_enabled: boolean;
  risk_profile: "low" | "normal" | "high";
  quote_asset: "USDC" | "USDT";
  trade_cap_usdc: number;
  order_size_usdc: number;
  stop_loss_percent: number;
  take_profit_percent: number;
  max_daily_loss_usdc: number;
};

type Trade = { id: string; symbol: string; side: "BUY" | "SELL"; quantity: number; entry_price: number | null; exit_price: number | null; pnl: number | null; created_at: string };

const defaults: Settings = { bot_enabled: false, live_trading_enabled: false, risk_profile: "normal", quote_asset: "USDC", trade_cap_usdc: 100, order_size_usdc: 25, stop_loss_percent: 1, take_profit_percent: 2, max_daily_loss_usdc: 2 };
const assets = ["BTC", "ETH", "SOL", "BNB", "XRP"];
const money = (value: number) => new Intl.NumberFormat("nb-NO", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);

export default function TradingDashboard() {
  const [settings, setSettings] = useState<Settings>(defaults);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) return;
    const [{ data: row, error }, { data: recent }] = await Promise.all([
      supabase.from("bot_settings").select("bot_enabled,live_trading_enabled,risk_profile,quote_asset,trade_cap_usdc,order_size_usdc,stop_loss_percent,take_profit_percent,max_daily_loss_usdc").eq("user_id", userData.user.id).maybeSingle(),
      supabase.from("trades").select("id,symbol,side,quantity,entry_price,exit_price,pnl,created_at").order("created_at", { ascending: false }).limit(50),
    ]);
    if (error) setMessage(error.message);
    if (row) setSettings(row as Settings);
    if (recent) setTrades(recent as Trade[]);
    setLoaded(true);
  }, []);

  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 30_000); return () => window.clearInterval(timer); }, [load]);

  const stats = useMemo(() => {
    const now = Date.now();
    const pnl = (since: number) => trades.filter((trade) => new Date(trade.created_at).getTime() >= since).reduce((sum, trade) => sum + Number(trade.pnl ?? 0), 0);
    const invested = trades.filter((trade) => trade.side === "BUY").reduce((sum, trade) => sum + Number(trade.quantity) * Number(trade.entry_price ?? 0), 0);
    const feesEstimate = trades.reduce((sum, trade) => sum + Number(trade.quantity) * Number(trade.entry_price ?? trade.exit_price ?? 0) * 0.001, 0);
    return { total: pnl(0), day: pnl(now - 86_400_000), hour: pnl(now - 3_600_000), invested, feesEstimate };
  }, [trades]);

  const allocations = useMemo(() => assets.map((asset) => {
    const symbol = `${asset}${settings.quote_asset}`;
    const invested = trades.filter((trade) => trade.symbol === symbol && trade.side === "BUY").reduce((sum, trade) => sum + Number(trade.quantity) * Number(trade.entry_price ?? 0), 0);
    const pnl = trades.filter((trade) => trade.symbol === symbol).reduce((sum, trade) => sum + Number(trade.pnl ?? 0), 0);
    return { asset, invested, pnl };
  }), [settings.quote_asset, trades]);

  function update<K extends keyof Settings>(key: K, value: Settings[K]) { setSettings((current) => ({ ...current, [key]: value })); }

  async function save() {
    setSaving(true); setMessage("");
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) { setSaving(false); return; }
    const safe = { ...settings, trade_cap_usdc: Math.min(100, Math.max(5, Number(settings.trade_cap_usdc))), order_size_usdc: Math.min(Number(settings.trade_cap_usdc), Math.max(5, Number(settings.order_size_usdc))), updated_at: new Date().toISOString(), user_id: userData.user.id };
    const { error } = await supabase.from("bot_settings").upsert(safe, { onConflict: "user_id" });
    setSaving(false); setMessage(error ? error.message : "Innstillingene er lagret."); if (!error) setSettings(safe);
  }

  async function emergencyStop() {
    setSaving(true);
    const next = { ...settings, bot_enabled: false, live_trading_enabled: false };
    setSettings(next);
    const { data: userData } = await supabase.auth.getUser();
    if (userData.user) await supabase.from("bot_settings").upsert({ ...next, user_id: userData.user.id, updated_at: new Date().toISOString() }, { onConflict: "user_id" });
    setMessage("Nødstopp er lagret. Nye handler er blokkert."); setSaving(false);
  }

  return <main className="shell">
    <header className="topbar"><div><span className="eyebrow">AI TRADING APP</span><h1>Kontrollpanel</h1></div><span className="pill"><i /> Server tilkoblet</span></header>
    <section className="hero"><div><p className="eyebrow">BEGRENSET LIVE-RAMME</p><h2>100 USDC. Spot-only. Harde tapsgrenser.</h2><p className="muted">Binance-uttak, futures og giring er deaktivert.</p></div><button className="danger" onClick={() => void emergencyStop()} disabled={saving}>Nødstopp</button></section>
    <section className="grid metrics">
      <article><span className="label">Handelsramme</span><strong>{money(settings.trade_cap_usdc)} USDC</strong><small>Resten av saldoen er utenfor boten</small></article>
      <article><span className="label">Totalt resultat</span><strong className={stats.total < 0 ? "loss" : "gain"}>{money(stats.total)} USDC</strong><small>Realisert gevinst/tap</small></article>
      <article><span className="label">Siste døgn</span><strong className={stats.day < 0 ? "loss" : "gain"}>{money(stats.day)} USDC</strong><small>Siste time: {money(stats.hour)} USDC</small></article>
      <article><span className="label">Estimerte gebyrer</span><strong>{money(stats.feesEstimate)} USDC</strong><small>{trades.length} registrerte ordre</small></article>
    </section>
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">RISIKOKONTROLL</p><h3>Handelsinnstillinger</h3></div><span className={settings.live_trading_enabled ? "status-live" : "status-paused"}>{settings.live_trading_enabled ? "LIVE" : "PAUSET"}</span></div>
      <div className="form-grid">
        <Field label="Maks kapital (USDC)" value={settings.trade_cap_usdc} min={5} max={100} step={5} onChange={(value) => update("trade_cap_usdc", value)} />
        <Field label="Ordrestørrelse (USDC)" value={settings.order_size_usdc} min={5} max={settings.trade_cap_usdc} step={5} onChange={(value) => update("order_size_usdc", value)} />
        <Field label="Stop-loss (%)" value={settings.stop_loss_percent} min={0.25} max={10} step={0.25} onChange={(value) => update("stop_loss_percent", value)} />
        <Field label="Gevinstmål (%)" value={settings.take_profit_percent} min={0.5} max={25} step={0.5} onChange={(value) => update("take_profit_percent", value)} />
        <Field label="Maks dagstap (USDC)" value={settings.max_daily_loss_usdc} min={0.5} max={settings.trade_cap_usdc} step={0.5} onChange={(value) => update("max_daily_loss_usdc", value)} />
        <label className="select-field"><span>Risikonivå</span><select value={settings.risk_profile} onChange={(event) => update("risk_profile", event.target.value as Settings["risk_profile"])}><option value="low">Lav</option><option value="normal">Normal</option><option value="high">Høy</option></select></label>
      </div><div className="actions"><button className="primary" onClick={() => void save()} disabled={saving || !loaded}>{saving ? "Lagrer …" : "Lagre innstillinger"}</button></div>{message && <p className="inline-message">{message}</p>}
    </section>
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">PORTEFØLJE</p><h3>Investert per valuta</h3></div><span className="muted">Historikk fra boten</span></div><div className="assets">{allocations.map(({ asset, invested, pnl }) => <div className="asset" key={asset}><span className="coin">{asset[0]}</span><div><b>{asset}/{settings.quote_asset}</b><small>Investert: {money(invested)} USDC</small></div><span className={pnl < 0 ? "loss" : "gain"}>{money(pnl)} USDC</span></div>)}</div></section>
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">AKTIVITET</p><h3>Siste handler</h3></div><span className="muted">Oppdateres hvert 30. sekund</span></div>{trades.length === 0 ? <p className="empty">Ingen live-handler registrert ennå.</p> : <div className="trade-list">{trades.slice(0, 10).map((trade) => <div className="trade-row" key={trade.id}><b>{trade.side} {trade.symbol}</b><span>{Number(trade.quantity).toPrecision(6)}</span><span className={Number(trade.pnl ?? 0) < 0 ? "loss" : "gain"}>{money(Number(trade.pnl ?? 0))} USDC</span><time>{new Date(trade.created_at).toLocaleString("nb-NO")}</time></div>)}</div>}</section>
  </main>;
}

function Field({ label, value, min, max, step, onChange }: Readonly<{ label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void }>) { return <label className="number-field"><span>{label}</span><input type="number" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} /></label>; }
