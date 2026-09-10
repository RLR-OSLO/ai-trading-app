from pathlib import Path

path = Path('trader/manager.py')
text = path.read_text(encoding='utf-8')
old = '''    if account.legacy:\n        env["LIVE_STATE_PATH"] = os.getenv("LIVE_STATE_PATH", "/var/lib/ai-trading-app/live-state.json")\n    else:\n        state_dir = Path("/var/lib/ai-trading-app/users") / account.user_id\n        state_dir.mkdir(parents=True, exist_ok=True)\n        env["LIVE_STATE_PATH"] = str(state_dir / "live-state.json")\n    return env\n'''
new = '''    if account.legacy:\n        env["LIVE_STATE_PATH"] = os.getenv("LIVE_STATE_PATH", "/var/lib/ai-trading-app/live-state.json")\n        env["DERIVATIVES_STATE_PATH"] = os.getenv("DERIVATIVES_STATE_PATH", "/var/lib/ai-trading-app/derivatives-state.json")\n    else:\n        state_dir = Path("/var/lib/ai-trading-app/users") / account.user_id\n        state_dir.mkdir(parents=True, exist_ok=True)\n        env["LIVE_STATE_PATH"] = str(state_dir / "live-state.json")\n        env["DERIVATIVES_STATE_PATH"] = str(state_dir / "derivatives-state.json")\n    return env\n'''
if old not in text:
    raise SystemExit('manager isolation marker not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('UPGRADE_MULTIUSER_ISOLATION_V5_OK')
