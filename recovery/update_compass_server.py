#!/usr/bin/env python3
"""Upgrade the recovered, not-yet-activated Compass worker without changing keys/state."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

COMPASS = 'https://nsqsqupucxgrkwotegof.supabase.co'
REPO = 'https://github.com/RLR-OSLO/ai-trading-app.git'


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f'{args[0]} feilet (kode {result.returncode})')
    return result.stdout.strip()


def read_api(path, headers):
    request = urllib.request.Request(COMPASS + path, headers=headers, method='GET')
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def atomic_write(path, data):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.upgrade-')
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(name, 0o644)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def states(root):
    result = {}
    for path in root.rglob('*state*.json'):
        if path.is_symlink():
            raise RuntimeError('Tilstandsfil er en symbolsk lenke')
        result[str(path.relative_to(root))] = path.read_bytes()
    return result


def require_unactivated(rows):
    if not rows or any(any(row.get(key) is not False for key in ('bot_enabled', 'live_trading_enabled', 'execution_authorized')) for row in rows):
        raise RuntimeError('En konto er allerede aktivert for handel. Stoppet uten endring; oppdateringen ma tilpasses aktiv drift.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or not re.fullmatch('[0-9a-f]{40}', args.revision):
        raise RuntimeError('Krever root og fast commit-ID')
    os.umask(0o077)
    env = {}
    for line in Path('/etc/ai-trading-app.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            env[key.strip()] = value.strip().strip('\"\'')
    if env.get('SUPABASE_URL', '').rstrip('/') != COMPASS:
        raise RuntimeError('Serveren er ikke koblet til Compass Internal')
    key = env['SUPABASE_SERVICE_ROLE_KEY']
    headers = {'apikey': key}
    if not key.startswith('sb_secret_'):
        headers['Authorization'] = 'Bearer ' + key
    query = '/rest/v1/bot_settings?select=user_id,bot_enabled,live_trading_enabled,execution_authorized,ignore_rsi_high_veto,ignore_rsi_low_veto,ignore_atr_veto'
    require_unactivated(read_api(query, headers))
    override = Path('/etc/systemd/system/ai-trading-app.service.d/40-compass.conf')
    original = override.read_bytes()
    working = run('systemctl', 'show', 'ai-trading-app', '--property=WorkingDirectory', '--value')
    if not working.startswith('/opt/ai-trading-compass-'):
        raise RuntimeError('Uventet aktiv kodemappe')
    if run('git', '-C', working, 'rev-parse', 'HEAD') == args.revision:
        print('Denne versjonen er allerede installert. Ingen endring.')
        return
    stage = Path(tempfile.mkdtemp(prefix='ai-trading-compass-', dir='/opt'))
    print('Henter kontrollert kodeversjon ...', flush=True)
    run('git', '-C', str(stage), 'init', '-q')
    run('git', '-C', str(stage), 'fetch', '-q', '--depth', '1', REPO, args.revision)
    run('git', '-C', str(stage), 'checkout', '-q', '--detach', 'FETCH_HEAD')
    if run('git', '-C', str(stage), 'rev-parse', 'HEAD') != args.revision:
        raise RuntimeError('Kodeversjonen stemmer ikke')
    run('python3', '-m', 'compileall', '-q', str(stage / 'trader'))
    stage.chmod(0o755)
    for path in stage.rglob('*'):
        if '.git' not in path.relative_to(stage).parts:
            path.chmod(0o755 if path.is_dir() else 0o644)
    backup = Path(tempfile.mkdtemp(prefix='ai-trading-upgrade-', dir='/root'))
    (backup / '40-compass.conf').write_bytes(original)
    root = Path('/var/lib/ai-trading-app')
    started = datetime.now(timezone.utc).isoformat()
    try:
        run('systemctl', 'stop', 'ai-trading-app')
        require_unactivated(read_api(query, headers))
        before = states(root)
        for name, raw in before.items():
            target = backup / 'state' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        atomic_write(override, f'[Service]\nWorkingDirectory={stage}\nExecStart=\nExecStart=/usr/bin/python3 -m trader.manager\n'.encode())
        run('systemctl', 'daemon-reload')
        run('systemctl', 'start', 'ai-trading-app')
        print('Venter pa bekreftet RSI/ATR-rapport ...', flush=True)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            run('systemctl', 'is-active', '--quiet', 'ai-trading-app')
            q = urllib.parse.urlencode({'user_id': 'eq.' + env['APP_USER_ID'], 'event_type': 'eq.heartbeat', 'created_at': 'gte.' + started, 'select': 'message', 'order': 'created_at.desc', 'limit': '1'})
            rows = read_api('/rest/v1/bot_events?' + q, headers)
            if rows and 'veto_controls=v1;' in rows[0]['message'] and 'recovery_locked=True;' in rows[0]['message']:
                if states(root) != before:
                    raise RuntimeError('Tilstandsfilene er endret; krever kontroll')
                print('COMPASS_VETO_READY ' + args.revision)
                print('RSI/ATR og veto-valg er koblet til. Posisjoner og nokler er bevart. Handel er fortsatt avslatt.')
                print('Sikkerhetskopi: ' + str(backup))
                return
            time.sleep(5)
        raise RuntimeError('Ingen bekreftet rapport innen tidsfristen')
    except BaseException:
        run('systemctl', 'stop', 'ai-trading-app')
        atomic_write(override, original)
        run('systemctl', 'daemon-reload')
        run('systemctl', 'start', 'ai-trading-app')
        print('Tidligere kode er satt tilbake. Posisjonsfiler er ikke overskrevet.')
        raise


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Never print HTTP bodies or environment values.
        raise SystemExit('STOPPET: ' + (str(exc) if type(exc) is RuntimeError else type(exc).__name__))
