"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "../lib/supabase";
import ExchangeOnboarding from "./exchange-onboarding";

type GateState = "loading" | "signed-out" | "pending" | "rejected" | "ready" | "error";

export default function AuthGate({ children }: Readonly<{ children: React.ReactNode }>) {
  const [state, setState] = useState<GateState>("loading");
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");

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

  if (state === "ready") return <ExchangeOnboarding>{children}</ExchangeOnboarding>;

  return <main className="gate-shell"><section className="gate-card">
    <p className="eyebrow">AI TRADING APP</p>
    {state === "pending" ? <>
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
