"use client";

import Image from "next/image";
import { useCallback, useEffect, useState } from "react";
import { supabase } from "../lib/supabase";

type GateState = "loading" | "signed-out" | "enroll" | "verify" | "ready" | "error";

export default function AuthGate({ children }: Readonly<{ children: React.ReactNode }>) {
  const [state, setState] = useState<GateState>("loading");
  const [factorId, setFactorId] = useState("");
  const [challengeId, setChallengeId] = useState("");
  const [qrCode, setQrCode] = useState("");
  const [code, setCode] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    setState("loading");
    const { data: sessionData } = await supabase.auth.getSession();
    if (!sessionData.session) {
      setState("signed-out");
      return;
    }

    const { data: aal, error: aalError } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
    if (aalError) {
      setMessage(aalError.message);
      setState("error");
      return;
    }
    if (aal.currentLevel === "aal2") {
      setState("ready");
      return;
    }

    const { data: factors, error: factorsError } = await supabase.auth.mfa.listFactors();
    if (factorsError) {
      setMessage(factorsError.message);
      setState("error");
      return;
    }
    const verified = factors?.totp.find((factor) => factor.status === "verified");
    if (verified) {
      const { data, error } = await supabase.auth.mfa.challenge({ factorId: verified.id });
      if (error) {
        setMessage(error.message);
        setState("error");
        return;
      }
      setFactorId(verified.id);
      setChallengeId(data.id);
      setState("verify");
      return;
    }

    // An interrupted enrollment leaves an unverified factor behind. Supabase
    // requires friendly names to be unique, so remove stale attempts before
    // creating a fresh QR code.
    const staleFactors = factors?.all.filter(
      (factor) => factor.factor_type === "totp" && factor.status === "unverified",
    ) ?? [];
    for (const factor of staleFactors) {
      const { error } = await supabase.auth.mfa.unenroll({ factorId: factor.id });
      if (error) {
        setMessage(error.message);
        setState("error");
        return;
      }
    }

    const { data, error } = await supabase.auth.mfa.enroll({ factorType: "totp", friendlyName: "AI Trading App" });
    if (error) {
      setMessage(error.message);
      setState("error");
      return;
    }
    setFactorId(data.id);
    setQrCode(data.totp.qr_code);
    setState("enroll");
  }, []);

  useEffect(() => {
    void refresh();
    const { data } = supabase.auth.onAuthStateChange(() => window.setTimeout(() => void refresh(), 0));
    return () => data.subscription.unsubscribe();
  }, [refresh]);

  async function signIn() {
    setMessage("");
    const { error } = await supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo: window.location.origin } });
    if (error) setMessage(error.message);
  }

  async function verify() {
    setMessage("");
    let activeChallengeId = challengeId;
    if (!activeChallengeId) {
      const { data, error } = await supabase.auth.mfa.challenge({ factorId });
      if (error) { setMessage(error.message); return; }
      activeChallengeId = data.id;
      setChallengeId(data.id);
    }
    const { error } = await supabase.auth.mfa.verify({ factorId, challengeId: activeChallengeId, code: code.trim() });
    if (error) { setMessage("Koden ble ikke godkjent. Prøv en ny kode."); return; }
    setCode("");
    await refresh();
  }

  if (state === "ready") return <>{children}</>;

  return <main className="gate-shell"><section className="gate-card">
    <p className="eyebrow">AI TRADING APP</p><h1>Sikker tilgang</h1>
    {state === "loading" && <p className="muted">Kontrollerer innlogging …</p>}
    {state === "signed-out" && <><p className="muted">Logg inn med godkjent Google-konto. Deretter kreves Google Authenticator.</p><button className="primary" onClick={signIn}>Fortsett med Google</button></>}
    {state === "enroll" && <><p className="muted">Skann QR-koden i Google Authenticator og skriv inn sekssifret kode.</p>{qrCode && <Image className="qr" src={qrCode} width={220} height={220} unoptimized alt="QR-kode for Google Authenticator" />}<CodeForm code={code} setCode={setCode} verify={verify} /></>}
    {state === "verify" && <><p className="muted">Skriv inn den sekssifrede koden fra Google Authenticator.</p><CodeForm code={code} setCode={setCode} verify={verify} /></>}
    {state === "error" && <button className="primary" onClick={() => void refresh()}>Prøv igjen</button>}
    {message && <p className="gate-error" role="alert">{message}</p>}
  </section></main>;
}

function CodeForm({ code, setCode, verify }: Readonly<{ code: string; setCode: (value: string) => void; verify: () => Promise<void> }>) {
  return <form onSubmit={(event) => { event.preventDefault(); void verify(); }}>
    <label htmlFor="totp">Authenticator-kode</label>
    <input id="totp" inputMode="numeric" autoComplete="one-time-code" maxLength={6} pattern="[0-9]{6}" value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))} required />
    <button className="primary" type="submit">Bekreft kode</button>
  </form>;
}
