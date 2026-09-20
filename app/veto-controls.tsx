"use client";
import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";
export type Heartbeat = { message: string; created_at: string } | null;
const rules = [
  {key:"ignore_rsi_high_veto",name:"rsi_high",label:"Høy RSI",description:"Spot ≥ 75 · short ≥ 70 · scalp (1 min) ≥ 82"},
  {key:"ignore_rsi_low_veto",name:"rsi_low",label:"Lav RSI",description:"Spot ≤ 35 · short ≤ 25"},
  {key:"ignore_atr_veto",name:"atr",label:"1-times ATR > 8 %",description:"Høy volatilitet"},
] as const;
type Options = Record<typeof rules[number]["key"],boolean>;
const defaults:Options={ignore_rsi_high_veto:false,ignore_rsi_low_veto:false,ignore_atr_veto:false};
export function heartbeatValue(event:Heartbeat,name:string) {return event?.message.match(new RegExp(`(?:^|;)${name}=([^;]+)`))?.[1] ?? "";}
function fresh(event:Heartbeat) { return !!event && Date.now()-Date.parse(event.created_at)<180000; }
export function VetoIndicators({symbol,event,direction="LONG"}:{symbol:string;event:Heartbeat;direction?:string}) {
  const raw=heartbeatValue(event,"indicators").split(",").find(row=>row.split(":")[0]===symbol);
  if(!raw || !fresh(event)) return <div className="veto-indicators muted"><strong>{direction==="SHORT"?"Short-vetoer":"Long-vetoer"}</strong><div>RSI 1t: – · grenser {direction==="SHORT"?"≤ 25 / ≥ 70":"≤ 35 / ≥ 75"}</div><div>ATR 1t: – · grense &gt; 8 %</div><small>{!fresh(event)?"Venter på ferske analysedata":"Ikke analysert i siste runde"}</small></div>;
  const [,r,a]=raw.split(":"); const rsi=Number(r),atr=Number(a);
  if(!r || !a || !Number.isFinite(rsi) || !Number.isFinite(atr)) return <div className="veto-indicators muted">RSI / ATR 1t: måledata mangler</div>;
  const supported = direction !== "SHORT" || heartbeatValue(event,"veto_controls") === "v2";
  const ignored=supported ? heartbeatValue(event,"veto_ignored").split(",") : [];

  return <div className="veto-indicators"><strong>{direction === "SHORT" ? "Short" : "Long"}-vetoer · RSI 1t {rsi.toFixed(1)}</strong>{!supported && <small>Short-overstyring venter på serveroppdatering.</small>}{rules.map(rule=>{
    const triggered=rule.name==="rsi_high"?rsi>=(direction==="SHORT"?70:75):rule.name==="rsi_low"?rsi<=(direction==="SHORT"?25:35):atr>8;
    const bypass=ignored.includes(rule.name);
    return <div key={rule.key} className={triggered && !bypass?"loss":bypass?"veto-ignored":"muted"}><span>{rule.name==="rsi_high" ? `RSI ≥ ${direction==="SHORT"?70:75}` : rule.name==="rsi_low" ? `RSI ≤ ${direction==="SHORT"?25:35}` : rule.label}{rule.name==="atr"?` · nå ${atr.toFixed(2)} %`:""}</span><b>{bypass?(triggered?"Utløst · ignorert":"Ignorert"):triggered?"Blokkerer":"OK"}</b></div>;
  })}</div>;
}
export default function VetoControls({event}:{event:Heartbeat}) {
  const [values,setValues]=useState<Options>(defaults);
  const [saved,setSaved]=useState<Options>(defaults);
  const [ready,setReady]=useState(false);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("");
  const [userId,setUserId]=useState("");
  useEffect(()=>{let alive=true;void(async()=>{
    const {data:user}=await supabase.auth.getUser();if(!user.user)return;
    const {data,error}=await supabase.from("bot_settings").select("ignore_rsi_high_veto,ignore_rsi_low_veto,ignore_atr_veto").eq("user_id",user.user.id).single();
    if(!alive)return;
    if(error)setMessage(error.message);else {setUserId(user.user.id);setValues(data);setSaved(data);setReady(true);}
  })();return()=>{alive=false;};},[]);
  async function save() {
    setBusy(true);setMessage("");
    try {
      const {data,error}=await supabase.from("bot_settings").update(values).eq("user_id",userId).select("ignore_rsi_high_veto,ignore_rsi_low_veto,ignore_atr_veto").single();
      if(error)throw error;
      setSaved(data);setMessage("Lagret. Gjelder fra serverens neste analyserunde.");
    } catch(e) {setMessage(e instanceof Error?e.message:"Kunne ikke lagre veto-valgene.");}
    finally{setBusy(false);}
  }
  const supports=heartbeatValue(event,"veto_controls")==="v2";
  const applied=heartbeatValue(event,"veto_ignored").split(",");
  const pending=rules.some(rule=>saved[rule.key]!==applied.includes(rule.name));
  return <section className="panel"><div className="panel-head"><div><p className="eyebrow">DINE SIGNALREGLER</p><h3>Velg hvilke vetoer boten skal bruke</h3></div></div>
    <p className="muted">Avhuking betyr «se bort fra dette vetoet» for dine long- og short-innganger. Høy RSI kan også overstyres i scalp. Valgene gjelder bare din konto. Overstyring kan gi flere innganger i overkjøpte, fallende eller svært volatile markeder.</p>
    <div className="veto-options">{rules.map(rule=><label key={rule.key}><input type="checkbox" checked={values[rule.key]} disabled={!ready || busy} onChange={e=>setValues(current=>({...current,[rule.key]:e.target.checked}))}/><span>Ignorer {rule.label}<small>{rule.description}</small></span></label>)}</div>
    <p className="muted">Bullrun krever fortsatt blant annet volum og ATR mellom 0,35 og 6 %. Short har egne RSI-grenser, men følger de samme avhukingene. Scalp beholder krav til trend og maksimal prisbevegelse. Stop-loss, tapsgrense, kapitalgrense og maksimal posisjonsmengde gjelder fortsatt.</p>
    <button className="primary" disabled={!ready || busy} onClick={()=>void save()}>{busy?"Lagrer …":"Lagre veto-valg"}</button>
    <p role="status">{!supports?"Serveroppdatering gjenstår før veto-valgene og måleverdiene kan tas i bruk.":!fresh(event)?"Serverrapporten er gammel. Venter på bekreftelse.":pending?"Lagret valg venter på bekreftelse fra serveren.":"Serveren bruker de lagrede veto-valgene."}</p>
    {message && <p role="status">{message}</p>}
  </section>;
}
