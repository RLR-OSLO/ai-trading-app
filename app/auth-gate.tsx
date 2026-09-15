"use client";

import { useCallback, useEffect, useState } from "react";
import { isCompassInternalAuth, supabase } from "../lib/supabase";
import ExchangeOnboarding from "./exchange-onboarding";
import MfaGate from "./mfa-gate";

type GateState = "loading" | "signed-out" | "pending" | "rejected" | "recovery" | "ready" | "error";

export default function AuthGate({ children }: Readonly<{ children: React.ReactNode }>) {
  const [state, setState] = useState<GateState>("loading");
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [reconnect, setReconnect] = useState(false);

  const refresh = useCallback(async () => {
    setState("loading");
    setMessage("");
    const { data, error } = await supabase.auth.getSession();
    if (error) {
      setMessage(error.message);
      setState("error");
      return;
    }
    const session = data.session;
    if (!session) {
      setState("signed-out");
      return;
    }

    setEmail(session.user.email ?? "");
    if (isCompassInternalAuth) {
      // RLS exposes this app only to explicitly approved members. A Google
      // account in the shared project alone does not grant trading access.
      const { data: app, error: membershipError } = await supabase
        .from("internal_apps")
        .select("id")
        .eq("slug", "ai-trading-app")
        .maybeSingle();
      if (membershipError) {
        setMessage(membershipError.message);
        setState("error");
        return;
      }
      if (!app) {
        setState("pending");
        return;
      }
      const { data: recovery, error: recoveryError } = await supabase
        .from("trading_account_recovery")
        .select("completed_at")
        .eq("user_id", session.user.id)
        .maybeSingle();
      if (recoveryError) {
        setMessage(recoveryError.message);
        setState("error");
        return;
      }
      // Only an operator can mark recovery complete after restoring the old
      // account data, exchange credentials, MFA and worker identity mapping.
      setState(recovery?.completed_at ? "ready" : "recovery");
      return;
    }
    const { data: access, error: accessError } = await supabase
      .from("user_access")
      .select("approved,rejected")
      .eq("user_id", session.user.id)
      .maybeSingle();

    if (accessError) {
      setMessage(accessError.message);
      setState("error");
      return;
    }
    if (access?.rejected) setState("rejected");
    else setState(access?.approved ? "ready" : "pending");
  }, []);

  useEffect(() => {
    void refresh();
    const { data } = supabase.auth.onAuthStateChange(() => window.setTimeout(() => void refresh(), 0));
    return () => data.subscription.unsubscribe();
  }, [refresh]);

  async function signIn() {
    setMessage("");
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: window.location.origin },
    });
    if (error) setMessage(error.message);
  }

  async function signOut() {
    await supabase.auth.signOut();
    setState("signed-out");
  }

  if (state === "ready") return isCompassInternalAuth
    ? <MfaGate><ExchangeOnboarding>{children}</ExchangeOnboarding></MfaGate>
    : <ExchangeOnboarding>{children}</ExchangeOnboarding>;
  if (state === "recovery" && reconnect) return <MfaGate><ExchangeOnboarding>
    <main className="gate-shell"><section className="gate-card"><h1>Binance-kobling lagret</h1><p>Serveren må kontrollere kontoen før dashboardet åpnes. Handel er fortsatt avslått.</p><button className="primary" onClick={() => { setReconnect(false); void refresh(); }}>Sjekk status</button></section></main>
  </ExchangeOnboarding></MfaGate>;

  return <main className="gate-shell"><section className="gate-card">
    <p className="eyebrow">AI TRADING APP</p>
    {state === "recovery" ? <>
      <h1>Innlogget</h1>
      <p className="muted">Tilgangen til {email || "Google-kontoen din"} er bekreftet.</p>
      <p className="muted">Tidligere handelsdata og Binance-kobling må gjenopprettes før dashboardet kan åpnes. Innloggingen starter ingen nye handler.</p>
      <div className="gate-actions"><button className="secondary" onClick={() => void signOut()}>Logg ut</button><button className="primary" onClick={() => void refresh()}>Sjekk igjen</button></div>
      <button className="secondary" style={{ marginTop: 12 }} onClick={() => setReconnect(true)}>Koble Binance på nytt</button>
    </> : state === "pending" ? <>
      <h1>Venter på godkjenning</h1>
      <p className="muted">{email || "Denne Google-kontoen"} er registrert. Administrator må godkjenne brukeren før Binance-oppsett og trading blir tilgjengelig.</p>
      <div className="gate-actions"><button className="secondary" onClick={() => void signOut()}>Logg ut</button><button className="primary" onClick={() => void refresh()}>Sjekk igjen</button></div>
    </> : state === "rejected" ? <>
      <h1>Tilgang avslått</h1>
      <p className="muted">{email || "Denne Google-kontoen"} er ikke godkjent for bruk av AI Trading App.</p>
      <div className="gate-actions"><button className="secondary" onClick={() => void signOut()}>Logg ut</button></div>
    </> : <>
      <h1>Logg inn</h1>
      {state === "loading" && <p className="muted">Kontrollerer innlogging …</p>}
      {state === "signed-out" && <><p className="muted">Logg inn med Google. Hver bruker får sitt eget separate dashboard og sin egen Binance-konto.</p><button className="primary" onClick={() => void signIn()}>Fortsett med Google</button></>}
      {state === "error" && <button className="primary" onClick={() => void refresh()}>Prøv igjen</button>}
    </>}
    {message && <p className="gate-error" role="alert">{message}</p>}
  </section></main>;
}
