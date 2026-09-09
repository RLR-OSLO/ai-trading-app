"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "../lib/supabase";
import ExchangeOnboarding from "./exchange-onboarding";

type GateState = "loading" | "signed-out" | "ready" | "error";

export default function AuthGate({ children }: Readonly<{ children: React.ReactNode }>) {
  const [state, setState] = useState<GateState>("loading");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    setState("loading");
    const { data, error } = await supabase.auth.getSession();
    if (error) {
      setMessage(error.message);
      setState("error");
      return;
    }
    setState(data.session ? "ready" : "signed-out");
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

  if (state === "ready") return <ExchangeOnboarding>{children}</ExchangeOnboarding>;

  return <main className="gate-shell"><section className="gate-card">
    <p className="eyebrow">AI TRADING APP</p><h1>Logg inn</h1>
    {state === "loading" && <p className="muted">Kontrollerer innlogging …</p>}
    {state === "signed-out" && <><p className="muted">Logg inn med Google. Hver bruker får sitt eget separate dashboard og sin egen Binance-konto.</p><button className="primary" onClick={() => void signIn()}>Fortsett med Google</button></>}
    {state === "error" && <button className="primary" onClick={() => void refresh()}>Prøv igjen</button>}
    {message && <p className="gate-error" role="alert">{message}</p>}
  </section></main>;
}
