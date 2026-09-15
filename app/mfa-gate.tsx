"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "../lib/supabase";
import LogoutButton from "./logout-button";

export default function MfaGate({ children }: Readonly<{ children: React.ReactNode }>) {
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [factors, setFactors] = useState<{ id: string; friendly_name?: string }[]>([]);
  const [factorId, setFactorId] = useState("");
  const [qr, setQr] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    const { data, error: levelError } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
    if (levelError) { setError(levelError.message); setLoading(false); return; }
    if (data.currentLevel === "aal2") { setReady(true); setLoading(false); return; }
    const { data: listed, error: listError } = await supabase.auth.mfa.listFactors();
    if (listError) { setError(listError.message); setLoading(false); return; }
    const verified = listed.totp.filter((factor) => factor.status === "verified");
    setFactors(verified); setFactorId(verified[0]?.id ?? ""); setLoading(false);
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  async function enroll() {
    setBusy(true); setError("");
    const { data, error: enrollError } = await supabase.auth.mfa.enroll({ factorType: "totp", friendlyName: `AI Trading ${new Date().toISOString()}` });
    if (enrollError) setError(enrollError.message);
    else {
      setFactorId(data.id);
      setQr(data.totp.qr_code.startsWith("data:") ? data.totp.qr_code : `data:image/svg+xml;charset=utf-8,${encodeURIComponent(data.totp.qr_code)}`);
    }
    setBusy(false);
  }
  async function verify() {
    setBusy(true); setError("");
    const { error: verifyError } = await supabase.auth.mfa.challengeAndVerify({ factorId, code });
    setCode("");
    if (verifyError) setError(verifyError.message);
    else { setQr(""); await refresh(); }
    setBusy(false);
  }
  if (ready) return <>{children}</>;
  return <main className="gate-shell"><section className="gate-card" style={{ width: "min(560px, 100%)", padding: "clamp(16px, 4vw, 32px)" }}>
    <p className="eyebrow">AI TRADING APP</p><h1>Tofaktorbekreftelse</h1>
    {loading ? <p>Kontrollerer sikker innlogging …</p> : <>
      {!factorId && <><p>Koble Google Authenticator til innloggingen i Compass Internal. Oppsettet fra det tidligere prosjektet er ikke overført.</p><button className="primary" disabled={busy} onClick={() => void enroll()}>Koble Google Authenticator</button></>}
      {qr && <><p>Skann QR-koden med Google Authenticator og skriv inn den sekssifrede koden.</p><img src={qr} alt="QR-kode for tofaktoroppsett" width={400} height={400} style={{ display: "block", width: "100%", maxWidth: 400, height: "auto", margin: "24px auto", padding: 24, background: "#fff", imageRendering: "pixelated" }} /></>}
      {factorId && <form onSubmit={(event) => { event.preventDefault(); void verify(); }}>
        {factors.length > 1 && <label>Velg autentikator<select value={factorId} onChange={(event) => setFactorId(event.target.value)}>{factors.map((factor) => <option value={factor.id} key={factor.id}>{factor.friendly_name || "Autentikator"}</option>)}</select></label>}
        <label htmlFor="mfa-code">Kode fra Google Authenticator</label>
        <input id="mfa-code" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))} required />
        <button className="primary" disabled={busy || code.length !== 6}>Bekreft og fortsett</button>
      </form>}
    </>}
    {error && <p className="gate-error" role="alert">{error}</p>}
    <div style={{ marginTop: 16 }}><LogoutButton /></div>
  </section></main>;
}
