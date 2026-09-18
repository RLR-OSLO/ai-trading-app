export type ActivityEvent = { id: number; level: string; event_type: string; message: string; created_at: string };

export function eventFields(message: string): Record<string, string> {
  return Object.fromEntries(message.split(";").filter((part) => part.includes("=")).map((part) => {
    const split = part.indexOf("=");
    return [part.slice(0, split), part.slice(split + 1)];
  }));
}

export function cycleDescription(value: string): string {
  const code = value.split(":")[0];
  const labels: Record<string, string> = {
    no_signal: "Venter på et bekreftet kjøpssignal",
    no_short_signal: "Venter på et bekreftet shortsignal",
    paused_daily_loss: "Daglig tapsgrense nådd – nye kjøp er pauset",
    paused_trade_limit: "Dagens grense for antall handler er nådd",
    paused_new_entries: "Nye kjøp er pauset",
    short_new_entries_paused: "Nye shorts er pauset",
    short_disabled: "Shorting er avslått for denne kontoen",
    cooldown: "Venter mellom handler",
    short_cooldown: "Venter før neste short",
    max_positions: "Maksimalt antall posisjoner er nådd",
    capital_cap_reached: "Den valgte kapitalgrensen er nådd",
    paused_reporting_backlog: "Handelsrapport venter på lagring – nye kjøp er pauset",
    short_reporting_backlog: "Handelsrapport venter på lagring – nye shorts er pauset",
    pending_exchange_order: "Venter på endelig ordrebekreftelse fra Binance",
    paused_pending_reconciliation: "Kontrollerer en uavklart ordre hos Binance",
    holding: "Overvåker åpen posisjon",
    trailing_hold: "Overvåker posisjon med aktiv gevinstsikring",
    trailing_active: "Gevinstsikring er aktivert",
    trailing_raise: "Gevinstsikringen er flyttet opp",
    protected: "Posisjonen har beskyttelsesordre hos Binance",
    short_notional_below_minimum: "For lite tilgjengelig beløp til ny short",
  };
  if (labels[code]) return labels[code];
  if (code.startsWith("insufficient_")) return "For lite ledig beløp i valgt handelsvaluta";
  if (code.includes("reconciliation_required")) return "Avslutning må avstemmes mot Binance";
  if (code.startsWith("bought")) return `Kjøpt ${value.split(":")[1] ?? "spot"}`;
  if (code.startsWith("sold")) return `Solgt ${value.split(":")[1] ?? "spot"}`;
  if (code.includes("short_holding")) return "Overvåker åpen short";
  if (code.includes("short_opened")) return "Shortposisjon åpnet";
  if (code.includes("short_closed")) return "Shortposisjon avsluttet";
  if (code.includes("short_open_rejected")) return "Binance avviste shortordren";
  return value;
}

export function activityDescription(event: ActivityEvent): string {
  if (event.event_type === "cycle_status") {
    const fields = eventFields(event.message);
    return [fields.spot, fields.short].filter(Boolean).map(cycleDescription).join(" · ");
  }
  if (event.event_type === "trading_cycle_error") {
    if (event.message.includes("quoteOrderQty")) return "Binance avviste ordrebeløpets format. Handelen ble ikke gjennomført.";
    if (/timeout|timed out|RemoteDisconnected/i.test(event.message)) return "Forbindelsen til Binance ble avbrutt. Motoren forsøker igjen ved neste kontroll.";
    return "Handelskontrollen feilet. Se tekniske detaljer nedenfor.";
  }
  if (event.event_type === "spot_execution" || event.event_type === "short_execution") return cycleDescription(event.message);
  const labels: Record<string, string> = {
    state_recovered: "Åpne posisjoner er gjenfunnet i historikken",
    daily_loss_reset: "Dagens tapsgrense ble nullstilt fra kontrollpanelet",
    trade_directive_rejected: "Prioritert handel ble avvist av signal- eller kontokontrollen",
    trade_directive_executed: "Prioritert handel er gjennomført",
  };
  return labels[event.event_type] ?? event.message;
}

export function engineSummary(heartbeat: ActivityEvent | null, events: ActivityEvent[], now: number,
                              enabled: boolean, live: boolean): { label: string; detail: string; tone: string } {
  if (!heartbeat) return { label: "Ingen motorstatus", detail: "Venter på første rapport fra serveren.", tone: "warning" };
  const age = now - Date.parse(heartbeat.created_at);
  if (!Number.isFinite(age) || age > 180_000) return { label: "Utdatert motorstatus", detail: "Siste rapport er over tre minutter gammel. Handelsstatus kan ikke bekreftes.", tone: "warning" };
  const fields = eventFields(heartbeat.message);
  if (fields.recovery_locked === "True" && fields.user_commands === "ready") return {
    label: "Automatikk avslått", detail: "Du kan selge og prioritere kjøp fra posisjonene nedenfor. Velg Start automatisk handel for løpende automatiske kjøp og salg.", tone: "neutral" };
  if (fields.recovery_locked === "True") return { label: "Kun overvåking", detail: "Handel er ikke aktivert etter gjenopprettingen. Serveren sender status.", tone: "warning" };
  const failure = events.find((event) => event.level === "error" && Date.parse(event.created_at) >= Date.parse(heartbeat.created_at));
  if (failure) return { label: "Feil i siste kontroll", detail: activityDescription(failure), tone: "warning" };
  if (!enabled || !live || fields.live === "False") return { label: "Nye handler pauset", detail: "Eksisterende, aktiverte posisjoner kan fortsatt overvåkes av motoren.", tone: "neutral" };
  const cycle = events.find((event) => event.event_type === "cycle_status" && now - Date.parse(event.created_at) < 360_000);
  if (cycle) return { label: "Motoren er aktiv", detail: activityDescription(cycle), tone: "active" };
  return { label: "Motoren sender status", detail: fields.signals === "none" ? "Ingen bekreftede kjøpssignaler i siste analyse." : "Analysen har signaler. Utførelse må bekreftes i handelshistorikken.", tone: "active" };
}
