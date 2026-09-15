#!/usr/bin/env python3
"""Switch the existing server to Compass in reporting-only mode, with rollback."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

COMPASS = "https://nsqsqupucxgrkwotegof.supabase.co"
REPO = "https://github.com/RLR-OSLO/ai-trading-app.git"


class Stop(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api(url, headers=None, payload=None):
    request = urllib.request.Request(url, headers=headers or {},
        data=None if payload is None else json.dumps(payload).encode(),
        method="GET" if payload is None else "POST")
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=25) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raise Stop(f"HTTP {exc.code} fra {urllib.parse.urlparse(url).hostname}") from None
    except (urllib.error.URLError, TimeoutError):
        raise Stop("Nettverksfeil") from None


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise Stop(f"{args[0]} feilet (kode {result.returncode})")
    return result.stdout.strip()


def env_values(text):
    values = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


def rewrite_env(text, updates):
    rows, seen = [], set()
    for line in text.splitlines():
        key = line.split("=", 1)[0].strip()
        if "=" in line and key in updates and not line.lstrip().startswith("#"):
            if key not in seen:
                rows.append(key + "=" + updates[key])
                seen.add(key)
        else:
            rows.append(line)
    rows.extend(key + "=" + value for key, value in updates.items() if key not in seen)
    return "\n".join(rows) + "\n"


def atomic_write(path, raw, mode, uid=0, gid=0):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".compass-")
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary, mode)
        os.chown(temporary, uid, gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def snapshot(root):
    result = {}
    for path in sorted(root.rglob("*state*.json")):
        if path.is_symlink():
            raise Stop("Tilstandsfil er en symbolsk lenke")
        result[str(path.relative_to(root))] = path.read_bytes()
    return result


def exchange_read(env, base, path):
    allowed = {
        ("https://api.binance.com", "/api/v3/account"),
        ("https://api.binance.com", "/api/v3/openOrders"),
        ("https://api.binance.com", "/sapi/v1/margin/account"),
        ("https://api.binance.com", "/sapi/v1/account/apiRestrictions"),
        ("https://fapi.binance.com", "/fapi/v3/account"),
        ("https://fapi.binance.com", "/fapi/v3/positionRisk"),
    }
    if (base, path) not in allowed:
        raise Stop("Ikke et godkjent lesekall")
    server_time = api("https://api.binance.com/api/v3/time")["serverTime"]
    query = urllib.parse.urlencode({"timestamp": server_time, "recvWindow": 10000})
    signature = hmac.new(env["BINANCE_SECRET_KEY"].encode(), query.encode(), hashlib.sha256).hexdigest()
    return api(base + path + "?" + query + "&signature=" + signature,
        {"X-MBX-APIKEY": env["BINANCE_API_KEY"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--user-id", required=True, type=uuid.UUID)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0 or not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        raise Stop("Krever root og fast commit-ID")
    os.umask(0o077)
    backup = args.backup.resolve()
    if backup.parent != Path("/root") or not backup.name.startswith("ai-trading-recovery-"):
        raise Stop("Uventet sikkerhetskopimappe")
    evidence = json.loads((backup / "report.json").read_text())
    secret_path = backup / "compass-server-key"
    if secret_path.stat().st_uid != 0 or secret_path.stat().st_mode & 0o077:
        raise Stop("Servernokkelfilen ma vaere kun lesbar for root")
    key = secret_path.read_text().strip()
    headers = {"apikey": key, "Content-Type": "application/json"}
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = "Bearer " + key
    uid = str(args.user_id)
    user = api(COMPASS + "/auth/v1/admin/users/" + uid, headers)
    if user.get("email", "").lower() != args.email.lower() or not user.get("email_confirmed_at") or not any(i.get("provider") == "google" for i in user.get("identities", [])):
        raise Stop("Google-identiteten stemmer ikke med valgt konto")
    settings = api(COMPASS + "/rest/v1/bot_settings?user_id=eq." + uid + "&select=bot_enabled,live_trading_enabled,execution_authorized", headers)
    if len(settings) != 1 or any(settings[0].values()):
        raise Stop("Forventet konto med handel avslatt; endrer ikke en aktiv konto")
    env_path = Path("/etc/ai-trading-app.env")
    old_env = env_path.read_bytes()
    env_stat = env_path.stat()
    env = env_values(old_env.decode())
    if env.get("APP_USER_ID") != evidence["legacy_user_id"]:
        raise Stop("Serverens bruker-ID er endret siden sikkerhetskopien")
    for name in ("BINANCE_API_KEY", "BINANCE_SECRET_KEY"):
        if not env.get(name):
            raise Stop("Binance-nokler mangler")
    # Read the exchange before changing any server configuration.
    spot = exchange_read(env, "https://api.binance.com", "/api/v3/account")
    orders = exchange_read(env, "https://api.binance.com", "/api/v3/openOrders")
    balances = {r["asset"]: Decimal(r["free"]) + Decimal(r["locked"]) for r in spot["balances"]}
    state_path = Path(env.get("LIVE_STATE_PATH", "/var/lib/ai-trading-app/live-state.json"))
    owner_state = json.loads(state_path.read_text())
    if owner_state.get("positions", []) != evidence["local_states"]["live-state.json"].get("positions", []):
        raise Stop("Posisjonene er endret siden rapporten; hent en ny rapport forst")
    if owner_state.get("pending_action"):
        raise Stop("En uavklart ordre ma avstemmes forst")
    for position in owner_state.get("positions", []):
        asset = re.sub(r"(USDC|USDT)$", "", position["symbol"])
        if balances.get(asset, Decimal(0)) < Decimal(position["quantity"]):
            raise Stop("Binance-beholdning er lavere enn lagret posisjon: " + asset)
    extra = {}
    for label, base, path in [
        ("api_restrictions", "https://api.binance.com", "/sapi/v1/account/apiRestrictions"),
        ("margin_account", "https://api.binance.com", "/sapi/v1/margin/account"),
        ("futures_account", "https://fapi.binance.com", "/fapi/v3/account"),
        ("futures_positions", "https://fapi.binance.com", "/fapi/v3/positionRisk"),
    ]:
        try:
            extra[label] = exchange_read(env, base, path)
        except Stop as exc:
            extra[label] = {"error": str(exc)}
    stage = Path(tempfile.mkdtemp(prefix="ai-trading-compass-", dir="/opt"))
    print("Klargjor kode:", stage, flush=True)
    run("git", "-C", str(stage), "init", "-q")
    run("git", "-C", str(stage), "fetch", "-q", "--depth", "1", REPO, args.revision)
    run("git", "-C", str(stage), "checkout", "-q", "--detach", "FETCH_HEAD")
    if run("git", "-C", str(stage), "rev-parse", "HEAD") != args.revision:
        raise Stop("Feil kodeversjon")
    run("python3", "-m", "compileall", "-q", str(stage / "trader"))
    stage.chmod(0o755)
    for path in stage.rglob("*"):
        if ".git" not in path.relative_to(stage).parts:
            path.chmod(0o755 if path.is_dir() else 0o644)
    api(COMPASS + "/rest/v1/rpc/service_register_trading_server", headers,
        {"p_legacy_user_id": evidence["legacy_user_id"], "p_user_id": uid})
    updates = {"SUPABASE_URL": COMPASS, "SUPABASE_SERVICE_ROLE_KEY": key, "APP_USER_ID": uid,
        "LIVE_STATE_PATH": str(state_path),
        "DERIVATIVES_STATE_PATH": env.get("DERIVATIVES_STATE_PATH", "/var/lib/ai-trading-app/derivatives-state.json")}
    replacement = rewrite_env(old_env.decode(), updates).encode()
    override = Path("/etc/systemd/system/ai-trading-app.service.d/40-compass.conf")
    if override.exists():
        raise Stop("Compass-overstyring finnes allerede; kontroller for ny kjoring")
    transaction = Path(tempfile.mkdtemp(prefix="switch-", dir=backup))
    (transaction / "original.env").write_bytes(old_env)
    root = Path("/var/lib/ai-trading-app")
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        run("systemctl", "stop", "ai-trading-app")
        before = snapshot(root)
        if not state_path.resolve().is_relative_to(root) or json.loads(before[str(state_path.relative_to(root))]) != owner_state:
            raise Stop("Tilstanden endret seg under kontrollen; trenger ny avstemming")
        for name, raw in before.items():
            target = transaction / "state" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        atomic_write(env_path, replacement, env_stat.st_mode & 0o777, env_stat.st_uid, env_stat.st_gid)
        override.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        override.parent.chmod(0o755)
        atomic_write(override, f"[Service]\nWorkingDirectory={stage}\nExecStart=\nExecStart=/usr/bin/python3 -m trader.manager\n".encode(), 0o644)
        run("systemctl", "daemon-reload")
        run("systemctl", "start", "ai-trading-app")
        print("Venter pa fersk serverrapport ...", flush=True)
        deadline = time.monotonic() + 150
        heartbeat = None
        while time.monotonic() < deadline:
            run("systemctl", "is-active", "--quiet", "ai-trading-app")
            query = urllib.parse.urlencode({"user_id": "eq." + uid, "event_type": "eq.heartbeat", "created_at": "gte." + started_at, "select": "message,created_at", "order": "created_at.desc", "limit": "1"})
            rows = api(COMPASS + "/rest/v1/bot_events?" + query, headers)
            if rows and "recovery_locked=True" in rows[0]["message"]:
                heartbeat = rows[0]
                break
            time.sleep(5)
        if not heartbeat:
            raise Stop("Ingen bekreftet rapport med handel laset")
        if snapshot(root) != before:
            raise Stop("Tilstandsfilene ble endret; trenger avstemming")
        report = {"kind": "compass_server_connected", "user_id": uid, "revision": args.revision,
            "legacy_user_id": evidence["legacy_user_id"], "state_preserved": True,
            "spot_account": spot, "open_orders": orders, "additional_accounts": extra,
            "local_states": {name: json.loads(raw) for name, raw in before.items()},
            "heartbeat": heartbeat, "captured_at": datetime.now(timezone.utc).isoformat()}
        (transaction / "connection-report.json").write_text(json.dumps(report, indent=2))
        rows = api(COMPASS + "/rest/v1/trading_recovery_uploads", {**headers, "Prefer": "return=representation"}, {"legacy_user_id": evidence["legacy_user_id"], "payload": report})
        print("COMPASS_SERVER_CONNECTED", rows[0]["id"])
        print("Eksisterende posisjonsfiler er bevart. Ingen ordre er lagt inn.")
        print("Dashboardet venter pa siste kontroll. Ikke kjor kommandoen pa nytt.")
    except Exception:
        run("systemctl", "stop", "ai-trading-app")
        atomic_write(env_path, old_env, env_stat.st_mode & 0o777, env_stat.st_uid, env_stat.st_gid)
        override.unlink(missing_ok=True)
        run("systemctl", "daemon-reload")
        run("systemctl", "start", "ai-trading-app")
        print("Tidligere serverkonfigurasjon er gjenopprettet.")
        raise


if __name__ == "__main__":
    try:
        main()
    except (Stop, OSError, ValueError, KeyError) as exc:
        raise SystemExit("STOPPET: " + (str(exc) if isinstance(exc, Stop) else type(exc).__name__))
