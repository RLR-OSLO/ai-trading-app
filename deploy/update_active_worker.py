#!/usr/bin/env python3
"""Stage a pinned worker release, then preserve account state during a service switch.

This software updater never submits exchange orders or changes account settings.
Only --apply switches the existing service; its workers retain their existing
authorization and trading settings. Run on the existing host as root.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

REPO = "https://github.com/RLR-OSLO/ai-trading-app.git"
COMPASS = "https://nsqsqupucxgrkwotegof.supabase.co"
SERVICE = "ai-trading-app"
ENGINE = "user-commands-v5"
ENV_FILE = Path("/etc/ai-trading-app.env")
STATE_ROOT = Path("/var/lib/ai-trading-app")
OVERRIDE = Path("/etc/systemd/system/ai-trading-app.service.d/40-compass.conf")
SETTINGS_QUERY = "/rest/v1/bot_settings?select=*&order=user_id"
PENDING_FIELDS = ("pending_action", "pending_client_order_id", "pending_open", "pending_close_id", "pending_reports", "active_command")


class Stop(RuntimeError):
    pass


def run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if result.returncode:
        # Arguments, stderr and HTTP bodies may contain credentials. Keep them private.
        raise Stop(f"{Path(args[0]).name} feilet (kode {result.returncode})")
    return result.stdout.strip()


def property_value(name: str) -> str:
    return run("systemctl", "show", SERVICE, "--property=" + name, "--value")


def env_values(raw: bytes) -> dict[str, str]:
    result = {}
    for line in raw.decode().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip("\"'")
    return result


def api_read(path: str, key: str):
    headers = {"apikey": key}
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = "Bearer " + key
    request = urllib.request.Request(COMPASS + path, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise Stop(f"Databaselesing feilet (HTTP {exc.code})") from None


def read_states(root: Path) -> dict[str, bytes]:
    if not root.is_dir() or root.is_symlink():
        raise Stop("Uventet mappe for kontotilstand")
    result = {}
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in folders + files:
            path = Path(directory) / name
            if path.is_symlink():
                raise Stop("Symbolsk lenke i kontomappen; krever kontroll")
            if path.is_file() and "state" in name and name.endswith(".json"):
                raw = path.read_bytes()
                if not isinstance(json.loads(raw), dict):
                    raise Stop("Ugyldig kontotilstand")
                result[str(path.relative_to(root))] = raw
    if not result:
        raise Stop("Ingen eksisterende tilstandsfiler funnet")
    return result


def require_settled(states: dict[str, bytes]) -> None:
    for name, raw in states.items():
        state = json.loads(raw)
        if any(state.get(field) for field in PENDING_FIELDS):
            raise Stop("Uavklart ordre eller rapportko i " + name + "; avstemmes for oppdatering")


def state_summary(states: dict[str, bytes]) -> list[dict]:
    return [{"file": name, "day": json.loads(raw).get("day"),
             "trades_today": json.loads(raw).get("trades_today", 0),
             "positions": len(json.loads(raw).get("positions") or []) + bool(json.loads(raw).get("position")),
             "pending": any(json.loads(raw).get(field) for field in PENDING_FIELDS)}
            for name, raw in sorted(states.items())]


def rewrite_working_directory(original: bytes, stage: Path) -> bytes:
    if stage.parent != Path("/opt") or not re.fullmatch(r"ai-trading-compass-[A-Za-z0-9_-]+", stage.name):
        raise Stop("Uventet mappe for ny kode")
    result, count = re.subn(r"(?m)^WorkingDirectory=[^\r\n]*$", "WorkingDirectory=" + str(stage), original.decode())
    if count != 1:
        raise Stop("Forventet nøyaktig en WorkingDirectory i Compass-overstyringen")
    return result.encode()


def atomic_write(path: Path, content: bytes, mode: int = 0o644) -> None:
    fd, name = tempfile.mkstemp(prefix=".worker-update-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def require_unchanged_settings(before: list, after: list) -> None:
    if not before or before != after:
        raise Stop("Kontoinnstillingene er endret under oppdateringen; kontroller for videre handling")


def switch_service(override: Path, replacement: bytes, root: Path, backup: Path, before_start) -> str:
    """Rollback only before the new process can have run; never restore state."""
    original = override.read_bytes()
    (backup / "40-compass.conf").write_bytes(original)
    start_attempted = False
    try:
        print("Stopper tjenesten kort for a sikre sammenhengende kontotilstand ...", flush=True)
        run("systemctl", "stop", SERVICE)
        if property_value("MainPID") != "0" or property_value("ActiveState") != "inactive":
            raise Stop("Tjenesten er ikke helt stoppet")
        before = read_states(root)
        require_settled(before)
        for name, raw in before.items():
            target = backup / "state" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        before_start()
        atomic_write(override, replacement)
        run("systemctl", "daemon-reload")
        if read_states(root) != before:
            raise Stop("Tilstand endret mens tjenesten var stoppet")
        started = datetime.now(timezone.utc).isoformat()
        start_attempted = True
        run("systemctl", "start", SERVICE)
        return started
    except BaseException:
        if not start_attempted:
            atomic_write(override, original)
            run("systemctl", "daemon-reload")
            run("systemctl", "start", SERVICE)
            print("Tidligere kode startet igjen. Kontotilstanden er ikke overskrevet.", flush=True)
        else:
            print("Ny kode er valgt. Ingen automatisk tilbakerulling etter oppstart; kontroller tjenesten og ventende ordre.", flush=True)
        raise


def health_ready(rows: list[dict], expected: dict[str, bool]) -> bool:
    for uid, authorized in expected.items():
        heartbeats = [r for r in rows if r["user_id"] == uid and r["event_type"] == "heartbeat"]
        heartbeat = max(heartbeats, key=lambda r: r["created_at"], default=None)
        if not heartbeat:
            return False
        fields = dict(part.split("=", 1) for part in heartbeat["message"].split(";") if "=" in part)
        if fields.get("engine") != ENGINE or fields.get("recovery_locked") != str(not authorized):
            return False
        if authorized:
            cycles = [r for r in rows if r["user_id"] == uid and r["event_type"] == "cycle_status"]
            cycle = max(cycles, key=lambda r: r["created_at"], default=None)
            if not cycle or any(r["user_id"] == uid and r["event_type"] == "trading_cycle_error"
                                and r["created_at"] >= cycle["created_at"] for r in rows):
                return False
    return bool(expected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--expected-working-directory", required=True)
    parser.add_argument("--apply", action="store_true", help="Switch the existing service after checks and backup")
    args = parser.parse_args()
    if os.geteuid() != 0 or not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        raise Stop("Krever root og en fast commit-ID")
    os.umask(0o077)
    with open("/run/lock/ai-trading-worker-update.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        working = property_value("WorkingDirectory")
        if working != args.expected_working_directory or not working.startswith("/opt/ai-trading-compass-"):
            raise Stop("Aktiv kodemappe stemmer ikke; ingen tjenesteendring utfort")
        if property_value("User") != "trader" or property_value("ActiveState") != "active":
            raise Stop("Forventet aktiv trader-tjeneste")
        if property_value("KillMode") != "control-group" or "-m trader.manager" not in property_value("ExecStart"):
            raise Stop("Uventet prosessoppsett; krever kontroll")
        raw_env = ENV_FILE.read_bytes()
        env = env_values(raw_env)
        if env.get("SUPABASE_URL", "").rstrip("/") != COMPASS:
            raise Stop("Tjenesten bruker ikke forventet database")
        for field, default in (("LIVE_STATE_PATH", "live-state.json"), ("DERIVATIVES_STATE_PATH", "derivatives-state.json")):
            path = Path(env.get(field, str(STATE_ROOT / default)))
            if not path.resolve().is_relative_to(STATE_ROOT.resolve()):
                raise Stop("Kontotilstand ligger utenfor forventet mappe")
        key = env["SUPABASE_SERVICE_ROLE_KEY"]
        settings = api_read(SETTINGS_QUERY, key)
        require_unchanged_settings(settings, settings)
        api_read("/rest/v1/trades?select=execution_key&limit=0", key)
        api_read("/rest/v1/trading_commands?select=id,status&limit=0", key)
        api_read("/rest/v1/trading_position_snapshots?select=user_id,engine&limit=0", key)
        since = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        query = urllib.parse.urlencode({"select": "user_id", "event_type": "eq.heartbeat", "created_at": "gte." + since})
        recent = {row["user_id"] for row in api_read("/rest/v1/bot_events?" + query, key)}
        expected = {row["user_id"]: row.get("execution_authorized") is True for row in settings if row["user_id"] in recent}
        if not expected or env.get("APP_USER_ID") not in expected:
            raise Stop("Mangler fersk status for eksisterende kontoer")
        snapshot = read_states(STATE_ROOT)
        print("Tilstand: " + json.dumps(state_summary(snapshot)), flush=True)
        require_settled(snapshot)
        print(f"Kontroll OK: {len(expected)} rapporterende kontoer. Ingen innstillinger eller nokler endres.", flush=True)
        if not args.apply:
            print("Kun kontroll utfort. Bruk --apply for programoppdateringen.")
            return
        original_revision = run("git", "-C", working, "rev-parse", "HEAD")
        if original_revision == args.revision:
            print("Riktig kodeversjon er allerede installert. Ingen endring.")
            return
        stage = Path(tempfile.mkdtemp(prefix="ai-trading-compass-", dir="/opt"))
        print("Henter den faste kodeversjonen ...", flush=True)
        run("git", "-C", str(stage), "init", "-q")
        run("git", "-C", str(stage), "fetch", "-q", "--depth", "1", REPO, args.revision)
        run("git", "-C", str(stage), "checkout", "-q", "--detach", "FETCH_HEAD")
        if run("git", "-C", str(stage), "rev-parse", "HEAD") != args.revision:
            raise Stop("Kodeversjonen stemmer ikke")
        if "engine=" + ENGINE not in (stage / "trader/worker.py").read_text():
            raise Stop("Forventet motorversjon mangler i kildekoden")
        run("python3", "-m", "compileall", "-q", str(stage / "trader"))
        stage.chmod(0o755)
        for path in stage.rglob("*"):
            if ".git" not in path.relative_to(stage).parts:
                if path.is_symlink():
                    raise Stop("Uventet symbolsk lenke i kodeversjonen")
                path.chmod(0o755 if path.is_dir() else 0o644)
        replacement = rewrite_working_directory(OVERRIDE.read_bytes(), stage)
        backup = Path(tempfile.mkdtemp(prefix="ai-trading-worker-backup-", dir="/root"))
        (backup / "server.env").write_bytes(raw_env)
        (backup / "settings.json").write_text(json.dumps(settings))
        (backup / "release.json").write_text(json.dumps({"old_revision": original_revision, "new_revision": args.revision,
                                                        "old_working_directory": working, "new_working_directory": str(stage)}))
        print("Sikkerhetskopi: " + str(backup), flush=True)

        def before_start():
            if ENV_FILE.read_bytes() != raw_env:
                raise Stop("Miljofilen ble endret under klargjoring")
            require_unchanged_settings(settings, api_read(SETTINGS_QUERY, key))

        started = switch_service(OVERRIDE, replacement, STATE_ROOT, backup, before_start)
        print("Ny kode startet. Venter pa bekreftet motorstatus fra hver konto ...", flush=True)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            run("systemctl", "is-active", "--quiet", SERVICE)
            query = urllib.parse.urlencode({"select": "user_id,event_type,message,created_at", "created_at": "gte." + started,
                                           "event_type": "in.(heartbeat,cycle_status,trading_cycle_error)",
                                           "order": "created_at.desc", "limit": "200"})
            rows = api_read("/rest/v1/bot_events?" + query, key)
            if health_ready(rows, expected):
                before_start()
                if property_value("WorkingDirectory") != str(stage):
                    raise Stop("Tjenestens kodemappe er endret")
                print("WORKER_READY " + args.revision, flush=True)
                print("Aktiv kodemappe: " + str(stage), flush=True)
                print(f"Motor={ENGINE}; kontoer={len(expected)}; eksisterende innstillinger og tilstand bevart.", flush=True)
                print("Tilstand: " + json.dumps(state_summary(read_states(STATE_ROOT))), flush=True)
                return
            time.sleep(5)
        raise Stop("Ny kode er installert, men alle kontoer ble ikke bekreftet innen 180 sekunder. Ikke nullstill tilstand eller kjor gammel installer; del denne meldingen for kontroll.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit("STOPPET: " + (str(exc) if isinstance(exc, Stop) else type(exc).__name__))
