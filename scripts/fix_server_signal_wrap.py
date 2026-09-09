from pathlib import Path

path = Path('app/trading-dashboard.tsx')
text = path.read_text(encoding='utf-8')
old = '<p className={lastEvent?.level === "error" ? "loss" : "muted"}>{lastEvent?.message ?? "Serverrapportering er ikke koblet til ennå."}</p>'
new = '<p className={`server-signal ${lastEvent?.level === "error" ? "loss" : "muted"}`}>{lastEvent?.message ?? "Serverrapportering er ikke koblet til ennå."}</p>'
if old not in text:
    raise SystemExit('server signal marker not found')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')

css = Path('app/globals.css')
styles = css.read_text(encoding='utf-8')
rule = '.server-signal{max-width:100%;overflow-wrap:anywhere;word-break:break-word;white-space:normal;line-height:1.5}'
if rule not in styles:
    styles = styles.rstrip() + rule + '\n'
css.write_text(styles, encoding='utf-8')
