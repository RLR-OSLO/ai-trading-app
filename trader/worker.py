from __future__ import annotations

import logging
import os
import time

from .binance import BinanceCredentials, BinanceError, BinanceSpotClient
from .config import DEFAULT_CONFIG
from .simulation import paper_signal_from_klines


LOG = logging.getLogger("ai_trader")


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def configured_pairs() -> tuple[str, ...]:
    quote = os.getenv("TRADING_QUOTE_ASSET", "USDC").upper()
    if quote not in DEFAULT_CONFIG.preferred_quote_assets:
        raise ValueError("Quote asset is outside the approved allowlist")
    return tuple(f"{asset}{quote}" for asset in DEFAULT_CONFIG.symbols)


def build_client() -> BinanceSpotClient:
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret_key = os.getenv("BINANCE_SECRET_KEY", "")
    credentials = None
    if api_key or secret_key:
        credentials = BinanceCredentials(api_key, secret_key)
        credentials.validate()
    return BinanceSpotClient(
        credentials=credentials,
        base_url=os.getenv("BINANCE_BASE_URL", "https://api.binance.com"),
    )


def readiness_check(client: BinanceSpotClient) -> bool:
    pairs = configured_pairs()
    client.server_time()
    info = client.exchange_info(pairs)
    available = {item["symbol"] for item in info.get("symbols", [])}
    missing = set(pairs) - available
    if missing:
        raise BinanceError(f"Approved pairs unavailable: {sorted(missing)}")
    if client.credentials is not None:
        client.account()
        return True
    return False


def paper_scan(client: BinanceSpotClient) -> dict[str, bool]:
    """Read market data and return paper signals without placing orders."""
    return {
        pair: paper_signal_from_klines(client.klines(pair, "15m", limit=100))
        for pair in configured_pairs()
    }


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    client = build_client()
    live = _bool_env("LIVE_TRADING_ENABLED")
    LOG.info(
        "worker starting; live_trading=%s; symbols=%s",
        live,
        ",".join(configured_pairs()),
    )

    while True:
        try:
            authenticated = readiness_check(client)
            LOG.info(
                "health check passed; authenticated_account_read=%s",
                authenticated,
            )
            signals = paper_scan(client)
            LOG.info(
                "paper scan; buy_signals=%s",
                ",".join(pair for pair, signal in signals.items() if signal) or "none",
            )
        except Exception:
            LOG.exception("health check failed; no orders will be submitted")
        time.sleep(60)


if __name__ == "__main__":
    main()
