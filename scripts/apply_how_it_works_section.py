from pathlib import Path

path = Path('app/trading-dashboard.tsx')
text = path.read_text(encoding='utf-8')

import_line = 'import { supabase } from "../lib/supabase";\n'
if 'import HowItWorks from "./how-it-works";' not in text:
    text = text.replace(import_line, import_line + 'import HowItWorks from "./how-it-works";\n', 1)

marker = '    <section className="panel chat-panel"><div className="panel-head"><div><p className="eyebrow">SNAKK MED BOTTEN</p><h3>Du er sjefen</h3></div><span className="muted">Leser ferske kontrolldata</span></div>\n'
if marker not in text:
    raise SystemExit('chat section marker not found')

# Insert the explanatory section after the full chat section, immediately before </main>.
needle = '    </section>\n  </main>;\n}\n\nfunction Field('
if '<HowItWorks />' not in text:
    if needle not in text:
        raise SystemExit('dashboard closing marker not found')
    text = text.replace(needle, '    </section>\n    <HowItWorks />\n  </main>;\n}\n\nfunction Field(', 1)

path.write_text(text, encoding='utf-8')
