"use client";

import { useCallback, useEffect, useState } from "react";
import { supabase } from "../lib/supabase";

type AccessRow = {
  user_id: string;
  email: string;
  approved: boolean;
  rejected: boolean;
  is_admin: boolean;
  created_at: string;
};

export default function AdminUsers() {
  const [isAdmin, setIsAdmin] = useState(false);
  const [rows, setRows] = useState<AccessRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setMessage("");
    const { data: userData } = await supabase.auth.getUser();
    const userId = userData.user?.id;
    if (!userId) { setLoading(false); return; }

    const { data: ownAccess } = await supabase
      .from("user_access")
      .select("is_admin")
      .eq("user_id", userId)
      .maybeSingle();
    if (!ownAccess?.is_admin) { setIsAdmin(false); setLoading(false); return; }

    setIsAdmin(true);
    const { data, error } = await supabase
      .from("user_access")
      .select("user_id,email,approved,rejected,is_admin,created_at")
      .eq("is_admin", false)
      .eq("rejected", false)
      .order("created_at", { ascending: false });
    if (error) setMessage(error.message);
    else setRows((data ?? []) as AccessRow[]);
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function approve(row: AccessRow) {
    setBusy(row.user_id);
    setMessage("");
    const { data: userData } = await supabase.auth.getUser();
    const adminId = userData.user?.id;
    if (!adminId) { setMessage("Fant ikke innlogget administrator."); setBusy(null); return; }
    const { error } = await supabase
      .from("user_access")
      .update({ approved: true, rejected: false, approved_at: new Date().toISOString(), approved_by: adminId, rejected_at: null, rejected_by: null })
      .eq("user_id", row.user_id);
    if (error) setMessage(error.message);
    else {
      setRows((current) => current.map((item) => item.user_id === row.user_id ? { ...item, approved: true, rejected: false } : item));
      setMessage(`${row.email} er godkjent.`);
    }
    setBusy(null);
  }

  async function reject(row: AccessRow) {
    setBusy(row.user_id);
    setMessage("");
    const { data: userData } = await supabase.auth.getUser();
    const adminId = userData.user?.id;
    if (!adminId) { setMessage("Fant ikke innlogget administrator."); setBusy(null); return; }
    const { error } = await supabase
      .from("user_access")
      .update({ approved: false, rejected: true, rejected_at: new Date().toISOString(), rejected_by: adminId, approved_at: null, approved_by: null })
      .eq("user_id", row.user_id);
    if (error) setMessage(error.message);
    else {
      setRows((current) => current.filter((item) => item.user_id !== row.user_id));
      setMessage(`${row.email} er avslått og fjernet fra oversikten.`);
    }
    setBusy(null);
  }

  if (!loading && !isAdmin) return null;
  if (!isAdmin) return null;

  return <section className="panel admin-users-panel">
    <div className="panel-head">
      <div><p className="eyebrow">ADMIN</p><h3>Brukere</h3></div>
      <span className="muted">Nye brukere må godkjennes før de får tilgang til Binance-oppsett og trading.</span>
    </div>
    {loading ? <p className="muted">Henter brukere …</p> : rows.length === 0 ? <p className="muted">Ingen ventende/godkjente brukere.</p> : <div className="admin-user-list">
      {rows.map((row) => <div className="admin-user-row" key={row.user_id}>
        <span className="admin-user-email">{row.email}</span>
        <div className="admin-user-actions">
          {row.approved ? <span className="approved-badge">GODKJENT</span> : <>
            <button className="primary compact" disabled={busy === row.user_id} onClick={() => void approve(row)}>Godkjenn</button>
            <button className="danger compact" disabled={busy === row.user_id} onClick={() => void reject(row)}>Avslå</button>
          </>}
        </div>
      </div>)}
    </div>}
    {message && <p className="muted admin-message">{message}</p>}
  </section>;
}
