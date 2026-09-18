"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { isCompassInternalAuth, supabase } from "../lib/supabase";
import { cycleDescription } from "../lib/trading-activity";

type Mode = "SPOT" | "MARGIN" | "FUTURES";
type Position = { key: string; symbol: string; mode: Mode; quantity: string; trailing_active: boolean; trailing_stop_price: string | null };
type Command = { id: string; action: "CLOSE" | "PRIORITY_OPEN"; symbol: string; mode: Mode; status: string; result: string | null; created_at: string; expires_at: string; requested_notional: number | null; quantity: number | null };
type Request = { action: Command["action"]; symbol: string; mode: Mode; position_key?: string; quantity?: string; requested_notional?: number; leverage?: number };
type Context = { positions: Position[]; commands: Command[]; ready: boolean; busy: boolean; message: string; error: string; submit: (request: Request) => Promise<void>; cancel: (command: Command) => Promise<void>; cancelPendingEntries: () => Promise<void> };
const CommandsContext = createContext<Context | null>(null);
const active = (command: Command) => ["pending", "processing"].includes(command.status);
const labels: Record<string, string> = { pending: "Venter", processing: "Behandles – avventer ordrebekreftelse", executed: "Utført", rejected: "Ikke utført", expired: "Utløpt", cancelled: "Avbrutt" };
const amount = (value: number) => new Intl.NumberFormat("nb-NO", { maximumFractionDigits: 8 }).format(value);

export function TradingCommandsProvider({ children }: { children: ReactNode }) {
  const [positions, setPositions] = useState<Position[]>([]);
  const [commands, setCommands] = useState<Command[]>([]);
  const [stamp, setStamp] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const lock = useRef(false);
  const polling = useRef(false);
  const revision = useRef(0);
  const stopGeneration = useRef(0);
  // Retain a request ID after a lost reply. Retrying cannot insert a second row.
  const retry = useRef<{ fingerprint: string; id: string } | null>(null);

  const refresh = useCallback(async () => {
    if (!isCompassInternalAuth || polling.current) return;
    polling.current = true;
    const started = revision.current;
    try {
      const { data: { user }, error: authError } = await supabase.auth.getUser();
      if (authError || !user) throw new Error("Logg inn på nytt for å hente ordrestatus.");
      const [snapshot, history] = await Promise.all([
        supabase.from("trading_position_snapshots").select("positions,engine,updated_at").eq("user_id", user.id).maybeSingle(),
        supabase.from("trading_commands").select("id,action,symbol,mode,status,result,created_at,expires_at,requested_notional,quantity").eq("user_id", user.id).order("created_at", { ascending: false }).limit(100),
      ]);
      if (snapshot.error || history.error) throw new Error(snapshot.error?.message ?? history.error?.message);
      if (started !== revision.current) return;
      setCommands((history.data ?? []) as Command[]);
      setPositions((snapshot.data?.positions ?? []) as Position[]);
      setStamp(snapshot.data?.engine === "user-commands-v5" ? Date.parse(snapshot.data.updated_at) : 0);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Kunne ikke hente ordrestatus");
    } finally { polling.current = false; }
  }, []);
  useEffect(() => {
    void refresh();
    const tick = () => { setNow(Date.now()); void refresh(); };
    const timer = window.setInterval(tick, 5_000);
    window.addEventListener("focus", tick);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", tick); };
  }, [refresh]);
  const ready = stamp > 0 && now - stamp < 180_000 && !error;

  async function submit(request: Request) {
    if (lock.current || !ready) return;
    lock.current = true; setBusy(true); setMessage(""); revision.current++;
    const fingerprint = JSON.stringify(request);
    if (retry.current?.fingerprint !== fingerprint) retry.current = { fingerprint, id: window.crypto.randomUUID() };
    const id = retry.current.id;
    const generation = stopGeneration.current;
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error("Du må være innlogget.");
      if (request.action === "PRIORITY_OPEN" && generation !== stopGeneration.current) throw new Error("Kjøpsprioriteten ble avbrutt med nødstopp.");
      const { error: submitError } = await supabase.from("trading_commands").insert({ ...request, id, user_id: user.id });
      if (submitError && submitError.code !== "23505") throw new Error(submitError.message);
      if (request.action === "PRIORITY_OPEN" && generation !== stopGeneration.current) {
        const { error: cancelError } = await supabase.from("trading_commands").update({ status: "cancelled" }).eq("user_id", user.id).eq("id", id).eq("status", "pending");
        if (cancelError) throw new Error(`Kontroller ordrelisten: avbestilling kunne ikke bekreftes. ${cancelError.message}`);
      }
      // Also handles a duplicate click or a response lost after INSERT committed.
      const { data, error: lookupError } = await supabase.from("trading_commands").select("id,action,symbol,mode,status,result,created_at,expires_at,requested_notional,quantity").eq("user_id", user.id).eq("symbol", request.symbol).eq("mode", request.mode).eq("action", request.action).order("created_at", { ascending: false }).limit(1).maybeSingle();
      if (lookupError || !data) throw new Error("Kvitteringen kunne ikke hentes. Kontroller ordrelisten før nytt forsøk.");
      revision.current++;
      setCommands((rows) => [data as Command, ...rows.filter((row) => row.id !== data.id)]);
      retry.current = null;
      setMessage(request.action === "CLOSE" ? `Salg av ${request.symbol} er sendt. Følg bekreftelsen nedenfor.` : `${request.symbol} er prioritert. Følg utførelsen nedenfor.`);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Kunne ikke bekrefte forespørselen. Kontroller ordrelisten.");
    } finally { lock.current = false; setBusy(false); }
  }

  async function cancel(command: Command) {
    if (lock.current) return;
    lock.current = true; setBusy(true); revision.current++;
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error("Du må være innlogget.");
      const { data, error: cancelError } = await supabase.from("trading_commands").update({ status: "cancelled" }).eq("user_id", user.id).eq("id", command.id).eq("status", "pending").select("id");
      if (cancelError) throw new Error(cancelError.message);
      revision.current++;
      if (data?.length) {
        setCommands((rows) => rows.map((row) => row.id === command.id ? { ...row, status: "cancelled", result: "Avbrutt av deg" } : row));
        setMessage("Forespørselen er avbrutt.");
      } else setMessage("Motoren har allerede begynt å behandle ordren. Venter på bekreftelse.");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Kunne ikke avbryte"); }
    finally { lock.current = false; setBusy(false); }
  }
  async function cancelPendingEntries() {
    stopGeneration.current++;
    revision.current++;
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) throw new Error("Du må være innlogget.");
    const { data, error: cancelError } = await supabase.from("trading_commands").update({ status: "cancelled" }).eq("user_id", user.id).eq("action", "PRIORITY_OPEN").eq("status", "pending").select("id");
    if (cancelError) throw new Error(cancelError.message);
    const ids = new Set((data ?? []).map((row) => row.id));
    revision.current++;
    setCommands((rows) => rows.map((row) => ids.has(row.id) ? { ...row, status: "cancelled", result: "Avbrutt med nødstopp" } : row));
  }
  return <CommandsContext.Provider value={{ positions, commands, ready, busy, message, error, submit, cancel, cancelPendingEntries }}>{children}</CommandsContext.Provider>;
}

