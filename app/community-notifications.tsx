"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { supabase } from "../lib/supabase";
type Activity = { id: number; actor_name: string; kind: "chat" | "idea_created" | "idea_completed" | "idea_reopened"; item_id: number; preview: string; created_at: string; total_unread: number };
const labels = {chat:"skrev i chatten",idea_created:"la til en oppgave",idea_completed:"fullførte en oppgave",idea_reopened:"åpnet en oppgave igjen"};

export default function CommunityNotifications() {
  const [items,setItems]=useState<Activity[]>([]);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const running=useRef(false);
  const writing=useRef(false);
  const generation=useRef(0);
  const originalTitle=useRef("");
  const details=useRef<HTMLDetailsElement>(null);
  const refresh=useCallback(async()=>{
    if(running.current || writing.current)return;
    running.current=true;
    const requestGeneration=generation.current;
    try {
      const {data,error}=await supabase.rpc("unread_community_activity");
      if(error)throw error;
      if(requestGeneration!==generation.current)return;
      setItems((data ?? []) as Activity[]);setError("");
    }catch{setError("Aktivitetsvarsler kunne ikke oppdateres. Prøver igjen automatisk.");}
    finally{running.current=false;}
  },[]);
  useEffect(()=>{
    void refresh();
    const timer=window.setInterval(()=>{if(!document.hidden)void refresh();},5000);
    const resume=()=>{if(!document.hidden)void refresh();};
    document.addEventListener("visibilitychange",resume);
    window.addEventListener("focus",resume);
    return()=>{generation.current++;window.clearInterval(timer);document.removeEventListener("visibilitychange",resume);window.removeEventListener("focus",resume);};
  },[refresh]);
  const count=Number(items[0]?.total_unread ?? 0);
  useEffect(()=>{originalTitle.current=document.title;return()=>{document.title=originalTitle.current;};},[]);
  useEffect(()=>{if(originalTitle.current)document.title=count?`(${count}) ${originalTitle.current}`:originalTitle.current;},[count]);
  async function markRead() {
    if(busy)return;
    setBusy(true);writing.current=true;generation.current++;
    const ids=items.map(item=>item.id);
    try {
      const {error}=await supabase.rpc("mark_community_activity_read",{p_ids:ids});
      if(error)throw error;
      setItems(current=>current.filter(item=>!ids.includes(item.id)));
    }catch{setError("Kunne ikke markere varslene som lest. Prøv igjen.");}
    finally{writing.current=false;setBusy(false);void refresh();}
  }
  function goToCommunity() {
    if(details.current)details.current.open=false;
    window.dispatchEvent(new Event("community:open-activity"));
    document.getElementById("fellesskap")?.scrollIntoView({behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"start"});
    document.getElementById("fellesskap")?.focus({preventScroll:true});
  }
  return <aside className={`community-notification ${count?"has-unread":""}`} aria-label="Varsler fra fellesområdet">
    <div className="community-notification-row"><div role="status" aria-live="polite" aria-atomic="true"><strong>{count?`${count} uleste hendelser i chat og oppgaver`:"Chat og oppgaver"}</strong>{count>0 && <span>{items[0].actor_name} {labels[items[0].kind]}</span>}</div><div className="community-notification-actions"><button type="button" className={count?"primary":"secondary compact"} onClick={goToCommunity}>{count?"Se chat og oppgaver ↓":"Gå til fellesområdet ↓"}</button>{count>0 && <button type="button" className="secondary compact" disabled={busy} onClick={()=>void markRead()}>{busy?"Lagrer …":count>50?"Marker disse 50 som lest":"Marker som lest"}</button>}</div></div>
    {count>0 && <details ref={details} className="community-notification-details"><summary>Vis {Math.min(count,50)} {count>50?"nyeste ":""}hendelser</summary><ul>{items.map(item=><li key={item.id}><strong>{item.actor_name}</strong> {labels[item.kind]}<p>{item.preview}</p><time>{new Date(item.created_at).toLocaleString("nb-NO")}</time></li>)}</ul></details>}
    {error && <p role="alert">{error}</p>}
  </aside>;
}
