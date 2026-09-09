"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { supabase } from "../lib/supabase";
import HowItWorks from "./how-it-works";

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

type Trade = { id: string; symbol: string; mode: string; side: "BUY" | "SELL"; quantity: number; entry_price: number | null; exit_price: number | null; pnl: number | null; created_at: string };
type BotEvent = { id: number; level: "info" | "warning" | "error"; event_type: string; message: string; created_at: string };
type ChatMessage = { id: number; role: "boss" | "bot"; text: string };

const defaults: Settings = { bot_enabled: false, live_trading_enabled: false, risk_profile: "normal", quote_asset: "USDC", trade_cap_usdc: 100, order_size_usdc: 25, stop_loss_percent: 1, take_profit_percent: 2, max_daily_loss_usdc: 2 };
const MARKET_UNIVERSE = [
  "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "TRX", "AVAX", "LINK",
  "SUI", "XLM", "BCH", "LTC", "DOT", "SHIB", "TON", "HBAR", "UNI", "AAVE",
  "NEAR", "APT", "ETC", "FIL", "ICP", "ATOM", "ALGO", "VET", "POL", "ARB",
] as const;
const money = (value: number) => new Intl.NumberFormat("nb-NO", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
const crypto = (value: number) => new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 8 }).format(value);

export default function TradingDashboard() {
  const [settings, setSettings] = useState<Settings>(defaults);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [lastEvent, setLastEvent] = useState<BotEvent | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    { id: 1, role: "bot", text: "Hei, sjef. Spør meg om status, resultat, siste handel eller hvorfor jeg ikke har handlet. Du kan også skrive «pause botten»." },
  ]);

  const load = useCallback(async () => {
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) return;
    const [{ data: row, error }, { data: recent }, { data: events }] = await Promise.all([
      supabase.from("bot_settings").select("bot_enabled,live_trading_enabled,risk_profile,quote_asset,trade_cap_usdc,order_size_usdc,stop_loss_percent,take_profit_percent,max_daily_loss_usdc").eq("user_id", userData.user.id).maybeSingle(),
      supabase.from("trades").select("id,symbol,mode,side,quantity,entry_price,exit_price,pnl,created_at").order("created_at", { ascending: false }).limit(500),
      supabase.from("bot_events").select("id,level,event_type,message,created_at").order("created_at", { ascending: false }).limit(1),
    ]);
    if (error) setMessage(error.message);
    if (row) setSettings(row as Settings);
    if (recent) setTrades(recent as Trade[]);
    if (events?.[0]) setLastEvent(events[0] as BotEvent);
    setLoaded(true);
  }, []);

  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 30_000); return () => window.clearInterval(timer); }, [load]);

  const stats = useMemo(() => {
    const now = Date.now();
    const pnl = (since: number) => trades.filter((trade) => new Date(trade.created_at).getTime() >= since).reduce((sum, trade) => sum + Number(trade.pnl ?? 0), 0);
    const won = trades.reduce((sum, trade) => sum + Math.max(0, Number(trade.pnl ?? 0)), 0);
    const lost = trades.reduce((sum, trade) => sum + Math.min(0, Number(trade.pnl ?? 0)), 0);
    const feesEstimate = trades.reduce((sum, trade) => sum + Number(trade.quantity) * Number(trade.entry_price ?? trade.exit_price ?? 0) * 0.001, 0);
    return { total: pnl(0), day: pnl(now - 86_400_000), hour: pnl(now - 3_600_000), won, lost, feesEstimate };
  }, [trades]);

  const marketPrices = useMemo(() => {
    const prices = new Map<string, number>();
    const match = lastEvent?.message.match(/(?:^|;)prices=([^;]+)/);
    if (!match) return prices;
    for (const item of match[1].split(",")) {
      const [symbol, rawPrice] = item.split(":");
      const value = Number(rawPrice);
      if (symbol && Number.isFinite(value)) prices.set(symbol, value);
    }
    return prices;
  }, [lastEvent]);

  const binanceBalances = useMemo(() => {
    const balances = new Map<string, number>();
    const match = lastEvent?.message.match(/(?:^|;)balances=([^;]+)/);
    if (!match) return balances;
    for (const item of match[1].split(",")) {
      const [asset, rawQty] = item.split(":");
      const qty = Number(rawQty);
      if (asset && Number.isFinite(qty)) balances.set(asset, qty);
    }
    return balances;
  }, [lastEvent]);

  const binanceWalletValues = useMemo(() => {
    const values = new Map<string, number>();
    const match = lastEvent?.message.match(/(?:^|;)wallet_values=([^;]+)/);
    if (!match) return values;
    for (const item of match[1].split(",")) {
      const [asset, rawValue] = item.split(":");
      const value = Number(rawValue);
      if (asset && Number.isFinite(value)) values.set(asset, value);
    }
    return values;
  }, [lastEvent]);

  const assets = useMemo(() => {
    const suffix = settings.quote_asset;
    const names = new Set<string>(MARKET_UNIVERSE);
    for (const symbol of marketPrices.keys()) if (symbol.endsWith(suffix)) names.add(symbol.slice(0, -suffix.length));
    for (const trade of trades) if (trade.symbol.endsWith(suffix)) names.add(trade.symbol.slice(0, -suffix.length));
    for (const [asset, value] of binanceWalletValues.entries()) if (asset !== suffix && value >= 5) names.add(asset);
    return Array.from(names);
  }, [marketPrices, settings.quote_asset, trades, binanceWalletValues]);

  const allocations = useMemo(() => assets.map((asset) => {
    const symbol = `${asset}${settings.quote_asset}`;
    const assetTrades = trades.filter((trade) => trade.symbol === symbol);
    const orderedTrades = [...assetTrades].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
    let quantity = 0;
    let invested = 0;
    for (const trade of orderedTrades) {
      const tradeQuantity = Math.max(0, Number(trade.quantity));
      if (trade.side === "BUY") {
        quantity += tradeQuantity;
        invested += tradeQuantity * Number(trade.entry_price ?? 0);
      } else if (quantity > 0) {
        const soldQuantity = Math.min(quantity, tradeQuantity);
        const averageCost = invested / quantity;
        quantity = Math.max(0, quantity - soldQuantity);
        invested = Math.max(0, invested - soldQuantity * averageCost);
        if (quantity < 0.000000001) { quantity = 0; invested = 0; }
      }
    }
    const pnl = assetTrades.reduce((sum, trade) => sum + Number(trade.pnl ?? 0), 0);
    const walletQuantity = binanceBalances.has(asset) ? Number(binanceBalances.get(asset)) : quantity;
    const walletValue = binanceWalletValues.get(asset);
    const fallbackPrice = marketPrices.get(symbol) ?? null;
    const resolvedValue = walletValue !== undefined ? walletValue : (fallbackPrice === null ? null : walletQuantity * fallbackPrice);
    const owned = walletQuantity > 0.000000001 && resolvedValue !== null && resolvedValue >= 5;
    const authoritativeQuantity = owned ? walletQuantity : 0;
    const currentValue = owned ? resolvedValue : 0;
    const currentPrice = authoritativeQuantity > 0 && currentValue !== null ? currentValue / authoritativeQuantity : fallbackPrice;
    const adjustedInvested = quantity > 0 && authoritativeQuantity > 0 ? invested * Math.min(1, authoritativeQuantity / quantity) : 0;
    const unrealized = currentValue === null ? null : currentValue - adjustedInvested;
    return { asset, invested: adjustedInvested, quantity: authoritativeQuantity, pnl, currentPrice, currentValue, unrealized, owned };
  }).sort((a, b) => Number(b.owned) - Number(a.owned) || Number(b.currentValue ?? 0) - Number(a.currentValue ?? 0) || MARKET_UNIVERSE.indexOf(a.asset as typeof MARKET_UNIVERSE[number]) - MARKET_UNIVERSE.indexOf(b.asset as typeof MARKET_UNIVERSE[number])), [assets, settings.quote_asset, trades, marketPrices, binanceBalances, binanceWalletValues]);

  const availableCapital = useMemo(() => {
    const walletValue = binanceBalances.get(settings.quote_asset);
    if (walletValue !== undefined && Number.isFinite(walletValue)) return walletValue;
    const match = lastEvent?.message.match(/(?:^|;)available=([0-9.]+)/);
    const value = match ? Number(match[1]) : Number.NaN;
    return Number.isFinite(value) ? value : Number(settings.trade_cap_usdc);
  }, [binanceBalances, lastEvent, settings.quote_asset, settings.trade_cap_usdc]);

  const portfolioValue = useMemo(() => {
    const match = lastEvent?.message.match(/(?:^|;)invested_value=([0-9.]+)/);
    const value = match ? Number(match[1]) : Number.NaN;
    if (Number.isFinite(value)) return value;
    return allocations.reduce((sum, allocation) => sum + (allocation.owned ? Number(allocation.currentValue ?? 0) : 0), 0);
  }, [allocations, lastEvent]);

  const totalAssets = useMemo(() => {
    const match = lastEvent?.message.match(/(?:^|;)account_total=([0-9.]+)/);
    const value = match ? Number(match[1]) : Number.NaN;
    return Number.isFinite(value) ? value : availableCapital + portfolioValue;
  }, [availableCapital, lastEvent, portfolioValue]);

  const serverOnline = lastEvent ? Date.now() - new Date(lastEvent.created_at).getTime() < 900_000 : false;
  const maxOrderSize = Math.max(5, availableCapital);

  function update<K extends keyof Settings>(key: K, value: Settings[K]) { setSettings((current) => ({ ...current, [key]: value })); }

  async function save() {
    setSaving(true); setMessage("");
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) { setSaving(false); return; }
    const effectiveCapital = Math.max(5, availableCapital);
    const safe = { ...settings, trade_cap_usdc: effectiveCapital, order_size_usdc: Math.min(effectiveCapital, Math.max(5, Number(settings.order_size_usdc))), max_daily_loss_usdc: Math.min(effectiveCapital, Math.max(0.5, Number(settings.max_daily_loss_usdc))), updated_at: new Date().toISOString(), user_id: userData.user.id };
    const { error } = await supabase.from("bot_settings").upsert(safe, { onConflict: "user_id" });
    setSaving(false); setMessage(error ? error.message : "Innstillingene er lagret."); if (!error) setSettings(safe);
  }

  async function setLive(enabled: boolean) {
    setSaving(true); setMessage("");
    const next = { ...settings, trade_cap_usdc: Math.max(5, availableCapital), bot_enabled: enabled, live_trading_enabled: enabled };
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) { setSaving(false); return; }
    const { error } = await supabase.from("bot_settings").upsert({ ...next, user_id: userData.user.id, updated_at: new Date().toISOString() }, { onConflict: "user_id" });
    if (!error) setSettings(next);
    setMessage(error ? error.message : enabled ? "Live trading er aktivert." : "Trading er pauset.");
    setSaving(false);
  }

  async function emergencyStop() {
    setSaving(true);
    const next = { ...settings, bot_enabled: false, live_trading_enabled: false };
    setSettings(next);
    const { data: userData } = await supabase.auth.getUser();
    if (userData.user) await supabase.from("bot_settings").upsert({ ...next, user_id: userData.user.id, updated_at: new Date().toISOString() }, { onConflict: "user_id" });
    setMessage("Nødstopp er lagret. Nye handler er blokkert."); setSaving(false);
  }

  async function sendChat() {
    const text = chatInput.trim();
    if (!text) return;
    const normalized = text.toLocaleLowerCase("nb-NO"); const nextId = Date.now(); setChatInput(""); setChatMessages((current) => [...current, { id: nextId, role: "boss", text }]);
    let reply: string;
    if (normalized.includes("pause") || normalized.includes("stopp")) { await setLive(false); reply = "Botten er pauset. Ingen nye handler kan åpnes før du aktiverer LIVE igjen med knappen over."; }
    else if (normalized.includes("kjøp") || normalized.includes("selg") || normalized.includes("trade") || normalized.includes("handel nå")) reply = "Direkte kjøp og salg fra fritekst er sperret. Jeg handler bare når den godkjente strategien og tapsgrensene tillater det.";
    else if (normalized.includes("siste") && normalized.includes("handel")) { const trade = trades[0]; reply = trade ? `Siste handel: ${trade.side} ${trade.symbol}, ${Number(trade.quantity).toPrecision(6)} enheter, ${money(Number(trade.pnl ?? 0))} USDC realisert resultat.` : "Det er ikke registrert noen handler ennå."; }
    else if (normalized.includes("resultat") || normalized.includes("gevinst") || normalized.includes("tap")) reply = `Realisert totalresultat er ${money(stats.total)} USDC. Siste døgn: ${money(stats.day)} USDC. Estimerte gebyrer: ${money(stats.feesEstimate)} USDC.`;
    else if (normalized.includes("hvorfor") || normalized.includes("signal") || normalized.includes("analyse")) reply = lastEvent?.message ? `Siste analyse fra serveren: ${lastEvent.message}` : "Jeg har ikke mottatt et analysesignal fra serveren ennå.";
    else if (normalized.includes("status") || normalized.includes("live") || normalized.includes("aktiv")) reply = `${serverOnline ? "Serveren er online" : "Serverstatusen er ikke fersk"}. Trading er ${settings.live_trading_enabled ? "LIVE" : "PAUSET"}. Tilgjengelig kapital er ${money(availableCapital)} ${settings.quote_asset}, og ordrestørrelsen er ${money(settings.order_size_usdc)} ${settings.quote_asset}.`;
    else reply = "Jeg kan svare om status, resultat, siste handel og siste analyse. Jeg kan også pause botten. Direkte kjøp/salg fra chat er sperret.";
    setChatMessages((current) => [...current, { id: nextId + 1, role: "bot", text: reply }]);
  }

  return <main className="shell">
    <header className="topbar"><div><span className="eyebrow">AI TRADING APP</span><h1>Kontrollpanel</h1></div><span className="pill"><i /> {serverOnline ? "Server online" : "Ingen fersk serverstatus"}</span></header>
    <section className="hero"><div><p className="eyebrow">LIVE SPOT-TRADING</p><h2>Tilgjengelig saldo. Spot-only. Harde tapsgrenser.</h2><p className="muted">Binance-uttak, futures og giring er deaktivert.</p></div><button className="danger" onClick={() => void emergencyStop()} disabled={saving}>Nødstopp</button></section>
    <section className="panel" style={{ marginBottom: 18 }}>
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 18, alignItems: "end" }}>
        <div><span className="label">TOTAL BINANCE-VERDI</span><strong style={{ display: "block", fontSize: "clamp(2.2rem, 5vw, 4.4rem)", lineHeight: 1.05, marginTop: 8 }}>{money(totalAssets)} {settings.quote_asset}</strong><small>Kun faktisk beholdning på Binance, verdsatt til markedspris</small></div>
        <div><span className="label">Investert på Binance</span><strong style={{ display: "block", fontSize: "1.6rem", marginTop: 8 }}>{money(portfolioValue)} {settings.quote_asset}</strong><small>Faktisk krypto-beholdning nå</small></div>
        <div><span className="label">Ledig på Binance</span><strong style={{ display: "block", fontSize: "1.6rem", marginTop: 8 }}>{money(availableCapital)} {settings.quote_asset}</strong><small>Faktisk fri {settings.quote_asset}-saldo</small></div>
      </div>
    </section>
    <section className="grid metrics">
      <article><span className="label">Tilgjengelig kapital</span><strong>{money(availableCapital)} {settings.quote_asset}</strong><small>Fri saldo tilgjengelig for boten</small></article>
      <article><span className="label">Totalt resultat</span><strong className={stats.total < 0 ? "loss" : "gain"}>{money(stats.total)} USDC</strong><small>Realisert gevinst/tap</small></article>
      <article><span className="label">Vunnet</span><strong className="gain">{money(stats.won)} USDC</strong><small>Sum lønnsomme handler</small></article>
      <article><span className="label">Tapt</span><strong className="loss">{money(Math.abs(stats.lost))} USDC</strong><small>Sum tapte handler</small></article>
      <article><span className="label">Siste døgn</span><strong className={stats.day < 0 ? "loss" : "gain"}>{money(stats.day)} USDC</strong><small>Siste time: {money(stats.hour)} USDC</small></article>
      <article><span className="label">Estimerte gebyrer</span><strong>{money(stats.feesEstimate)} USDC</strong><small>{trades.length} registrerte ordre</small></article>
    </section>
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">RISIKOKONTROLL</p><h3>Handelsinnstillinger</h3></div><span className={settings.live_trading_enabled ? "status-live" : "status-paused"}>{settings.live_trading_enabled ? "LIVE" : "PAUSET"}</span></div>
      <div className="form-grid">
        <label className="number-field"><span>Tilgjengelig kapital ({settings.quote_asset})</span><input type="number" value={availableCapital} readOnly /></label>
        <Field label={`Ordrestørrelse (${settings.quote_asset})`} value={settings.order_size_usdc} min={5} max={maxOrderSize} step={5} onChange={(value) => update("order_size_usdc", value)} />
        <Field label="Stop-loss (%)" value={settings.stop_loss_percent} min={0.25} max={10} step={0.25} onChange={(value) => update("stop_loss_percent", value)} />
        <Field label="Gevinstmål (%)" value={settings.take_profit_percent} min={0.5} max={25} step={0.5} onChange={(value) => update("take_profit_percent", value)} />
        <Field label={`Maks dagstap (${settings.quote_asset})`} value={settings.max_daily_loss_usdc} min={0.5} max={Math.max(0.5, availableCapital)} step={0.5} onChange={(value) => update("max_daily_loss_usdc", value)} />
        <label className="select-field"><span>Risikonivå</span><select value={settings.risk_profile} onChange={(event) => update("risk_profile", event.target.value as Settings["risk_profile"])}><option value="low">Lav</option><option value="normal">Normal</option><option value="high">Høy</option></select></label>
      </div><div className="actions"><button onClick={() => void setLive(!settings.live_trading_enabled)} disabled={saving || !loaded}>{settings.live_trading_enabled ? "Pause trading" : "Start live"}</button><button className="primary" onClick={() => void save()} disabled={saving || !loaded}>{saving ? "Lagrer …" : "Lagre innstillinger"}</button></div>{message && <p className="inline-message">{message}</p>}
    </section>
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">PORTEFØLJE</p><h3>Investert per valuta</h3></div><span className="muted">Alle godkjente markeder · investerte posisjoner vises først</span></div><div className="assets">{allocations.map(({ asset, invested, quantity, pnl, currentPrice, currentValue, unrealized, owned }) => <div className={`asset${owned ? " invested" : ""}`} key={asset}><span className="coin">{asset[0]}</span><div><b>{asset}/{settings.quote_asset}</b>{owned && <span className="owned-badge">INVESTERT</span>}<small>Investert: {money(invested)} {settings.quote_asset} · Eier: {crypto(quantity)} {asset}</small><small>Nåpris: {currentPrice === null ? "–" : `${money(currentPrice)} ${settings.quote_asset}`} · Verdi nå: {currentValue === null ? "–" : `${money(currentValue)} ${settings.quote_asset}`}</small></div><span className={(unrealized ?? pnl) < 0 ? "loss" : "gain"}>{unrealized === null ? `${money(pnl)} ${settings.quote_asset}` : `${unrealized >= 0 ? "+" : ""}${money(unrealized)} ${settings.quote_asset}`}</span></div>)}</div></section>
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">AKTIVITET</p><h3>Siste handler</h3></div><span className="muted">Oppdateres hvert 30. sekund</span></div>{trades.length === 0 ? <p className="empty">Ingen live-handler registrert ennå.</p> : <div className="trade-list">{trades.slice(0, 20).map((trade) => <div className="trade-row" key={trade.id}><b>{trade.side} {trade.symbol}</b><span>{Number(trade.quantity).toPrecision(6)}</span><span className={Number(trade.pnl ?? 0) < 0 ? "loss" : "gain"}>{money(Number(trade.pnl ?? 0))} {settings.quote_asset}</span><time>{new Date(trade.created_at).toLocaleString("nb-NO")}</time></div>)}</div>}</section>
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">SERVERSTATUS</p><h3>Siste kontrollsignal</h3></div>{lastEvent && <time className="muted">{new Date(lastEvent.created_at).toLocaleString("nb-NO")}</time>}</div><p className={lastEvent?.level === "error" ? "loss" : "muted"}>{lastEvent?.message ?? "Serverrapportering er ikke koblet til ennå."}</p></section>
    <section className="panel chat-panel"><div className="panel-head"><div><p className="eyebrow">SNAKK MED BOTTEN</p><h3>Du er sjefen</h3></div><span className="muted">Leser ferske kontrolldata</span></div>
      <div className="chat-log" aria-live="polite">{chatMessages.map((item) => <div className={`chat-bubble ${item.role}`} key={item.id}><small>{item.role === "boss" ? "SJEFEN" : "BOTTEN"}</small><p>{item.text}</p></div>)}</div>
      <form className="chat-form" onSubmit={(event) => { event.preventDefault(); void sendChat(); }}><input aria-label="Skriv til botten" value={chatInput} onChange={(event) => setChatInput(event.target.value)} placeholder="F.eks. «Hva er status?»" /><button className="primary" type="submit">Send</button></form>
      <p className="chat-note">Chatten kan lese status og pause botten. Direkte ordre fra fritekst er sperret.</p>
    </section>
    <HowItWorks />
  </main>;
}

function Field({ label, value, min, max, step, onChange }: Readonly<{ label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void }>) { return <label className="number-field"><span>{label}</span><input type="number" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} /></label>; }
