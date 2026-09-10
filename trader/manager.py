from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

LOG = logging.getLogger("ai_trader.manager")
REFRESH_SECONDS = 60


@dataclass
class Account:
    user_id: str
    api_key: str
    api_secret: str
    legacy: bool = False

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.api_key}\0{self.api_secret}".encode()).hexdigest()


def _vault_accounts() -> list[Account]:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not (url and key):
        return []
    request = urllib.request.Request(
        f"{url}/rest/v1/rpc/service_trading_accounts",
        data=b"{}",
        method="POST",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            rows = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        LOG.warning("could not refresh configured trading accounts: %s", exc)
        return []
    return [
        Account(str(row["user_id"]), str(row["api_key"]), str(row["api_secret"]))
        for row in rows
        if row.get("user_id") and row.get("api_key") and row.get("api_secret")
    ]


def _legacy_account() -> Account | None:
    user_id = os.getenv("APP_USER_ID", "").strip()
    api_key = os.getenv("BINANCE_API_KEY", "").strip()
    api_secret = os.getenv("BINANCE_SECRET_KEY", "").strip()
    if not (user_id and api_key and api_secret):
        return None
    return Account(user_id, api_key, api_secret, legacy=True)


def _desired_accounts() -> dict[str, Account]:
    accounts = {account.user_id: account for account in _vault_accounts()}
    legacy = _legacy_account()
    if legacy is not None:
        # Keep the already-running owner account on its existing server env and
        # state file until that account explicitly replaces its API credentials.
        accounts.setdefault(legacy.user_id, legacy)
    return accounts


def _child_env(account: Account) -> dict[str, str]:
    env = os.environ.copy()
    env["APP_USER_ID"] = account.user_id
    env["BINANCE_API_KEY"] = account.api_key
    env["BINANCE_SECRET_KEY"] = account.api_secret
    env["AI_TRADING_MANAGED_CHILD"] = "1"
    if account.legacy:
        env["LIVE_STATE_PATH"] = os.getenv("LIVE_STATE_PATH", "/var/lib/ai-trading-app/live-state.json")
        env["DERIVATIVES_STATE_PATH"] = os.getenv("DERIVATIVES_STATE_PATH", "/var/lib/ai-trading-app/derivatives-state.json")
    else:
        state_dir = Path("/var/lib/ai-trading-app/users") / account.user_id
        state_dir.mkdir(parents=True, exist_ok=True)
        env["LIVE_STATE_PATH"] = str(state_dir / "live-state.json")
        env["DERIVATIVES_STATE_PATH"] = str(state_dir / "derivatives-state.json")
    return env


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    children: dict[str, tuple[subprocess.Popen[bytes], str]] = {}
    stopping = False

    def stop_all(*_: object) -> None:
        nonlocal stopping
        stopping = True
        for process, _fingerprint in children.values():
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, stop_all)
    signal.signal(signal.SIGINT, stop_all)
    LOG.info("multi-user manager starting")

    while not stopping:
        desired = _desired_accounts()

        for user_id, (process, fingerprint) in list(children.items()):
            account = desired.get(user_id)
            restart = account is None or account.fingerprint != fingerprint or process.poll() is not None
            if restart:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                children.pop(user_id, None)

        for user_id, account in desired.items():
            if user_id in children:
                continue
            process = subprocess.Popen(
                [sys.executable, "-m", "trader.worker"],
                env=_child_env(account),
                cwd="/opt/ai-trading-app",
            )
            children[user_id] = (process, account.fingerprint)
            LOG.info("started isolated trader for user=%s legacy=%s pid=%s", user_id, account.legacy, process.pid)

        time.sleep(REFRESH_SECONDS)

    for process, _fingerprint in children.values():
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    main()