export function useTradingCommands() {
  const context = useContext(CommandsContext);
  if (!context) throw new Error("TradingCommandsProvider missing");
  return context;
}

export function PositionActions({ symbol }: { symbol: string }) {
  const { positions, commands, ready, busy, submit } = useTradingCommands();
  return <div className="position-actions">{positions.filter((p) => p.symbol === symbol).map((position) => {
    const pending = commands.find((c) => c.action === "CLOSE" && c.symbol === symbol && c.mode === position.mode && active(c));
    return <div key={position.key}>
      <button type="button" className="danger compact" disabled={!ready || busy || !!pending} onClick={() => {
        const wording = position.mode === "SPOT" ? "Selge" : "Lukke shortposisjonen på";
        if (window.confirm(`${wording} inntil ${amount(Number(position.quantity))} ${symbol} (${position.mode}) til markedspris? Prisen kan endre seg. Dette gjelder denne posisjonen på din konto. Nye automatiske kjøp blir ikke aktivert. Forespørselen utløper etter 15 minutter hvis den ikke er startet.`)) {
          void submit({ action: "CLOSE", symbol, mode: position.mode, position_key: position.key, quantity: position.quantity });
        }
      }}>{pending ? labels[pending.status] : position.mode === "SPOT" ? "Selg spot" : `Lukk ${position.mode.toLowerCase()}-short`}</button>
      {position.trailing_active && position.trailing_stop_price && <small>Gevinstsikring ved {amount(Number(position.trailing_stop_price))}</small>}
    </div>;
  })}</div>;
}

export function TradingCommandStatus() {
  const { commands, ready, busy, message, error, cancel } = useTradingCommands();
  if (!isCompassInternalAuth) return null;
  const visible = [...commands.filter(active), ...commands.filter((c) => !active(c)).slice(0, 8)];
  return <section className="panel" aria-label="Dine handelsforespørsler">
    <p className="eyebrow">DINE VALG</p><h3>Salg og kjøpsprioritet</h3>
    <p className="muted">Salg og kjøpsprioritet fungerer også når automatiske kjøp er pauset. Prioritet venter på et gyldig markedssignal og utløper etter 15 minutter. Beløpsgrensene du har valgt gjelder fortsatt.</p>
    {!ready && <p role="status">Venter på fersk posisjonsrapport fra den oppdaterte motoren. Knappene blir tilgjengelige når forbindelsen er bekreftet.</p>}
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {visible.length > 0 && <ul className="command-list">{visible.map((command) => <li key={command.id}>
      <div><strong>{command.action === "CLOSE" ? "Avslutt" : "Prioriter kjøp"} {command.symbol} · {command.mode}</strong><small>{new Date(command.created_at).toLocaleString("nb-NO")}</small></div>
      <div><strong>{labels[command.status] ?? command.status}</strong><small>{command.result ? cycleDescription(command.result) : "Motoren kontrollerer forespørselen ved neste syklus."}</small></div>
      {command.status === "pending" && <button type="button" className="secondary compact" disabled={busy} onClick={() => void cancel(command)}>Avbryt</button>}
    </li>)}</ul>}
  </section>;
}
