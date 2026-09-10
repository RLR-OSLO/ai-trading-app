"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { supabase } from "../lib/supabase";
import HowItWorks from "./how-it-works";
import LogoutButton from "./logout-button";

type Settings = {
  bot_enabled: boolean;
  live_trading_enabled: boolean;
  risk_profile: "low" | "normal" | "high" | "extreme";
  quote_asset: "USDC" | "USDT";
  trade_cap_usdc: number;
  order_size_usdc: number;
  stop_loss_percent: number;
  take_profit_percent: number;
  max_daily_loss_usdc: number;
  short_enabled: boolean;
  futures_enabled: boolean;
  leverage: number;
  daily_loss_reset_at: string | null;
};

type Trade = { id: string; symbol: string; mode: string; side: "BUY" | "SELL"; quantity: number; entry_price: number | null; exit_price: number | null; pnl: number | null; leverage?: number | null; created_at: string };
type BotEvent = { id: number; level: "info" | "warning" | "error"; event_type: string; message: string; created_at: string };
type ChatMessage = { id: number; role: "boss" | "bot"; text: string };
type TradeDirective = { id: number; symbol: string; direction: "LONG" | "SHORT"; mode: "SPOT" | "MARGIN" | "FUTURES"; requested_notional: number; leverage: number; status: string; created_at: string; expires_at: string };

const defaults: Settings = {
  bot_enabled: false,
  live_trading_enabled: false,
  risk_profile: "normal",
  quote_asset: "USDC",
  trade_cap_usdc: 100,
  order_size_usdc: 25,
  stop_loss_percent: 1,
  take_profit_percent: 2,
  max_daily_loss_usdc: 2,
  short_enabled: false,
  futures_enabled: false,
  leverage: 1,
  daily_loss_reset_at: null,
};
const MARKET_UNIVERSE = [
  "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "TRX", "AVAX", "LINK",
  "SUI", "XLM", "BCH", "LTC", "DOT", "SHIB", "TON", "HBAR", "UNI", "AAVE",
  "NEAR", "APT", "ETC", "FIL", "ICP", "ATOM", "ALGO", "VET", "POL", "ARB",
] as const;
const money = (value: number) => new Intl.NumberFormat("nb-NO", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
const crypto = (value: number) => new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 8 }).format(value);

type HistoryPoint = { t: number; c: number };
type HistoryMap = Record<string, HistoryPoint[]>;

