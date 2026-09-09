from pathlib import Path

path = Path('app/trading-dashboard.tsx')
text = path.read_text(encoding='utf-8')

old = '''  async function emergencyStop() {\n    setSaving(true);\n    const next = { ...settings, bot_enabled: false, live_trading_enabled: false };\n    setSettings(next);\n    const { data: userData } = await supabase.auth.getUser();\n    if (userData.user) await supabase.from("bot_settings").upsert({ ...next, user_id: userData.user.id, updated_at: new Date().toISOString() }, { onConflict: "user_id" });\n    setMessage("Nødstopp er lagret. Nye handler er blokkert."); setSaving(false);\n  }\n'''
new = '''  async function emergencyStop() {\n    const confirmed = window.confirm("Aktivere nødstopp? Nye kjøp stoppes. Eksisterende posisjoner beholdes under aktiv stop-loss/trailing og kan fortsatt selges automatisk for å beskytte kapitalen.");\n    if (!confirmed) return;\n    setSaving(true); setMessage("");\n    const next = { ...settings, bot_enabled: false, live_trading_enabled: false };\n    const { data: userData } = await supabase.auth.getUser();\n    if (!userData.user) { setSaving(false); return; }\n    const { error } = await supabase.from("bot_settings").upsert({ ...next, user_id: userData.user.id, updated_at: new Date().toISOString() }, { onConflict: "user_id" });\n    if (!error) setSettings(next);\n    setMessage(error ? error.message : "NØDSTOPP AKTIV: Nye kjøp er blokkert. Eksisterende posisjoner overvåkes fortsatt av stop-loss/trailing og kan selges automatisk.");\n    setSaving(false);\n  }\n'''
if old not in text:
    raise SystemExit('emergencyStop marker not found')
text = text.replace(old, new, 1)

old_hero = '''<button className="danger" onClick={() => void emergencyStop()} disabled={saving}>Nødstopp</button></section>'''
new_hero = '''<div className="emergency-stop-box"><button className="danger" onClick={() => void emergencyStop()} disabled={saving}>Nødstopp</button><small>Nødstopp blokkerer nye kjøp. Åpne posisjoner blir ikke dumpet umiddelbart; boten fortsetter å overvåke dem og kan selge ved stop-loss, trailing-stop eller annen aktiv exitregel. Start live igjen for å tillate nye kjøp.</small></div></section>'''
if old_hero not in text:
    raise SystemExit('hero emergency button marker not found')
text = text.replace(old_hero, new_hero, 1)
path.write_text(text, encoding='utf-8')
