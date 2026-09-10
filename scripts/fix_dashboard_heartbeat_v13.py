from pathlib import Path

p = Path('app/trading-dashboard.tsx')
s = p.read_text(encoding='utf-8')
old = 'supabase.from("bot_events").select("id,level,event_type,message,created_at").order("created_at", { ascending: false }).limit(1),'
new = 'supabase.from("bot_events").select("id,level,event_type,message,created_at").eq("event_type", "heartbeat").order("created_at", { ascending: false }).limit(1),'
if new in s:
    print('DASHBOARD_HEARTBEAT_V13_ALREADY_APPLIED')
elif old in s:
    p.write_text(s.replace(old, new, 1), encoding='utf-8')
    print('patched app/trading-dashboard.tsx')
    print('DASHBOARD_HEARTBEAT_V13_OK')
else:
    raise SystemExit('marker missing in app/trading-dashboard.tsx')
