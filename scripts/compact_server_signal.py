from pathlib import Path

p = Path('app/trading-dashboard.tsx')
t = p.read_text(encoding='utf-8')

state_old = '  const [chatInput, setChatInput] = useState("");\n'
state_new = '  const [chatInput, setChatInput] = useState("");\n  const [serverSignalExpanded, setServerSignalExpanded] = useState(false);\n'
if state_old not in t:
    raise SystemExit('chatInput state marker not found')
t = t.replace(state_old, state_new, 1)

old = '''    <section className="panel"><div className="panel-head"><div><p className="eyebrow">SERVERSTATUS</p><h3>Siste kontrollsignal</h3></div>{lastEvent && <time className="muted">{new Date(lastEvent.created_at).toLocaleString("nb-NO")}</time>}</div><p className={`server-signal ${lastEvent?.level === "error" ? "loss" : "muted"}`}>{lastEvent?.message ?? "Serverrapportering er ikke koblet til ennå."}</p></section>'''
new = '''    <section className="panel"><div className="panel-head"><div><p className="eyebrow">SERVERSTATUS</p><h3>Siste kontrollsignal</h3></div><div className="server-signal-actions">{lastEvent && <time className="muted">{new Date(lastEvent.created_at).toLocaleString("nb-NO")}</time>}<button type="button" className="secondary compact" onClick={() => setServerSignalExpanded((value) => !value)}>{serverSignalExpanded ? "Skjul" : "Utvid"}</button></div></div><p className={`server-signal ${serverSignalExpanded ? "expanded" : "collapsed"} ${lastEvent?.level === "error" ? "loss" : "muted"}`}>{lastEvent?.message ?? "Serverrapportering er ikke koblet til ennå."}</p></section>'''
if old not in t:
    raise SystemExit('server signal section not found')
t = t.replace(old, new, 1)
p.write_text(t, encoding='utf-8')

p = Path('app/globals.css')
css = p.read_text(encoding='utf-8')
append = '\n.server-signal.collapsed{max-height:3.2em;overflow:hidden}.server-signal.expanded{max-height:none}.server-signal-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end}.secondary.compact{padding:8px 12px}@media(max-width:520px){.server-signal-actions{justify-content:flex-start}}\n'
if '.server-signal.collapsed{' not in css:
    css += append
p.write_text(css, encoding='utf-8')
