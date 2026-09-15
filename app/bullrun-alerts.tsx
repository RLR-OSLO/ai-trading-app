"use client";
import { useEffect, useRef, useState } from "react";
import { supabase } from "../lib/supabase";
type Alert = { id: number; message: string; created_at: string };
export default function BullrunAlerts() {
  const [alerts,setAlerts]=useState<Alert[]>([]);
  const [enabled,setEnabled]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const userId=useRef("");
  const enabledRef=useRef(false);
  const seen=useRef<number | null>(null);
  useEffect(()=>{
    let stopped=false, running=false;
    async function poll() {
      if(running) return;
      running=true;
      try {
        if(!userId.current) {
          const {data}=await supabase.auth.getUser();
          if(!data.user) return;
          userId.current=data.user.id;
          try { enabledRef.current=localStorage.getItem(`bullrun-notify:${userId.current}`)==="on"; setEnabled(enabledRef.current); } catch { /* Notifications still work for this session. */ }
        }
        const {data,error}=await supabase.from("bot_events").select("id,message,created_at").eq("event_type","bullrun_alert").order("id",{ascending:false}).limit(20);
        if(error) throw error;
        if(stopped) return;
        const rows=data ?? [];
        const latest=rows[0]?.id ?? 0;
        if(seen.current!==null && enabledRef.current && "Notification" in window && Notification.permission==="granted") {
          const fresh=rows.filter(row=>row.id>seen.current! && Date.now()-Date.parse(row.created_at)<120000);
          if(fresh.length) {
            const coins=fresh.map(row=>row.message.replace("symbol=","")).join(", ");
            try { new Notification("Bullrun-signal",{body:coins+" – åpne appen for signal og vetoer.",tag:"ai-trading-bullrun"}); } catch { setNotice("Nettleservarsel støttes ikke her. Varslene vises i appen."); }
          }
        }
        seen.current=latest; setAlerts(rows); setError("");
      } catch { if(!stopped) setError("Kunne ikke hente bullrun-varsler. Prøver igjen automatisk."); }
      finally { running=false; }
    }
    void poll(); const timer=setInterval(()=>void poll(),15000);
    return ()=>{ stopped=true; clearInterval(timer); };
  },[]);
  async function notifications() {
    if(!("Notification" in window)) {setNotice("Bruk varslene i appen; denne nettleseren støtter ikke nettleservarsler.");return;}
    let next=false;
    if(!enabled) next=(await Notification.requestPermission())==="granted";
    enabledRef.current=next;setEnabled(next);
    try {localStorage.setItem(`bullrun-notify:${userId.current}`,next?"on":"off");} catch { /* Session-only preference. */ }
    setNotice(next?"Varsler er på mens appen er åpen.":Notification.permission==="denied"?"Varsler er blokkert i nettleseren. Du kan tillate dem i nettstedsinnstillingene.":"Nettleservarsler er av.");
  }
  const latest=alerts[0];
  const fresh=latest && Date.now()-Date.parse(latest.created_at)<120000;
  return <section className={`panel bullrun-panel ${fresh?"bullrun-active":""}`}><div className="panel-head"><div><p className="eyebrow">MARKEDSVARSEL</p><h3>Bullrun alert</h3></div><button type="button" className="secondary compact" onClick={()=>void notifications()}>{enabled?"Slå av nettleservarsler":"Aktiver nettleservarsler"}</button></div>
    <p className="muted">Varsler når boten finner et bullrun-signal i markedene den analyserer med dine innstillinger. Ett varsel per valuta per 30 minutter. Et signal betyr ikke at en ordre er lagt inn.</p>
    <p role="status">{latest?`${fresh?"Nytt signal":"Siste signal"}: ${latest.message.replace("symbol=","")} · ${new Date(latest.created_at).toLocaleString("nb-NO")}`:"Ingen bullrun-signaler registrert ennå."}</p>
    {alerts.length>1 && <details><summary>Tidligere varsler ({alerts.length})</summary><ul>{alerts.slice(1).map(row=><li key={row.id}>{row.message.replace("symbol=","")} · {new Date(row.created_at).toLocaleString("nb-NO")}</li>)}</ul></details>}
    <small>Nettleservarsler krever at appen er åpen. Historikken lagres også når appen er lukket.</small>
    {notice && <p role="status">{notice}</p>}{error && <p role="alert" className="loss">{error}</p>}
  </section>;
}
