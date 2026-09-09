"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "../lib/supabase";

type SetupState = "loading" | "required" | "ready" | "saving" | "error";

export default function ExchangeOnboarding({ children }: Readonly<{ children: React.ReactNode }>) {
  const [state, setState] = useState<SetupState>("loading");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    setState("loading");
    const { data, error } = await supabase.rpc("exchange_setup_status");
    if (error) {
      setMessage(error.message);
      setState("error");
      return;
    }
    const row = Array.isArray(data) ? data[0] : data;
    setState(row?.configured ? "ready" : "required");
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function save() {
    setMessage("");
    setState("saving");
    const validation = await fetch("/api/validate-binance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apiKey: apiKey.trim(), apiSecret: apiSecret.trim() }),
    });
    const result = await validation.json();
    if (!validation.ok || !result?.ok) {
      setMessage(result?.error ?? "Binance-nøkkelen kunne ikke verifiseres.");
      setState("required");
      return;
    }

    const { error } = await supabase.rpc("save_binance_credentials", {
      p_api_key: apiKey.trim(),
      p_api_secret: apiSecret.trim(),
    });
    if (error) {
      setMessage(error.message);
      setState("required");
      return;
    }
    setApiKey("");
    setApiSecret("");
    setState("ready");
  }

  if (state === "ready") return <>{children}</>;

  return <main className="gate-shell"><section className="gate-card" style={{ maxWidth: 620 }}>
    <p className="eyebrow">NY BRUKER · BINANCE</p>
    <h1>Koble din Binance-konto</h1>
    <p className="muted">Hver bruker får sin egen Binance-konto, egne handler, egne innstillinger og eget dashboard. Ingenting deles mellom brukere.</p>

    {state === "loading" && <p className="muted">Kontrollerer Binance-oppsettet …</p>}
    {state === "error" && <button className="primary" onClick={() => void refresh()}>Prøv igjen</button>}
    {(state === "required" || state === "saving") && <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
      <label htmlFor="binance-api-key">Binance API Key</label>
      <input id="binance-api-key" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} required />
      <details className="setup-help"><summary>ⓘ Hvor finner jeg API Key?</summary><p>Binance → profil/konto → API Management. Opprett en vanlig API-nøkkel. Aktiver lesetilgang og Spot trading. Ikke aktiver uttak, futures eller margin.</p></details>

      <label htmlFor="binance-api-secret">Binance Secret Key</label>
      <input id="binance-api-secret" type="password" autoComplete="new-password" value={apiSecret} onChange={(event) => setApiSecret(event.target.value)} required />
      <details className="setup-help"><summary>ⓘ Viktig om Secret Key</summary><p>Secret vises normalt bare når nøkkelen opprettes. Lim den inn her. Den lagres kryptert i Supabase Vault og vises ikke igjen i dashboardet.</p></details>

      <div className="setup-note"><b>Anbefalt sikkerhet:</b> Begrens API-nøkkelen til server-IP <code>146.190.20.51</code>. Tillat kun Read + Spot Trading. Uttak skal være deaktivert.</div>
      <button className="primary" type="submit" disabled={state === "saving" || !apiKey.trim() || !apiSecret.trim()}>{state === "saving" ? "Kontrollerer og lagrer …" : "Koble Binance og fortsett"}</button>
    </form>}
    {message && <p className="gate-error" role="alert">{message}</p>}
  </section></main>;
}
