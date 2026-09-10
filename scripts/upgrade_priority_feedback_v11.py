from pathlib import Path

p = Path("app/trading-dashboard.tsx")
s = p.read_text()

if "type TradeDirective =" not in s:
    marker = 'type ChatMessage = { id: number; role: "boss" | "bot"; text: string };\n'
    insert = marker + 'type TradeDirective = { id: number; symbol: string; direction: "LONG" | "SHORT"; mode: "SPOT" | "MARGIN" | "FUTURES"; requested_notional: number; leverage: number; status: string; created_at: string; expires_at: string };\n'
    if marker not in s:
        raise SystemExit("marker missing: ChatMessage type")
    s = s.replace(marker, insert, 1)
    print("patched directive type")

if "const [priorityDirectives" not in s:
    marker = '  const [serverSignalExpanded, setServerSignalExpanded] = useState(false);\n'
    insert = marker + '  const [priorityDirectives, setPriorityDirectives] = useState<TradeDirective[]>([]);\n  const [priorityBusy, setPriorityBusy] = useState<number | null>(null);\n'
    if marker not in s:
        raise SystemExit("marker missing: serverSignalExpanded state")
    s = s.replace(marker, insert, 1)
    print("patched priority state")

if "async function loadPriorityDirectives()" not in s:
    marker = '  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 30_000); return () => window.clearInterval(timer); }, [load]);\n'
    insert = marker + '''\n  async function loadPriorityDirectives() {\n    const { data: userData } = await supabase.auth.getUser();\n    if (!userData.user) { setPriorityDirectives([]); return; }\n    const { data, error } = await supabase\n      .from("trade_directives")\n      .select("id,symbol,direction,mode,requested_notional,leverage,status,created_at,expires_at")\n      .eq("user_id", userData.user.id)\n      .eq("status", "pending")\n      .gt("expires_at", new Date().toISOString())\n      .order("created_at", { ascending: false });\n    if (!error) setPriorityDirectives((data ?? []) as TradeDirective[]);\n  }\n\n  useEffect(() => {\n    void loadPriorityDirectives();\n    const timer = window.setInterval(() => void loadPriorityDirectives(), 5_000);\n    return () => window.clearInterval(timer);\n  }, []);\n'''
    if marker not in s:
        raise SystemExit("marker missing: load effect")
    s = s.replace(marker, insert, 1)
    print("patched priority polling")

if "async function stopPriority(" not in s:
    marker = '  async function prioritizeSetup(setup: { symbol: string; direction: "LONG" | "SHORT" | "VENT"; mode: string; suggested: number }) {'
    insert = '''  async function stopPriority(directive: TradeDirective) {\n    setPriorityBusy(directive.id);\n    const { data: userData } = await supabase.auth.getUser();\n    if (!userData.user) { setPriorityBusy(null); return; }\n    const { error } = await supabase\n      .from("trade_directives")\n      .update({ status: "cancelled", result: "Priority stopped by user" })\n      .eq("id", directive.id)\n      .eq("user_id", userData.user.id)\n      .eq("status", "pending");\n    if (error) {\n      setMessage(`Kunne ikke stoppe prioritet: ${error.message}`);\n    } else {\n      setPriorityDirectives((current) => current.filter((item) => item.id !== directive.id));\n      setMessage(`Prioritet stoppet for ${directive.direction} ${directive.symbol}.`);\n    }\n    setPriorityBusy(null);\n  }\n\n''' + marker
    if marker not in s:
        raise SystemExit("marker missing: prioritizeSetup")
    s = s.replace(marker, insert, 1)
    print("patched stop priority")

old_insert = '''    const { error } = await supabase.from("trade_directives").insert({\n      user_id: userData.user.id,\n      symbol: setup.symbol,\n      direction: setup.direction,\n      mode: cleanMode,\n      requested_notional: Math.max(5, setup.suggested),\n      leverage: cleanMode === "FUTURES" ? Math.max(1, Math.min(3, settings.leverage)) : 1,\n    });\n    setMessage(error ? `Kunne ikke sende direktiv: ${error.message}` : `Direktiv sendt: prioriter ${setup.direction} ${setup.symbol}. Boten forsøker på neste syklus hvis signalet fortsatt er gyldig.`);'''
new_insert = '''    const { data: created, error } = await supabase.from("trade_directives").insert({\n      user_id: userData.user.id,\n      symbol: setup.symbol,\n      direction: setup.direction,\n      mode: cleanMode,\n      requested_notional: Math.max(5, setup.suggested),\n      leverage: cleanMode === "FUTURES" ? Math.max(1, Math.min(3, settings.leverage)) : 1,\n    }).select("id,symbol,direction,mode,requested_notional,leverage,status,created_at,expires_at").single();\n    if (error) {\n      setMessage(`Kunne ikke sende direktiv: ${error.message}`);\n    } else {\n      if (created) setPriorityDirectives((current) => [created as TradeDirective, ...current.filter((item) => item.symbol !== setup.symbol)]);\n      setMessage(`PRIORITERT: ${setup.direction} ${setup.symbol}. Boten forsøker på neste syklus hvis signalet fortsatt er gyldig.`);\n    }'''
if old_insert in s:
    s = s.replace(old_insert, new_insert, 1)
    print("patched optimistic priority feedback")
elif ".select(\"id,symbol,direction,mode,requested_notional,leverage,status,created_at,expires_at\").single()" not in s:
    raise SystemExit("marker missing: directive insert block")

old_button = '{setup.direction !== "VENT" && <button type="button" className="primary compact" onClick={() => void prioritizeSetup(setup)}>Prioriter og gjennomfør</button>}'
new_button = '''{setup.direction !== "VENT" && (() => {\n          const active = priorityDirectives.find((item) => item.symbol === setup.symbol && item.direction === setup.direction);\n          return active\n            ? <div className="priority-active"><span className="priority-active-badge">PRIORITERT</span><button type="button" className="danger compact" disabled={priorityBusy === active.id} onClick={() => void stopPriority(active)}>{priorityBusy === active.id ? "Stopper …" : "Stopp prioritet"}</button></div>\n            : <button type="button" className="primary compact" onClick={() => void prioritizeSetup(setup)}>Prioriter og gjennomfør</button>;\n        })()}'''
if old_button in s:
    s = s.replace(old_button, new_button, 1)
    print("patched priority button state")
elif "priority-active-badge" not in s:
    raise SystemExit("marker missing: priority button")

p.write_text(s)

css = Path("app/globals.css")
c = css.read_text()
if "/* Priority feedback v11 */" not in c:
    c += '''\n\n/* Priority feedback v11 */\n.priority-active{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:2px}.priority-active-badge{display:inline-flex;align-items:center;min-height:34px;padding:0 10px;border-radius:9px;background:rgba(239,68,68,.14);border:1px solid rgba(248,113,113,.55);color:#fca5a5;font-size:10px;font-weight:900;letter-spacing:.1em}.best-setup-card:has(.priority-active){border-color:rgba(239,68,68,.72);box-shadow:inset 4px 0 0 rgba(239,68,68,.9),0 0 22px rgba(239,68,68,.07)}\n'''
    css.write_text(c)
    print("patched priority css")

print("UPGRADE_PRIORITY_FEEDBACK_V11_OK")
