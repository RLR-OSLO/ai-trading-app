#!/usr/bin/env python3
"""Back up local state and collect Spot evidence; never submit exchange orders.

Run on the existing trading server as root. Optionally upload the report to the
service-only Compass recovery table. Does not change env, state or services.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import getpass
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
SPOT = "https://api.binance.com"
ALLOWED_READS = {"/api/v3/time", "/api/v3/account", "/api/v3/openOrders", "/api/v3/myTrades"}


class RecoveryError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url, *, headers=None, payload=None):
    req = urllib.request.Request(url, headers=headers or {},
        data=None if payload is None else json.dumps(payload).encode(),
        method="GET" if payload is None else "POST")
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=25) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        # Never include request URLs, signatures, keys or arbitrary response text.
        if exc.code in (418, 429):
            raise RecoveryError("RATE_LIMIT: Binance ber oss stoppe; prov igjen senere") from None
        raise RecoveryError(f"HTTP {exc.code} fra {urllib.parse.urlparse(url).hostname}") from None
    except (urllib.error.URLError, TimeoutError):
        raise RecoveryError("Nettverksfeil; ingen innstillinger er endret") from None


def parse_env(text):
    result = {}
    for line in text.splitlines():
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


class SpotReader:
    def __init__(self, env):
        self.key = env.get("BINANCE_API_KEY", "")
        self.secret = env.get("BINANCE_SECRET_KEY", "")
        if not self.key or not self.secret:
            raise RecoveryError("Binance-nokler mangler i serverens env-fil")
        self.offset = int(self.read("/api/v3/time", signed=False)["serverTime"]) - int(time.time() * 1000)

    def read(self, path, params=None, *, signed=True):
        if path not in ALLOWED_READS:
            raise RecoveryError("Kun godkjente lese-endepunkter er tillatt")
        params = dict(params or {})
        headers = {}
        if signed:
            params.update(timestamp=int(time.time() * 1000) + self.offset, recvWindow=10000)
            headers["X-MBX-APIKEY"] = self.key
        query = urllib.parse.urlencode(params)
        if signed:
            query += "&signature=" + hmac.new(self.secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        return request_json(SPOT + path + ("?" + query if query else ""), headers=headers)


def history(reader, symbol, max_pages=5):
    rows, next_id = [], 0
    for _ in range(max_pages):
        batch = reader.read("/api/v3/myTrades", {"symbol": symbol, "fromId": next_id, "limit": 1000})
        if not isinstance(batch, list):
            raise RecoveryError("Uventet handelshistorikkformat")
        ids = [int(row["id"]) for row in batch]
        if ids and (min(ids) < next_id or len(set(ids)) != len(ids)):
            raise RecoveryError("Uventet paginering av handelshistorikk")
        rows.extend(batch)
        if len(batch) < 1000:
            return {"rows": rows, "pagination_exhausted": True}
        next_id = max(ids) + 1
        time.sleep(0.2)
    return {"rows": rows, "pagination_exhausted": False}


def collect(env, states):
    reader = SpotReader(env)
    account = reader.read("/api/v3/account")
    balances = [r for r in account.get("balances", [])
        if Decimal(r.get("free", "0")) + Decimal(r.get("locked", "0")) > 0]
    orders = reader.read("/api/v3/openOrders")
    symbols = {f"{a}{q}" for a in ("BTC", "ETH", "SOL", "BNB", "XRP") for q in ("USDC", "USDT")}
    # Keep snapshots from all local users, but query Binance only with the
    # legacy owner's key. Never attribute another user's file to this account.
    for name, state in states.items():
        if name.startswith("users/"):
            continue
        positions = state.get("positions") or ([state["position"]] if state.get("position") else [])
        symbols.update(str(p.get("symbol", "")) for p in positions)
    symbols.update(str(row.get("symbol", "")) for row in orders)
    symbols.update(f"{r['asset']}{q}" for r in balances for q in ("USDC", "USDT") if r["asset"] not in ("USDC", "USDT"))
    symbols = sorted(s for s in symbols if re.fullmatch(r"[A-Z0-9]{3,24}", s))
    trades = {}
    for symbol in symbols:
        try:
            trades[symbol] = history(reader, symbol)
        except RecoveryError as exc:
            if str(exc).startswith("RATE_LIMIT:"):
                raise
            trades[symbol] = {"error": str(exc), "pagination_exhausted": False}
        time.sleep(0.2)
    return {"account": account, "nonzero_balances": balances,
        "open_orders": orders, "spot_trades": trades,
        "scope": "Spot only, listed symbols only; not proof of complete bot history",
        "margin_futures_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--expected-legacy-id", required=True, type=uuid.UUID)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RecoveryError("Kjor med sudo")
    os.umask(0o077)
    env_path = Path("/etc/ai-trading-app.env")
    env = parse_env(env_path.read_text())
    legacy_id = str(uuid.UUID(env.get("APP_USER_ID", "")))
    if legacy_id != str(args.expected_legacy_id):
        raise RecoveryError("Serverens bruker-ID avviker; avbryter")
    folder = Path(tempfile.mkdtemp(prefix="ai-trading-recovery-", dir="/root"))
    shutil.copyfile(env_path, folder / "server.env.backup")
    os.chmod(folder / "server.env.backup", 0o600)
    root = Path("/var/lib/ai-trading-app")
    states = {}
    for path in sorted(root.rglob("*state*.json")):
        if path.is_symlink():
            raise RecoveryError("Symbolsk lenke i tilstandsmappe; avbryter")
        name = str(path.relative_to(root))
        raw = path.read_bytes()
        target = folder / "state" / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(raw)
        states[name] = json.loads(raw)
    if not states:
        raise RecoveryError("Ingen tilstandsfiler funnet")
    print("SIKKERHETSKOPI:", folder, flush=True)
    print("Henter ferske Binance-data med lesekall ...", flush=True)
    report = {"schema_version": 1, "captured_at": datetime.now(timezone.utc).isoformat(),
        "legacy_user_id": legacy_id, "local_states": states,
        "state_files_are_individual_live_snapshots": True,
        "service_active": subprocess.run(["systemctl", "is-active", "ai-trading-app"], capture_output=True, text=True).stdout.strip(),
        "server_commit": subprocess.run(["git", "-C", "/opt/ai-trading-app", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
        "binance": collect(env, states)}
    report_path = folder / "report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print("LOKAL RAPPORT:", report_path)
    for row in report["binance"]["nonzero_balances"]:
        print("SALDO", row["asset"], "fri", row["free"], "last", row["locked"])
    print("APNE SPOT-ORDRE:", len(report["binance"]["open_orders"]))
    print("HENTET HANDELSLINJER:", sum(len(x.get("rows", [])) for x in report["binance"]["spot_trades"].values()))
    if args.upload:
        if not os.isatty(0):
            raise RecoveryError("Opplasting krever interaktiv terminal for skjult nokkelinntasting")
        key = getpass.getpass("Compass Internal servernokkel (skjult): ").strip()
        if not key or any(c.isspace() for c in key):
            raise RecoveryError("Ugyldig nokkelformat")
        headers = {"apikey": key, "Content-Type": "application/json", "Prefer": "return=representation"}
        # Modern sb_secret keys belong in apikey, not the JWT Authorization header.
        if key.count(".") == 2:
            headers["Authorization"] = "Bearer " + key
        request_json(COMPASS + "/rest/v1/trading_recovery_uploads?select=id&limit=1", headers=headers)
        rows = request_json(COMPASS + "/rest/v1/trading_recovery_uploads", headers=headers,
            payload={"legacy_user_id": legacy_id, "payload": report})
        # Preserve the validated replacement credential only in this root-only
        # recovery folder for the later server migration, never in the report.
        (folder / "compass-server-key").write_text(key + "\n")
        os.chmod(folder / "compass-server-key", 0o600)
        print("OPPLASTET TIL COMPASS:", rows[0]["id"])
    print("FERDIG. Ingen ordre, omstart eller endring av serverinnstillinger er utfort.")


if __name__ == "__main__":
    try:
        main()
    except (RecoveryError, ValueError, OSError, KeyError) as exc:
        # These messages never include key values; unknown OS/parse errors show
        # only the type, not file contents or signed URLs.
        message = str(exc) if isinstance(exc, RecoveryError) else type(exc).__name__
        raise SystemExit("STOPPET: " + message)
