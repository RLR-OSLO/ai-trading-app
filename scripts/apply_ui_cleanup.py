from pathlib import Path

p = Path('app/trading-dashboard.tsx')
t = p.read_text(encoding='utf-8')

t = t.replace(
'''<div className="emergency-stop-box"><button className="danger" onClick={() => void emergencyStop()} disabled={saving}>Nødstopp</button><small>Nødstopp blokkerer nye kjøp. Åpne posisjoner blir ikke dumpet umiddelbart; boten fortsetter å overvåke dem og kan selge ved stop-loss, trailing-stop eller annen aktiv exitregel. Start live igjen for å tillate nye kjøp.</small></div>''',
'''<div className="emergency-stop-box"><button className="danger" onClick={() => void emergencyStop()} disabled={saving}>Nødstopp</button><small>Nødstopp blokkerer nye kjøp. Åpne posisjoner blir ikke dumpet umiddelbart; boten fortsetter å overvåke dem og kan selge ved stop-loss, trailing-stop eller annen aktiv exitregel. Start live igjen for å tillate nye kjøp.</small></div>''')

t = t.replace(
'''{ id: 1, role: "bot", text: "Hei, sjef. Spør meg om status, resultat, siste handel eller hvorfor jeg ikke har handlet. Du kan også skrive «pause botten»." },''',
'''{ id: 1, role: "bot", text: "Jeg leser ferske data fra tradingmotoren. Spør for eksempel: «Hva er status?», «Hvorfor handler du ikke?», «Hva er siste handel?», «Hvordan går resultatet?» eller «Hvilket marked er sterkest nå?»." },''')

t = t.replace(
'''<section className="panel chat-panel"><div className="panel-head"><div><p className="eyebrow">SNAKK MED BOTTEN</p><h3>Du er sjefen</h3></div><span className="muted">Leser ferske kontrolldata</span></div>''',
'''<section className="panel chat-panel"><div className="panel-head"><div><p className="eyebrow">TRADINGASSISTENT</p><h3>Spør om det boten faktisk gjør</h3></div><span className="muted">Basert på ferske Binance- og botdata</span></div>''')

t = t.replace(
'''<form className="chat-form" onSubmit={(event) => { event.preventDefault(); void sendChat(); }}><input aria-label="Skriv til botten" value={chatInput} onChange={(event) => setChatInput(event.target.value)} placeholder="F.eks. «Hva er status?»" /><button className="primary" type="submit">Send</button></form>\n      <p className="chat-note">Chatten kan lese status og pause botten. Direkte ordre fra fritekst er sperret.</p>''',
'''<div className="chat-suggestions"><span>Prøv:</span><button type="button" onClick={() => setChatInput("Hva er status?")}>Status</button><button type="button" onClick={() => setChatInput("Hvorfor handler du ikke?")}>Hvorfor ingen handel?</button><button type="button" onClick={() => setChatInput("Hva er siste handel?")}>Siste handel</button><button type="button" onClick={() => setChatInput("Hvordan går resultatet?")}>Resultat</button></div>\n      <form className="chat-form" onSubmit={(event) => { event.preventDefault(); void sendChat(); }}><input aria-label="Skriv til botten" value={chatInput} onChange={(event) => setChatInput(event.target.value)} placeholder="Spør om status, handler, signaler, risiko eller resultat …" /><button className="primary" type="submit">Send</button></form>\n      <p className="chat-note">Dette er en lokal tradingassistent uten ekstra AI-kostnad. Den svarer ut fra ferske botdata og kan pause boten. Direkte ordre fra fritekst er sperret.</p>''')

p.write_text(t, encoding='utf-8')

css = Path('app/globals.css')
c = css.read_text(encoding='utf-8')
extra = '''\n.emergency-stop-box{margin-left:auto;display:flex;flex-direction:column;align-items:flex-end;max-width:360px;text-align:right;gap:10px}.emergency-stop-box small{display:block;line-height:1.45;color:var(--muted)}.emergency-stop-box .danger{align-self:flex-end}.chat-suggestions{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 14px;color:var(--muted);font-size:12px}.chat-suggestions button{padding:8px 10px;border:1px solid #38506c;background:#0b1827;color:var(--text);font-size:12px}.chat-suggestions button:hover{border-color:#5c7898}@media(max-width:820px){.emergency-stop-box{margin-left:0;align-items:flex-start;text-align:left;max-width:none}.emergency-stop-box .danger{align-self:flex-start}}\n'''
if '.emergency-stop-box{margin-left:auto;' not in c:
    c += extra
css.write_text(c, encoding='utf-8')
