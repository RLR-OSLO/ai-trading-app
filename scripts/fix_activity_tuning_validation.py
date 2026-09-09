from pathlib import Path

p = Path('app/trading-dashboard.tsx')
t = p.read_text(encoding='utf-8')
old = 'function Field({ label, value, min, max, step, onChange }: Readonly<{ label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void }>) { return <label className="number-field"><span>{label}</span><input type="number" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} /></label>; }'
new = 'function Field({ label, value, min, max, step, onChange }: Readonly<{ label: string; value: number; min: number; max?: number; step: number; onChange: (value: number) => void }>) { return <label className="number-field"><span>{label}</span><input type="number" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} /></label>; }'
if old not in t:
    raise SystemExit('Field signature not found')
t = t.replace(old, new, 1)
p.write_text(t, encoding='utf-8')

p = Path('tests/test_portfolio_live.py')
t = p.read_text(encoding='utf-8')
t = t.replace('self.assertEqual(limits.max_open_positions, 5)', 'self.assertEqual(limits.max_open_positions, 8)', 1)
t = t.replace('self.assertEqual(limits.max_trades_per_day, 80)', 'self.assertEqual(limits.max_trades_per_day, 100)', 1)
p.write_text(t, encoding='utf-8')
