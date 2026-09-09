"use client";

import { useState } from "react";
import { supabase } from "../lib/supabase";

export default function LogoutButton() {
  const [busy, setBusy] = useState(false);

  async function logout() {
    setBusy(true);
    await supabase.auth.signOut();
    window.location.assign("/");
  }

  return <button className="secondary" type="button" onClick={() => void logout()} disabled={busy}>
    {busy ? "Logger ut …" : "Logg ut"}
  </button>;
}