function Sparkline({ points, hours }: { points: HistoryPoint[]; hours: 3 | 6 | 12 }) {
  const cutoff = Date.now() - hours * 3_600_000;
  const visible = points.filter((point) => point.t >= cutoff);
  if (visible.length < 2) return <div className="sparkline-empty">Ingen grafdata</div>;
  const values = visible.map((point) => point.c);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, Math.max(Math.abs(max), 1) * 0.000001);
  const width = 150;
  const height = 42;
  const path = visible.map((point, index) => {
    const x = (index / Math.max(1, visible.length - 1)) * width;
    const y = height - ((point.c - min) / span) * height;
    return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const first = visible[0].c;
  const last = visible[visible.length - 1].c;
  const change = first ? ((last / first) - 1) * 100 : 0;
  const trend = change >= 0 ? "up" : "down";
  return <div className={`sparkline-wrap ${trend}`} title={`${change >= 0 ? "+" : ""}${change.toFixed(2)} % siste ${hours}t`}>
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true"><path d={path} /></svg>
    <span>{change >= 0 ? "+" : ""}{change.toFixed(2)} %</span>
  </div>;
}

export default function TradingDashboard() {
  const [settings, setSettings] = useState<Settings>(defaults);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [lastEvent, setLastEvent] = useState<BotEvent | null>(null);
  const [chatInput, setChatInput] = useState("");
  const [serverSignalExpanded, setServerSignalExpanded] = useState(false);
  const [priorityDirectives, setPriorityDirectives] = useState<TradeDirective[]>([]);
  const [priorityBusy, setPriorityBusy] = useState<number | null>(null);
  const [historyHours, setHistoryHours] = useState<3 | 6 | 12>(6);
  const [marketHistory, setMarketHistory] = useState<HistoryMap>({});
  const [setupAmounts, setSetupAmounts] = useState<Record<string, string>>({});
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    { id: 1, role: "bot", text: "Jeg leser ferske data fra tradingmotoren. Spør for eksempel: «Hva er status?», «Hvorfor handler du ikke?», «Hva er siste handel?», «Hvordan går resultatet?» eller «Hvilket marked er sterkest nå?»." },
  ]);

  const load = useCallback(async () => {
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) return;
    const [{ data: row, error }, { data: recent }, { data: events }] = await Promise.all([
      supabase.from("bot_settings").select("bot_enabled,live_trading_enabled,risk_profile,quote_asset,trade_cap_usdc,order_size_usdc,stop_loss_percent,take_profit_percent,max_daily_loss_usdc,short_enabled,futures_enabled,leverage,daily_loss_reset_at").eq("user_id", userData.user.id).maybeSingle(),
      supabase.from("trades").select("id,symbol,mode,side,quantity,entry_price,exit_price,pnl,leverage,created_at").order("created_at", { ascending: false }).limit(500),
      supabase.from("bot_events").select("id,level,event_type,message,created_at").eq("event_type", "heartbeat").order("created_at", { ascending: false }).limit(1),
    ]);
    if (error) setMessage(error.message);
    if (row) setSettings(row as Settings);
    if (recent) setTrades(recent as Trade[]);
    if (events?.[0]) setLastEvent(events[0] as BotEvent);
    setLoaded(true);
  }, []);

  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 30_000); return () => window.clearInterval(timer); }, [load]);

  async function loadPriorityDirectives() {
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) { setPriorityDirectives([]); return; }
    const { data, error } = await supabase
      .from("trade_directives")
      .select("id,symbol,direction,mode,requested_notional,leverage,status,created_at,expires_at")
      .eq("user_id", userData.user.id)
      .eq("status", "pending")
      .order("created_at", { ascending: false });
    if (!error) setPriorityDirectives((data ?? []) as TradeDirective[]);
  }

  useEffect(() => {
    void loadPriorityDirectives();
    const timer = window.setInterval(() => void loadPriorityDirectives(), 5_000);
    return () => window.clearInterval(timer);
  }, []);

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
    const assetTrades = trades.filter((trade) => trade.symbol === symbol && trade.mode === "live");
    const derivativeTrades = trades.filter((trade) => trade.symbol === symbol && (trade.mode === "margin" || trade.mode === "futures")).sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
    let derivativeQuantity = 0;
    let derivativeMode: "margin" | "futures" | null = null;
    let derivativeLeverage: number | null = null;
    for (const trade of derivativeTrades) {
      const qty = Math.max(0, Number(trade.quantity));
      if (trade.side === "SELL") {
        derivativeQuantity += qty;
        derivativeMode = trade.mode as "margin" | "futures";
        derivativeLeverage = trade.mode === "futures" ? Number(trade.leverage ?? 1) : 1;
      } else {
        derivativeQuantity = Math.max(0, derivativeQuantity - qty);
        if (derivativeQuantity < 0.000000001) { derivativeQuantity = 0; derivativeMode = null; derivativeLeverage = null; }
      }
    }
    const derivativeOpen = derivativeQuantity > 0.000000001 && derivativeMode !== null;
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
    const hasBinanceBalances = /(?:^|;)balances=/.test(lastEvent?.message ?? "");
    const walletQuantity = hasBinanceBalances ? Number(binanceBalances.get(asset) ?? 0) : quantity;
    const walletValue = binanceWalletValues.get(asset);
    const fallbackPrice = marketPrices.get(symbol) ?? null;
    const resolvedValue = walletValue !== undefined ? walletValue : (fallbackPrice === null ? null : walletQuantity * fallbackPrice);
    const owned = walletQuantity > 0.000000001 && resolvedValue !== null && resolvedValue >= 5;
    const authoritativeQuantity = owned ? walletQuantity : 0;
    const currentValue = owned ? resolvedValue : 0;
    const currentPrice = authoritativeQuantity > 0 && currentValue !== null ? currentValue / authoritativeQuantity : fallbackPrice;
    const adjustedInvested = quantity > 0 && authoritativeQuantity > 0 ? invested * Math.min(1, authoritativeQuantity / quantity) : 0;
    const unrealized = currentValue === null ? null : currentValue - adjustedInvested;
    return { asset, invested: adjustedInvested, quantity: authoritativeQuantity, pnl, currentPrice, currentValue, unrealized, owned, derivativeOpen, derivativeMode, derivativeQuantity, derivativeLeverage };
  }).sort((a, b) => Number(b.derivativeOpen) - Number(a.derivativeOpen) || Number(b.owned) - Number(a.owned) || Number(b.currentValue ?? 0) - Number(a.currentValue ?? 0) || MARKET_UNIVERSE.indexOf(a.asset as typeof MARKET_UNIVERSE[number]) - MARKET_UNIVERSE.indexOf(b.asset as typeof MARKET_UNIVERSE[number])),[assets, settings.quote_asset, trades, marketPrices, binanceBalances, binanceWalletValues]);

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

  const heartbeatNumber = (name: string, fallback = 0) => {
    const match = lastEvent?.message.match(new RegExp(`(?:^|;)${name}=([0-9.]+)`));
    const value = match ? Number(match[1]) : Number.NaN;
    return Number.isFinite(value) ? value : fallback;
  };
  const spotAvailable = heartbeatNumber("spot_available", availableCapital);
  const spotTotal = heartbeatNumber("spot_total", availableCapital + portfolioValue);
  const futuresAvailable = heartbeatNumber("futures_available", 0);
  const futuresTotal = heartbeatNumber("futures_total", 0);

  const totalAssets = useMemo(() => {
    const match = lastEvent?.message.match(/(?:^|;)account_total=([0-9.]+)/);
    const value = match ? Number(match[1]) : Number.NaN;
    return Number.isFinite(value) ? value : spotTotal + futuresTotal;
  }, [lastEvent, spotTotal, futuresTotal]);

  const serverOnline = lastEvent ? Date.now() - new Date(lastEvent.created_at).getTime() < 900_000 : false;


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
      const mode = direction === "LONG" ? "SPOT" : direction === "SHORT" ? (settings.futures_enabled && settings.risk_profile === "extreme" ? `FUTURES ${settings.leverage}x` : settings.short_enabled ? "MARGIN" : "SHORT AV") : "INGEN HANDEL";
      const walletAvailable = mode.startsWith("FUTURES") ? futuresAvailable : spotAvailable;
      const suggested = Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc), walletAvailable) * sizeFactor;
      return { symbol, direction, mode, rawScore, longScore, shortScore, rank, grade, suggested };
    }).sort((a, b) => b.rank - a.rank || b.rawScore - a.rawScore).slice(0, 3);
  }, [lastEvent, settings.order_size_usdc, settings.trade_cap_usdc, settings.futures_enabled, settings.short_enabled, settings.risk_profile, settings.leverage, availableCapital, spotAvailable, futuresAvailable]);

  useEffect(() => {
    let cancelled = false;
    const loadHistory = async () => {
      const since = new Date(Date.now() - 12 * 3_600_000).toISOString();
      const pages = await Promise.all([
        supabase.from("bot_events").select("message,created_at").eq("event_type", "heartbeat").gte("created_at", since).order("created_at", { ascending: false }).range(0, 999),
        supabase.from("bot_events").select("message,created_at").eq("event_type", "heartbeat").gte("created_at", since).order("created_at", { ascending: false }).range(1000, 1999),
      ]);
      const rows = pages.flatMap((page) => page.data ?? []);
      const series: HistoryMap = {};
      for (const row of rows.reverse()) {
        const match = String(row.message ?? "").match(/(?:^|;)prices=([^;]+)/);
        if (!match) continue;
        const t = new Date(row.created_at).getTime();
        for (const item of match[1].split(",")) {
          const [symbol, raw] = item.split(":");
          const c = Number(raw);
          if (!symbol || !Number.isFinite(c)) continue;
          (series[symbol] ??= []).push({ t, c });
        }
      }
      if (!cancelled) setMarketHistory(series);
    };
    void loadHistory();
    const timer = window.setInterval(() => void loadHistory(), 60_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  function update<K extends keyof Settings>(key: K, value: Settings[K]) { setSettings((current) => ({ ...current, [key]: value })); }

  function applyRiskProfile(profile: Settings["risk_profile"]) {
    const capital = Math.max(5, availableCapital);
    const presets = {
      low: { orderShare: 0.15, stop_loss_percent: 0.75, take_profit_percent: 1.5, dailyLossShare: 0.01 },
      normal: { orderShare: 0.25, stop_loss_percent: 1.0, take_profit_percent: 2.0, dailyLossShare: 0.02 },
      high: { orderShare: 0.35, stop_loss_percent: 1.5, take_profit_percent: 3.0, dailyLossShare: 0.03 },
      extreme: { orderShare: 0.40, stop_loss_percent: 1.75, take_profit_percent: 3.5, dailyLossShare: 0.04 },
    } as const;
    const preset = presets[profile];
    const roundedOrder = Math.round((capital * preset.orderShare) * 2) / 2;
    const roundedDailyLoss = Math.round((capital * preset.dailyLossShare) * 2) / 2;
    setSettings((current) => ({
      ...current,
      risk_profile: profile,
      short_enabled: profile === "high" || profile === "extreme" ? current.short_enabled : false,
      futures_enabled: profile === "extreme" ? current.futures_enabled : false,
      leverage: profile === "extreme" ? Math.max(1, Math.min(3, Number(current.leverage || 1))) : 1,
      order_size_usdc: Math.min(Math.max(5, Number(current.trade_cap_usdc)), Math.max(5, roundedOrder)),
      stop_loss_percent: preset.stop_loss_percent,
      take_profit_percent: preset.take_profit_percent,
      max_daily_loss_usdc: Math.min(capital, Math.max(0.5, roundedDailyLoss)),
    }));
    setMessage(`${profile === "low" ? "Lav" : profile === "normal" ? "Normal" : profile === "high" ? "Høy" : "Ekstrem"} risiko valgt. Standardverdiene er satt automatisk – trykk Lagre innstillinger for å aktivere dem.`);
  }

  async function save() {
    setSaving(true); setMessage("");
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) { setSaving(false); return; }
    const configuredCap = Math.max(5, Number(settings.trade_cap_usdc));
    const safe = {
      ...settings,
      trade_cap_usdc: configuredCap,
      order_size_usdc: Math.min(configuredCap, Math.max(5, Number(settings.order_size_usdc))),
      max_daily_loss_usdc: Math.min(configuredCap, Math.max(0.5, Number(settings.max_daily_loss_usdc))),
      short_enabled: ["high", "extreme"].includes(settings.risk_profile) ? settings.short_enabled : false,
      futures_enabled: settings.risk_profile === "extreme" ? settings.futures_enabled : false,
      leverage: settings.risk_profile === "extreme" ? Math.max(1, Math.min(3, Number(settings.leverage))) : 1,
      updated_at: new Date().toISOString(),
      user_id: userData.user.id
    };
    const { error } = await supabase.from("bot_settings").upsert(safe, { onConflict: "user_id" });
    setSaving(false); setMessage(error ? error.message : "Innstillingene er lagret."); if (!error) setSettings(safe);
  }

  async function setLive(enabled: boolean) {
    setSaving(true); setMessage("");
    const next = { ...settings, bot_enabled: enabled, live_trading_enabled: enabled };
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) { setSaving(false); return; }
    const { error } = await supabase.from("bot_settings").upsert({ ...next, user_id: userData.user.id, updated_at: new Date().toISOString() }, { onConflict: "user_id" });
    if (!error) setSettings(next);
    setMessage(error ? error.message : enabled ? "Live trading er aktivert." : "Trading er pauset.");
    setSaving(false);
  }

  async function resetDailyLoss() {
    if (!window.confirm("Nullstille dagens registrerte tapsgrense og handelsantall?")) return;
    setSaving(true); setMessage("");
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) { setSaving(false); return; }
    const stamp = new Date().toISOString();
    const { error } = await supabase.from("bot_settings")
      .update({ daily_loss_reset_at: stamp, updated_at: stamp })
      .eq("user_id", userData.user.id);
    if (!error) setSettings((current) => ({ ...current, daily_loss_reset_at: stamp }));
    setMessage(error ? error.message : "Reset av dagstap er sendt til tradingmotoren.");
    setSaving(false);
  }

  async function emergencyStop() {
    const confirmed = window.confirm("Aktivere nødstopp? Nye kjøp stoppes. Eksisterende posisjoner beholdes under aktiv stop-loss/trailing og kan fortsatt selges automatisk for å beskytte kapitalen.");
    if (!confirmed) return;
    setSaving(true); setMessage("");
    const next = { ...settings, bot_enabled: false, live_trading_enabled: false };
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) { setSaving(false); return; }
    const { error } = await supabase.from("bot_settings").upsert({ ...next, user_id: userData.user.id, updated_at: new Date().toISOString() }, { onConflict: "user_id" });
    if (!error) setSettings(next);
    setMessage(error ? error.message : "NØDSTOPP AKTIV: Nye kjøp er blokkert. Eksisterende posisjoner overvåkes fortsatt av stop-loss/trailing og kan selges automatisk.");
    setSaving(false);
  }

  function heartbeatField(name: string): string | null {
    const match = lastEvent?.message.match(new RegExp(`(?:^|;)${name}=([^;]+)`));
    return match?.[1] ?? null;
  }

  function scoreMap(field: string): Map<string, number> {
    const result = new Map<string, number>();
    const raw = heartbeatField(field);
    if (!raw || raw === "none") return result;
    for (const item of raw.split(",")) {
      const [symbol, value] = item.split(":");
      const number = Number(value);
      if (symbol && Number.isFinite(number)) result.set(symbol, number);
    }
    return result;
  }

  function requestedSymbol(normalized: string): string | null {
    const upper = normalized.toUpperCase();
    for (const asset of MARKET_UNIVERSE) {
      if (new RegExp(`(^|[^A-Z0-9])${asset}([^A-Z0-9]|$)`).test(upper)) return `${asset}${settings.quote_asset}`;
    }
    return null;
  }

  function explainMarket(symbol: string): string {
    if (!lastEvent) return "Jeg mangler ferske markedsdata akkurat nå.";
    const markets = (heartbeatField("markets") ?? "").split(",").filter(Boolean);
    const signals = heartbeatField("signals") ?? "none";
    const bullruns = heartbeatField("bullrun") ?? "none";
    const swingScores = scoreMap("scores");
    const scalpScores = scoreMap("scalp_scores");
    const threshold = Number(heartbeatField("threshold") ?? "0");
    const base = symbol.replace(settings.quote_asset, "");
    if (!markets.includes(symbol)) {
      return `${base} er ikke blant de aktive markedene boten følger akkurat nå. Boten velger bare opptil 12 markeder som består likviditetskravene og rangerer høyest på volum/aktivitet. Derfor vurderes ikke ${base} for kjøp i denne syklusen.`;
    }
    const swing = swingScores.get(symbol);
    const scalp = scalpScores.get(symbol);
    const hasSignal = signals !== "none" && signals.split(",").some((item) => item.startsWith(`${symbol}:`));
    const isBullrun = bullruns !== "none" && bullruns.split(",").includes(symbol);
    if (hasSignal) {
      return `${base} har faktisk et aktivt kjøpssignal nå. Swing-score er ${swing ?? "–"}${threshold ? ` (krav ${threshold})` : ""}, scalp-score er ${scalp ?? "–"}${isBullrun ? ", og den er markert som bull run" : ""}. Hvis den likevel ikke kjøper, er neste sperre typisk kapital, cooldown, maks antall posisjoner eller daglig tapsgrense.`;
    }
    return `${base} er med i aktiv overvåking, men har ikke kjøpssignal nå. Swing-score er ${swing ?? "–"}${threshold ? ` mot krav ${threshold}` : ""}, og scalp-score er ${scalp ?? "–"}. ${isBullrun ? "Den er markert som bull run, men et annet risikofilter blokkerer entry." : "Bull-run-signal er ikke aktivt."}`;
  }

  async function stopPriority(directive: TradeDirective) {
    setPriorityBusy(directive.id);
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) { setPriorityBusy(null); return; }
    const { error } = await supabase
      .from("trade_directives")
      .update({ status: "cancelled", result: "Priority stopped by user" })
      .eq("id", directive.id)
      .eq("user_id", userData.user.id)
      .eq("status", "pending");
    if (error) {
      setMessage(`Kunne ikke stoppe prioritet: ${error.message}`);
    } else {
      setPriorityDirectives((current) => current.filter((item) => item.id !== directive.id));
      setMessage(`Prioritet stoppet for ${directive.direction} ${directive.symbol}.`);
    }
    setPriorityBusy(null);
  }

  async function prioritizeSetup(setup: { symbol: string; direction: "LONG" | "SHORT" | "VENT"; mode: string; suggested: number }) {
    if (setup.direction === "VENT") return;
    const requestedAmount = Number(setupAmounts[setup.symbol] ?? setup.suggested.toFixed(2));
    if (!Number.isFinite(requestedAmount) || requestedAmount < 5) { setMessage("Beløpet må være minst 5 USDC."); return; }
    const hardMax = Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc));
    if (requestedAmount > hardMax) { setMessage(`Beløpet kan ikke være høyere enn ${money(hardMax)} ${settings.quote_asset}.`); return; }
    const confirmed = window.confirm(`Be boten prioritere og gjennomføre ${setup.direction} ${setup.symbol} via ${setup.mode} for ${money(requestedAmount)} ${settings.quote_asset}? Alle vanlige risikogrenser gjelder fortsatt.`);
    if (!confirmed) return;
    const { data: userData } = await supabase.auth.getUser();
    if (!userData.user) { setMessage("Du må være innlogget."); return; }
    const cleanMode = setup.mode.startsWith("FUTURES") ? "FUTURES" : setup.mode === "MARGIN" ? "MARGIN" : "SPOT";
    const { data: created, error } = await supabase.from("trade_directives").insert({
      user_id: userData.user.id,
      symbol: setup.symbol,
      direction: setup.direction,
      mode: cleanMode,
      requested_notional: requestedAmount,
      leverage: cleanMode === "FUTURES" ? Math.max(1, Math.min(3, settings.leverage)) : 1,
    }).select("id,symbol,direction,mode,requested_notional,leverage,status,created_at,expires_at").single();
    if (error) {
      setMessage(`Kunne ikke sende direktiv: ${error.message}`);
    } else {
      if (created) setPriorityDirectives((current) => [created as TradeDirective, ...current.filter((item) => item.symbol !== setup.symbol)]);
      setMessage(`PRIORITERT: ${setup.direction} ${setup.symbol}. Boten forsøker på neste syklus hvis signalet fortsatt er gyldig.`);
    }
  }

  async function downloadTradesCsv() {
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

  async function sendChat() {
    const text = chatInput.trim();
    if (!text) return;
    const normalized = text.toLocaleLowerCase("nb-NO");
    const nextId = Date.now();
    setChatInput("");
    setChatMessages((current) => [...current, { id: nextId, role: "boss", text }]);
    const symbol = requestedSymbol(normalized);
    let reply: string;

    if (normalized.includes("pause") || normalized.includes("stopp bot") || normalized === "stopp") {
      await setLive(false);
      reply = "Boten er pauset. Nye kjøp er blokkert, mens åpne posisjoner fortsatt overvåkes av stop-loss/trailing.";
    } else if ((normalized.includes("hvorfor") || normalized.includes("signal") || normalized.includes("analyse")) && symbol) {
      reply = explainMarket(symbol);
    } else if (normalized.includes("hvorfor") && (normalized.includes("kjøp") || normalized.includes("handler") || normalized.includes("handel"))) {
      const best = heartbeatField("best");
      const signals = heartbeatField("signals") ?? "none";
      const news = heartbeatField("news");
      reply = signals === "none"
        ? `Det er ingen godkjente kjøpssignaler akkurat nå. ${best ? `Sterkeste kandidat er ${best.replaceAll(":", " / ")}. ` : ""}${news ? `Nyhetsscore er ${news}. ` : ""}Boten venter fordi minst ett av kravene for entry ikke er oppfylt.`
        : `Det finnes signaler nå: ${signals}. Hvis ingen ordre er lagt, er en senere sperre aktiv, for eksempel cooldown, maks posisjoner, kapital eller daglig tapsgrense.`;
    } else if (normalized.includes("siste") && normalized.includes("handel")) {
      const trade = trades[0];
      reply = trade ? `Siste registrerte handel er ${trade.side} ${trade.symbol}, ${Number(trade.quantity).toPrecision(6)} enheter. Realisert resultat: ${money(Number(trade.pnl ?? 0))} USDC.` : "Det er ikke registrert noen handler ennå.";
    } else if (normalized.includes("resultat") || normalized.includes("gevinst") || normalized.includes("tap")) {
      reply = `Realisert totalresultat er ${money(stats.total)} USDC. Siste døgn: ${money(stats.day)} USDC. Vunnet: ${money(stats.won)} USDC. Tapt: ${money(Math.abs(stats.lost))} USDC. Estimerte gebyrer: ${money(stats.feesEstimate)} USDC.`;
    } else if (normalized.includes("sterkest") || normalized.includes("beste") || normalized.includes("best nå")) {
      const best = heartbeatField("best");
      reply = best ? `Sterkeste kandidat i siste scan er ${best.replaceAll(":", " / ")}. Dette er kandidat-rangering, ikke nødvendigvis et godkjent kjøpssignal.` : "Jeg har ikke fersk rangering fra siste scan.";
    } else if (normalized.includes("status") || normalized.includes("live") || normalized.includes("aktiv")) {
      const signals = heartbeatField("signals") ?? "none";
      const markets = heartbeatField("markets")?.split(",").length ?? 0;
      reply = `${serverOnline ? "Serveren er online" : "Serverstatusen er ikke fersk"}. Trading er ${settings.live_trading_enabled ? "LIVE" : "PAUSET"}. Ledig kapital er ${money(availableCapital)} ${settings.quote_asset}. ${markets} markeder overvåkes. Aktive signaler: ${signals}.`;
    } else if ((normalized.startsWith("kjøp ") || normalized.startsWith("selg ") || normalized.includes("handel nå")) && !normalized.includes("hvorfor")) {
      reply = "Direkte kjøp og salg fra fritekst er sperret. Tradingassistenten kan forklare hvorfor boten handler eller ikke handler, men kan ikke omgå risikoreglene.";
    } else if (symbol) {
      reply = explainMarket(symbol);
    } else {
      reply = "Spør meg konkret om en coin eller om boten, for eksempel «Hvorfor kjøper du ikke LTC nå?», «Hva er sterkeste marked?», «Hva er status?» eller «Hva var siste handel?». Jeg svarer fra siste faktiske bot- og Binance-data.";
    }
    setChatMessages((current) => [...current, { id: nextId + 1, role: "bot", text: reply }]);
  }

  return <main className="shell">
    <header className="topbar"><div><span className="eyebrow">AI TRADING APP</span><h1>Kontrollpanel</h1></div><div style={{ display: "flex", gap: 10, alignItems: "center" }}><span className="pill"><i /> {serverOnline ? "Server online" : "Ingen fersk serverstatus"}</span><LogoutButton /></div></header>
    <section className="hero"><div><p className="eyebrow">AI TRADING</p><h2>Spot, short-analyse og utvidet risikokontroll.</h2><p className="muted">Binance-uttak er deaktivert. Margin/Futures krever egne Binance-rettigheter.</p></div><div className="emergency-stop-box"><button className="danger" onClick={() => void emergencyStop()} disabled={saving}>Nødstopp</button><small>Nødstopp blokkerer nye kjøp. Åpne posisjoner blir ikke dumpet umiddelbart; boten fortsetter å overvåke dem og kan selge ved stop-loss, trailing-stop eller annen aktiv exitregel. Start live igjen for å tillate nye kjøp.</small></div></section>
    <section className="panel" style={{ marginBottom: 18 }}>
      <div className="wallet-overview">
        <div className="wallet-total"><span className="label">TOTAL BINANCE-VERDI</span><strong>{money(totalAssets)} {settings.quote_asset}</strong><small>Spot + Futures</small></div>
        <div><span className="label">SPOT TOTALT</span><strong>{money(spotTotal)} {settings.quote_asset}</strong><small>Ledig Spot: {money(spotAvailable)} · Investert Spot: {money(portfolioValue)}</small></div>
        <div><span className="label">FUTURES TOTALT</span><strong>{money(futuresTotal)} {settings.quote_asset}</strong><small>Ledig Futures: {money(futuresAvailable)} {settings.quote_asset}</small></div>
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
        <Field label={`Maks botkapital (${settings.quote_asset})`} value={settings.trade_cap_usdc} min={5} step={5} onChange={(value) => update("trade_cap_usdc", value)} />
        <Field label={`Maks per posisjon (${settings.quote_asset})`} value={settings.order_size_usdc} min={5} max={Math.max(5, settings.trade_cap_usdc)} step={5} onChange={(value) => update("order_size_usdc", value)} />
        <Field label="Stop-loss (%)" value={settings.stop_loss_percent} min={0.25} max={10} step={0.25} onChange={(value) => update("stop_loss_percent", value)} />
        <Field label="Gevinstmål (%)" value={settings.take_profit_percent} min={0.5} max={25} step={0.5} onChange={(value) => update("take_profit_percent", value)} />
        <Field label={`Maks dagstap (${settings.quote_asset})`} value={settings.max_daily_loss_usdc} min={0.5} max={Math.max(0.5, availableCapital)} step={0.5} onChange={(value) => update("max_daily_loss_usdc", value)} />
        <label className="select-field"><span>Risikonivå</span><select value={settings.risk_profile} onChange={(event) => applyRiskProfile(event.target.value as Settings["risk_profile"])}><option value="low">Lav</option><option value="normal">Normal</option><option value="high">Høy</option><option value="extreme">Ekstrem</option></select><small>Bytte av risikonivå setter automatisk nye standardverdier. Du kan deretter overstyre «Maks per investering» manuelt.</small></label>

        <label className="select-field">
          <span>Shorting</span>
          <select
            value={settings.short_enabled ? "on" : "off"}
            disabled={!["high", "extreme"].includes(settings.risk_profile)}
            onChange={(e) => update("short_enabled", e.target.value === "on")}
          >
            <option value="off">AV</option>
            <option value="on">PÅ</option>
          </select>
          <small>Tilgjengelig på Høy og Ekstrem. Krever Binance Margin-rettigheter.</small>
        </label>

        <label className="select-field">
          <span>Futures</span>
          <select
            value={settings.futures_enabled ? "on" : "off"}
            disabled={settings.risk_profile !== "extreme"}
            onChange={(e) => update("futures_enabled", e.target.value === "on")}
          >
            <option value="off">AV</option>
            <option value="on">PÅ</option>
          </select>
          <small>Kun Ekstrem risiko. Krever Binance Futures-rettighet.</small>
        </label>

        <Field
          label="Gearing"
          value={settings.leverage}
          min={1}
          max={3}
          step={1}
          onChange={(value) => update("leverage", Math.max(1, Math.min(3, value)))}
        />
      </div><div className="actions"><button onClick={() => void setLive(!settings.live_trading_enabled)} disabled={saving || !loaded}>{settings.live_trading_enabled ? "Pause trading" : "Start live"}</button><button className="primary" onClick={() => void save()} disabled={saving || !loaded}>{saving ? "Lagrer …" : "Lagre innstillinger"}</button><button className="secondary" onClick={() => void resetDailyLoss()} disabled={saving || !loaded}>Reset dagstap</button></div>{message && <p className="inline-message">{message}</p>}
    </section>
    <section className="panel best-setup-panel">
      <div className="panel-head"><div><p className="eyebrow">BESTE OPPSETT AKKURAT NÅ</p><h3>Botens høyest rangerte muligheter</h3></div><div className="chart-actions"><div className="chart-range" aria-label="Grafperiode">{([3,6,12] as const).map((hours) => <button type="button" key={hours} className={historyHours === hours ? "active" : ""} onClick={() => setHistoryHours(hours)}>{hours}t</button>)}</div><button type="button" className="secondary compact" onClick={() => void load()}>Oppdater nå</button></div></div>
      <p className="muted best-setup-intro">Rangert fra siste faktiske markedsscan. A = sterkest oppsett, B = godt oppsett, C = svakere/vent. Beløpet er et forslag innenfor dine nåværende grenser – ingen ordre sendes fra denne boksen.</p>
      {bestSetups.length === 0 ? <p className="empty">Venter på ferske markedsdata.</p> : <div className="best-setup-grid">{bestSetups.map((setup, index) => <article className={`best-setup-card ${setup.direction.toLowerCase()}`} key={setup.symbol}>
        <div className="best-setup-rank">#{index + 1}</div>
        <div><span className={`setup-grade grade-${setup.grade.toLowerCase()}`}>{setup.grade}</span><strong>{setup.symbol}</strong></div>
        <div className={`setup-direction ${setup.direction.toLowerCase()}`}>{setup.direction}</div>
        <small>Modus: <b>{setup.mode}</b></small>
        <small>Aktuell score: <b>{setup.rawScore}</b> · Long {setup.longScore} / Short {setup.shortScore}</small>
        <Sparkline points={marketHistory[setup.symbol] ?? []} hours={historyHours} />
        <div className="setup-amount"><small>Beløp ({settings.quote_asset}) · forslag {money(setup.suggested)}</small><input type="number" min={5} max={Math.min(Number(settings.order_size_usdc), Number(settings.trade_cap_usdc))} step="1" value={setupAmounts[setup.symbol] ?? setup.suggested.toFixed(2)} onFocus={(event) => event.currentTarget.select()} onChange={(event) => setSetupAmounts((current) => ({ ...current, [setup.symbol]: event.target.value }))} /></div>
        {setup.direction !== "VENT" && (() => {
          const active = priorityDirectives.find((item) => item.symbol === setup.symbol && item.direction === setup.direction);
          return active
            ? <div className="priority-active"><span className="priority-active-badge">PRIORITERT</span><button type="button" className="danger compact" disabled={priorityBusy === active.id} onClick={() => void stopPriority(active)}>{priorityBusy === active.id ? "Stopper …" : "Stopp prioritet"}</button></div>
            : <button type="button" className="primary compact" onClick={() => void prioritizeSetup(setup)}>Prioriter og gjennomfør</button>;
        })()}
      </article>)}</div>}
      <p className="muted best-setup-note">«Prioriter og gjennomfør» sender et kortvarig direktiv til boten – ikke en Binance-ordre fra nettleseren. Boten gjennomfører bare dersom samme signal fortsatt er gyldig og alle vanlige stop-loss-, dagstap-, kapital-, cooldown- og posisjonsgrenser fortsatt er oppfylt.</p>
    </section>
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">PORTEFØLJE</p><h3>Investert per valuta</h3></div><span className="muted">Spot, Margin-short og Futures vises tydelig hver for seg</span></div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 14 }}>
        <span style={{ padding: "6px 10px", borderRadius: 999, background: "rgba(34,197,94,.12)", border: "1px solid rgba(34,197,94,.32)", fontSize: 12 }}>SPOT · vanlig beholdning</span>
        <span style={{ padding: "6px 10px", borderRadius: 999, background: "rgba(168,85,247,.12)", border: "1px solid rgba(168,85,247,.35)", fontSize: 12 }}>MARGIN SHORT · lånt og solgt</span>
        <span style={{ padding: "6px 10px", borderRadius: 999, background: "rgba(245,158,11,.13)", border: "1px solid rgba(245,158,11,.38)", fontSize: 12 }}>FUTURES SHORT · kan ha gearing</span>
      </div>
      <div className="assets">{allocations.map(({ asset, invested, quantity, pnl, currentPrice, currentValue, unrealized, owned, derivativeOpen, derivativeMode, derivativeQuantity, derivativeLeverage }) => {
        const derivativeStyle = derivativeOpen ? (derivativeMode === "futures"
          ? { borderColor: "rgba(245,158,11,.65)", background: "rgba(245,158,11,.08)" }
          : { borderColor: "rgba(168,85,247,.60)", background: "rgba(168,85,247,.08)" }) : undefined;
        return <div className={`asset${owned ? " invested" : ""}`} style={derivativeStyle} key={asset}><span className="coin">{asset[0]}</span><div><b>{asset}/{settings.quote_asset}</b>{owned && <span className="owned-badge">SPOT</span>}{derivativeOpen && <span className="owned-badge" style={{ marginLeft: 6 }}>{derivativeMode === "futures" ? `SHORT · FUTURES · ${derivativeLeverage ?? 1}x` : "SHORT · MARGIN"}</span>}<small>Spot investert: {money(invested)} {settings.quote_asset} · Eier: {crypto(quantity)} {asset}</small>{derivativeOpen && <small style={{ fontWeight: 700 }}>Åpen derivatposisjon: short {crypto(derivativeQuantity)} {asset}{derivativeMode === "futures" ? ` · gearing ${derivativeLeverage ?? 1}x` : " · margin/lån"}</small>}<small>Nåpris: {currentPrice === null ? "–" : `${money(currentPrice)} ${settings.quote_asset}`} · Spotverdi nå: {currentValue === null ? "–" : `${money(currentValue)} ${settings.quote_asset}`}</small><Sparkline points={marketHistory[`${asset}${settings.quote_asset}`] ?? []} hours={historyHours} /></div><span className={(unrealized ?? pnl) < 0 ? "loss" : "gain"}>{unrealized === null ? `${money(pnl)} ${settings.quote_asset}` : `${unrealized >= 0 ? "+" : ""}${money(unrealized)} ${settings.quote_asset}`}</span></div>;
      })}</div>
      <p className="muted" style={{ marginTop: 12, marginBottom: 0 }}>Farget markering betyr at denne valutaen har en åpen short-/derivatposisjon i tillegg til eventuell spotbeholdning. Lilla = Margin-short. Oransje = Futures-short; badge viser gearingen som ble brukt ved åpning.</p>
    </section>
    <section className="panel trade-history-panel"><div className="panel-head"><div><p className="eyebrow">AKTIVITET</p><h3>Siste handler</h3></div><div className="trade-head-actions"><span className="muted">Oppdateres hvert 30. sekund</span><button type="button" className="secondary compact" onClick={() => void downloadTradesCsv()}>Last ned CSV</button></div></div>{trades.length === 0 ? <p className="empty">Ingen live-handler registrert ennå.</p> : <div className="trade-list"><div className="trade-row trade-header"><span>Handel</span><span>Antall</span><span>Inngang</span><span>Utgang</span><span>Resultat</span><span>Tid</span></div>{trades.slice(0, 20).map((trade) => { const derivative = trade.mode === "margin" || trade.mode === "futures"; const modeClass = trade.mode === "futures" ? "trade-futures" : trade.mode === "margin" ? "trade-margin" : "trade-spot"; const label = trade.mode === "futures" ? `SHORT · FUTURES · ${Number(trade.leverage ?? 1)}x` : trade.mode === "margin" ? "SHORT · MARGIN" : "SPOT"; return <div className={`trade-row ${modeClass}`} key={trade.id}><div><span className={`trade-mode-badge ${modeClass}`}>{label}</span><b>{trade.side} {trade.symbol}</b><small>{derivative ? (trade.side === "SELL" ? "Åpnet short-posisjon" : "Lukket short-posisjon") : (trade.side === "BUY" ? "Kjøpt spot" : "Solgt spot")}</small></div><span>{Number(trade.quantity).toPrecision(6)}</span><span>{trade.entry_price == null ? "–" : money(Number(trade.entry_price))}</span><span>{trade.exit_price == null ? "ÅPEN" : money(Number(trade.exit_price))}</span><span className={Number(trade.pnl ?? 0) < 0 ? "loss" : "gain"}>{trade.pnl == null ? "–" : `${Number(trade.pnl) >= 0 ? "+" : ""}${money(Number(trade.pnl))} ${settings.quote_asset}`}</span><time>{new Date(trade.created_at).toLocaleString("nb-NO")}</time></div>; })}</div>}</section>
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">SERVERSTATUS</p><h3>Siste kontrollsignal</h3></div><div className="server-signal-actions">{lastEvent && <time className="muted">{new Date(lastEvent.created_at).toLocaleString("nb-NO")}</time>}<button type="button" className="secondary compact" onClick={() => setServerSignalExpanded((value) => !value)}>{serverSignalExpanded ? "Skjul" : "Utvid"}</button></div></div><p className={`server-signal ${serverSignalExpanded ? "expanded" : "collapsed"} ${lastEvent?.level === "error" ? "loss" : "muted"}`}>{lastEvent?.message ?? "Serverrapportering er ikke koblet til ennå."}</p></section>
    <section className="panel chat-panel"><div className="panel-head"><div><p className="eyebrow">TRADINGASSISTENT</p><h3>Spør om det boten faktisk gjør</h3></div><span className="muted">Basert på ferske Binance- og botdata</span></div>
      <div className="chat-log" aria-live="polite">{chatMessages.map((item) => <div className={`chat-bubble ${item.role}`} key={item.id}><small>{item.role === "boss" ? "SJEFEN" : "BOTTEN"}</small><p>{item.text}</p></div>)}</div>
      <div className="chat-suggestions"><span>Prøv:</span><button type="button" onClick={() => setChatInput("Hva er status?")}>Status</button><button type="button" onClick={() => setChatInput("Hvorfor handler du ikke?")}>Hvorfor ingen handel?</button><button type="button" onClick={() => setChatInput("Hva er siste handel?")}>Siste handel</button><button type="button" onClick={() => setChatInput("Hvordan går resultatet?")}>Resultat</button></div>
      <form className="chat-form" onSubmit={(event) => { event.preventDefault(); void sendChat(); }}><input aria-label="Skriv til botten" value={chatInput} onChange={(event) => setChatInput(event.target.value)} placeholder="Spør om status, handler, signaler, risiko eller resultat …" /><button className="primary" type="submit">Send</button></form>
      <p className="chat-note">Dette er en lokal tradingassistent uten ekstra AI-kostnad. Den svarer ut fra ferske botdata og kan pause boten. Direkte ordre fra fritekst er sperret.</p>
    </section>
    <HowItWorks />
  </main>;
}

function Field({ label, value, min, max, step, onChange }: Readonly<{ label: string; value: number; min: number; max?: number; step: number; onChange: (value: number) => void }>) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => { setDraft(String(value)); }, [value]);
  const commit = () => {
    const parsed = Number(draft);
    if (!Number.isFinite(parsed)) { setDraft(String(value)); return; }
    const bounded = Math.min(max ?? Number.POSITIVE_INFINITY, Math.max(min, parsed));
    onChange(bounded);
    setDraft(String(bounded));
  };
  return <label className="number-field"><span>{label}</span><input type="number" value={draft} min={min} max={max} step={step} onFocus={(event) => event.currentTarget.select()} onChange={(event) => setDraft(event.target.value)} onBlur={commit} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} /></label>;
}
