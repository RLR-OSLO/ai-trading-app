from pathlib import Path

# Make Futures wallet breakdown explicit in top summary.
p = Path('app/trading-dashboard.tsx')
s = p.read_text(encoding='utf-8')
old = '<div><span className="label">FUTURES TOTALT</span><strong>{money(futuresTotal)} {settings.quote_asset}</strong><small>Ledig Futures: {money(futuresAvailable)} {settings.quote_asset}</small></div>'
new = '<div><span className="label">FUTURES TOTALT</span><strong>{money(futuresTotal)} {settings.quote_asset}</strong><small>Disponibelt: {money(futuresAvailable)} · Investert: {money(Math.max(0, futuresTotal - futuresAvailable))} {settings.quote_asset}</small></div>'
if new in s:
    print('already: explicit futures breakdown')
elif old in s:
    p.write_text(s.replace(old, new, 1), encoding='utf-8')
    print('patched: explicit futures breakdown')
else:
    raise SystemExit('missing marker: futures top card')

# Make chart lines thinner and white while keeping the percentage text colored.
p = Path('app/globals.css')
s = p.read_text(encoding='utf-8')
marker = '/* v20 white ultra-thin sparklines */'
override = '\n\n/* v20 white ultra-thin sparklines */\n.sparkline-wrap path{stroke:#fff!important;stroke-width:.55!important;opacity:.9}.sparkline-wrap.up,.sparkline-wrap.down{color:inherit}.sparkline-wrap.up span{color:#4ade80}.sparkline-wrap.down span{color:#fb7185}\n'
if marker not in s:
    p.write_text(s + override, encoding='utf-8')
    print('patched: white ultra-thin sparklines')
else:
    print('already: white ultra-thin sparklines')

print('FIX_V20_OK')
