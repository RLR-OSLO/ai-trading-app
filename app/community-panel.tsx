"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { supabase } from "../lib/supabase";

type Item = { id: number; user_id: string; author_name: string; body: string; created_at: string; done?: boolean };
const fields = "id,user_id,author_name,body,created_at";
const ideaFields = "id,user_id,author_name,body,created_at,done";

export default function CommunityPanel() {
  const [messages, setMessages] = useState<Item[]>([]);
  const [ideas, setIdeas] = useState<Item[]>([]);
  const [message, setMessage] = useState("");
  const [idea, setIdea] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [showDone, setShowDone] = useState(false);
  const [olderAvailable, setOlderAvailable] = useState(true);
  const log = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const inFlight = useRef(false);
  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const [chat, open] = await Promise.all([
        supabase.from("trading_chat_messages").select(fields).order("id", { ascending: false }).limit(100),
        supabase.from("trading_development_ideas").select(ideaFields).eq("done", false).order("id").range(0, 999),
      ]);
      if (chat.error || open.error) throw new Error(chat.error?.message || open.error?.message);
      setMessages(current => {
        const rows = new Map(current.map(row => [row.id, row]));
        for (const row of chat.data ?? []) rows.set(row.id, row);
        return [...rows.values()].sort((a,b) => a.id-b.id);
      });
      if ((chat.data?.length ?? 0) < 100) setOlderAvailable(false);
      const all = [...(open.data ?? [])];
      // Keep every unfinished idea visible even after the first API page.
      for (let offset=1000; all.length===offset; offset+=1000) {
        const next = await supabase.from("trading_development_ideas").select(ideaFields).eq("done", false).order("id").range(offset,offset+999);
        if (next.error) throw next.error;
        all.push(...(next.data ?? []));
      }
      if (showDone) {
        for (let offset=0;;offset+=1000) {
          const done = await supabase.from("trading_development_ideas").select(ideaFields).eq("done", true).order("id", {ascending:false}).range(offset,offset+999);
          if (done.error) throw done.error;
          all.push(...(done.data ?? []));
          if ((done.data?.length ?? 0)<1000) break;
        }
      }
      setIdeas(all); setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "Kunne ikke hente fellesområdet. Prøv igjen."); }
    finally { inFlight.current=false; }
  }, [showDone]);
  useEffect(() => { void refresh(); const timer=window.setInterval(()=>{ if (!document.hidden) void refresh(); },5000); return ()=>window.clearInterval(timer); }, [refresh]);
  useEffect(() => { if (nearBottom.current && log.current) log.current.scrollTop=log.current.scrollHeight; }, [messages]);
  async function add(kind: "chat" | "idea") {
    const body=(kind==="chat"?message:idea).trim();
    if (!body || busy) return;
    setBusy(kind); setError("");
    try {
      const result=await supabase.from(kind==="chat"?"trading_chat_messages":"trading_development_ideas").insert({body});
      if (result.error) setError(result.error.message);
      else { if(kind==="chat") { setMessage(""); nearBottom.current=true; } else setIdea(""); await refresh(); }
    } catch { setError("Kunne ikke sende. Teksten er beholdt; prøv igjen."); }
    finally { setBusy(""); }
  }
  async function toggle(item: Item) {
    setBusy(String(item.id));
    try {
      const result=await supabase.from("trading_development_ideas").update({done:!item.done}).eq("id",item.id).select("id").single();
      if(result.error) setError(result.error.message); else await refresh();
    } catch { setError("Kunne ikke lagre avhukingen. Prøv igjen."); }
    finally { setBusy(""); }
  }
  async function older() {
    if(!messages.length) return;
    setBusy("older");
    try {
      const result=await supabase.from("trading_chat_messages").select(fields).lt("id",messages[0].id).order("id",{ascending:false}).limit(100);
      if(result.error) setError(result.error.message);
      else { nearBottom.current=false; setMessages(current=>[...(result.data ?? []).reverse(),...current]); setOlderAvailable(result.data.length===100); }
    } catch { setError("Kunne ikke hente eldre meldinger. Prøv igjen."); }
    finally { setBusy(""); }
  }
  return <div className="community-grid" id="fellesskap">
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">FELLES FOR GODKJENTE BRUKERE</p><h3>Brukerchat</h3></div><small>Oppdateres hvert 5. sekund</small></div>
      {olderAvailable && messages.length>0 && <button className="secondary compact" disabled={!!busy} onClick={()=>void older()}>Vis eldre meldinger</button>}
      <div className="community-chat" ref={log} onScroll={()=>{ if(log.current) nearBottom.current=log.current.scrollHeight-log.current.scrollTop-log.current.clientHeight<60; }} role="log" aria-label="Felles brukerchat">
        {messages.length===0 && <p className="muted">Ingen meldinger ennå. Start samtalen.</p>}
        {messages.map(row=><article key={row.id}><div><strong>{row.author_name}</strong><time>{new Date(row.created_at).toLocaleString("nb-NO")}</time></div><p>{row.body}</p></article>)}
      </div>
      <form className="community-form" onSubmit={e=>{e.preventDefault();void add("chat");}}><textarea aria-label="Melding til brukerne" placeholder="Skriv til de andre brukerne …" maxLength={2000} value={message} onChange={e=>setMessage(e.target.value)} rows={2}/><button className="primary" disabled={!!busy || !message.trim()}>Send melding</button></form>
    </section>
    <section className="panel"><div className="panel-head"><div><p className="eyebrow">IDEER OG FORBEDRINGER</p><h3>Utviklingsliste</h3></div><label className="community-check"><input type="checkbox" checked={showDone} onChange={e=>setShowDone(e.target.checked)}/>Vis utførte</label></div>
      <p className="muted">Felles liste. Punktene blir stående til noen huker dem av. Utførte punkter kan åpnes igjen.</p>
      <ul className="development-list">{ideas.map(row=><li key={row.id} className={row.done?"done":""}><label><input type="checkbox" checked={!!row.done} disabled={!!busy} onChange={()=>void toggle(row)}/><span>{row.body}<small>Lagt til av {row.author_name}</small></span></label></li>)}</ul>
      {ideas.length===0 && <p className="muted">Ingen åpne punkter.</p>}
      <form className="community-form" onSubmit={e=>{e.preventDefault();void add("idea");}}><textarea aria-label="Ny utviklingsidé" placeholder="Legg til en idé eller oppgave …" value={idea} maxLength={1000} rows={2} onChange={e=>setIdea(e.target.value)}/><button className="primary" disabled={!!busy || !idea.trim()}>Legg til punkt</button></form>
    </section>
    {error && <p role="alert" className="loss">{error}</p>}
  </div>;
}
