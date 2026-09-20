export function walletFields(message: string) {
  return Object.fromEntries(message.split(";").filter(p => p.includes("=")).map(p => {
    const i = p.indexOf("="); return [p.slice(0, i), p.slice(i + 1)];
  }));
}

export function walletNumber(value: string | undefined): number | null {
  if (!value?.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function futuresWallet(message: string, fresh: boolean) {
  const fields = walletFields(message);
  const status = !fresh ? "stale" : fields.futures_status ?? "legacy";
  const total = walletNumber(fields.futures_total);
  const available = walletNumber(fields.futures_available);
  return {
    status, total, available,
    value: fields.futures_wallet_version === "v2" ? walletNumber(fields.futures_value) : total,
    positionMargin: walletNumber(fields.futures_position_margin),
    orderMargin: walletNumber(fields.futures_order_margin),
    mode: fields.futures_margin_mode,
    assets: (fields.futures_assets ?? "").split(",").flatMap(row => {
      const [asset, raw] = row.split(":"); const balance = walletNumber(raw);
      return asset && balance !== null ? [{ asset, balance }] : [];
    }),
    tradable: fresh && status === "ready" && available !== null ? Math.max(0, available) : 0,
  };
}

export function futuresStatus(status: string): string {
  const labels: Record<string, string> = {
    ready: "Tilgjengelig for futureshandel når signal og innstillinger tillater det.",
    stale: "Saldorapporten er utdatert. Venter på nye data.",
    legacy: "Detaljert futuresstatus krever oppdatering av handelsserveren.",
    no_quote_collateral: "Futuresmidler i andre valutaer kan ikke brukes direkte til valgt kontrakt. Kontroller handelsvaluta og margin i Binance.",
    margin_in_use: "Margin er bundet i posisjoner eller åpne ordre hos Binance.",
    no_available_margin: "Binance rapporterer ingen tilgjengelig margin. Kontroller Futures → tilgjengelig saldo og eventuelle kredittvilkår i Binance.",
    trading_disabled: "Binance rapporterer at futureshandel ikke er tillatt på kontoen.",
    balance_unavailable: "Tilgjengelig futuresmargin kunne ikke bekreftes.",
    read_error: "Futuressaldo kunne ikke hentes. Kontroller tilkobling og Futures-rettigheter i Binance.",
    not_connected: "Binance er ikke tilkoblet.",
  };
  return labels[status] ?? "Venter på futuresstatus fra serveren.";
}
