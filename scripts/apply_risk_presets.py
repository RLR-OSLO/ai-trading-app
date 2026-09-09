from pathlib import Path

path = Path('app/trading-dashboard.tsx')
text = path.read_text(encoding='utf-8')

old = '  function update<K extends keyof Settings>(key: K, value: Settings[K]) { setSettings((current) => ({ ...current, [key]: value })); }\n'
new = '''  function update<K extends keyof Settings>(key: K, value: Settings[K]) { setSettings((current) => ({ ...current, [key]: value })); }\n\n  function applyRiskProfile(profile: Settings["risk_profile"]) {\n    const capital = Math.max(5, availableCapital);\n    const presets = {\n      low: { orderShare: 0.15, stop_loss_percent: 0.75, take_profit_percent: 1.5, dailyLossShare: 0.01 },\n      normal: { orderShare: 0.25, stop_loss_percent: 1.0, take_profit_percent: 2.0, dailyLossShare: 0.02 },\n      high: { orderShare: 0.35, stop_loss_percent: 1.5, take_profit_percent: 3.0, dailyLossShare: 0.03 },\n    } as const;\n    const preset = presets[profile];\n    const roundedOrder = Math.round((capital * preset.orderShare) * 2) / 2;\n    const roundedDailyLoss = Math.round((capital * preset.dailyLossShare) * 2) / 2;\n    setSettings((current) => ({\n      ...current,\n      risk_profile: profile,\n      trade_cap_usdc: capital,\n      order_size_usdc: Math.min(capital, Math.max(5, roundedOrder)),\n      stop_loss_percent: preset.stop_loss_percent,\n      take_profit_percent: preset.take_profit_percent,\n      max_daily_loss_usdc: Math.min(capital, Math.max(0.5, roundedDailyLoss)),\n    }));\n    setMessage(`${profile === "low" ? "Lav" : profile === "normal" ? "Normal" : "Høy"} risiko valgt. Standardverdiene er satt automatisk – trykk Lagre innstillinger for å aktivere dem.`);\n  }\n'''
if old not in text:
    raise SystemExit('update function marker not found')
text = text.replace(old, new, 1)

old_select = '<label className="select-field"><span>Risikonivå</span><select value={settings.risk_profile} onChange={(event) => update("risk_profile", event.target.value as Settings["risk_profile"])}><option value="low">Lav</option><option value="normal">Normal</option><option value="high">Høy</option></select></label>'
new_select = '<label className="select-field"><span>Risikonivå</span><select value={settings.risk_profile} onChange={(event) => applyRiskProfile(event.target.value as Settings["risk_profile"])}><option value="low">Lav</option><option value="normal">Normal</option><option value="high">Høy</option></select><small>Bytte av risikonivå setter automatisk nye standardverdier for ordrestørrelse, stop-loss, gevinstmål og maks dagstap.</small></label>'
if old_select not in text:
    raise SystemExit('risk select marker not found')
text = text.replace(old_select, new_select, 1)

path.write_text(text, encoding='utf-8')
